"""Capture the client's spawn_agent model-override list, with no billing.

Plan 151 stage 4. The desktop client builds `spawn_agent`'s "Available model
overrides" text from the first five picker-visible catalogue rows, so what a
routed session may delegate to is decided by catalogue order rather than by
the roster the router serves. This probe starts a real app-server thread
against a local sink that answers 426 to the websocket upgrade and records
the `/responses` body, then asserts the advertised list against the catalogue
the installed router serves. No model is ever called: the run is free, needs
no credential, and leaves the live configuration alone.
"""
import json
import os
import queue
import re
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from compression import zstd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.appserver_probe import AppServer, codex_bin

ZSTD_MAGIC = b'\x28\xb5\x2f\xfd'
INSTALLED_CATALOGUE = Path.home() / '.codex/mixed-model-router/mixed-models.json'
CODEX_BIN = codex_bin()


class _Sink(BaseHTTPRequestHandler):
    """Local sink: 426 to the websocket upgrade, record the first POST body."""

    protocol_version = 'HTTP/1.1'  # the client refuses an HTTP/1.0 426
    bodies = None

    def log_message(self, *args):
        """Silence the default stderr access log."""

    def do_GET(self):
        if self.headers.get('Upgrade'):
            self.send_response(426)
            self.send_header('Upgrade', 'websocket')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        self.send_error(404)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get('Content-Length') or 0))
        if raw[:4] == ZSTD_MAGIC:
            raw = zstd.decompress(raw)
        if type(self).bodies is not None and not type(self).bodies:
            type(self).bodies.append(raw)
        self.send_response(400)
        self.send_header('Content-Type', 'application/json')
        body = b'{"error":{"message":"synthetic sink","type":"invalid_request_error"}}'
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def spawn_override_models(description):
    """The model ids the spawn_agent description advertises, in order.

    Only the bullet list counts: the paragraphs after it name task paths and
    model ids too, and counting those would misreport the list length.
    """
    match = re.search(r'Available model overrides[^:]*:(.*)', description, re.S)
    if match is None:
        return []
    tail = match.group(1)
    stop = re.search(r'\n\s*\n', tail)
    if stop:
        tail = tail[:stop.start()]
    return re.findall(r'^\s*-\s*`([^`]+)`', tail, re.M)


def declared_tools(body):
    """Every tool declaration in a captured request, in both client shapes.

    This build sends them as an `additional_tools` developer item; earlier
    builds sent a top-level `tools` array. Both are read.
    """
    yield from body.get('tools') or []
    for item in body.get('input') or []:
        if item.get('type') != 'additional_tools':
            continue
        for namespace in item.get('tools') or []:
            yield from namespace.get('tools') or []


def expected_overrides(rows):
    """The ids the client's five override slots should show, in order.

    The client takes the first five picker-visible rows that support a
    multi-agent backend, in catalogue order, so the subscription head rows
    win the slots (MAX_SPAWN_AGENT_MODEL_OVERRIDES = 5).
    """
    return [row['slug'] for row in rows
            if row.get('visibility') == 'list'
            and row.get('multi_agent_version')][:5]


def capture_spawn_list(codex_bin=CODEX_BIN, timeout=120, print_only=False):
    """Start a thread against a local sink and read the spawn_agent text.

    Returns `(found, expected)`: the override list the client advertised and
    the five ids its catalogue should yield, so a caller can assert them.
    The catalogue is the one the installed router serves, copied read-only
    into the probe's own work directory.
    """
    if not INSTALLED_CATALOGUE.is_file():
        raise SystemExit(f'spawn-list probe needs the served catalogue: {INSTALLED_CATALOGUE}')
    bodies = []
    _Sink.bodies = bodies
    server = ThreadingHTTPServer(('127.0.0.1', 0), _Sink)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    work = Path(tempfile.mkdtemp(prefix='spawn-list-'))
    catalogue = work / 'catalogue.json'
    catalogue.write_text(INSTALLED_CATALOGUE.read_text())
    expected = expected_overrides(json.loads(catalogue.read_text())['models'])
    if not expected:
        raise SystemExit('spawn-list probe found no picker rows to expect')
    cfg = {'model_provider': 'openai',
           'openai_base_url': f'http://127.0.0.1:{server.server_address[1]}',
           'model_catalog_json': str(catalogue), 'project_doc_max_bytes': 0,
           'approval_policy': 'never', 'sandbox_mode': 'read-only',
           'features.multi_agent': True, 'features.multi_agent_v2': True,
           'features.shell_tool': False, 'features.apps': False,
           'features.memories': False, 'features.code_mode': False,
           'web_search': 'disabled'}
    args = [codex_bin, 'app-server', '--stdio']
    for key, value in cfg.items():
        args.extend(['-c', key + '=' + json.dumps(value)])
    args.extend(['-c', 'mcp_servers={}'])
    child = AppServer(args, cwd=str(work), env=dict(os.environ),
                      stderr=(work / 'app-server.log').open('w'))
    try:
        child.rpc('initialize', {'clientInfo': {'name': 'spawn_list_probe',
                                                'version': '1.0'},
                                 'capabilities': {'experimentalApi': True}})
        child.send({'method': 'initialized', 'params': {}})
        thread = child.rpc('thread/start', {'model': expected[0],
            'modelProvider': 'openai', 'cwd': str(work), 'ephemeral': True,
            'approvalPolicy': 'never', 'sandbox': 'read-only',
            'baseInstructions': 'Synthetic protocol capture only. No files or external tools.',
            'developerInstructions': 'Reply to the user in one word.'})['thread']['id']
        child.rpc('turn/start', {'threadId': thread, 'effort': 'low',
            'input': [{'type': 'text', 'text': 'Reply with the single word ready.',
                       'text_elements': []}]})
        # The sink answers 400 by design, so the turn ends in an error; the
        # captured body is the evidence. Drain until it lands or time runs out.
        deadline = time.monotonic() + timeout
        while not bodies and time.monotonic() < deadline:
            try:
                child.next_event(deadline=deadline)
            except (queue.Empty, RuntimeError):
                break
    finally:
        child.close()
        server.shutdown()
        server.server_close()
    if not bodies:
        raise SystemExit('spawn-list probe captured no upstream request')
    for tool in declared_tools(json.loads(bodies[0])):
        description = tool.get('description') or ''
        if tool.get('name') == 'spawn_agent' and 'model overrides' in description:
            if print_only:
                print(json.dumps({'spawn_agent_description': description[:1200]}, indent=2))
            return spawn_override_models(description), expected
    raise SystemExit('spawn-list probe found no spawn_agent tool in the captured body')


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    codex = argv[argv.index('--codex') + 1] if '--codex' in argv else CODEX_BIN
    found, expected = capture_spawn_list(codex, print_only='--print' in argv)
    print(json.dumps({'models': found, 'catalogue_head': expected}), flush=True)
    if '--print' in argv:
        return 0
    if found != expected:
        print('spawn override list differs from the catalogue head', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
