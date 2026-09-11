"""Exercise the real Codex client with a loopback router and fake upstream.

No live credentials or model calls. Usage: python3.14 tools/probe_context_budget.py
--codex-bin /path/to/codex. Temporary client history is removed on exit.
"""
import argparse
import http.client
import io
import json
import os
from pathlib import Path
import queue
import re
import signal
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
        self.calls = self.compactions = 0
        self.failures = []

    def connection(self, host, **kwargs):
        assert host == 'openrouter.ai', 'unexpected upstream host'
        owner = self

        class Connection:
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
            assert payload['max_output_tokens'] == 4000, 'unexpected summarizer budget'
            assert MARKER in json.dumps(payload['input']), 'summary input lost marker'
            self.compactions += 1
            return Reply(200, json.dumps({'output': [message(MARKER)]}).encode(),
                         'application/json')
        self.calls += 1
        assert payload['max_output_tokens'] == 32000, 'incorrect default output budget'
        if self.scenario == 'context_error' and self.calls == 2:
            return Reply(400, b'{"error":{"code":"context_length_exceeded"}}',
                         'application/json')
        if self.calls > 1:
            assert self.compactions == 1, 'client did not compact before resuming'
            assert MARKER in json.dumps(payload['input']), 'post-compact request lost marker'
        used = 943719 if self.scenario == 'threshold' and self.calls == 1 else 1000
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
    def __init__(self, binary, home, url, catalog):
        config = {'model': MODEL, 'model_provider': 'openai', 'openai_base_url': url,
                  'model_catalog_json': str(catalog),
                  'mcp_servers': {}, 'web_search': 'disabled', 'project_doc_max_bytes': 0,
                  'approval_policy': 'never', 'sandbox_mode': 'read-only',
                  'analytics.enabled': False, 'feedback.enabled': False}
        for flag in ('apps', 'memories', 'shell_tool', 'collab', 'multi_agent',
                     'code_mode', 'remote_compaction_v2', 'token_budget', 'plugins'):
            config['features.' + flag] = False
        command = [binary, 'app-server', '--stdio']
        for key, value in config.items():
            command += ['-c', key + '=' + json.dumps(value)]
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('OPENAI_', 'CODEX_', 'CHATGPT_'))}
        env.update(CODEX_HOME=str(home), OPENAI_API_KEY='synthetic-test-key', OPENAI_BASE_URL=url)
        self.diagnostics = (home / 'client.log').open('w+')
        self.process = subprocess.Popen(command, cwd=home, env=env, text=True,
                                        start_new_session=os.name != 'nt',
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.diagnostics)
        self.events = queue.Queue()
        self.sequence = 0
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        for line in self.process.stdout:
            self.events.put(json.loads(line))
        self.events.put({'eof': True})

    def send(self, obj):
        self.process.stdin.write(json.dumps(obj) + '\n')
        self.process.stdin.flush()

    def next_event(self, deadline):
        event = self.events.get(timeout=max(0.01, deadline - time.monotonic()))
        if event.get('eof'):
            self.diagnostics.seek(0)
            detail = re.sub(r'https?://\S+', '[URL]', self.diagnostics.read()[-1500:])
            raise RuntimeError('Codex exited: ' + detail)
        return event

    def rpc(self, method, params):
        self.sequence += 1
        self.send({'id': self.sequence, 'method': method, 'params': params})
        deadline = time.monotonic() + 30
        while True:
            event = self.next_event(deadline)
            if event.get('id') == self.sequence and 'method' not in event:
                assert 'error' not in event, str(event.get('error'))
                return event['result']

    def turn(self, thread, expect_error=False):
        self.rpc('turn/start', {'threadId': thread, 'input': [
            {'type': 'text', 'text': 'Continue the synthetic probe.', 'text_elements': []}]})
        deadline = time.monotonic() + 40
        answer = ''
        while True:
            event = self.next_event(deadline)
            if event.get('method') == 'error':
                if not expect_error:
                    raise RuntimeError(re.sub(r'https?://\S+', '[URL]', str(event['params'])))
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
                return

    def compact(self, thread):
        self.rpc('thread/compact/start', {'threadId': thread})
        deadline = time.monotonic() + 40
        while True:
            event = self.next_event(deadline)
            if event.get('method') == 'turn/completed':
                assert event['params']['turn']['status'] == 'completed', 'compaction failed'
                return

    def close(self):
        if os.name != 'nt':
            os.killpg(self.process.pid, signal.SIGTERM)
        else:
            self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.process.stdin.close()
        self.process.stdout.close()
        self.diagnostics.close()


def run(binary, scenario, home):
    # Scope router caches as well as client state to the disposable directory.
    with mock.patch.dict(os.environ, {'ROUTER_HOME': str(home / 'router')}):
        from ai_router.router import Router
        upstream = Upstream(scenario)
        with mock.patch.object(http.client, 'HTTPSConnection', upstream.connection):
            server = Router({'port': 0, 'token': 'probe-token', 'openai_models': []},
                            credentials=SimpleNamespace(
                                key_for=lambda _provider_id=None: 'synthetic-test-key'))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            catalog = home / 'catalog.json'
            catalog.write_text(json.dumps({'models': [external_entry(by_slug(MODEL))]}))
            url = f'http://127.0.0.1:{server.server_port}/probe-token/backend-api/codex'
            client = Client(binary, home, url, catalog)
            try:
                client.rpc('initialize', {'clientInfo': {'name': 'context_probe', 'version': '1'},
                                         'capabilities': {'experimentalApi': True}})
                client.send({'method': 'initialized', 'params': {}})
                result = client.rpc('thread/start', {'model': MODEL, 'modelProvider': 'openai',
                    'cwd': str(home), 'approvalPolicy': 'never', 'sandbox': 'read-only'})
                thread = result['thread']['id']
                client.turn(thread)
                if scenario == 'context_error':
                    client.turn(thread, expect_error=True)
                    # This client recognizes the error but does not reliably
                    # auto-compact next turn; prove its explicit recovery path.
                    client.compact(thread)
                client.turn(thread)
                assert upstream.compactions == 1, 'wrong compaction count'
                assert upstream.calls == (3 if scenario == 'context_error' else 2), 'unexpected retries'
                assert not upstream.failures, upstream.failures
                print(json.dumps({'scenario': scenario, 'passed': True,
                                  'compactions': upstream.compactions, 'marker_preserved': True}))
            finally:
                client.close()
                server.shutdown()
                server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-bin', default='/Applications/ChatGPT.app/Contents/Resources/codex')
    args = parser.parse_args()
    print(subprocess.check_output([args.codex_bin, '--version'], text=True).strip(), flush=True)
    for scenario in ('threshold', 'context_error'):
        with tempfile.TemporaryDirectory(prefix='context-probe-') as tmp:
            run(args.codex_bin, scenario, Path(tmp))


if __name__ == '__main__':
    main()
