"""Real Codex custom-tool switching; offline by default, bounded with --live.

Only synthetic files and prompts are used. Live mode uses the client's existing
sign-in and the installed router's credential reader without copying credentials.
The candidate router runs on a disposable loopback listener; installed state and
client settings are never written. Output contains counters and identities only.
The live client can reach only this listener; unavailable isolation refuses startup.
"""
import argparse
import copy
import http.client
import json
import os
import secrets
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_router import catalogue, outbound, transport, upstream, wire_shape
from ai_router.credentials import Credentials
from ai_router.history_items import block_text
from ai_router.registry import by_slug
from tools.appserver_probe import AppServer, AGENT_HANDOFFS, CONTEXT_BUDGET, codex_bin, failure_shape, scrub_env
from tools.probe_agent_handoffs import frame_data, message, sse
from tools.probe_context_budget import Reply
from tools.probe_history_switch import Upstream
from tools.probe_parent_switch import sandboxed

EXTERNAL, NATIVE = 'deepseek/deepseek-v4.1-flash-1017', 'gpt-6.1-sol'
MARKER = 'SYNTH_CUSTOM_SWITCH_829'
PATCH = '*** Begin Patch\n*** Update File: note.txt\n@@\n-alpha\n+beta\n*** End Patch\n'
ECHO_PROMPT = 'Call echo_probe with value "probe". Return its result.'
PATCH_PROMPT = 'Use apply_patch once to change alpha to beta in note.txt. Stop.'
RECALL_PROMPT = 'Without tools, return the exact marker from echo_probe, then the final word in note.txt.'
MAX_CALLS, MAX_INPUT, MAX_OUTPUT, TOKEN_STOP, TIMEOUT = 10, 32768, 1024, 16000, 180


def probe_tools(tools):
    """The synthetic task needs only its echo function and freeform patch."""
    kept = []
    for tool in tools:
        if tool.get('type') == 'namespace':
            nested = probe_tools(tool.get('tools', []))
            if nested:
                kept.append({**tool, 'tools': nested})
        elif (tool.get('name') in ('echo_probe', 'apply_patch')
              or (tool.get('description') or '').startswith('functions.apply_patch:')):
            kept.append(tool)
    return kept


def probe_input(items):
    """Keep synthetic turns and tool history, excluding ambient agent instructions."""
    kept = []
    for item in items:
        if item.get('type') == 'additional_tools':
            item = {**item, 'tools': probe_tools(item['tools'])}
        elif item.get('role') in ('user', 'developer'):
            text = block_text(item.get('content'))
            if text not in (ECHO_PROMPT, PATCH_PROMPT, RECALL_PROMPT) and not text.lstrip().startswith('<model_switch>'):
                continue
        kept.append(item)
    return kept


class Budget:
    """Every actual send, including router repair, shares these limits."""
    def __init__(self, send):
        self.send, self.calls, self.tokens, self.stopped = send, 0, 0, False
        self.deadline = time.monotonic() + TIMEOUT
        self.reports = []
        self.refused = None
        self.lock = threading.Lock()

    def __call__(self, conn, prepared, metrics):
        payload = wire_shape.decode_wire(prepared.body)
        if not payload or payload.get('model') not in (EXTERNAL, NATIVE):
            self.refused = 'model'
            raise ValueError('custom probe model budget')
        if isinstance(payload.get('tools'), list):
            payload['tools'] = probe_tools(payload['tools'])
        payload['instructions'] = ('Synthetic protocol test. Follow the latest user request. '
                                   'Use only the explicitly requested tool; otherwise answer without tools.')
        if isinstance(payload.get('input'), list):
            payload['input'] = probe_input(payload['input'])
        payload['max_output_tokens'] = min(payload.get('max_output_tokens', MAX_OUTPUT), MAX_OUTPUT)
        body = json.dumps(payload).encode()
        with self.lock:
            remaining = self.deadline - time.monotonic()
            if (self.stopped or self.calls >= MAX_CALLS or self.tokens >= TOKEN_STOP
                    or remaining <= 0 or len(body) > MAX_INPUT):
                self.refused = self.refused or ('input' if len(body) > MAX_INPUT else 'send')
                self.stopped = True
                self.refused_bytes = len(body)
                raise ValueError('custom probe send budget')
            self.calls += 1
        prepared.body, prepared.decoded_body_bytes = body, len(body)
        prepared.headers = {k: v for k, v in prepared.headers.items()
                            if k.lower() not in ('content-encoding', 'accept-encoding', 'content-length')}
        prepared.headers['Accept-Encoding'] = 'identity'
        conn.timeout = min(conn.timeout or remaining, remaining)
        if conn.sock is not None:
            conn.sock.settimeout(conn.timeout)
        response, headers_done = self.send(conn, prepared, metrics)
        raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            self.stopped = True
            raise ValueError('custom probe response budget')
        completed = None
        for frame in raw.replace(b'\r\n', b'\n').split(b'\n\n'):
            data = frame_data(frame)
            if data and data != b'[DONE]':
                event = json.loads(data)
                if event.get('type') == 'response.completed':
                    completed = event.get('response')
        usage = (completed or {}).get('usage') or {}
        tokens = usage.get('total_tokens')
        self.stopped |= response.status != 200 or type(tokens) is not int or tokens <= 0
        self.tokens += tokens if type(tokens) is int and tokens > 0 else 0
        self.reports.append({'requested_model': payload['model'], 'requested_effort':
            (payload.get('reasoning') or {}).get('effort'), 'status': response.status,
            'served_model': (completed or {}).get('model'), 'reported_effort':
            ((completed or {}).get('reasoning') or {}).get('effort'), 'tokens': tokens})
        buffered = Reply(response.status, raw, response.getheader('Content-Type'))
        buffered.headers = response.getheaders()
        return buffered, headers_done


class CustomUpstream(Upstream):
    """Script the real client's function, patch, native replay and return."""
    def __init__(self):
        super().__init__('custom')

    def respond(self, payload):
        self.calls += 1
        self.models.append(payload['model'])
        if self.calls in (1, 3):
            target = 'echo_probe' if self.calls == 1 else 'apply_patch'
            tool = next(t for t in payload['tools'] if t.get('name') == target
                        or (t.get('description') or '').startswith('functions.' + target + ':'))
            arguments = {'value': 'probe'} if self.calls == 1 else {'input': PATCH}
            output = [{'type': 'function_call', 'id': 'fc_synthetic_' + str(self.calls),
                'call_id': 'call_synthetic_' + str(self.calls), 'name': tool['name'],
                'arguments': json.dumps(arguments)}]
        else:
            output = [message(MARKER + (' beta' if self.calls >= 5 else ''), 'synthetic_' + str(self.calls))]
        if payload['model'] == NATIVE:
            custom = [i for i in payload['input'] if i.get('type') == 'custom_tool_call']
            assert len(custom) == 1 and custom[0]['id'] == 'ctc_synthetic_3'
        return Reply(200, sse(output, 'synthetic_' + str(self.calls)), 'text/event-stream')


def turn(app, thread, model, text, deadline, facts):
    app.rpc('turn/start', {'threadId': thread, 'model': model, 'effort': 'low',
        'input': [{'type': 'text', 'text': text, 'text_elements': []}]})
    answer = ''
    while True:
        event = app.next_event(deadline=deadline)
        params = event.get('params') or {}
        if event.get('method') == 'error':
            facts.setdefault('client_failures', []).append(failure_shape(event, params.get('error') or params))
        if event.get('method') == 'item/tool/call':
            assert params['tool'] == 'echo_probe' and params['arguments'] == {'value': 'probe'}
            facts['function_calls'] += 1
            assert facts['function_calls'] == 1
            app.send({'id': event['id'], 'result': {'success': True,
                'contentItems': [{'type': 'inputText', 'text': MARKER}]}})
        if event.get('method') == 'item/completed':
            item = params.get('item') or {}
            if item.get('type') == 'agentMessage':
                answer = item.get('text', '')
            if item.get('type') == 'fileChange':
                facts['file_changes'] += 1
        if event.get('method') == 'turn/completed':
            if params['turn']['status'] != 'completed':
                error = params['turn'].get('error') or {}
                facts['client_error'] = error.get('codexErrorInfo', 'unverified')
                try:
                    facts['router_error'] = json.loads(error.get('message', '{}')).get('error', {}).get('code')
                except ValueError:
                    pass
            assert params['turn']['status'] == 'completed', 'custom probe turn failed'
            return answer


def run(binary, live=False):
    facts = {'live': live, 'function_calls': 0, 'file_changes': 0,
             'native_replay': False, 'legacy_injected': False, 'switch_back': False}
    with tempfile.TemporaryDirectory(prefix='custom-switch-') as folder:
        home = Path(folder)
        (home / 'note.txt').write_text('alpha\n')
        state = {'port': 0, 'token': secrets.token_urlsafe(32) if live else 'synthetic-custom-token',
                 'openai_models': [NATIVE]}
        credentials = SimpleNamespace(key_for=lambda _provider=None: 'synthetic-test-key')
        if live:
            installed = Path.home() / '.codex/mixed-model-router'
            source = json.loads((installed / 'mixed-router-state.json').read_text())
            state = {**source, **state}
            credentials = Credentials(source, home=installed, env={})
        fake = CustomUpstream()
        budget = Budget(transport.post_with_phases)
        original = outbound.project_subscription

        def subscription(payload, *args, **kwargs):
            custom = [i for i in payload.get('input', []) if i.get('type') == 'custom_tool_call']
            if custom:
                assert all(i.get('id', '').startswith('ctc_') for i in custom), 'client saved wrong custom ID'
                facts['native_replay'] = True
                if not live:
                    payload = copy.deepcopy(payload)
                    for item in payload['input']:
                        if item.get('type') == 'custom_tool_call':
                            item['id'] = 'fc_' + item['id'][4:]
                    facts['legacy_injected'] = True
            return original(payload, *args, **kwargs)

        from contextlib import ExitStack
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {'ROUTER_HOME': str(home / 'router')}))
            if live:
                stack.enter_context(patch.object(transport, 'post_with_phases', budget))
            else:
                stack.enter_context(patch.object(http.client, 'HTTPSConnection', fake.connection))
            stack.enter_context(patch.object(outbound, 'project_subscription', subscription))
            from ai_router.router import Router
            def capture(event, **fields):
                if event in ('request_rejected', 'request_failed', 'upstream_rejected'):
                    facts.setdefault('router_failures', []).append({k: fields.get(k)
                        for k in ('code', 'status', 'model')})
            stack.enter_context(patch('ai_router.router.log_event', capture))
            server = Router(state, credentials=credentials)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            stack.callback(server.server_close)
            stack.callback(server.shutdown)
            rows = [catalogue.external_entry(by_slug(EXTERNAL)), catalogue.subscription_stub(NATIVE)]
            rows[0]['apply_patch_tool_type'] = 'freeform'
            catalog = home / 'catalog.json'
            catalog.write_text(json.dumps({'models': rows}))
            config = {'model_provider': 'openai', 'openai_base_url':
                f'http://127.0.0.1:{server.server_port}/{state["token"]}/backend-api/codex',
                'model_catalog_json': str(catalog), 'mcp_servers': {}, 'notify': [], 'web_search': 'disabled',
                'project_doc_max_bytes': 0, 'approval_policy': 'never', 'sandbox_mode': 'workspace-write',
                'developer_instructions': 'Synthetic protocol test only.',
                **{'features.' + name: False for name in ('apps', 'plugins', 'memories', 'shell_tool',
                    'code_mode', 'multi_agent', 'hooks', 'shell_snapshot', 'in_app_local_automation',
                    'in_app_updates', 'remote_compaction_v2', 'token_budget', 'remote_plugin')}}
            command = [binary, 'app-server', '--stdio']
            for key, value in config.items():
                command += ['-c', key + '=' + json.dumps(value)]
            env = scrub_env(os.environ, AGENT_HANDOFFS) if live else scrub_env(
                os.environ, CONTEXT_BUDGET, inject={'CODEX_HOME': folder,
                    'OPENAI_API_KEY': 'synthetic-test-key', 'OPENAI_BASE_URL': config['openai_base_url']})
            if live:
                command = sandboxed(command, server.server_port, folder)
            app = AppServer(command, cwd=home, env=env, stderr=subprocess.PIPE)
            try:
                app.rpc('initialize', {'clientInfo': {'name': 'custom_switch_probe', 'version': '1'},
                    'capabilities': {'experimentalApi': True}})
                app.send({'method': 'initialized', 'params': {}})
                if live:
                    account = app.rpc('account/read', {'refreshToken': False})
                    assert (account.get('account') or {}).get('type') == 'chatgpt'
                thread = app.rpc('thread/start', {'model': EXTERNAL, 'modelProvider': 'openai',
                    'cwd': folder, 'ephemeral': True, 'approvalPolicy': 'never', 'sandbox': 'workspace-write',
                    'baseInstructions': 'Synthetic protocol test. Use only the tool explicitly requested.',
                    'dynamicTools': [{'type': 'function', 'name': 'echo_probe', 'description': 'Synthetic echo.',
                        'inputSchema': {'type': 'object', 'properties': {'value': {'type': 'string'}},
                            'required': ['value'], 'additionalProperties': False}}]})['thread']['id']
                deadline = budget.deadline
                facts['stage'] = 'function'
                turn(app, thread, EXTERNAL, ECHO_PROMPT, deadline, facts)
                facts['stage'] = 'custom'
                turn(app, thread, EXTERNAL, PATCH_PROMPT, deadline, facts)
                assert (home / 'note.txt').read_text().strip() == 'beta'
                assert facts['function_calls'] == facts['file_changes'] == 1
                facts['stage'] = 'native_recall'
                answer = turn(app, thread, NATIVE, RECALL_PROMPT, deadline, facts)
                assert MARKER in answer and 'beta' in answer, 'native recall mismatch'
                facts['stage'] = 'external_recall'
                answer = turn(app, thread, EXTERNAL, RECALL_PROMPT, deadline, facts)
                assert MARKER in answer and 'beta' in answer, 'external recall mismatch'
                facts['switch_back'] = True
                assert facts['native_replay'] and not budget.stopped and not fake.failures
                assert all(r['served_model'] in (None, r['requested_model'])
                           and r['reported_effort'] in (None, r['requested_effort']) for r in budget.reports)
                if not live:
                    assert facts['legacy_injected'] and fake.calls == 6
                facts.update(passed=True, upstream_calls=budget.calls if live else fake.calls,
                    tokens=budget.tokens if live else None, reports=budget.reports,
                    client_version=subprocess.check_output([binary, '--version'], text=True).strip())
            except Exception as exc:
                facts.update(passed=False, error_type=type(exc).__name__,
                    upstream_calls=budget.calls if live else fake.calls,
                    tokens=budget.tokens if live else None, reports=budget.reports,
                    budget_refused=budget.refused, refused_bytes=getattr(budget, 'refused_bytes', None))
            finally:
                app.close()
                upstream.clear_refusals()
    return facts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--codex-bin', default=codex_bin())
    args = parser.parse_args()
    try:
        result = run(args.codex_bin, args.live)
    except Exception as exc:
        print(json.dumps({'passed': False, 'live': args.live, 'error_type': type(exc).__name__}))
        return 1
    print(json.dumps(result))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
