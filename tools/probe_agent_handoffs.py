"""Isolated native-client handoff proof; live mode requires an explicit call cap.

Children are scripted sinks. --live sends only the synthetic parent to the
installed router, testing real schema acceptance and canonical replay.
No request content, ciphertext, credentials or private URLs are printed.
"""
import argparse
from compression import zstd
import io
import json
import logging
import os
from pathlib import Path
import queue
import shutil
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_router.agent_handoffs import add_plaintext_tools
from ai_router import handoff_response
from ai_router.catalogue import external_entry, subscription_stub
from ai_router.registry import by_slug
from tools.appserver_probe import AppServer, AGENT_HANDOFFS, codex_bin, scrub_env

PARENT = 'gpt-6-astra'
CHILD = 'deepseek/deepseek-v4.1-flash'
MARKERS = ('SYNTH_066_INITIAL', 'SYNTH_066_FOLLOWUP', 'SYNTH_066_MESSAGE')
ALL_MARKERS = (*MARKERS, 'SYNTH_NATIVE_CONTROL')


def message(text, ident):
    return {'type': 'message', 'id': 'msg_' + ident, 'role': 'assistant',
            'content': [{'type': 'output_text', 'text': text}]}


def frame_data(frame):
    return b'\n'.join(line[5:].lstrip() for line in frame.splitlines() if line.startswith(b'data:'))


def sse(items, ident):
    response = {'id': 'resp_' + ident, 'status': 'in_progress', 'output': []}
    events = [{'type': 'response.created', 'response': response}]
    for index, item in enumerate(items):
        for phase in ('added', 'done'):
            events.append({'type': 'response.output_item.' + phase,
                           'output_index': index, 'item': item})
    events.append({'type': 'response.completed', 'response': {
        **response, 'status': 'completed', 'output': items,
        'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}})
    return b''.join(b'data: ' + json.dumps(e).encode() + b'\n\n' for e in events)


class Probe:
    required_final = None
    live_prompts = None

    def __init__(self, live, call_limit, live_children=False):
        self.live, self.call_limit = live, call_limit
        self.live_children = live_children
        self.live_calls = self.parent_calls = 0
        self.alias_call_ids = set()
        self.lock = threading.Lock()
        self.facts = {'markers': [], 'encrypted_child': False,
                      'canonical_replay': False, 'alias_emitted': False, 'calls': [], 'child_shapes': [],
                      'tool_failures': [], 'replies': []}
        self.errors = []
        self.upstream = None
        if live:
            home = Path.home() / '.codex/mixed-model-router'
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.upstream = (f'http://127.0.0.1:{state["port"]}/{state["token"]}'
                             '/backend-api/codex/responses')

    def scripted(self, body, ordinal):
        if body.get('model') != PARENT:
            agent_items = [i for i in body.get('input', []) if i.get('type') == 'agent_message']
            self.facts['child_shapes'].append({'model': body.get('model'),
                'blocks': [[b.get('type') for b in item.get('content', [])] for item in agent_items]})
            text = '\n'.join(b.get('text', '') for item in agent_items
                             for b in item.get('content', []) if b.get('type') == 'input_text')
            for marker in MARKERS:
                if marker in text and marker not in self.facts['markers']:
                    self.facts['markers'].append(marker)
            if body.get('model') == CHILD and any(b.get('type') == 'encrypted_content'
                    for item in agent_items for b in item.get('content', [])):
                raise ValueError('plaintext child received opaque content')
            if body.get('model') != CHILD:
                self.facts['encrypted_child'] |= any(
                    b.get('type') == 'encrypted_content'
                    for item in agent_items for b in item.get('content', []))
            return sse([message(' '.join(m for m in MARKERS if m in text), str(ordinal))], str(ordinal))
        step = self.parent_calls
        self.parent_calls += 1
        calls = [
            ('spawn_agent', {'task_name': 'plain', 'model': CHILD, 'fork_turns': 'none', 'reasoning_effort': 'max', 'message': MARKERS[0]}),
            ('followup_task', {'target': 'plain', 'message': MARKERS[1]}),
            ('send_message', {'target': 'plain', 'message': MARKERS[2]}),
            ('followup_task', {'target': 'plain', 'message': 'SYNTH_WAKE_READ_QUEUED_MESSAGE'}),
            ('spawn_agent', {'task_name': 'native', 'model': 'gpt-5.6-sol', 'fork_turns': 'none', 'message': 'SYNTH_OPAQUE_CONTROL'}),
        ]
        if step >= len(calls):
            return sse([message('SYNTH_DONE', str(ordinal))], str(ordinal))
        name, arguments = calls[step]
        item = {'type': 'function_call', 'namespace': 'collaboration_plaintext' if step < 4 else 'collaboration',
                'name': name, 'id': 'fc_' + str(ordinal), 'call_id': 'call_' + str(ordinal),
                'arguments': json.dumps(arguments)}
        return sse([item], str(ordinal))

    def respond(self, body, headers, ordinal, path='/responses'):
        for item in body.get('input', []):
            if item.get('type') == 'function_call' and item.get('namespace') == 'collaboration':
                self.facts['canonical_replay'] |= item.get('call_id') in self.alias_call_ids
            if item.get('type') == 'function_call_output':
                output = item.get('output')
                if isinstance(output, str) and ('error' in output.lower() or 'failed' in output.lower()):
                    safe = 'tool_output_reported_failure'
                    if safe not in self.facts['tool_failures']:
                        self.facts['tool_failures'].append(safe)
        # Collaboration tools only; the turn log is structural, no payload.
        offered = body.get('tools', []) if isinstance(body.get('tools'), list) else []
        self.facts.setdefault('turns', []).append({
            'model': body.get('model'),
            'tool_namespaces': sorted({t.get('name') for t in offered if isinstance(t, dict)}),
            'namespace_tools': {t.get('name'): [u.get('name') for u in t.get('tools', [])]
                                for t in offered
                                if isinstance(t, dict) and t.get('type') == 'namespace'},
            'input_kinds': sorted({i.get('type') for i in body.get('input', [])
                                   if isinstance(i, dict)}),
        })
        containers = [body, *(i for i in body.get('input', [])
            if i.get('type') == 'additional_tools' and i.get('role') == 'developer')]
        self.facts['turns'][-1]['tool_location'] = (
            'additional_tools' if len(containers) > 1 else 'tools')
        for container in containers:
            if isinstance(container.get('tools'), list):
                container['tools'] = [t for t in container['tools']
                                      if t.get('name') == 'collaboration']
        if self.live_children:
            if body.get('model') != PARENT:
                self.scripted(body, ordinal)  # Observe input shape only; discard scripted reply.
            raw = self.forward(body, headers, path)
            for frame in raw.split(b'\n\n'):
                data = frame_data(frame)
                if not data or data == b'[DONE]':
                    continue
                event = json.loads(data)
                if event.get('type') != 'response.output_item.done':
                    continue
                item = event.get('item', {})
                if item.get('type') == 'function_call':
                    try:
                        call_args = json.loads(item.get('arguments') or '{}')
                    except ValueError:
                        call_args = {}
                    self.facts['calls'].append({
                        'model': body.get('model'), 'namespace': item.get('namespace'),
                        'name': item.get('name'),
                        'encrypted_fields': ('absent' if item.get('encrypted_function_args', 'absent') == 'absent'
                            else ('empty' if item.get('encrypted_function_args') == [] else 'nonempty')),
                        'target': call_args.get('target'), 'task': call_args.get('task_name'),
                        'child_model': call_args.get('model')})
                if item.get('encrypted_function_args') == []:
                    self.alias_call_ids.add(item.get('call_id'))
                    self.facts['alias_emitted'] = True
                if body.get('model') != PARENT and item.get('type') == 'message':
                    text = ''.join(b.get('text', '') for b in item.get('content', []))
                    for marker in ALL_MARKERS:
                        if marker in text and marker not in self.facts['replies']:
                            self.facts['replies'].append(marker)
            return raw
        body, aliases = add_plaintext_tools(body)
        if body.get('model') == PARENT and not aliases:
            raise ValueError('parent collaboration aliases were not advertised')
        if self.live and body.get('model') == PARENT:
            raw = self.forward(body, headers)
        else:
            raw = self.scripted(body, ordinal)
        for frame in raw.replace(b'\r\n', b'\n').split(b'\n\n'):
            data = frame_data(frame)
            if not data or data == b'[DONE]':
                continue
            event = json.loads(data)
            if event.get('type') == 'response.output_item.done':
                item = event.get('item', {})
                if item.get('type') == 'function_call':
                    fields = item.get('encrypted_function_args', 'absent')
                    arguments = json.loads(item.get('arguments') or '{}')
                    self.facts['calls'].append({'namespace': item.get('namespace'),
                        'name': item.get('name'),
                        'encrypted_fields': 'absent' if fields == 'absent' else ('empty' if fields == [] else 'nonempty'),
                        'model': arguments.get('model'), 'fork_turns': arguments.get('fork_turns')})
                if item.get('namespace') == 'collaboration_plaintext':
                    self.facts['alias_emitted'] = True
                    self.alias_call_ids.add(item.get('call_id'))
        source = io.BytesIO(raw)
        source.getheader = lambda name, default='': 'text/event-stream'
        return b''.join(handoff_response.adapt_response(source, aliases))

    def forward(self, body, headers, path='/responses'):
        with self.lock:
            if self.live_calls >= self.call_limit:
                raise ValueError('live call limit reached')
            self.live_calls += 1
        forward = {k: v for k, v in headers.items() if k.lower() not in (
            'host', 'content-length', 'content-encoding', 'accept-encoding', 'connection')}
        forward['Accept-Encoding'] = 'identity'
        url = self.upstream + ('/compact' if path.endswith('/compact') else '')
        request = urllib.request.Request(url, data=json.dumps(body).encode(),
                                         headers=forward, method='POST')
        with urllib.request.urlopen(request, timeout=120) as response:
            if response.getheader('Content-Encoding', 'identity') != 'identity':
                raise ValueError('unexpected live response encoding')
            return response.read()


def run(args, probe_type=Probe):
    if args.live and not 1 <= args.max_live_calls <= 24:
        raise ValueError('--live requires --max-live-calls between 1 and 24')
    if args.live_children and not args.live:
        raise ValueError('--live-children requires --live')
    if getattr(args, 'installed', False) and (not args.live_children or args.lifecycle):
        raise ValueError('--installed requires --live-children without --lifecycle')
    if getattr(args, 'child', CHILD) == getattr(args, 'parent', PARENT):
        raise ValueError('--parent and --child must name different rows')
    probe = probe_type(args.live, args.max_live_calls, args.live_children)
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *unused):
            pass

        def do_GET(self):
            # Match the router's unsupported route (404) so Codex falls back.
            self.send_response(404)
            self.send_header('Content-Length', '0')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.close_connection = True

        def do_POST(self):
            try:
                raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                if self.headers.get('Content-Encoding') == 'zstd':
                    with zstd.ZstdFile(io.BytesIO(raw)) as stream:
                        raw = stream.read()
                body = json.loads(raw)
                with probe.lock:
                    self.server.ordinal += 1
                    ordinal = self.server.ordinal
                result = probe.respond(body, self.headers, ordinal, self.path)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json' if self.path.endswith('/compact') else 'text/event-stream')
            except Exception as exc:
                known = ('live call limit reached', 'unexpected live response encoding',
                         'plaintext child received opaque content', 'encrypted plaintext collaboration call',
                         'unadvertised plaintext collaboration call')
                reason = str(exc) if str(exc) in known else 'protocol_or_transport_failure'
                probe.errors.append({'type': type(exc).__name__, 'status': getattr(exc, 'code', None), 'reason': reason})
                result = b'{"error":{"message":"synthetic handoff probe failed"}}'
                self.send_response(409 if isinstance(exc, ValueError) else 502)
                self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(result)))
            self.end_headers()
            try:
                self.wfile.write(result)
            except OSError:
                pass

    with tempfile.TemporaryDirectory(prefix='agent-handoff-probe-') as temp:
        root = Path(temp)
        candidate = None
        if args.live_children and not getattr(args, 'installed', False):
            from ai_router.credentials import Credentials
            from ai_router.router import Router
            from ai_router.runtime import LOG
            class Events(logging.Handler):
                def emit(self, record):
                    row = json.loads(record.getMessage())
                    if row.get('event') in ('transport_error', 'request_rejected', 'preparation_error'):
                        probe.errors.append({key: row.get(key) for key in
                            ('event', 'status', 'code', 'error_type', 'location')})
            LOG.addHandler(Events())
            LOG.setLevel(logging.INFO)
            home = Path.home() / '.codex/mixed-model-router'
            state = json.loads((home / 'mixed-router-state.json').read_text())
            candidate = Router({**state, 'port': 0, 'token': secrets.token_urlsafe(24)},
                               credentials=Credentials(state, home))
            threading.Thread(target=candidate.serve_forever, daemon=True).start()
            probe.upstream = (f'http://127.0.0.1:{candidate.server_port}/'
                f'{candidate.state["token"]}/backend-api/codex/responses')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.ordinal = 0
        threading.Thread(target=server.serve_forever, daemon=True).start()
        child = external_entry(by_slug(CHILD))
        child['prefer_websockets'] = False
        if args.live:
            installed = json.loads((Path.home() / '.codex/mixed-model-router'
                                    / 'mixed-models.json').read_text())
            rows = {m['slug']: m for m in installed['models']}
            if PARENT not in rows:
                raise SystemExit(f'live catalogue has no parent row: {PARENT}')
            parent = dict(rows[PARENT])
            native = dict(rows['gpt-5.6-sol'])
        else:
            parent = (subscription_stub(PARENT) if PARENT.startswith('gpt-')
                      else external_entry(by_slug(PARENT)))
            parent['use_responses_lite'] = args.wire_mode == 'lite'
            parent['multi_agent_version'] = 'v2'
            native = dict(parent, slug='gpt-5.6-sol')
        probe.facts['parent_wire_mode'] = 'lite' if parent['use_responses_lite'] else 'classic'
        probe.facts['child_effort'] = 'max'
        catalog = root / 'catalog.json'
        catalog.write_text(json.dumps({'models': [parent, child, native]}))
        if args.live:
            auth = root / 'auth.json'
            auth.touch(mode=0o600)
            shutil.copyfile(Path.home() / '.codex/auth.json', auth)
        provider = 'openai' if args.live else 'probe'
        config = {'model_provider': provider, 'model_catalog_json': str(catalog),
            'project_doc_max_bytes': 0, 'approval_policy': 'never', 'sandbox_mode': 'read-only',
            'features.multi_agent': True, 'features.multi_agent_v2': True,
            'features.apps': False, 'features.memories': False, 'features.code_mode': False,
            'features.shell_tool': False, 'web_search': 'disabled'}
        base = f'http://127.0.0.1:{server.server_port}/v1'
        if args.live:
            config['openai_base_url'] = base
        else:
            config.update({'model_providers.probe.name': 'Synthetic loopback',
                'model_providers.probe.base_url': base, 'model_providers.probe.wire_api': 'responses',
                'model_providers.probe.requires_openai_auth': False,
                'model_providers.probe.supports_websockets': False})
        command = [args.codex, 'app-server', '--stdio']
        for key, value in config.items():
            command.extend(['-c', key + '=' + json.dumps(value)])
        env = scrub_env(os.environ, AGENT_HANDOFFS, inject={'CODEX_HOME': temp})
        deadline = time.monotonic() + (600 if args.live else 40)
        sequence = 0
        def record_failure(event):
            # Probe policy: every dequeued event is scanned for failures and
            # recorded via the on_event hook; the shared class stays generic.
            params = event.get('params', {})
            failure = params.get('error') if event.get('method') == 'error' else None
            if event.get('method') == 'turn/completed' and params.get('turn', {}).get('status') == 'failed':
                failure = params['turn'].get('error')
            if failure:
                if hasattr(probe, 'negotiation_failure') and probe.negotiation_failure(event, failure):
                    return
                safe = {'event': event.get('method'),
                        'code': failure.get('codexErrorInfo') if isinstance(failure, dict) else None}
                if safe not in probe.facts['tool_failures']:
                    probe.facts['tool_failures'].append(safe)
        # Piped stderr drained silently, plain terminate, ambient-adjacent
        # scrub: the shared AppServer default. This probe keeps its own reply
        # loop and never calls the shared rpc, so the shared cap is untouched.
        server_process = AppServer(command, cwd=temp, env=env, stderr=subprocess.PIPE,
                                   on_event=record_failure)
        def send(value):
            server_process.send(value)
        def next_event():
            return server_process.next_event(deadline=deadline)
        def rpc(method, params):
            nonlocal sequence
            sequence += 1
            send({'id': sequence, 'method': method, 'params': params})
            while True:
                event = next_event()
                if event.get('id') == sequence:
                    if 'error' in event:
                        raise ValueError('native RPC rejected ' + method)
                    return event['result']
        try:
            rpc('initialize', {'clientInfo': {'name': 'agent_handoff_probe', 'version': '1.0'},
                              'capabilities': {'experimentalApi': True}})
            send({'method': 'initialized', 'params': {}})
            thread = rpc('thread/start', {'model': PARENT, 'modelProvider': provider,
                'cwd': temp, 'ephemeral': not args.lifecycle, 'approvalPolicy': 'never', 'sandbox': 'read-only',
                'baseInstructions': 'Synthetic collaboration protocol test. No files or external tools.',
                'developerInstructions': 'Use only the collaboration tools requested by the user.'})['thread']['id']
            prompts = [
                f'Use collaboration_plaintext.spawn_agent once to create plain on {CHILD}, '
                f'fork_turns none, reasoning_effort max, message "Reply exactly {MARKERS[0]}". Then finish this turn.',
                'The plain child uses OpenRouter. Call collaboration_plaintext.followup_task '
                f'once with target plain, message "Reply exactly {MARKERS[1]}". Then finish this turn.',
                'The plain child uses OpenRouter. Call collaboration_plaintext.send_message '
                f'once with target plain, message "Reply exactly {MARKERS[2]}". Then finish this turn.',
                'Wake the plain OpenRouter child using collaboration_plaintext.followup_task '
                'once with target plain and message "Reply with every SYNTH_066 marker from your assignments". Then finish.',
                'Use original collaboration.spawn_agent once to create native on gpt-5.6-sol, '
                'fork_turns none, message "Reply exactly SYNTH_NATIVE_CONTROL". Then finish this turn.',
                'Without tools, reply SYNTH_REPLAY_TWO.'] if args.live else ['Synthetic test.']
            if args.native_only:
                prompts = prompts[-2:]
            if probe.live_prompts:
                prompts = probe.live_prompts
            def turn(prompt_text):
                answer = []
                rpc('turn/start', {'threadId': thread, 'input': [{'type': 'text', 'text': prompt_text,
                    'text_elements': []}], 'effort': 'low'})
                while True:
                    event = next_event()
                    if event.get('method') == 'item/completed' and event.get('params', {}).get('threadId') == thread:
                        item = event['params'].get('item', {})
                        if item.get('type') == 'agentMessage':
                            answer.append(item.get('text', ''))
                    if event.get('method') == 'turn/completed' and event.get('params', {}).get('threadId') == thread:
                        if (event['params']['turn']['status'] != 'completed'
                                and not getattr(probe, 'expected_parent_failure', False)):
                            raise ValueError('synthetic parent turn failed')
                        break
                return '\n'.join(answer)
            for prompt_text in prompts:
                answer = turn(prompt_text)
                if probe.required_final and probe.required_final not in answer:
                    raise ValueError('parent did not finish after handoff recovery')
            # A non-native parent drives the plaintext path only (leg F).
            expected_replies = (
                {'SYNTH_NATIVE_CONTROL'} if args.native_only
                else set(ALL_MARKERS) if PARENT.startswith('gpt-')
                else set(MARKERS))
            settle = min(deadline, time.monotonic() + (120 if args.live_children else 2))
            while time.monotonic() < settle:
                if args.live_children and expected_replies <= set(probe.facts['replies']):
                    break
                try:
                    # Raw dequeue-and-discard, exactly as before: the
                    # failure-recording hook must not see settle events.
                    server_process.events.get(timeout=.1)
                except queue.Empty:
                    pass
            if args.lifecycle:
                if candidate is None or not expected_replies <= set(probe.facts['replies']):
                    raise ValueError('lifecycle requires completed live children')
                state, credentials = candidate.state, candidate.credentials
                state['port'] = candidate.server_port
                candidate.shutdown()
                candidate.server_close()
                candidate = Router(state, credentials=credentials)
                threading.Thread(target=candidate.serve_forever, daemon=True).start()
                turn('Without tools, reply SYNTH_AFTER_ROUTER_RESTART.')
                probe.facts['router_restart'] = True
                rpc('thread/resume', {'threadId': thread, 'model': PARENT,
                    'modelProvider': provider, 'cwd': temp})
                turn('Without tools, reply SYNTH_AFTER_RESUME.')
                probe.facts['resume'] = True
                rpc('thread/compact/start', {'threadId': thread})
                while True:
                    event = next_event()
                    if event.get('method') == 'turn/completed' and event.get('params', {}).get('threadId') == thread:
                        if event['params']['turn']['status'] != 'completed':
                            raise ValueError('synthetic compaction failed')
                        break
                for _ in range(2):
                    answer = turn('Without tools, repeat the three SYNTH_066 markers from the earlier child assignments.')
                    if not all(marker in answer for marker in MARKERS):
                        raise ValueError('post-compaction marker recall failed')
                probe.facts['compaction_and_two_turns'] = True
            verified = probe.verify() if hasattr(probe, 'verify') else None
            print(json.dumps({'live_parent': args.live, 'scripted_children': not args.live_children,
                'live_calls': probe.live_calls, **probe.facts, 'errors': probe.errors}), flush=True)
            if verified is not None:
                return 0 if verified else 1
            if args.native_only:
                return 0 if (probe.facts['encrypted_child'] and not probe.errors
                    and (not args.live_children or expected_replies <= set(probe.facts['replies']))) else 1
            if (probe.errors or not probe.facts['alias_emitted']
                    or (PARENT.startswith('gpt-') and not probe.facts['encrypted_child'])
                    or not probe.facts['canonical_replay']):
                return 1
            if args.live_children and not expected_replies <= set(probe.facts['replies']):
                return 1
            return 0 if set(probe.facts['markers']) == set(MARKERS) else 1
        except Exception as exc:
            print(json.dumps({'probe_error': type(exc).__name__, 'live_calls': probe.live_calls,
                              'facts': probe.facts, 'errors': probe.errors}), flush=True)
            return 1
        finally:
            server_process.close()
            server.shutdown()
            server.server_close()
            if candidate is not None:
                candidate.shutdown()
                candidate.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', default=codex_bin())
    parser.add_argument('--wire-mode', choices=('classic', 'lite'), default='lite',
                        help='Offline variant; live always uses installed catalogue metadata.')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--live-children', action='store_true')
    parser.add_argument('--installed', action='store_true', help='Verify the installed router, not a candidate.')
    parser.add_argument('--native-only', action='store_true')
    parser.add_argument('--lifecycle', action='store_true')
    parser.add_argument('--max-live-calls', type=int, default=0)
    # Any routed row may be the child: leg F is that row's own evidence leg, so
    # the roster owns the list; a parent may be a client-native subscription id.
    parser.add_argument('--parent', default=PARENT, help='Parent row slug for leg F.')
    parser.add_argument('--child', default=CHILD, help='Child row slug for leg F.')
    arguments = parser.parse_args()
    if by_slug(arguments.child) is None:
        parser.error('unknown child row: ' + arguments.child)
    PARENT = arguments.parent
    CHILD = arguments.child
    raise SystemExit(run(arguments))
