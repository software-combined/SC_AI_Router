"""Anthropic Messages ingress: billing split without translation.

Fake upstream only; never opens a real network connection. An
OpenRouter-registry slug must reach openrouter.ai with the router key as
the only credential and a byte-identical body; every other model must pass
through to api.anthropic.com with the client's credentials untouched.
"""
import http.client
import json
import unittest
from tests.fakes import FakeUpstream, install_fake
from tests.test_handler import _auth_file, _post
from tests.test_mixed_router import _start_server, _test_state


def _messages(model='z-ai/glm-5.3-flash'):
    return {'model': model, 'max_tokens': 64,
            'system': 'Be brief.',
            'messages': [{'role': 'user',
                           'content': [{'type': 'text', 'text': 'hi'}]}],
            'tools': [{'name': 'get_time',
                       'input_schema': {'type': 'object'}}]}


class ClaudeIngressTests(unittest.TestCase):
    def _server(self, **overrides):
        state = _test_state(_auth_file(self))
        state.update(overrides)
        server = _start_server(state)
        self.addCleanup(server.shutdown)
        return server

    def test_openrouter_slug_reaches_openrouter_with_key_only_and_identical_body(self):
        # Listing visibility never gates routing: the hidden Anthropic alias
        # takes the same byte-identical OpenRouter path as a visible slug.
        for slug in ('z-ai/glm-5.3-flash', '~anthropic/claude-sonnet-latest'):
            with self.subTest(slug=slug):
                self._check_openrouter_split(slug)

    def _check_openrouter_split(self, slug):
        recorded = install_fake(self, lambda: FakeUpstream(
            200, b'{"id":"msg_1","type":"message","content":[]}', []))
        server = self._server()
        payload = _messages(slug)
        raw = json.dumps(payload)
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('POST', '/test-token/v1/messages', body=raw,
                     headers={'Content-Type': 'application/json',
                              'Authorization': 'Bearer subscription-secret',
                              'x-api-key': 'client-key',
                              'anthropic-version': '2023-06-01',
                              'Cookie': 'c=1'})
        self.assertEqual(conn.getresponse().read(),
                         b'{"id":"msg_1","type":"message","content":[]}')
        self.assertEqual(len(recorded), 1)
        host, _, path, body, headers = recorded[0]
        self.assertEqual(host, 'openrouter.ai')
        self.assertEqual(path, '/api/v1/messages')
        self.assertEqual(headers, {'Authorization': 'Bearer test-key',
                                   'Content-Type': 'application/json'})
        self.assertEqual(body.decode(), raw)
        self.assertNotIn('subscription-secret', json.dumps(headers) + body.decode())
        self.assertNotIn('client-key', json.dumps(headers) + body.decode())

    def test_count_tokens_follows_the_same_split(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{"input_tokens":3}', []))
        server = self._server()
        response = _post(server.server_port, '/test-token/v1/messages/count_tokens',
                         _messages(), {'Authorization': 'Bearer test-key-bearer'})
        self.assertEqual(response.status, 200)
        host, _, path, _, _ = recorded[0]
        self.assertEqual((host, path), ('openrouter.ai', '/api/v1/messages/count_tokens'))

    def test_subscription_model_forwards_client_auth_and_betas_untouched(self):
        recorded = install_fake(self, lambda: FakeUpstream(
            200, b'{"id":"msg_2","type":"message","content":[]}', []))
        server = self._server()
        response = _post(server.server_port, '/test-token/v1/messages',
                         _messages('claude-opus-4-6'),
                         {'Authorization': 'Bearer subscription-secret',
                          'anthropic-version': '2023-06-01',
                          'anthropic-beta': 'prompt-caching-2024-07-31',
                          'Connection': 'keep-alive'})
        self.assertEqual(response.status, 200)
        host, _, path, _, headers = recorded[0]
        self.assertEqual(host, 'api.anthropic.com')
        self.assertEqual(path, '/v1/messages')
        self.assertEqual(headers.get('Authorization'), 'Bearer subscription-secret')
        self.assertEqual(headers.get('anthropic-version'), '2023-06-01')
        self.assertEqual(headers.get('anthropic-beta'), 'prompt-caching-2024-07-31')
        self.assertNotIn('Connection', headers)
        self.assertNotIn('test-key', json.dumps(headers))

    def test_subscription_accepts_api_key_auth(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server()
        response = _post(server.server_port, '/test-token/v1/messages',
                         _messages('claude-opus-4-6'), {'x-api-key': 'client-key'})
        self.assertEqual(response.status, 200)
        self.assertEqual(recorded[0][0], 'api.anthropic.com')
        self.assertEqual(recorded[0][4].get('x-api-key'), 'client-key')

    def test_subscription_without_client_auth_is_401(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server()
        response = _post(server.server_port, '/test-token/v1/messages',
                         _messages('claude-opus-4-6'))
        self.assertEqual(response.status, 401)
        self.assertEqual(recorded, [])

    def test_subscription_without_router_path_token_is_rejected(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server()
        response = _post(server.server_port, '/v1/messages',
                         _messages('claude-opus-4-6'),
                         {'Authorization': 'Bearer subscription-secret'})
        self.assertEqual(response.status, 403)
        self.assertEqual(recorded, [])

    def test_no_subscription_mode_serves_openrouter_but_rejects_passthrough(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server(openai_mode='none')
        ok_response = _post(server.server_port, '/test-token/v1/messages',
                            _messages(), {'Authorization': 'Bearer test-key-bearer'})
        self.assertEqual(ok_response.status, 200)
        bad_response = _post(server.server_port, '/test-token/v1/messages',
                             _messages('claude-opus-4-6'),
                             {'Authorization': 'Bearer subscription-secret'})
        self.assertEqual(bad_response.status, 400)
        self.assertEqual(len(recorded), 1)

    def test_missing_model_is_400_and_never_reaches_upstream(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server()
        payload = _messages()
        del payload['model']
        response = _post(server.server_port, '/test-token/v1/messages', payload)
        self.assertEqual(response.status, 400)
        self.assertEqual(recorded, [])


if __name__ == '__main__':
    unittest.main()
