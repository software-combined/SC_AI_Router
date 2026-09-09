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
from codex_router import claude as claude_mod
from codex_router.registry import MODELS


def _messages(model='z-ai/glm-5.3-flash'):
    return {'model': model, 'max_tokens': 64,
            'system': 'Be brief.',
            'messages': [{'role': 'user',
                           'content': [{'type': 'text', 'text': 'hi'}]}],
            'tools': [{'name': 'get_time',
                       'input_schema': {'type': 'object'}}]}


def _get(port, target):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    conn.request('GET', target)
    return conn.getresponse()


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

    def test_models_listing_lists_every_openrouter_row_once(self):
        server = self._server()
        response = _get(server.server_port, '/test-token/v1/models')
        self.assertEqual(response.status, 200)
        body = json.loads(response.read())
        ids = [row['id'] for row in body['data']]
        self.assertEqual(len(ids), len(set(ids)))
        want = {claude_mod.claude_alias(m.slug) for m in MODELS
                if m.provider == 'openrouter'}
        self.assertEqual(set(ids), want)
        for row in body['data']:
            self.assertEqual(set(row), {'id', 'display_name'})
        listed = {row['id']: row['display_name'] for row in body['data']}
        self.assertEqual(
            listed['claude/z-ai/glm-5.3-flash'], 'Z.ai: GLM 5.3 Flash \u00b7 OpenRouter')
        self.assertIn('anthropic/claude-sonnet-latest', listed)

    def test_models_listing_ignores_discovery_query_string(self):
        # Claude fetches <base>/v1/models?limit=1000; the query must not 404.
        server = self._server()
        response = _get(server.server_port, '/test-token/v1/models?limit=1000')
        self.assertEqual(response.status, 200)
        self.assertIn('data', json.loads(response.read()))

    def test_models_listing_requires_router_token(self):
        server = self._server()
        self.assertEqual(_get(server.server_port, '/v1/models').status, 403)

    def test_models_listing_needs_no_openrouter_key(self):
        # Discovery is metadata, not billable: a keyless router still lists.
        server = _start_server(_test_state('/nonexistent'))
        self.addCleanup(server.shutdown)
        self.assertEqual(_get(server.server_port, '/test-token/v1/models').status, 200)

    def test_discovery_alias_routes_to_openrouter_with_registry_slug(self):
        recorded = install_fake(self, lambda: FakeUpstream(
            200, b'{"id":"msg_3","type":"message","content":[]}', []))
        server = self._server()
        for alias, slug in (('claude/z-ai/glm-5.3-flash', 'z-ai/glm-5.3-flash'),
                            ('anthropic/claude-sonnet-latest',
                             '~anthropic/claude-sonnet-latest')):
            with self.subTest(alias=alias):
                recorded.clear()
                response = _post(server.server_port, '/test-token/v1/messages',
                                 _messages(alias),
                                 {'Authorization': 'Bearer test-key-bearer'})
                self.assertEqual(response.status, 200)
                host, _, path, body, _ = recorded[0]
                self.assertEqual((host, path), ('openrouter.ai', '/api/v1/messages'))
                self.assertEqual(json.loads(body)['model'], slug)

    def test_direct_slug_still_routes_byte_identical(self):
        recorded = install_fake(self, lambda: FakeUpstream(
            200, b'{"id":"msg_4","type":"message","content":[]}', []))
        server = self._server()
        payload = _messages('z-ai/glm-5.3-flash')
        raw = json.dumps(payload)
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('POST', '/test-token/v1/messages', body=raw,
                     headers={'Content-Type': 'application/json'})
        self.assertEqual(conn.getresponse().status, 200)
        self.assertEqual(recorded[0][3].decode(), raw)

    def test_post_with_query_string_routes_like_bare_path(self):
        # Claude's gateway client sends /v1/messages?beta=true; the query
        # must not 404 a route the bare path serves.
        recorded = install_fake(self, lambda: FakeUpstream(
            200, b'{"id":"msg_q","type":"message","content":[]}', []))
        server = self._server()
        response = _post(server.server_port, '/test-token/v1/messages?beta=true',
                         _messages(), {'Authorization': 'Bearer test-key-bearer'})
        self.assertEqual(response.status, 200)
        host, _, path, _, _ = recorded[0]
        self.assertEqual((host, path), ('openrouter.ai', '/api/v1/messages'))

    def test_post_to_models_listing_is_404(self):
        server = self._server()
        response = _post(server.server_port, '/test-token/v1/models',
                         _messages(), {'Authorization': 'Bearer test-key-bearer'})
        self.assertEqual(response.status, 404)

    def test_unknown_claude_prefixed_id_passes_through_to_subscription(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server()
        response = _post(server.server_port, '/test-token/v1/messages',
                         _messages('claude/bogus'),
                         {'Authorization': 'Bearer subscription-secret'})
        self.assertEqual(response.status, 200)
        host, _, _, body, _ = recorded[0]
        self.assertEqual(host, 'api.anthropic.com')
        self.assertEqual(json.loads(body)['model'], 'claude/bogus')

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
