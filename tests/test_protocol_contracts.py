"""Plan 062 Step 1: freeze the two observable protocol contracts.

Responses and Messages traverse the same HTTP transport with explicitly
selected policy. These pins use FakeUpstream and the local handler harness
only. Add only missing cases needed to tell whether the extraction changes
on-wire behavior; existing handler/ingress/response/V2 suites own the rest.
"""
import http.client
import json
import unittest

from tests.fakes import FakeUpstream, install_fake
from tests.test_handler import _auth_file, _post
from tests.test_mixed_router import _start_server, _test_state
from tests.test_claude_ingress import _messages


class ProtocolContractTests(unittest.TestCase):
    def _server(self, **overrides):
        state = _test_state(_auth_file(self))
        state.update(overrides)
        server = _start_server(state)
        self.addCleanup(server.shutdown)
        return server

    def test_messages_429_keeps_retryable_503_shape(self):
        # Responses pins this in test_handler; Messages must keep the same
        # transport-level retry contract through the shared relay path.
        install_fake(self, lambda: FakeUpstream(429, b'{"error": "slow"}',
                                                [('Content-Type', 'application/json'),
                                                 ('Retry-After', '7')]))
        server = self._server()
        response = _post(server.server_port, '/test-token/v1/messages',
                         _messages(), {'Authorization': 'Bearer subscription-secret'})
        self.assertEqual(response.status, 503)
        self.assertEqual(response.getheader('Retry-After'), '7')

    def test_messages_response_shares_the_model_pin_behavior(self):
        # Coupling pin: the shared relay path currently pins openai-model on
        # Messages responses too. Preserved through extraction; a later change
        # needs a client contract test or live compatibility gate.
        install_fake(self, lambda: FakeUpstream(
            200, b'{"id":"msg_1","type":"message","content":[]}',
            [('Content-Type', 'application/json')]))
        server = self._server()
        response = _post(server.server_port, '/test-token/v1/messages',
                         _messages(), {'Authorization': 'Bearer subscription-secret'})
        self.assertEqual(response.status, 200)
        response.read()
        self.assertEqual(response.getheader('openai-model'), 'z-ai/glm-5.3-flash')

    def test_messages_alias_body_stays_byte_identical(self):
        # The ingress contract is byte-identity: a known alias slug is a
        # registry slug already, so resolve() returns it unchanged and the
        # whole body forwards untouched.
        recorded = install_fake(self, lambda: FakeUpstream(
            200, b'{"id":"msg_1","type":"message","content":[]}', []))
        server = self._server()
        payload = _messages('anthropic/claude-sonnet-5')
        raw = json.dumps(payload)
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('POST', '/test-token/v1/messages', body=raw,
                     headers={'Content-Type': 'application/json',
                              'Authorization': 'Bearer subscription-secret'})
        self.assertEqual(conn.getresponse().status, 200)
        self.assertEqual(recorded[0][3].decode(), raw)

    def test_unknown_paths_cause_no_upstream_call(self):
        for path in ('/test-token/nope', '/test-token/v1/unknown'):
            with self.subTest(path=path):
                recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
                server = self._server()
                response = _post(server.server_port, path,
                                 {'model': 'z-ai/glm-5.3', 'input': []})
                self.assertEqual(response.status, 404)
                response.read()
                self.assertEqual(recorded, [])

    def test_missing_token_is_rejected_without_upstream_call(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server()
        response = _post(server.server_port, '/wrong-token/responses',
                         {'model': 'z-ai/glm-5.3', 'input': []})
        self.assertEqual(response.status, 403)
        response.read()
        self.assertEqual(recorded, [])


if __name__ == '__main__':
    unittest.main()
