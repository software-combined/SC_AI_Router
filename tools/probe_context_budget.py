"""Exercise the real Codex client with a loopback router and fake upstream.

No live credentials or model calls. Usage: python3.14 tools/probe_context_budget.py
--codex-bin /path/to/codex [--mode both|v1|v2]. Temporary client history is
removed on exit.
"""
import argparse
import http.client
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_router.catalogue import external_entry
from ai_router.registry import by_slug
from tools.appserver_probe import AppServer, CONTEXT_BUDGET, scrub_env

MODEL = 'meta/muse-spark-1.3-contributor'
MARKER = 'CONTEXT_BUDGET_MARKER_719'


class Reply(io.BytesIO):
    def __init__(self, status, body, content_type):
        super().__init__(body)
        self.status = status
        self.headers = [('Content-Type', content_type)]

    def getheaders(self):
        return self.headers

    def getheader(self, name, default=None):
        return next((v for k, v in self.headers if k.lower() == name.lower()), default)


def message(text):
    return {'type': 'message', 'id': 'msg_probe', 'role': 'assistant',
            'status': 'completed', 'content': [{'type': 'output_text', 'text': text}]}


class Upstream:
    def __init__(self, scenario):
        self.scenario = scenario
        self.calls = self.compactions = self.summary_attempts = 0
        self.failures = []

    def connection(self, host, **kwargs):
        assert host == 'openrouter.ai', 'unexpected upstream host'
        owner = self

        class Connection:
            def connect(self):
                pass

            def request(self, method, path, body=None, headers=None):
                assert path == '/api/v1/responses', 'unexpected upstream path'
                self.payload = json.loads(body)

            def getresponse(self):
                try:
                    return owner.respond(self.payload)
                except AssertionError as exc:
                    owner.failures.append(str(exc))
                    raise

            def close(self):
                pass

        return Connection()

    def respond(self, payload):
        if not payload.get('stream'):
            self.summary_attempts += 1
            assert MARKER in json.dumps(payload['input']), 'summary input lost marker'
            if self.scenario == 'truncated' and self.summary_attempts == 1:
                partial = message(MARKER + ' partial')
                partial['status'] = 'incomplete'
                body = {'status': 'incomplete',
                        'incomplete_details': {'reason': 'max_output_tokens'},
                        'output': [partial]}
                return Reply(200, json.dumps(body).encode(), 'application/json')
            expected = 8000 if self.scenario == 'truncated' else 4000
            assert payload['max_output_tokens'] == expected, \
                'unexpected summarizer budget'
            self.compactions += 1
            return Reply(200, json.dumps({'output': [message(MARKER)]}).encode(),
                         'application/json')
        self.calls += 1
        assert payload['max_output_tokens'] == 32000, 'incorrect default output budget'
        if self.scenario == 'context_error' and self.calls == 2:
            return Reply(400, b'{"error":{"code":"context_length_exceeded"}}',
                         'application/json')
        if self.scenario in ('stream_context_error', 'metadata_context_error') and self.calls == 2:
            error = {'message': 'The prompt is too long: 4290688, model maximum context length: 1048571'}
            if self.scenario == 'metadata_context_error':
                error = {'code': 'invalid_prompt', 'metadata': {'error_type': 'context_length_exceeded'}}
            event = {'type': 'response.failed', 'response': {'error': error}}
            return Reply(200, ('data: ' + json.dumps(event) + '\n\n').encode(),
                         'text/event-stream')
        if self.calls > 1:
            assert self.compactions == 1, 'client did not compact before resuming'
            assert MARKER in json.dumps(payload['input']), 'post-compact request lost marker'
        used = 943719 if self.scenario in ('threshold', 'truncated') \
            and self.calls == 1 else 1000
        output = message(MARKER)
        response = {'id': 'resp_probe', 'model': MODEL, 'status': 'completed',
                    'output': [output], 'usage': {'input_tokens': used, 'output_tokens': 10,
                                                'total_tokens': used + 10}}
        events = [{'type': 'response.created', 'response': {'id': 'resp_probe'}},
                  {'type': 'response.output_item.added', 'output_index': 0, 'item': output},
                  {'type': 'response.output_item.done', 'output_index': 0, 'item': output},
                  {'type': 'response.completed', 'response': response}]
        body = ''.join('data: ' + json.dumps(e) + '\n\n' for e in events).encode()
        return Reply(200, body, 'text/event-stream')


class Client:
    """Thin scenario driver over the shared AppServer harness.

    Keeps this probe's exact behaviour: the same `-c` config list, the
    CONTEXT_BUDGET scrub (strip then inject, in that order), the client.log
    stderr file re-read on EOF, the 30s RPC / 40s turn timeouts, and the
    process-group SIGTERM teardown.
    """
    def __init__(self, binary, home, url, catalog, mode):
        config = {'model': MODEL, 'model_provider': 'openai', 'openai_base_url': url,
                  'model_catalog_json': str(catalog),
                  'mcp_servers': {}, 'web_search': 'disabled', 'project_doc_max_bytes': 0,
                  'approval_policy': 'never', 'sandbox_mode': 'read-only',
                  'analytics.enabled': False, 'feedback.enabled': False}
        for flag in ('apps', 'memories', 'shell_tool', 'collab', 'multi_agent',
                     'code_mode', 'remote_compaction_v2', 'token_budget', 'plugins'):
            config['features.' + flag] = False
        config['features.remote_compaction_v2'] = mode == 'v2'
        command = [binary, 'app-server', '--stdio']
        for key, value in config.items():
            command += ['-c', key + '=' + json.dumps(value)]
        env = scrub_env(os.environ, CONTEXT_BUDGET, inject={
            'CODEX_HOME': str(home), 'OPENAI_API_KEY': 'synthetic-test-key',
            'OPENAI_BASE_URL': url})
        self.diagnostics = (home / 'client.log').open('w+')
        self.diagnostics_path = home / 'client.log'
        self.server = AppServer(command, cwd=home, env=env, stderr=self.diagnostics,
                                start_new_session=os.name != 'nt', kill_group=True,
                                rpc_timeout=30.0, eof_detail=self._eof_detail,
                                strict_lines=True)

    def _eof_detail(self):
        with open(self.diagnostics_path) as handle:
            detail = handle.read()[-1500:]
        return re.sub(r'https?://\S+', '[URL]', detail)

    def send(self, obj):
        self.server.send(obj)

    def next_event(self, deadline):
        return self.server.next_event(deadline=deadline)

    def rpc(self, method, params):
        return self.server.rpc(method, params)

    def turn(self, thread, expect_error=False):
        request = {'threadId': thread, 'input': [
            {'type': 'text', 'text': 'Continue the synthetic probe.',
             'text_elements': []}]}
        self.rpc('turn/start', request)
        deadline = time.monotonic() + 40.0
        answer = ''
        while True:
            event = self.next_event(deadline=deadline)
            if event.get('method') == 'error':
                params = event.get('params')
                params = params if isinstance(params, dict) else {}
                nested = params.get('error')
                retryable = params.get('willRetry') is True or (
                    isinstance(nested, dict) and nested.get('willRetry') is True)
                if retryable:
                    continue
                if not expect_error:
                    raise RuntimeError(re.sub(r'https?://\S+', '[URL]', str(params)))
            if event.get('method') == 'item/completed':
                item = event['params']['item']
                if item.get('type') == 'agentMessage':
                    answer = item.get('text', '')
            if event.get('method') == 'turn/completed':
                turn = event['params']['turn']
                if expect_error:
                    assert turn['status'] == 'failed', 'expected context exhaustion'
                    assert turn['error']['codexErrorInfo'] == 'contextWindowExceeded', turn['error']
                else:
                    assert turn['status'] == 'completed', str(turn.get('error'))
                    assert MARKER in answer, 'client did not retain the synthetic marker'
                return answer, turn

    def compact(self, thread):
        self.rpc('thread/compact/start', {'threadId': thread})
        deadline = time.monotonic() + 40
        while True:
            event = self.next_event(deadline)
            if event.get('method') == 'turn/completed':
                assert event['params']['turn']['status'] == 'completed', 'compaction failed'
                return

    def close(self):
        self.server.close()


def run(binary, mode, scenario, home):
    # Scope router caches as well as client state to the disposable directory.
    with mock.patch.dict(os.environ, {'ROUTER_HOME': str(home / 'router')}):
        from ai_router.router import Handler, Router
        upstream = Upstream(scenario)
        compact_requests = []
        original_read_body = Handler.read_body

        def observe_read_body(handler):
            raw, payload, size = original_read_body(handler)
            path, _ = handler.authorized_path()
            path = path.split('?', 1)[0] if isinstance(path, str) else None
            items = payload.get('input') if isinstance(payload, dict) else None
            trigger = (isinstance(items, list)
                       and any(isinstance(item, dict)
                               and item.get('type') == 'compaction_trigger'
                               for item in items))
            if path == '/responses/compact' or (path == '/responses' and trigger):
                compact_requests.append({'path': path,
                                         'stream': payload.get('stream') is True,
                                         'trigger': trigger})
            return raw, payload, size

        with mock.patch.object(Handler, 'read_body', observe_read_body), \
                mock.patch.object(http.client, 'HTTPSConnection', upstream.connection):
            server = Router({'port': 0, 'token': 'probe-token', 'openai_models': []},
                            credentials=SimpleNamespace(
                                key_for=lambda _provider_id=None: 'synthetic-test-key'))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            catalog = home / 'catalog.json'
            catalog.write_text(json.dumps({'models': [external_entry(by_slug(MODEL))]}))
            url = f'http://127.0.0.1:{server.server_port}/probe-token/backend-api/codex'
            client = Client(binary, home, url, catalog, mode)
            try:
                client.rpc('initialize', {'clientInfo': {'name': 'context_probe', 'version': '1'},
                                         'capabilities': {'experimentalApi': True}})
                client.send({'method': 'initialized', 'params': {}})
                result = client.rpc('thread/start', {'model': MODEL, 'modelProvider': 'openai',
                    'cwd': str(home), 'approvalPolicy': 'never', 'sandbox': 'read-only'})
                thread = result['thread']['id']
                client.turn(thread)
                context_error = scenario not in ('threshold', 'truncated')
                if context_error:
                    client.turn(thread, expect_error=True)
                    # This client recognizes the error but does not reliably
                    # auto-compact next turn; prove its explicit recovery path.
                    client.compact(thread)
                client.turn(thread)
                assert upstream.compactions == 1, 'wrong compaction count'
                expected_attempts = 2 if scenario == 'truncated' else 1
                assert upstream.summary_attempts == expected_attempts, \
                    'unexpected summarizer attempts'
                assert upstream.calls == (3 if context_error else 2), \
                    'unexpected retries'
                assert len(compact_requests) == 1, 'compaction repeated unexpectedly'
                request = compact_requests[0]
                if mode == 'v2':
                    assert request == {'path': '/responses', 'stream': True, 'trigger': True}, \
                        'V2 trigger wire contract was not observed'
                else:
                    assert request == {'path': '/responses/compact',
                                       'stream': False, 'trigger': False}, \
                        'V1 compaction wire contract was not observed'
                assert not upstream.failures, upstream.failures
                print(json.dumps({'mode': mode, 'scenario': scenario, 'passed': True,
                                  'compactions': upstream.compactions,
                                  'summary_attempts': upstream.summary_attempts,
                                  'marker_preserved': True}))
            finally:
                client.close()
                server.shutdown()
                server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-bin', default='/Applications/ChatGPT.app/Contents/Resources/codex')
    parser.add_argument('--mode', choices=('both', 'v1', 'v2'), default='both')
    args = parser.parse_args()
    print(subprocess.check_output([args.codex_bin, '--version'], text=True,
                                  timeout=10).strip(), flush=True)
    modes = ('v1', 'v2') if args.mode == 'both' else (args.mode,)
    for mode in modes:
        for scenario in ('threshold', 'context_error', 'stream_context_error',
                         'metadata_context_error'):
            with tempfile.TemporaryDirectory(prefix='context-probe-') as tmp:
                run(args.codex_bin, mode, scenario, Path(tmp))
    if args.mode in ('both', 'v2'):
        with tempfile.TemporaryDirectory(prefix='context-probe-') as tmp:
            run(args.codex_bin, 'v2', 'truncated', Path(tmp))


if __name__ == '__main__':
    main()
