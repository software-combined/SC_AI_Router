"""End-to-end handler characterisation (Plan 036 safety net for the 037 refactor).

Fake upstream only; never opens a real network connection. Assertions here
are the contract: Plan 037 must keep them green without editing them.
"""
import http.client
import json
import os
import tempfile
import unittest
from compression import zstd
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

    def test_openrouter_request_reaches_openrouter_with_router_key_only(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{"output": []}', []))
        server = self._server()
        response = _post(server.server_port, '/test-token/responses',
            {'model': 'z-ai/glm-5.3',
             'input': [{'type': 'message', 'role': 'user', 'content': 'hi'}],
             'service_tier': 'priority', 'max_output_tokens': 99999},
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
        self.assertEqual(sent['max_output_tokens'], 32768)
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
        install_fake(self, lambda: FakeUpstream(429, b'{"error": "slow down"}',
                                                [('Content-Type', 'application/json')]))
        server = self._server()
        response = _post(server.server_port, '/test-token/responses',
                         {'model': 'z-ai/glm-5.3', 'input': []})
        self.assertEqual(response.status, 429)
        self.assertEqual(json.loads(response.read()), {'error': 'slow down'})

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

    def test_health_json(self):
        server = self._server()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('GET', '/test-token/health')
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.read())['status'], 'ok')


if __name__ == '__main__':
    unittest.main()
