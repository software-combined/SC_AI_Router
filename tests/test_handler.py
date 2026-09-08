"""End-to-end handler characterisation (Plan 036 safety net for the 037 refactor).

Fake upstream only; never opens a real network connection. Assertions here
are the contract: Plan 037 must keep them green without editing them.
"""
import http.client
import json
import os
import pathlib
import tempfile
import unittest
from compression import zstd
from codex_router.registry import by_slug
from tests.fakes import FakeUpstream, install_fake
from tests.test_mixed_router import _start_server, _test_state


def _auth_file(test):
    auth = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
    json.dump({'openrouter': {'type': 'api', 'key': 'test-key'}}, auth)
    auth.close()
    test.addCleanup(os.unlink, auth.name)
    return auth.name


def _post(port, path, payload, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    conn.request('POST', path, body=json.dumps(payload),
                 headers={'Content-Type': 'application/json', **(headers or {})})
    return conn.getresponse()


class HandlerCharacterisationTests(unittest.TestCase):
    def _server(self, **state_overrides):
        state = _test_state(_auth_file(self))
        state.update(state_overrides)
        server = _start_server(state)
        self.addCleanup(server.shutdown)
        return server

    def _state_base(self):
        return {'port': 0, 'token': 'test-token', 'openai_models': []}

    def _state_file(self, state):
        f = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
        json.dump(state, f)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return pathlib.Path(f.name)

    def test_openrouter_request_reaches_openrouter_with_router_key_only(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{"output": []}', []))
        server = self._server()
        cap = by_slug('z-ai/glm-5.3').max_output_tokens
        response = _post(server.server_port, '/test-token/responses',
            {'model': 'z-ai/glm-5.3',
             'input': [{'type': 'message', 'role': 'user', 'content': 'hi'}],
             'service_tier': 'priority', 'max_output_tokens': cap + 1000},
            {'Authorization': 'Bearer subscription-secret', 'Cookie': 'c=1'})
        self.assertEqual(response.status, 200)
        self.assertEqual(len(recorded), 1)
        host, _, path, body, headers = recorded[0]
        self.assertEqual(host, 'openrouter.ai')
        self.assertEqual(path, '/api/v1/responses')
        self.assertEqual(headers, {'Authorization': 'Bearer test-key',
                                   'Content-Type': 'application/json'})
        sent = json.loads(body)
        self.assertNotIn('service_tier', sent)
        self.assertEqual(sent['max_output_tokens'], cap)
        self.assertNotIn('subscription-secret', json.dumps(headers) + body.decode())

    def test_openai_request_forwards_subscription_bearer_and_strips_hop_headers(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server(openai_models=['gpt-6-astra'])
        response = _post(server.server_port, '/test-token/responses',
            {'model': 'gpt-6-astra',
             'input': [{'type': 'message', 'role': 'user', 'content': 'hi'}]},
            {'Authorization': 'Bearer subscription-secret',
             'ChatGPT-Account-ID': 'acct', 'Connection': 'keep-alive'})
        self.assertEqual(response.status, 200)
        host, _, path, body, headers = recorded[0]
        self.assertEqual(host, 'chatgpt.com')
        self.assertEqual(path, '/backend-api/codex/responses')
        self.assertEqual(headers.get('Authorization'), 'Bearer subscription-secret')
        self.assertEqual(headers.get('ChatGPT-Account-ID'), 'acct')
        for dropped in ('Connection', 'Host', 'Content-Length', 'Cookie'):
            self.assertNotIn(dropped, headers)
        self.assertNotIn('test-key', json.dumps(headers))

    def test_openai_request_without_bearer_is_401(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server(openai_models=['gpt-6-astra'])
        response = _post(server.server_port, '/test-token/responses',
                         {'model': 'gpt-6-astra', 'input': []})
        self.assertEqual(response.status, 401)
        self.assertEqual(recorded, [])

    def test_unknown_model_is_400_and_never_reaches_upstream(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server()
        response = _post(server.server_port, '/test-token/responses',
                         {'model': 'nobody/none', 'input': []})
        self.assertEqual(response.status, 400)
        self.assertEqual(recorded, [])

    def test_unsupported_route_is_404(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server()
        response = _post(server.server_port, '/test-token/nope', {'model': 'z-ai/glm-5.3'})
        self.assertEqual(response.status, 404)
        self.assertEqual(recorded, [])

    def test_oversized_content_length_is_413(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.putrequest('POST', '/test-token/responses')
        conn.putheader('Content-Length', '17000000')
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 413)
        self.assertEqual(recorded, [])

    def test_zstd_body_is_decoded(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{"output": []}', []))
        server = self._server()
        payload = {'model': 'z-ai/glm-5.3',
                   'input': [{'type': 'message', 'role': 'user', 'content': 'hi'}]}
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('POST', '/test-token/responses', body=zstd.compress(json.dumps(payload).encode()),
                     headers={'Content-Type': 'application/json', 'Content-Encoding': 'zstd'})
        self.assertEqual(conn.getresponse().status, 200)
        self.assertEqual(json.loads(recorded[0][3])['model'], 'z-ai/glm-5.3')

    def test_upstream_status_and_body_are_relayed(self):
        install_fake(self, lambda: FakeUpstream(400, b'{"error": "slow down"}',
                                                [('Content-Type', 'application/json')]))
        server = self._server()
        response = _post(server.server_port, '/test-token/responses',
                         {'model': 'z-ai/glm-5.3', 'input': []})
        self.assertEqual(response.status, 400)
        self.assertEqual(json.loads(response.read()), {'error': 'slow down'})

    def test_upstream_429_becomes_retryable_503(self):
        for headers, expected in (([], '2'), ([('Retry-After', '9')], '9')):
            with self.subTest(headers=headers):
                install_fake(self, lambda: FakeUpstream(429, b'{"error": "slow"}', [
                    ('Content-Type', 'application/json'), *headers]))
                server = self._server()
                response = _post(server.server_port, '/test-token/responses',
                                 {'model': 'z-ai/glm-5.3', 'input': []})
                self.assertEqual(response.status, 503)
                self.assertEqual(response.getheader('Retry-After'), expected)

    def test_health_reports_served_model(self):
        wire = (b'data: {"type": "response.completed", "response": '
                b'{"model": "x-ai/grok-4.6", "output": []}}\n\n')
        install_fake(self, lambda: FakeUpstream(200, wire, [('Content-Type', 'text/event-stream')]))
        server = self._server()
        response = _post(server.server_port, '/test-token/responses',
            {'model': '~x-ai/grok-latest', 'input': [],
             'tools': [{'type': 'custom', 'name': 'exec'}]})
        self.assertEqual(response.status, 200)
        response.read()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('GET', '/test-token/health')
        served = json.loads(conn.getresponse().read())['served_models']
        self.assertEqual(served, {'~x-ai/grok-latest': 'x-ai/grok-4.6'})

    def test_streaming_tool_call_is_adapted_end_to_end(self):
        item = {'id': 'item1', 'type': 'function_call', 'call_id': 'call1',
                'name': 'exec', 'arguments': json.dumps({'input': 'code'})}
        events = [
            {'type': 'response.output_item.added', 'item': {**item, 'arguments': ''}},
            {'type': 'response.function_call_arguments.delta', 'item_id': 'item1',
             'delta': '{"input":'},
            {'type': 'response.function_call_arguments.done', 'item_id': 'item1',
             'arguments': item['arguments']},
            {'type': 'response.output_item.done', 'item': item}]
        wire = b''.join(b'data: ' + json.dumps(event).encode() + b'\n\n' for event in events)
        install_fake(self, lambda: FakeUpstream(200, wire, [('Content-Type', 'text/event-stream')]))
        server = self._server()
        response = _post(server.server_port, '/test-token/responses',
            {'model': 'z-ai/glm-5.3',
             'input': [{'type': 'message', 'role': 'user', 'content': 'hi'}],
             'tools': [{'type': 'custom', 'name': 'exec'}]})
        self.assertEqual(response.status, 200)
        seen = [json.loads(block[6:]) for block in response.read().split(b'\n\n') if block.startswith(b'data:')]
        done = [e for e in seen if e.get('type') == 'response.output_item.done']
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]['item']['type'], 'custom_tool_call')
        self.assertEqual(done[0]['item']['input'], 'code')

    def test_openai_mode_validation(self):
        from codex_router.runtime import load_state
        good = dict(self._state_base(), openai_mode='none', opencode_auth=_auth_file(self))
        self.assertEqual(load_state(self._state_file(good))['openai_mode'], 'none')
        bad = dict(self._state_base(), openai_mode='sometimes')
        with self.assertRaises(SystemExit) as ctx:
            load_state(self._state_file(bad))
        self.assertIn('openai_mode must be subscription or none', str(ctx.exception))

    def test_none_mode_rejects_openai_models_without_upstream_call(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server(openai_models=['gpt-6-astra'], openai_mode='none')
        response = _post(server.server_port, '/test-token/responses',
                         {'model': 'gpt-6-astra', 'input': []})
        self.assertEqual(response.status, 400)
        self.assertEqual(recorded, [])

    def test_none_mode_answers_native_paths_locally(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server(openai_models=['gpt-6-astra'], openai_mode='none')
        response = _post(server.server_port, '/test-token/alpha/search',
                         {'model': 'gpt-6-astra'})
        self.assertEqual(response.status, 404)
        self.assertEqual(recorded, [])

    def test_bearer_token_authorises_when_path_token_absent(self):
        server = self._server()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('GET', '/health', headers={'Authorization': 'Bearer test-token'})
        self.assertEqual(conn.getresponse().status, 200)

    def test_bearer_authed_subscription_request_never_reaches_upstream(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server(openai_models=['gpt-6-astra'])
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('POST', '/responses',
                     body=json.dumps({'model': 'gpt-6-astra', 'input': []}),
                     headers={'Content-Type': 'application/json',
                              'Authorization': 'Bearer test-token'})
        self.assertEqual(conn.getresponse().status, 401)
        self.assertEqual(recorded, [])

    def test_bearer_with_wrong_token_is_403(self):
        server = self._server()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('GET', '/health', headers={'Authorization': 'Bearer wrong-token'})
        self.assertEqual(conn.getresponse().status, 403)

    def test_native_upstream_401_falls_back_to_local_answer(self):
        recorded = install_fake(self, lambda: FakeUpstream(401, b'{"error": "expired"}', []))
        server = self._server(openai_models=['gpt-6-astra'])
        response = _post(server.server_port, '/test-token/alpha/search',
                         {'model': 'gpt-6-astra'},
                         {'Authorization': 'Bearer subscription-secret'})
        self.assertEqual(response.status, 404)
        self.assertEqual(len(recorded), 1)

    def test_non_native_upstream_401_passes_through(self):
        install_fake(self, lambda: FakeUpstream(401, b'{"error": "expired"}', []))
        server = self._server(openai_models=['gpt-6-astra'])
        response = _post(server.server_port, '/test-token/responses',
                         {'model': 'gpt-6-astra', 'input': []},
                         {'Authorization': 'Bearer subscription-secret'})
        self.assertEqual(response.status, 401)
        self.assertEqual(response.read(), b'{"error": "expired"}')

    def test_origin_with_valid_bearer_is_403(self):
        server = self._server()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('GET', '/health', headers={'Authorization': 'Bearer test-token',
                                                'Origin': 'https://x.example'})
        self.assertEqual(conn.getresponse().status, 403)

    def test_bearer_with_wrong_prefixed_path_is_404(self):
        server = self._server()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('GET', '/wrong/health', headers={'Authorization': 'Bearer test-token'})
        self.assertEqual(conn.getresponse().status, 404)

    def test_header_authed_rejection_logs_unrouted_without_token(self):
        server = self._server()
        with self.assertLogs('codex_router', level='INFO') as logs:
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            conn.request('GET', '/nope', headers={'Authorization': 'Bearer test-token'})
            self.assertEqual(conn.getresponse().status, 404)
        events = [json.loads(record.getMessage()) for record in logs.records]
        rejected = [e for e in events if e.get('event') == 'request_rejected']
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]['path'], '<unrouted>')
        self.assertNotIn('test-token', ''.join(record.getMessage() for record in logs.records))

    def test_health_json(self):
        server = self._server()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('GET', '/test-token/health')
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.read())['status'], 'ok')


if __name__ == '__main__':
    unittest.main()
