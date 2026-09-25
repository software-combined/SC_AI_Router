"""Real Codex, candidate router, fake upstream: history switching and retries.

No live credentials or model calls. All client state is disposable.
"""
import argparse
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_router import catalogue, outbound, provider_defs, upstream
from ai_router.history_portability import portable_history
from ai_router.registry import by_slug
from tools.probe_context_budget import Client, Reply, MODEL, contract_failure, message

EXTERNAL = 'deepseek/deepseek-v4.1-flash'
NATIVE = 'gpt-6-astra'
MARKER = 'HISTORY_SWITCH_MARKER_837'


class Upstream:
    def __init__(self, scenario):
        self.scenario = scenario
        self.calls = 0
        self.failures = []
        self.models = []

    def connection(self, host, **kwargs):
        assert host in (provider_defs.OPENAI.host, provider_defs.OPENROUTER.host)
        owner = self

        class Connection:
            def connect(self):
                pass

            def request(self, method, path, body=None, headers=None):
                from compression import zstd
                assert path.endswith('/responses'), 'unexpected compaction or native service request'
                if any(k.lower() == 'content-encoding' and v == 'zstd' for k, v in headers.items()):
                    body = zstd.decompress(body)
                self.payload = json.loads(body)
                failure = contract_failure(host, self.payload)
                if failure:
                    owner.failures.append(failure)

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
        self.calls += 1
        self.models.append(payload['model'])
        if self.scenario == 'invalid':
            return Reply(400, b'{"error":{"code":"array_above_max_length",'
                         b'"param":"input[0].content","message":"invalid synthetic input"}}',
                         'application/json')
        if self.scenario == 'transient' and self.calls == 1:
            return Reply(503, b'{"error":{"message":"temporarily unavailable"}}', 'application/json')
        if self.scenario == 'switch' and self.calls > 1:
            assert MARKER in json.dumps(payload['input']), 'lost earlier conversation marker'
            foreign = [i for i in payload['input'] if i.get('type') == 'reasoning' and i.get('content')]
            if payload['model'] == NATIVE:
                assert not foreign, 'foreign reasoning leaked to subscription upstream'
        output = [message(MARKER)]
        if self.scenario == 'switch' and self.calls == 1:
            output.insert(0, {'type': 'reasoning', 'id': 'rs_foreign', 'summary': [],
                             'content': [{'type': 'reasoning_text', 'text': 'Synthetic reasoning.'}]})
        response = {'id': 'resp_probe', 'model': payload['model'], 'status': 'completed',
                    'output': output, 'usage': {'input_tokens': 100, 'output_tokens': 20,
                                               'total_tokens': 120}}
        events = [{'type': 'response.created', 'response': {'id': 'resp_probe'}}]
        for index, item in enumerate(output):
            events.extend({'type': kind, 'output_index': index, 'item': item} for kind in
                          ('response.output_item.added', 'response.output_item.done'))
        events.append({'type': 'response.completed', 'response': response})
        return Reply(200, ''.join('data: ' + json.dumps(e) + '\n\n' for e in events).encode(),
                     'text/event-stream')


def turn(client, thread, model, scenario):
    client.rpc('turn/start', {'threadId': thread, 'model': model, 'effort': 'low',
        'input': [{'type': 'text', 'text': 'Continue the synthetic probe.', 'text_elements': []}]})
    deadline = time.monotonic() + 40
    answer = ''
    while True:
        event = client.next_event(deadline)
        if event.get('method') == 'error' and scenario == 'invalid':
            assert not event['params'].get('willRetry'), 'client retried a permanent rejection'
        if event.get('method') == 'item/completed':
            item = event['params']['item']
            if item.get('type') == 'agentMessage':
                answer = item.get('text', '')
        if event.get('method') == 'turn/completed':
            result = event['params']['turn']
            if scenario == 'invalid':
                assert result['status'] == 'failed', 'expected permanent rejection'
                # 0.153.4 maps terminal InvalidRequest to protocol "other".
                assert result['error']['codexErrorInfo'] == 'other', 'wrong client error category'
                assert json.loads(result['error']['message'])['error']['code'] == 'PROVIDER_REJECTED'
            else:
                assert result['status'] == 'completed', 'synthetic turn failed'
                assert MARKER in answer, 'client lost the conversation marker'
            return


def run(binary, scenario, home):
    with mock.patch.dict(os.environ, {'ROUTER_HOME': str(home / 'router')}):
        from ai_router.router import Router
        fake = Upstream(scenario)
        upstream.clear_refusals()
        with (mock.patch.object(http.client, 'HTTPSConnection', fake.connection),
              mock.patch.object(outbound, 'portable_replay',
                                wraps=outbound.portable_replay) as replay):
            server = Router({'port': 0, 'token': 'probe-token', 'openai_models': [NATIVE]},
                            credentials=SimpleNamespace(key_for=lambda _pid=None: 'synthetic-test-key'))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            catalog = home / 'catalog.json'
            catalog.write_text(json.dumps({'models': [catalogue.subscription_stub(NATIVE),
                *[catalogue.external_entry(by_slug(m)) for m in (EXTERNAL, MODEL)]]}))
            url = f'http://127.0.0.1:{server.server_port}/probe-token/backend-api/codex'
            client = None
            try:
                # The carried-history path is not the V2 compaction path, so
                # this probe drives the client's default (v1) feature set.
                client = Client(binary, home, url, catalog, 'v1')
                client.rpc('initialize', {'clientInfo': {'name': 'history_probe', 'version': '1'},
                                         'capabilities': {'experimentalApi': True}})
                client.send({'method': 'initialized', 'params': {}})
                initial = EXTERNAL if scenario == 'switch' else NATIVE
                thread = client.rpc('thread/start', {'model': initial, 'modelProvider': 'openai',
                    'cwd': str(home), 'approvalPolicy': 'never', 'sandbox': 'read-only',
                    'baseInstructions': 'Synthetic protocol check; no tools.'})['thread']['id']
                models = (EXTERNAL, NATIVE, EXTERNAL) if scenario == 'switch' else (initial,)
                for model in models:
                    turn(client, thread, model, scenario)
                if scenario == 'switch':
                    assert any(i.get('type') == 'reasoning' and i.get('content')
                               for call in replay.call_args_list for i in call.args[0]['input']), \
                        'probe did not exercise replay of foreign reasoning'
                    assert any(portable_history(c.args[0]['input'], outbound.SEARCH_NAME, 'native')
                               is not c.args[0]['input'] for c in replay.call_args_list), \
                        'router did not find the client <model_switch> marker'
                expected = {'switch': 3, 'invalid': 1, 'transient': 2}[scenario]
                assert fake.calls == expected, f'expected {expected} attempts, got {fake.calls}'
                assert not fake.failures, fake.failures
                print(json.dumps({'scenario': scenario, 'passed': True, 'attempts': fake.calls,
                                  'models': fake.models}), flush=True)
            finally:
                if client:
                    client.close()
                server.shutdown()
                server.server_close()
                upstream.clear_refusals()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-bin', default='/Applications/ChatGPT.app/Contents/Resources/codex')
    args = parser.parse_args()
    print(subprocess.check_output([args.codex_bin, '--version'], text=True).strip(), flush=True)
    for scenario in ('switch', 'invalid', 'transient'):
        with tempfile.TemporaryDirectory(prefix='history-probe-') as tmp:
            run(args.codex_bin, scenario, Path(tmp))


if __name__ == '__main__':
    main()
