"""Capture the bodies the installed Codex sends the router, with no model call.

Plan 182. The router can only project shapes the client really sends, so
this drives the real app-server through scripted scenarios against an
in-process router and a fake upstream: a dynamic-tool turn, a switch from an
external row to `gpt-6-astra`, and a V2 compaction on the external row. The
router's own entry points record every client body before any rewrite:
`subscription_fallback.prepare` for turns, plus `compact` and
`compact_trigger`, which external compaction reaches instead of `prepare`.

Each body is sanitised before it is written to
`tests/fixtures/replay/captured/<codex version>/<scenario>.json`: the
instructions become their SHA-256, tool descriptions are cut to 80
characters and the disposable work directory reads `<work>`. Values minted
per run become stable placeholders, so a capture is the same on every run and
machine: the prompt cache key, every client id and the router's compaction
id (numbered, so equal ids stay equal) and the client's timestamps. The
prompts are this tool's own synthetic text. The run then prints what changed
since the newest earlier capture: item types, top-level keys and
developer-message prefixes. No network call, no billing, and no credential is
read: the router holds a synthetic key, and the client a synthetic API key
with the disposable directory as both its home and CODEX_HOME.

Usage: python3.14 tools/capture_codex_shapes.py [--codex-bin PATH] [--scenarios NAME ...]
"""
import argparse
import copy
import hashlib
import http.client
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from compression import zstd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_router import availability, catalogue, subscription_fallback, upstream
from ai_router.compaction_summary import SUMMARY_MODEL_SLUGS
from ai_router.providers import ExternalResponsesProvider
from ai_router.registry import by_slug
from tools.appserver_probe import codex_bin
from tools.probe_context_budget import MODEL, Client, Reply, message

CAPTURED = Path(__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'replay' / 'captured'
CODEX_BIN = codex_bin()
EXTERNAL = 'deepseek/deepseek-v4.1-flash-1017'
NATIVE = 'gpt-6-astra'
DESCRIPTION_CHARS = 80
PREFIX_CHARS = 24
ECHO = {'type': 'function', 'name': 'echo_capture',
        'description': 'Returns a synthetic value for the shape capture.',
        'inputSchema': {'type': 'object', 'properties': {'value': {'type': 'string'}},
                        'required': ['value'], 'additionalProperties': False}}
# scenario: (client compaction mode, the turns it drives as (model, prompt))
SCENARIOS = {
    'dynamic_tool': ('v1', [(EXTERNAL, 'Call echo_capture with value "capture", then reply.')]),
    'switch': ('v1', [(EXTERNAL, 'Reply with one synthetic word.'),
                      (NATIVE, 'Reply with one more synthetic word.')]),
    'compaction': ('v2', [(EXTERNAL, 'Reply with one synthetic word.'),
                          (EXTERNAL, 'Continue the synthetic task.')]),
}
COMPACTION_PATHS = {'compact': '/responses/compact', 'compact_trigger': '/responses'}
# Minted per run: every client id is a UUID; the router's compaction id is
# `cmp_` plus 16 hex digits (compaction.v2_compaction_item).
RUN_ID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|(?<=\bcmp_)[0-9a-f]{16}\b')
# Scalars that differ on every run whatever their shape.
VOLATILE = {'prompt_cache_key': '<prompt_cache_key>', 'create_time': 0,
            'turn_started_at_unix_ms': 0}


def sse(items, used):
    """One streamed response carrying `items`, reporting `used` input tokens."""
    response = {'id': 'resp_capture', 'status': 'completed', 'output': items,
                'usage': {'input_tokens': used, 'output_tokens': 10, 'total_tokens': used + 10}}
    events = [{'type': 'response.created', 'response': {'id': 'resp_capture'}}]
    for index, item in enumerate(items):
        events += [{'type': kind, 'output_index': index, 'item': item}
                   for kind in ('response.output_item.added', 'response.output_item.done')]
    events.append({'type': 'response.completed', 'response': response})
    return ''.join('data: ' + json.dumps(event) + '\n\n' for event in events).encode()


class Upstream:
    """Both fake hosts: the first streamed turn steers the scenario."""

    def __init__(self, scenario):
        self.scenario = scenario
        self.turns = 0

    def connection(self, host, **kwargs):
        owner = self

        class Connection:
            def connect(self):
                pass

            def request(self, method, path, body=None, headers=None):
                if any(k.lower() == 'content-encoding' and v == 'zstd'
                       for k, v in (headers or {}).items()):
                    body = zstd.decompress(body)
                self.payload = json.loads(body)

            def getresponse(self):
                return owner.reply(self.payload)

            def close(self):
                pass

        return Connection()

    def reply(self, payload):
        if not payload.get('stream'):  # the router's own compaction summary request
            return Reply(200, json.dumps({'model': payload['model'],
                         'output': [message('Synthetic summary.')]}).encode(),
                         'application/json')
        self.turns += 1
        items, used = [message('Synthetic reply.')], 1000
        if self.turns == 1 and self.scenario == 'dynamic_tool':
            items = [{'type': 'function_call', 'id': 'fc_capture', 'call_id': 'call_capture',
                      'name': ECHO['name'], 'arguments': '{"value": "capture"}'}]
        elif self.turns == 1 and self.scenario == 'switch':
            items.insert(0, {'type': 'reasoning', 'id': 'rs_capture', 'summary': [],
                             'content': [{'type': 'reasoning_text', 'text': 'Synthetic reasoning.'}]})
        elif self.turns == 1 and self.scenario == 'compaction':
            # One token past the client's compaction threshold (90% of the row's
            # window), read here so a retired row cannot break importing the tool.
            used = by_slug(EXTERNAL).context_window * 9 // 10 + 1
        return Reply(200, sse(items, used), 'text/event-stream')


def drive(client, thread, model, prompt):
    """Run one turn to completion, answering any dynamic tool call."""
    client.rpc('turn/start', {'threadId': thread, 'model': model, 'effort': 'low',
                              'input': [{'type': 'text', 'text': prompt, 'text_elements': []}]})
    deadline = time.monotonic() + 60
    while True:
        event = client.next_event(deadline)
        method, params = event.get('method'), event.get('params') or {}
        if method == 'item/tool/call':
            client.send({'id': event['id'], 'result': {'success': True, 'contentItems': [
                {'type': 'inputText', 'text': 'synthetic capture result'}]}})
        elif method == 'error':
            nested = params.get('error') if isinstance(params.get('error'), dict) else {}
            if not (params.get('willRetry') or nested.get('willRetry')):
                raise RuntimeError(f'client error {nested.get("codexErrorInfo")}')
        elif method == 'turn/completed' and params['turn']['status'] != 'completed':
            raise RuntimeError(f'turn {params["turn"]["status"]}')
        elif method == 'turn/completed':
            return


def record_compaction(original, via, records):
    def record(self, model, payload, key, *args, **kwargs):
        records.append({'via': via, 'path': COMPACTION_PATHS[via],
                        'payload': copy.deepcopy(payload)})
        return original(self, model, payload, key, *args, **kwargs)
    return record


def capture(binary, name, home):
    """The sanitised client bodies one scenario sent the router, in order."""
    mode, turns = SCENARIOS[name]
    records = []
    prepare = subscription_fallback.prepare

    def record_prepare(provider, model, path, payload, *args, **kwargs):
        records.append({'via': 'prepare', 'path': path, 'payload': copy.deepcopy(payload)})
        return prepare(provider, model, path, payload, *args, **kwargs)

    fake = Upstream(name)
    upstream.clear_refusals()
    # The disposable directory is HOME too: the client lists user-level skills
    # from the real home otherwise, whatever CODEX_HOME says. UTC keeps the
    # machine's timezone out of the environment context.
    isolated = {'ROUTER_HOME': str(home / 'router'), 'HOME': str(home), 'TZ': 'UTC'}
    snapshot = {'key': availability.key_fingerprint('synthetic-capture-key'),
                'region': 'global', 'models': frozenset(SUMMARY_MODEL_SLUGS)}
    with mock.patch.dict(os.environ, isolated), \
            mock.patch.object(http.client, 'HTTPSConnection', fake.connection), \
            mock.patch.object(availability, 'current', return_value=snapshot), \
            mock.patch.object(subscription_fallback, 'prepare', record_prepare), \
            mock.patch.object(ExternalResponsesProvider, 'compact', record_compaction(
                ExternalResponsesProvider.compact, 'compact', records)), \
            mock.patch.object(ExternalResponsesProvider, 'compact_trigger',
                              record_compaction(ExternalResponsesProvider.compact_trigger,
                                                'compact_trigger', records)):
        from ai_router.router import Router
        server = Router({'port': 0, 'token': 'capture-token', 'openai_models': [NATIVE]},
                        credentials=SimpleNamespace(key_for=lambda _pid=None: 'synthetic-capture-key'))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        catalog = home / 'catalog.json'
        # The client's configured default (MODEL) must be listed too.
        catalog.write_text(json.dumps({'models': [catalogue.subscription_stub(NATIVE), *[
            catalogue.external_entry(by_slug(slug)) for slug in (EXTERNAL, MODEL)]]}))
        url = f'http://127.0.0.1:{server.server_port}/capture-token/backend-api/codex'
        client = None
        try:
            client = Client(binary, home, url, catalog, mode)
            client.rpc('initialize', {'clientInfo': {'name': 'shape_capture', 'version': '1'},
                                      'capabilities': {'experimentalApi': True}})
            client.send({'method': 'initialized', 'params': {}})
            start = {'model': turns[0][0], 'modelProvider': 'openai', 'cwd': str(home),
                     'approvalPolicy': 'never', 'sandbox': 'read-only',
                     'baseInstructions': 'Synthetic shape capture; there is no real task.'}
            if name == 'dynamic_tool':
                start['dynamicTools'] = [ECHO]
            thread = client.rpc('thread/start', start)['thread']['id']
            for model, prompt in turns:
                drive(client, thread, model, prompt)
        finally:
            if client:
                client.close()
            server.shutdown()
            server.server_close()
            upstream.clear_refusals()
    return [dict(record, payload=sanitise(record['payload'], home)) for record in records]


def sanitise(payload, work=None):
    """A copy safe to commit and stable across runs; the module docstring lists the rules."""
    paths = sorted({str(work), str(Path(work).resolve())}, key=len, reverse=True) if work else []
    # Numbered in written (sorted-key) order: the client emits some maps in a
    # different key order on every run.
    ids = {}
    for match in RUN_ID.finditer(json.dumps(payload, sort_keys=True)):
        ids.setdefault(match.group(), f'<id-{len(ids) + 1}>')

    def run_id(match):
        return ids.setdefault(match.group(), f'<id-{len(ids) + 1}>')

    def field(key, item, in_tools):
        if key in VOLATILE and not isinstance(item, (dict, list)):
            return VOLATILE[key]
        if in_tools and key == 'description' and isinstance(item, str):
            return clean(item)[:DESCRIPTION_CHARS]
        return clean(item, in_tools or key == 'tools')

    def clean(value, in_tools=False):
        if isinstance(value, dict):
            return {key: field(key, item, in_tools) for key, item in value.items()}
        if isinstance(value, list):
            return [clean(item, in_tools) for item in value]
        if not isinstance(value, str):
            return value
        for path in paths:
            value = value.replace(path, '<work>')
        value = RUN_ID.sub(run_id, value)
        if value.startswith('{'):  # JSON-encoded metadata such as x-codex-turn-metadata
            try:
                inner = json.loads(value)
            except ValueError:
                return value
            # Rewritten only when a field inside changed, so tool arguments keep their spelling.
            if isinstance(inner, dict) and (scrubbed := clean(inner)) != inner:
                return json.dumps(scrubbed, separators=(',', ':'))
        return value

    def instruction_text(text):
        fingerprint = '<instructions sha256=' + hashlib.sha256(text.encode()).hexdigest() + '>'
        stripped = text.lstrip()
        if stripped.startswith('<model_switch>'):
            # Keep the wire boundary observable without retaining client prose.
            closing = '\n</model_switch>' if stripped.rstrip().endswith('</model_switch>') else ''
            return text[:len(text) - len(stripped)] + '<model_switch>\n' + fingerprint + closing
        return fingerprint

    cleaned = clean(payload)
    if isinstance(cleaned.get('instructions'), str):
        digest = hashlib.sha256(cleaned['instructions'].encode()).hexdigest()
        cleaned['instructions'] = f'<instructions sha256={digest}>'
    for item in cleaned.get('input') or []:
        if not isinstance(item, dict) or item.get('role') not in ('developer', 'system'):
            continue
        content = item.get('content')
        if isinstance(content, str):
            item['content'] = instruction_text(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and isinstance(block.get('text'), str):
                    block['text'] = instruction_text(block['text'])
    return cleaned


def shape(records):
    """Item types, top-level keys and developer-message prefixes across one scenario."""
    found = {'item_types': set(), 'top_level_keys': set(), 'developer_prefixes': set()}
    for record in records:
        payload = record['payload']
        found['top_level_keys'].update(payload)
        for item in payload.get('input') or []:
            if not isinstance(item, dict):
                continue
            kind = str(item.get('type') or ('message' if 'role' in item else 'unknown'))
            found['item_types'].add(kind)
            if kind == 'message' and item.get('role') == 'developer':
                content = item.get('content')
                blocks = content if isinstance(content, list) else [{'text': content}]
                found['developer_prefixes'].update(
                    block['text'][:PREFIX_CHARS] for block in blocks
                    if isinstance(block, dict) and isinstance(block.get('text'), str))
    return found


def drift(before, after):
    """{field: {'added': [...], 'removed': [...]}} from one capture of a scenario to the next."""
    old, new = shape(before), shape(after)
    return {field: {'added': sorted(new[field] - old[field]),
                    'removed': sorted(old[field] - new[field])} for field in new}


def _version_key(name):
    # ponytail: numeric fields only, so a final release sorts before its own
    # pre-releases; order by capture date instead if that ever matters.
    return tuple(int(part) for part in re.findall(r'\d+', name))


def earlier_capture(root, version):
    """The newest captured version directory older than `version`, else None."""
    older = [path for path in (root.iterdir() if root.is_dir() else ())
             if path.is_dir() and _version_key(path.name) < _version_key(version)]
    return max(older, key=lambda path: _version_key(path.name), default=None)


def report(root, version, captures):
    """Print one drift line per captured scenario against the newest earlier capture."""
    earlier = earlier_capture(root, version)
    if earlier is None:
        print(json.dumps({'codex': version, 'drift': 'no earlier capture to compare'}))
        return
    for name, records in captures.items():
        path = earlier / f'{name}.json'
        before = (json.loads(path.read_text(encoding='utf-8'))['requests']
                  if path.is_file() else [])
        print(json.dumps({'scenario': name, 'against': earlier.name, **drift(before, records)}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--codex-bin', default=CODEX_BIN)
    parser.add_argument('--scenarios', nargs='+', choices=list(SCENARIOS), default=list(SCENARIOS))
    args = parser.parse_args(argv)
    version = subprocess.check_output([args.codex_bin, '--version'], text=True,
                                      timeout=10).split()[-1]
    if not re.fullmatch(r'[0-9A-Za-z.+-]+', version):
        raise SystemExit('unexpected codex --version output')
    captures, failed = {}, []
    for name in args.scenarios:
        with tempfile.TemporaryDirectory(prefix='codex-capture-') as tmp:
            try:
                captures[name] = capture(args.codex_bin, name, Path(tmp))
            except Exception as exc:  # noqa: BLE001 - one failed scenario must not hide the rest
                failed.append(name)
                print(json.dumps({'scenario': name, 'captured': False,
                                  'error': f'{type(exc).__name__}: {str(exc)[:300]}'}), flush=True)
                continue
        out = CAPTURED / version
        out.mkdir(parents=True, exist_ok=True)
        (out / f'{name}.json').write_text(json.dumps(
            {'scenario': name, 'requests': captures[name]}, sort_keys=True, indent=1) + '\n',
            encoding='utf-8')
        print(json.dumps({'scenario': name, 'captured': True,
                          'requests': len(captures[name])}), flush=True)
    report(CAPTURED, version, captures)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
