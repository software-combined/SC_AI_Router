"""Parent model switches with one child kept alive (Plan 185 cells C3 and C5).

A real Codex app-server runs one parent thread through a parent sequence. The
first parent spawns one sub-agent and waits for its reply in the same step,
because Codex only moves a child's reply into the parent's history when the
parent waits. A cell that compacts then compacts the parent, and the parent
switches to each later model and is asked for the child's synthetic marker.
The child is never closed, so it stays alive across every switch.

Offline (the default) points a disposable Codex home at a scripted loopback
upstream: no credentials and no billed call. --live needs --max-live-calls N
and --max-live-tokens N. It runs the client on the ambient Codex home, keeping
its own sign-in with nothing copied, points it at this probe with command-line
overrides and forwards each request to the installed router. Both caps are
hard stops for calls that reach this probe, and nothing is retried: after a
refused or failed call, or once the relayed `usage` totals reach the budget,
every later request is refused locally. The call that crosses the budget still
completes, so the overshoot is at most one call (these sequences never have
two in flight); the router's own compaction summary reports no usage.

tools/probe_codex_runtime.py refuses the live home with a base-URL override.
Plan 185 step 3 confirmed that this client honours the override, and the owner
accepted the writes it still makes there: its own logs, state databases and
temporary files, as every Codex session does, never configuration or
credentials. Live mode runs the client under a sandbox-exec profile that
reaches only this probe's port, so nothing else it starts (such as the user's
MCP servers) reaches the network, and refuses to start without it. Features
that write or reach beyond the probe are off; the client ends when its input
closes.

Output is one JSON line of markers received, calls and tokens used, requested
and served identities, the child-reply shape in the last parent request and a
result, never content, ports or credentials. Exit 1 only on a `fail` result.
"""
import argparse
from compression import zstd
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_router.history_items import inbound_agent_message
from ai_router.catalogue import external_entry, subscription_stub
from ai_router.registry import by_slug
from ai_router.subscription_history import encrypted_field_count
from tools.appserver_probe import AGENT_HANDOFFS, AppServer, codex_bin, scrub_env
from tools.probe_agent_handoffs import Probe, frame_data, message, sse

MARKER = 'SYNTH_PARENT_SWITCH_451'
EFFORT = 'low'
# Plan 185 cells: parent sequence, child, and whether the parent compacts
# before its first switch. A subscription child's reply is expected to carry
# an encrypted block; a run without one records "shape not produced".
CELLS = {
    'C3': (('z-ai/glm-5.3-flash', 'gpt-6-luna'), 'deepseek/deepseek-v4.1-flash', False),
    'C5': (('deepseek/deepseek-v4.1-flash', 'gpt-6-luna'), 'gpt-6-luna', True),
}
STOPPED = 'probe stopped after a refused or failed call'
BUDGET = 'live token budget reached'
MAX_LIVE_TOKENS = 500_000  # 24 calls of about 20,000 tokens; one request here is about 6,000.
KNOWN = ('live call limit reached', STOPPED, BUDGET, 'parent turn failed',
         'parent turn timed out', 'client bypassed the probe', 'network sandbox unavailable')
INSTALLED = Path.home() / '.codex/mixed-model-router'
SANDBOX = '/usr/bin/sandbox-exec'
RECALL = 'Without calling any tools, reply with the exact marker the plain agent sent you.'


def spawn_prompt(child):
    return (f'In one step, call collaboration.spawn_agent with task_name "plain", model '
            f'"{child}", fork_turns "none", reasoning_effort "{EFFORT}" and message '
            f'"Reply exactly {MARKER}", and call collaboration.wait_agent with '
            'timeout_ms 120000. When the wait returns, finish this turn with one '
            'short sentence. Do not close the agent.')


def reply_facts(raw):
    """Served model, text, failure flag and `usage` tokens of one relayed SSE reply.

    A late upstream failure arrives as a terminal event inside an HTTP 200, and
    a stream cut short has no `response.completed`: both count as failed."""
    completed, texts, failed = None, [], False
    for frame in raw.replace(b'\r\n', b'\n').split(b'\n\n'):
        data = frame_data(frame)
        if not data or data == b'[DONE]':
            continue
        event = json.loads(data)
        item = event.get('item') or {}
        failed |= event.get('type') in ('response.failed', 'response.incomplete', 'error')
        if event.get('type') == 'response.completed':
            completed = event.get('response') or {}
        elif event.get('type') == 'response.output_item.done' and item.get('type') == 'message':
            texts += [b.get('text', '') for b in item.get('content', []) if isinstance(b, dict)]
    usage = (completed or {}).get('usage') or {}
    tokens = usage.get('total_tokens') or usage.get('input_tokens', 0) + usage.get('output_tokens', 0)
    return (completed or {}).get('model'), '\n'.join(texts), failed or completed is None, tokens


def child_replies(items):
    return [i for i in items if isinstance(i, dict) and i.get('type') == 'agent_message'
            and inbound_agent_message(i)]


class SwitchProbe(Probe):
    """Scripted upstream offline; the shared capped forwarder when live."""

    def __init__(self, live, cap, child, upstream=None, token_limit=0):
        # The base reads the installed router's state only for a real live
        # run; a test hands in its own fake upstream instead.
        super().__init__(live and upstream is None, cap)
        self.live, self.child = live, child
        self.upstream = upstream or self.upstream
        self.identities, self.switched = [], []
        self.compacted = self.child_marker = False
        self.child_reply, self.steps, self.stopped = 'missing', 0, ''
        # Like the call cap, a budget of 0 allows nothing when live.
        self.token_limit, self.tokens = token_limit, 0

    def respond(self, body, headers, path='/responses'):
        if self.live and self.tokens >= self.token_limit:
            self.stopped = self.stopped or BUDGET
        if self.stopped:
            raise ValueError(self.stopped)
        # Codex marks every request a spawned child sends with this header.
        child = bool(headers.get('x-codex-parent-thread-id'))
        if not child:
            replies = child_replies(body.get('input', []))
            self.child_reply = ('encrypted' if any(map(encrypted_field_count, replies))
                                else 'readable' if replies else 'missing')
        try:
            raw = self.forward(body, headers, path) if self.live else self.fake(body, child)
            served, text, failed, tokens = reply_facts(raw)
        except Exception:
            self.stopped = STOPPED
            raise
        self.identities.append([body.get('model'), served])
        self.tokens += tokens
        self.child_marker |= child and MARKER in text
        if failed:  # Relay it, but refuse the client's retry.
            self.stopped = STOPPED
            self.errors.append({'reason': 'upstream stream failed', 'status': 200})
        return raw

    def fake(self, body, child):
        ident = str(len(self.identities) + 1)
        items = body.get('input', [])
        if child:
            text = MARKER if MARKER in json.dumps(items) else 'SYNTH_NO_ASSIGNMENT'
            return sse([message(text, ident)], ident)
        self.steps += 1
        if self.steps > 1:
            delivered = any(MARKER in json.dumps(i) for i in child_replies(items))
            return sse([message(MARKER if delivered else 'SYNTH_NO_REPLY', ident)], ident)
        calls = (('spawn_agent', {'task_name': 'plain', 'model': self.child, 'fork_turns': 'none',
                                  'reasoning_effort': EFFORT, 'message': 'Reply exactly ' + MARKER}),
                 ('wait_agent', {'timeout_ms': 120000}))
        return sse([{'type': 'function_call', 'namespace': 'collaboration', 'name': name,
                     'id': f'fc_{ident}_{n}', 'call_id': f'call_{ident}_{n}',
                     'arguments': json.dumps(arguments)}
                    for n, (name, arguments) in enumerate(calls)], ident)


def serve(probe):
    """Loopback upstream for the client. Codex retries a refusal's 409
    (docs/compatibility.md); a stopped probe refuses the retry locally too."""
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *unused):
            pass

        def reply(self, status, kind, body):
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass

        def do_GET(self):
            # The router's answers: 426 moves a websocket attempt to HTTP
            # streaming (a 404 fails the turn), 404 for any other route.
            if self.headers.get('Upgrade', '').lower() == 'websocket':
                return self.reply(426, 'application/json', b'{"error":{"code":"WEBSOCKET_REJECTED"}}')
            self.reply(404, 'application/json', b'{}')

        def do_POST(self):
            try:
                raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                if self.headers.get('Content-Encoding') == 'zstd':
                    raw = zstd.decompress(raw)
                result = probe.respond(json.loads(raw), self.headers, self.path)
            except Exception as exc:
                if hasattr(exc, 'close'):
                    exc.close()  # A refused call's HTTPError holds its response open.
                probe.errors.append({'reason': str(exc) if str(exc) in KNOWN else type(exc).__name__,
                                     'status': getattr(exc, 'code', None)})
                return self.reply(409, 'application/json',
                                  b'{"error":{"message":"synthetic parent-switch probe refused"}}')
            self.reply(200, 'application/json' if self.path.endswith('/compact')
                       else 'text/event-stream', result)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def catalogue_row(slug, installed):
    if installed is None:
        entry = by_slug(slug)
        row = external_entry(entry) if entry else subscription_stub(slug)
    elif slug in installed:
        row = dict(installed[slug])
    else:
        raise SystemExit('live catalogue has no row: ' + slug)
    row['prefer_websockets'] = False
    return row


def sandboxed(command, port, folder):
    """Wrap the live client so it can reach only this probe's port, or refuse."""
    profile = Path(folder) / 'network.sb'
    profile.write_text('(version 1)\n(allow default)\n(deny network-outbound)\n'
                       f'(allow network-outbound (remote ip "localhost:{port}"))\n')
    wrapper = [SANDBOX, '-f', str(profile)]
    try:  # Prove the profile applies before any client starts under it.
        applied = subprocess.run([*wrapper, '/usr/bin/true'], capture_output=True,
                                 timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        applied = False
    if not applied:
        raise RuntimeError('network sandbox unavailable')
    return [*wrapper, *command]


def step(app, thread, method, params, live):
    """Start one parent turn or compaction and wait for it; returns its answer."""
    deadline = time.monotonic() + (300 if live else 60)
    app.rpc(method, {'threadId': thread, **params})
    answer = ''
    while True:
        try:
            event = app.next_event(deadline=deadline)
        except queue.Empty:
            raise RuntimeError('parent turn timed out') from None
        found = event.get('params') or {}
        if found.get('threadId') != thread:
            continue  # The child's own events.
        if event.get('method') == 'item/completed' and found['item'].get('type') == 'agentMessage':
            answer = found['item'].get('text', '')
        if event.get('method') == 'turn/completed':
            if found['turn'].get('status') != 'completed':
                raise RuntimeError('parent turn failed')
            return answer


def drive(args, probe, parents, compact):
    """Run the parent sequence; facts land on `probe` even when a step fails."""
    installed = None
    if args.live:
        rows = json.loads((INSTALLED / 'mixed-models.json').read_text())['models']
        installed = {row['slug']: row for row in rows}
    models = [catalogue_row(slug, installed) for slug in dict.fromkeys((*parents, probe.child))]
    server = serve(probe)
    try:
        with tempfile.TemporaryDirectory(prefix='parent-switch-probe-') as temp:
            catalog = Path(temp) / 'catalog.json'
            catalog.write_text(json.dumps({'models': models}))
            base = f'http://127.0.0.1:{server.server_port}/v1'
            # Plan 185 step 3's set: nothing that writes or reaches beyond the probe.
            config = {'model_catalog_json': str(catalog), 'project_doc_max_bytes': 0,
                      'approval_policy': 'never', 'sandbox_mode': 'read-only',
                      'web_search': 'disabled', 'mcp_servers': {}, 'notify': [],
                      'features.multi_agent': True, 'features.multi_agent_v2': True,
                      **{'features.' + name: False for name in
                         ('apps', 'plugins', 'memories', 'code_mode', 'shell_tool', 'shell_snapshot',
                          'hooks', 'in_app_local_automation', 'in_app_updates', 'remote_plugin')}}
            if args.live:
                # Ambient Codex home: the client reads its own sign-in, nothing
                # is copied, and only these overrides point it at this probe.
                provider = 'openai'
                config.update(model_provider=provider, openai_base_url=base)
                env = scrub_env(os.environ, AGENT_HANDOFFS)
            else:
                provider = 'probe'
                config.update({'model_provider': provider,
                               'model_providers.probe.name': 'Synthetic loopback',
                               'model_providers.probe.base_url': base,
                               'model_providers.probe.wire_api': 'responses',
                               'model_providers.probe.requires_openai_auth': False,
                               'model_providers.probe.supports_websockets': False})
                env = scrub_env(os.environ, AGENT_HANDOFFS, inject={'CODEX_HOME': temp})
            command = [args.codex, 'app-server', '--stdio']
            for key, value in config.items():
                command += ['-c', key + '=' + json.dumps(value)]
            if args.live:
                command = sandboxed(command, server.server_port, temp)
            app = AppServer(command, cwd=temp, env=env, stderr=subprocess.PIPE)
            try:
                app.rpc('initialize', {'clientInfo': {'name': 'parent_switch_probe', 'version': '1'},
                                       'capabilities': {'experimentalApi': True}})
                app.send({'method': 'initialized', 'params': {}})
                thread = app.rpc('thread/start', {
                    'model': parents[0], 'modelProvider': provider, 'cwd': temp,
                    'ephemeral': True, 'approvalPolicy': 'never', 'sandbox': 'read-only',
                    'baseInstructions': 'Synthetic collaboration protocol test. No files or other tools.',
                    'developerInstructions': 'Use only the collaboration tools the user names.'})['thread']['id']

                def turn(model, text):
                    return step(app, thread, 'turn/start', {'model': model, 'effort': EFFORT, 'input': [
                        {'type': 'text', 'text': text, 'text_elements': []}]}, args.live)

                turn(parents[0], spawn_prompt(probe.child))
                if args.live and not probe.live_calls:
                    raise RuntimeError('client bypassed the probe')
                if compact:
                    step(app, thread, 'thread/compact/start', {}, args.live)
                    probe.compacted = True
                for model in parents[1:]:
                    probe.switched.append([model, MARKER in turn(model, RECALL)])
            finally:
                try:  # Closing its input lets the client clean up after itself.
                    app.process.stdin.close()
                    app.process.wait(timeout=10)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    pass
                app.close()  # Terminates only a client that is still running.
    finally:
        server.shutdown()
        server.server_close()


def summary(cell, parents, probe):
    """The printed record: identities, counts, markers and shapes only."""
    if probe.errors:
        result = 'fail'
    elif by_slug(probe.child) is None and probe.child_reply != 'encrypted':
        result = 'shape not produced'
    elif (not probe.child_marker or probe.child_reply == 'missing'
          or not (probe.compacted or all(recalled for _, recalled in probe.switched))):
        result = 'fail'  # Without compaction the switched parent must recall the reply.
    else:
        result = 'pass'
    return {'cell': cell, 'live': probe.live, 'parents': list(parents), 'child': probe.child,
            'effort': EFFORT, 'calls': probe.live_calls if probe.live else len(probe.identities),
            'max_live_calls': probe.call_limit if probe.live else None, 'tokens': probe.tokens,
            'max_live_tokens': probe.token_limit if probe.live else None, 'identities': probe.identities,
            'markers': {'child': probe.child_marker, 'switched': probe.switched},
            'child_reply': probe.child_reply, 'compacted': probe.compacted,
            'errors': probe.errors, 'result': result}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cell', choices=sorted(CELLS), required=True)
    parser.add_argument('--parents', help='comma-separated parent sequence replacing the preset')
    parser.add_argument('--codex', default=codex_bin())
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--max-live-calls', type=int, default=0)
    parser.add_argument('--max-live-tokens', type=int, default=0)
    args = parser.parse_args(argv)
    if args.live and not 1 <= args.max_live_calls <= 24:
        parser.error('--live requires --max-live-calls between 1 and 24')
    if args.live and not 1 <= args.max_live_tokens <= MAX_LIVE_TOKENS:
        parser.error(f'--live requires --max-live-tokens between 1 and {MAX_LIVE_TOKENS}')
    parents, child, compact = CELLS[args.cell]
    parents = tuple(args.parents.split(',')) if args.parents else parents
    if len(parents) < 2:
        parser.error('--parents needs at least two models')
    probe = SwitchProbe(args.live, args.max_live_calls, child, token_limit=args.max_live_tokens)
    try:
        drive(args, probe, parents, compact)
    except Exception as exc:
        probe.errors.append({'reason': str(exc) if str(exc) in KNOWN else type(exc).__name__})
    record = summary(args.cell, parents, probe)
    print(json.dumps(record), flush=True)
    return 1 if record['result'] == 'fail' else 0


if __name__ == '__main__':
    raise SystemExit(main())
