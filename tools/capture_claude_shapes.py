"""Capture the Messages shapes Claude Code sends, with no model call.

The router can only repair shapes the client actually sends, so this drives
the installed `claude` binary against a loopback sink scripted to walk one
deferred-tool turn. Every request is summarised as it arrives and never
stored whole, no header value except the beta list is recorded, and nothing
leaves the machine. A synthetic bearer is supplied by default, because a host
whose OAuth credential the CLI cannot read outside its own terminal answers
"Not logged in" before the first request, and the shapes captured here do not
depend on which credential the session presents; `CAPTURE_AUTH_TOKEN`
overrides it.

Usage:
    python3.14 tools/capture_claude_shapes.py --matrix
    python3.14 tools/capture_claude_shapes.py --matrix --models z-ai/glm-5.3
    python3.14 tools/capture_claude_shapes.py --matrix --tool-count 700
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
try:
    from tools.claude_probe_env import environment
except ModuleNotFoundError:
    from claude_probe_env import environment

CLAUDE_BIN = os.environ.get('CLAUDE_BIN') or shutil.which('claude')
STUB_MCP = Path(__file__).resolve().parent / 'mcp_stub_server.py'
STUB_SERVER = 'stubtools'  # the key the client sees; tools become mcp__<key>__*
STUB_TOOL = 'mcp__%s__tool_000' % STUB_SERVER
REFERENCE_TYPE = 'tool_reference'
PROMPT = 'Reply with the single word ready.'
TIMEOUT_S = 180
AUTH_TOKEN = os.environ.get('CAPTURE_AUTH_TOKEN') or 'synthetic-capture-token'

# One deferred-tool turn: search for the stub tool, call it, then answer.
SCRIPT = (('tool_search', 'select:' + STUB_TOOL),
          ('tool_call', STUB_TOOL),
          ('text', 'captured'))

SCENARIOS = (
    ('baseline', {}),
    ('tool-search', {'ENABLE_TOOL_SEARCH': 'true'}),
    ('tool-search+betas-suppressed',
     {'ENABLE_TOOL_SEARCH': 'true',
      'CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS': '1'}),
)


def _sse(events):
    return b''.join(b'event: %s\ndata: %s\n\n'
                    % (kind.encode(), json.dumps(payload).encode())
                    for kind, payload in events)


def _start(model):
    return ('message_start', {'type': 'message_start', 'message': {
        'id': 'msg_capture', 'type': 'message', 'role': 'assistant',
        'model': model, 'content': [], 'stop_reason': None, 'stop_sequence': None,
        'usage': {'input_tokens': 1, 'output_tokens': 1}}})


def _end(stop_reason):
    return [('message_delta', {'type': 'message_delta',
                               'delta': {'stop_reason': stop_reason,
                                         'stop_sequence': None},
                               'usage': {'output_tokens': 1}}),
            ('message_stop', {'type': 'message_stop'})]


def _tool_use(model, name, tool_input):
    return _sse([
        _start(model),
        ('content_block_start', {'type': 'content_block_start', 'index': 0,
                                 'content_block': {'type': 'tool_use',
                                                   'id': 'toolu_capture',
                                                   'name': name, 'input': {}}}),
        ('content_block_delta', {'type': 'content_block_delta', 'index': 0,
                                 'delta': {'type': 'input_json_delta',
                                           'partial_json': json.dumps(tool_input)}}),
        ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
    ] + _end('tool_use'))


def _text(model, text):
    return _sse([
        _start(model),
        ('content_block_start', {'type': 'content_block_start', 'index': 0,
                                 'content_block': {'type': 'text', 'text': ''}}),
        ('content_block_delta', {'type': 'content_block_delta', 'index': 0,
                                 'delta': {'type': 'text_delta', 'text': text}}),
        ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
    ] + _end('end_turn'))


def _blocks(body):
    """Every message content block, in order; a string reads as text-string."""
    for message in body.get('messages') or []:
        content = message.get('content') if isinstance(message, dict) else None
        if isinstance(content, str):
            yield {'type': 'text-string'}
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict):
                yield block


def _results(body, preview=False):
    """(released tool names, tool_result shapes) for one request body."""
    names, shapes = [], []
    for block in _blocks(body):
        if block.get('type') != 'tool_result':
            continue
        inner = block.get('content')
        if isinstance(inner, str):
            shape = {'content': 'text', 'chars': len(inner)}
            if preview:
                shape['preview'] = inner[:160]
        else:
            items = [item for item in inner or [] if isinstance(item, dict)]
            names += [str(item.get('tool_name')) for item in items
                      if item.get('type') == REFERENCE_TYPE]
            shape = {'content': 'blocks',
                     'kinds': sorted({str(item.get('type')) for item in items}),
                     'chars': len(json.dumps(inner or []))}
            if preview:
                shape['preview'] = json.dumps(inner or [])[:160]
        shapes.append(shape)
    return names, shapes


def _cache_ttls(body):
    seen = set()

    def walk(node):
        if isinstance(node, dict):
            control = node.get('cache_control')
            if isinstance(control, dict) and 'ttl' in control:
                seen.add(str(control['ttl']))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(body)
    return sorted(seen)


def summarise(raw, headers, preview=False):
    """Shape summary of one request; never the body itself."""
    record = {'bytes': len(raw), 'betas': headers.get('anthropic-beta'),
              'version': headers.get('anthropic-version'),
              'app': headers.get('x-app'),
              'user_agent': (headers.get('user-agent') or '')[:60]}
    try:
        body = json.loads(raw)
    except ValueError:
        record['json'] = False
        return record
    if not isinstance(body, dict):
        record['json'] = True
        record['object'] = False
        return record
    tools = [tool for tool in body.get('tools') or [] if isinstance(tool, dict)]
    system = body.get('system')
    texts = [block.get('text') or '' for block in system
             if isinstance(block, dict)] if isinstance(system, list) else []
    blocks = list(_blocks(body))
    references, results = _results(body, preview)
    record.update({
        'keys': sorted(body),
        'model': body.get('model'),
        'stream': body.get('stream'),
        'max_tokens': body.get('max_tokens'),
        'tools': len(tools),
        'tool_names': sorted(str(tool.get('name')) for tool in tools)[:40],
        'tool_types': sorted({str(tool.get('type')) for tool in tools}),
        'deferred': sorted(tool.get('name') or '' for tool in tools
                           if tool.get('defer_loading')),
        'search_entries': sorted(str(tool.get('name') or tool.get('type'))
                                 for tool in tools
                                 if 'tool_search' in str(tool.get('type'))
                                 or tool.get('name') in ('ToolSearch',
                                                         'DeferredToolPlaceholder')),
        'mcp_tools': sorted(str(tool.get('name')) for tool in tools
                            if str(tool.get('name') or '').startswith('mcp__')),
        'block_types': sorted({str(block.get('type')) for block in blocks}),
        'tool_references': references,
        'tool_results': results,
        'cache_ttls': _cache_ttls(body),
        'deferred_hint': any('defer' in text for text in texts),
        'system_blocks': len(texts),
        'context_management': 'context_management' in body,
        'output_config': body.get('output_config'),
        'thinking': body.get('thinking'),
        'task_budget': 'task_budget' in body,
    })
    return record


class Sink:
    """One scripted turn, with every request summarised on arrival."""

    def __init__(self, script=SCRIPT, preview=False):
        self.script = tuple(script)
        self.preview = preview
        self.requests = []
        self.lock = threading.Lock()

    def step(self, index):
        return self.script[index] if index < len(self.script) else ('text', 'done')


def _handler(sink):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def _reply(self, status, body, content_type):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._reply(404, b'{"error":{"message":"no listing"}}', 'application/json')

        def do_POST(self):
            path = self.path.split('?')[0]
            length = int(self.headers.get('Content-Length') or 0)
            raw = self.rfile.read(length) if length else b''
            if path.endswith('/count_tokens'):
                return self._reply(200, b'{"input_tokens":1}', 'application/json')
            if not path.endswith('/v1/messages'):
                return self._reply(404, b'{}', 'application/json')
            summary = summarise(raw, dict(self.headers), sink.preview)
            with sink.lock:
                sink.requests.append(summary)
                index = len(sink.requests) - 1
            model = summary.get('model') or 'claude-sonnet-5'
            kind, value = sink.step(index)
            if kind == 'tool_search':
                body = _tool_use(model, 'ToolSearch', {'query': value})
            elif kind == 'tool_call':
                body = _tool_use(model, value, {'value': 'stub'})
            elif kind == 'http_error':
                return self._reply(int(value), b'{"type":"error","error":{"type":"overloaded_error",'
                                   b'"message":"Synthetic limit check"}}', 'application/json')
            else:
                body = _text(model, value)
            self._reply(200, body, 'text/event-stream')

    return Handler


def capture(model, env_overrides, tool_count, root, script=SCRIPT, preview=False):
    """Drive one client session against the sink; returns its record."""
    sink = Sink(script, preview)
    server = ThreadingHTTPServer(('127.0.0.1', 0), _handler(sink))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    work = Path(tempfile.mkdtemp(prefix='scg-shape.', dir=str(root)))
    try:
        servers = {} if not tool_count else {STUB_SERVER: {
            'command': sys.executable,
            'args': [str(STUB_MCP), '--tools', str(tool_count)]}}
        mcp_path = work / 'mcp.json'
        mcp_path.write_text(json.dumps({'mcpServers': servers}))
        settings = work / 'settings.json'
        settings.write_text(json.dumps({'env': {
            'ANTHROPIC_BASE_URL': 'http://127.0.0.1:%d/synthetic/'
                                  % server.server_port,
            'CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY': 'false'}}))
        os.chmod(settings, 0o600)
        env = environment(work, 'http://127.0.0.1:%d/synthetic/' % server.server_port,
                          AUTH_TOKEN, 'low', env_overrides)
        command = [CLAUDE_BIN, '-p', PROMPT, '--model', model,
                   '--strict-mcp-config', '--mcp-config', str(mcp_path),
                   '--dangerously-skip-permissions',
                   '--settings', str(settings), '--output-format', 'json']
        started = time.time()
        done, error = None, None
        try:
            done = subprocess.run(command, cwd=str(work), env=env,
                                  capture_output=True, text=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            error = 'timeout'
        return {'model': model, 'env': env_overrides, 'mcp_tools': tool_count,
                'seconds': round(time.time() - started, 1), 'error': error,
                'exit': None if done is None else done.returncode,
                'stdout_tail': '' if done is None else done.stdout.strip()[-300:],
                'stderr_tail': '' if done is None else done.stderr.strip()[-300:],
                'requests': list(sink.requests)}
    finally:
        server.shutdown()
        server.server_close()
        shutil.rmtree(work, ignore_errors=True)


def _line(record):
    if not record['requests']:
        return 'no request reached the sink (%s)' % (record['error'] or 'no output')
    first = record['requests'][0]
    beta = (first.get('betas') or '-')[:38]
    return ('%2d reqs | beta %-38s | tools %3d | deferred %3d | search %-28s '
            '| refs %s' % (len(record['requests']), beta, first.get('tools', 0),
                           len(first.get('deferred') or []),
                           ','.join(first.get('search_entries') or []) or '-',
                           ','.join(record['requests'][-1].get('tool_references')
                                    or []) or '-'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--matrix', action='store_true',
                        help='capture every scenario for each model')
    parser.add_argument('--models', nargs='+',
                        default=['z-ai/glm-5.3', 'claude-sonnet-5'],
                        help='model ids to drive (default: a routed row and a '
                             'subscription-shaped one)')
    parser.add_argument('--tool-count', type=int, default=3,
                        help='stub MCP tools advertised (default 3)')
    parser.add_argument('--scenarios', nargs='*',
                        help='scenario names to run (default: all of them)')
    parser.add_argument('--preview', action='store_true',
                        help='include bounded text previews of tool results')
    parser.add_argument('--output', type=Path, help='write the records as JSON')
    args = parser.parse_args(argv)

    if not args.matrix:
        parser.error('--matrix is required')
    if not CLAUDE_BIN:
        raise SystemExit('the claude binary is not on PATH')

    records = []
    with tempfile.TemporaryDirectory(prefix='scg-shapes.') as root:
        for model in args.models:
            for name, overrides in SCENARIOS:
                if args.scenarios and name not in args.scenarios:
                    continue
                record = capture(model, overrides, args.tool_count, root,
                                 preview=args.preview)
                record['scenario'] = name
                records.append(record)
                print('%-34s %-24s %s' % (name, model, _line(record)), flush=True)

    if args.output:
        args.output.write_text(json.dumps(records, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
