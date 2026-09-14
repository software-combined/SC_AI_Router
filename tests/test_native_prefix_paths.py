"""Native service prefix rule: forward, local 404, and traversal refusal (Plan 171).

Fake upstream only; never opens a real network connection. Subscription
mode forwards prefix paths to the ChatGPT backend with the client's own
login; `none` mode answers them locally; siblings and traversal shapes
stay UNSUPPORTED_ROUTE and never reach the upstream.
"""
import http.client
import json
import unittest

from tests.fakes import FakeUpstream, install_fake
from tests.harness import (
    auth_file as _auth_file,
    post as _post,
    start_server as _start_server,
    test_state as _test_state,
)


class NativePrefixPathTests(unittest.TestCase):
    def _server(self, **state_overrides):
        state = _test_state(_auth_file(self))
        state.update(state_overrides)
        server = _start_server(state)
        self.addCleanup(server.shutdown)
        return server

    def test_native_prefix_path_forwards_with_client_headers_only(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{"items": []}', []))
        server = self._server(openai_models=['gpt-6-astra'])
        response = _post(server.server_port, '/test-token/alpha/history/v2/list_items',
                         {'cursor': 'w1'},
                         {'Authorization': 'Bearer subscription-secret',
                          'Cookie': 'c=1'})
        self.assertEqual(response.status, 200)
        self.assertEqual(len(recorded), 1)
        host, _, path, _, headers = recorded[0]
        self.assertEqual((host, path),
                         ('chatgpt.com', '/backend-api/codex/alpha/history/v2/list_items'))
        self.assertEqual(headers.get('Authorization'), 'Bearer subscription-secret')
        self.assertNotIn('Cookie', headers)
        self.assertNotIn('openrouter', json.dumps(headers).lower())

    def test_native_prefix_path_without_model_is_accepted(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server(openai_models=['gpt-6-astra'])
        response = _post(server.server_port, '/test-token/alpha/notes/v2/write_file',
                         {'path': 'n.txt', 'text': 'checkpoint'})
        self.assertEqual(response.status, 200)
        self.assertEqual(len(recorded), 1)

    def test_native_prefix_path_in_none_mode_answers_locally(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server(openai_models=['gpt-6-astra'], openai_mode='none')
        response = _post(server.server_port, '/test-token/alpha/history/v2/list_items',
                         {'cursor': 'w1'})
        self.assertEqual(response.status, 404)
        self.assertEqual(json.loads(response.read())['error']['code'], 'NATIVE_UNAVAILABLE')
        self.assertEqual(recorded, [])

    def test_sibling_of_native_prefix_is_not_routed(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server(openai_models=['gpt-6-astra'])
        response = _post(server.server_port, '/test-token/alphabet',
                         {'cursor': 'w1'})
        self.assertEqual(response.status, 404)
        self.assertEqual(json.loads(response.read())['error']['code'], 'UNSUPPORTED_ROUTE')
        self.assertEqual(recorded, [])

    def test_traversal_native_path_never_reaches_upstream(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server(openai_models=['gpt-6-astra'])
        for path in ('/test-token/alpha/../v1/me', '/test-token/alpha/%2e%2e/x'):
            with self.subTest(path=path):
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
                conn.request('POST', path, body=json.dumps({'x': 1}),
                             headers={'Content-Type': 'application/json',
                                      'Authorization': 'Bearer subscription-secret'})
                response = conn.getresponse()
                self.assertEqual(response.status, 404)
                self.assertEqual(json.loads(response.read())['error']['code'],
                                 'UNSUPPORTED_ROUTE')
        self.assertEqual(recorded, [])
