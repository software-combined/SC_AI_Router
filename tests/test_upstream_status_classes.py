"""Responses status classes: deterministic 400s, retryable 503s (Plan 169).

Fake upstream only; never opens a real network connection. Upstream 429
bodies classify from structured codes (quota/auth/transient) and 5xx/408
turns answer 503; the Messages path pins its unchanged answers in
tests/test_protocol_contracts.py and tests/test_claude_ingress.py.
"""
import json
import unittest
from unittest import mock

from ai_router import relay as relay_mod
from tests.fakes import FakeUpstream, install_fake
from tests.harness import (
    auth_file as _auth_file,
    post as _post,
    start_server as _start_server,
    test_state as _test_state,
)


class UpstreamStatusClassTests(unittest.TestCase):
    def _server(self, **state_overrides):
        state = _test_state(_auth_file(self))
        state.update(state_overrides)
        server = _start_server(state)
        self.addCleanup(server.shutdown)
        return server

    def test_responses_quota_429_is_a_final_400(self):
        install_fake(self, lambda: FakeUpstream(
            429, b'{"error": {"code": "insufficient_quota", "message": "no credit"}}',
            [('Content-Type', 'application/json')]))
        server = self._server()
        response = _post(server.server_port, '/test-token/responses',
                         {'model': 'z-ai/glm-5.3', 'input': []})
        self.assertEqual(response.status, 400)
        body = json.loads(response.read())
        self.assertEqual(body['error']['code'], 'PROVIDER_REJECTED')
        self.assertIn('no remaining credit', body['error']['message'])

    def test_responses_auth_429_opens_the_key_window(self):
        install_fake(self, lambda: FakeUpstream(
            429, b'{"error": {"code": "invalid_api_key", "message": "bad key"}}',
            [('Content-Type', 'application/json')]))
        server = self._server()
        server.credentials.key_rejected = lambda provider: True
        server.credentials.home = '/nonexistent-test-home'
        with mock.patch.object(relay_mod.setup, 'open_key_window') as window:
            response = _post(server.server_port, '/test-token/responses',
                             {'model': 'z-ai/glm-5.3', 'input': []})
        self.assertEqual(response.status, 400)
        body = json.loads(response.read())
        self.assertEqual(body['error']['code'], 'CREDENTIAL_PROBLEM')
        self.assertIn('key setup page', body['error']['message'])
        self.assertEqual(window.call_count, 1)

    def test_responses_transient_429_stays_retryable_503(self):
        install_fake(self, lambda: FakeUpstream(
            429, b'{"error": {"code": "rate_limit_exceeded", "message": "slow"}}',
            [('Content-Type', 'application/json')]))
        server = self._server()
        response = _post(server.server_port, '/test-token/responses',
                         {'model': 'z-ai/glm-5.3', 'input': []})
        self.assertEqual(response.status, 503)
        self.assertEqual(response.getheader('Retry-After'), '2')

    def test_responses_upstream_502_is_a_retryable_503(self):
        install_fake(self, lambda: FakeUpstream(
            502, b'{"error": {"message": "model down"}}',
            [('Content-Type', 'application/json')]))
        server = self._server()
        response = _post(server.server_port, '/test-token/responses',
                         {'model': 'z-ai/glm-5.3', 'input': []})
        self.assertEqual(response.status, 503)
        body = json.loads(response.read())
        self.assertEqual(body['error']['code'], 'UPSTREAM_UNAVAILABLE')
        self.assertIn('retry shortly', body['error']['message'])
        self.assertEqual(response.getheader('Retry-After'), '2')
