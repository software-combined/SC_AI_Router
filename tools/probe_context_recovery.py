"""Real Codex new_context acceptance with synthetic, read-only history.

Default is scripted and costs nothing. --live uses the selected model only
after the real client discards its assignment; --max-live-calls is required.
History retrieval is a local dynamic tool, not access to any user's tasks.
"""
import argparse
from compression import zstd
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_router.catalogue import external_entry, subscription_stub
from ai_router.context_recovery import RECOVERY_GUIDANCE
from ai_router.registry import by_slug
from tools.appserver_probe import AGENT_HANDOFFS, AppServer, codex_bin, scrub_env
from tools.probe_agent_handoffs import message, sse
from tools.probe_context_budget import Reply

MARKER = 'SYNTH_RECOVERED_ASSIGNMENT_819'
ASSIGNMENT = 'Your assignment: reply exactly ' + MARKER + '. Do not edit files.'
HISTORY_TOOL = {'type': 'namespace', 'name': 'history',
    'description': 'Read-only access to this synthetic task\'s earlier context windows.',
    'tools': [{'type': 'function', 'name': 'list_items',
        'description': 'Read earlier items from the specified context window.',
        'inputSchema': {'type': 'object', 'properties': {'window_id': {'type': 'string'}},
                        'required': ['window_id'], 'additionalProperties': False}}]}


class Scenario:
    def __init__(self, args):
        self.args = args
        self.calls = self.live_calls = self.retrievals = 0
        self.previous = None
        self.reset_verified = False
        self.failure = None
        self.connection_type = http.client.HTTPSConnection

    def connect(self, host, **kwargs):
        owner = self

        class Connection:
            real = None

            def connect(self):
                pass

            def request(self, method, path, body=None, headers=None):
                encoding = next((v for k, v in (headers or {}).items()
                                 if k.lower() == 'content-encoding'), '')
                payload = json.loads(zstd.decompress(body) if encoding == 'zstd' else body)
                owner.calls += 1
                try:
                    scripted = owner.response(payload)
                    if scripted is not None:
                        self.reply = Reply(200, scripted, 'text/event-stream')
                    else:
                        if owner.live_calls >= owner.args.max_live_calls:
                            raise AssertionError('live call cap reached')
                        owner.live_calls += 1
                        self.real = owner.connection_type(host, timeout=60)
                        self.real.request(method, path, body=body, headers=headers)
                except AssertionError as exc:
                    owner.failure = str(exc)
                    raise ValueError(str(exc)) from exc

            def getresponse(self):
                return self.real.getresponse() if self.real else self.reply

            def close(self):
                if self.real:
                    self.real.close()

        return Connection()

    def response(self, payload):
        text = json.dumps(payload.get('input', []))
        ident = str(self.calls)
        if self.calls == 1:
            assert MARKER in text, 'initial brief did not arrive'
            match = re.search(r'Current context window id: ([0-9a-f-]+)', text)
            assert match, 'client did not expose a context window'
            self.previous = match[1]
            assert any(t.get('name') == 'new_context' for t in payload.get('tools', [])), 'reset tool missing'
            return sse([{'type': 'function_call', 'name': 'new_context',
                         'call_id': 'call_reset', 'id': 'fc_reset', 'arguments': '{}'}], ident)
        if self.calls == 2:
            assert MARKER not in text, 'reset did not reproduce the missing assignment'
            assert 'Previous context window id: ' + self.previous in text, 'previous window missing'
            assert RECOVERY_GUIDANCE in '\n'.join(
                b.get('text', '') for i in payload['input'] for b in i.get('content', [])
                if isinstance(b, dict)), 'router recovery guidance missing'
            self.reset_verified = True
        if self.args.live:
            return None
        if self.calls == 2:
            for tool in payload['tools']:
                if tool.get('name') == 'history':
                    name, namespace = 'list_items', 'history'
                    break
                if 'history.list_items:' in tool.get('description', ''):
                    name, namespace = tool['name'], None
                    break
            else:
                raise AssertionError('history tool missing')
            item = {'type': 'function_call', 'name': name, 'call_id': 'call_history',
                    'id': 'fc_history', 'arguments': json.dumps({'window_id': self.previous})}
            if namespace:
                item['namespace'] = namespace
            return sse([item], ident)
        assert MARKER in text and self.retrievals == 1, 'retrieved brief was not replayed'
        return sse([message(MARKER, ident)], ident)

    def tool_result(self, params):
        assert params.get('namespace') == 'history' and params['tool'] == 'list_items', 'unexpected tool'
        assert params['arguments'].get('window_id') == self.previous, 'wrong history window'
        self.retrievals += 1
        assert self.retrievals <= 3, 'repeated history retrieval'
        return {'success': True, 'contentItems': [{'type': 'inputText', 'text': json.dumps({
            'window_id': self.previous, 'items': [{'id': 'synthetic-assignment',
                'role': 'user', 'text': ASSIGNMENT}]})}]}


def run(args):
    from ai_router.router import Router
    scenario = Scenario(args)
    with tempfile.TemporaryDirectory(prefix='context-recovery-') as temp:
        root = Path(temp)
        entry = by_slug(args.model)
        row = external_entry(entry) if entry else subscription_stub(args.model)
        row['prefer_websockets'] = row['use_responses_lite'] = False
        catalog = root / 'catalog.json'
        catalog.write_text(json.dumps({'models': [row]}))
        state = {'port': 0, 'token': 'synthetic-probe', 'openai_models': [args.model]}
        credentials = SimpleNamespace(key_for=lambda _: 'synthetic')
        if args.live:
            from ai_router.credentials import Credentials
            home = Path.home() / '.codex/mixed-model-router'
            live_state = json.loads((home / 'mixed-router-state.json').read_text())
            credentials = Credentials(live_state, home)
            auth = root / 'auth.json'
            auth.touch(mode=0o600)
            shutil.copyfile(Path.home() / '.codex/auth.json', auth)
        transport = SimpleNamespace(client=SimpleNamespace(
            HTTPSConnection=scenario.connect, HTTPException=http.client.HTTPException))
        with mock.patch.dict(os.environ, {'ROUTER_HOME': str(root / 'router')}), \
                mock.patch('ai_router.relay.http', transport):
            router = Router(state, credentials=credentials)
            threading.Thread(target=router.serve_forever, daemon=True).start()
            url = f'http://127.0.0.1:{router.server_port}/synthetic-probe/backend-api/codex'
            config = {'model_provider': 'openai', 'openai_base_url': url,
                'model_catalog_json': str(catalog), 'project_doc_max_bytes': 0,
                'approval_policy': 'never', 'sandbox_mode': 'read-only',
                'web_search': 'disabled', 'mcp_servers': {},
                'features.token_budget.enabled': True,
                'features.token_budget.use_history_notes_extension': False}
            for flag in ('apps', 'memories', 'plugins', 'shell_tool', 'multi_agent', 'code_mode'):
                config['features.' + flag] = False
            command = [args.codex_bin, 'app-server', '--stdio']
            for key, value in config.items():
                command += ['-c', key + '=' + json.dumps(value)]
            env = scrub_env(os.environ, AGENT_HANDOFFS, {'CODEX_HOME': temp})
            if not args.live:
                env['OPENAI_API_KEY'] = 'synthetic-test-key'
            client = AppServer(command, cwd=temp, env=env, stderr=subprocess.PIPE)
            try:
                client.rpc('initialize', {'clientInfo': {'name': 'context_recovery', 'version': '1'},
                           'capabilities': {'experimentalApi': True}})
                client.send({'method': 'initialized', 'params': {}})
                thread = client.rpc('thread/start', {'model': args.model, 'cwd': temp,
                    'approvalPolicy': 'never', 'sandbox': 'read-only', 'ephemeral': True,
                    'baseInstructions': 'Complete the assigned synthetic task using only the supplied tools.',
                    'dynamicTools': [HISTORY_TOOL]})['thread']['id']
                client.rpc('turn/start', {'threadId': thread, 'effort': 'low',
                    'input': [{'type': 'text', 'text': ASSIGNMENT, 'text_elements': []}]})
                answer, deadline = '', time.monotonic() + 180
                while True:
                    event = client.next_event(deadline=deadline)
                    if event.get('method') == 'error':
                        raise RuntimeError(json.dumps({'client_error_code': event['params'].get(
                            'error', {}).get('codexErrorInfo'), 'probe_failure': scenario.failure}))
                    if event.get('method') == 'item/tool/call':
                        client.send({'id': event['id'], 'result': scenario.tool_result(event['params'])})
                    if event.get('method') == 'item/completed':
                        item = event['params']['item']
                        if item.get('type') == 'agentMessage':
                            answer = item.get('text', '')
                    if event.get('method') == 'turn/completed':
                        assert event['params']['turn']['status'] == 'completed', (
                            scenario.failure or 'client turn failed')
                        break
                assert not scenario.failure, scenario.failure
                assert scenario.reset_verified and scenario.retrievals > 0, 'recovery did not occur'
                assert answer.strip() == MARKER, 'model did not complete recovered assignment'
                print(json.dumps({'model': args.model, 'live': args.live, 'passed': True,
                    'reset_without_assignment': True, 'history_retrievals': scenario.retrievals,
                    'live_calls': scenario.live_calls, 'assignment_completed': True}))
            finally:
                client.close()
                router.shutdown()
                router.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-bin', default=codex_bin())
    parser.add_argument('--model', default='gpt-5.6-luna')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--max-live-calls', type=int, default=0)
    args = parser.parse_args()
    if args.live and not 1 <= args.max_live_calls <= 6:
        parser.error('--live requires --max-live-calls between 1 and 6')
    run(args)
