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
from tests.harness import (
    auth_file as _auth_file,
    post as _post,
    start_server as _start_server,
    test_state as _test_state,
)
from tests.test_claude_ingress import _messages


class ProtocolContractTests(unittest.TestCase):
    def test_protocol_rows_derive_from_their_path_owners(self):
        # Plan 125: a path added to providers/claude is routable here with
        # no second edit, and the union stays exact.
        from ai_router import claude as claude_mod
        from ai_router import protocols, providers as providers_mod
        from ai_router.protocols import messages as messages_mod
        from ai_router.protocols import responses as responses_mod
        for path in providers_mod.NATIVE_SERVICE_PATHS:
            self.assertIs(protocols.select('POST', path), responses_mod.POLICY)
        for path in claude_mod.CLAUDE_POST_PATHS:
            self.assertIs(protocols.select('POST', path), messages_mod.POLICY)
        self.assertEqual(
            protocols.owned_paths(),
            frozenset(providers_mod.NATIVE_SERVICE_PATHS)
            | claude_mod.CLAUDE_POST_PATHS
            | {'/responses', '/responses/compact', '/v1/models'})

    def test_policy_names_are_the_definition_constants(self):
        # Plan 155 (F10): the table exports the protocol names, so a policy
        # name cannot drift into a second literal.
        from ai_router import provider_defs
        from ai_router.protocols import messages as messages_mod
        from ai_router.protocols import responses as responses_mod
        self.assertEqual(responses_mod.POLICY.name, provider_defs.RESPONSES)
        self.assertEqual(messages_mod.POLICY.name, provider_defs.MESSAGES)

    def test_the_discovery_listing_is_a_table_row(self):
        # Plan 155 (F10): the handler asks the table, so the GET is owned by
        # the Messages family; an allowlist that names nothing lists nothing,
        # and the Responses family serves no listing at all.
        from ai_router import protocols
        from ai_router.protocols import messages as messages_mod
        self.assertIs(protocols.select('GET', '/v1/models'), messages_mod.POLICY)
        self.assertIsNone(protocols.select('POST', '/v1/models'))
        self.assertIsNone(protocols.listing('GET', '/responses'))
        self.assertEqual(protocols.listing('GET', '/v1/models', allowed=()),
                         {'data': []})

    def test_the_listing_hides_rows_outside_the_allowlist(self):
        # Every row this listing serves is externally routed, so the portco
        # allowlist is the whole answer: one named slug, one row.
        from ai_router import claude, protocols, registry
        from ai_router.clients import client_table
        defn = client_table.get('claude')
        slug = next(m.slug for m in registry.MODELS
                    if defn.discovery_visible(m) and claude.claude_alias(m.slug))
        listed = protocols.listing('GET', '/v1/models', allowed=(slug,))
        self.assertEqual([row['id'] for row in listed['data']],
                         [claude.claude_alias(slug)])

    def test_the_listing_without_an_allowlist_is_unchanged(self):
        from ai_router import claude, protocols
        self.assertEqual(protocols.listing('GET', '/v1/models'),
                         claude.models_listing())

    def test_native_prefix_paths_select_the_responses_policy(self):
        # Plan 171: the prefix rule routes new backend paths with no second
        # edit; the exact union above stays pinned.
        from ai_router import protocols
        from ai_router.protocols import responses as responses_mod
        for path in ('/alpha/history/v2/list_items', '/alpha/notes/v2/write_file',
                     '/alpha/search', '/guardian-classifier'):
            self.assertIs(protocols.select('POST', path), responses_mod.POLICY)
        for path in ('/alphabet', '/alpha/../v1/me', '/alpha/%2e%2e/x'):
            self.assertIsNone(protocols.select('POST', path))

    def _server(self, **overrides):
        state = _test_state(_auth_file(self))
        state.update(overrides)
        server = _start_server(state)
        self.addCleanup(server.shutdown)
        return server

    def test_messages_quota_429_keeps_retryable_503_shape(self):
        # The 429 quota/auth split is Responses-only: a Messages 429 with a
        # quota-coded body keeps today's 503, byte-identical.
        install_fake(self, lambda: FakeUpstream(429, b'{"error": {"code": "insufficient_quota"}}',
                                                [('Content-Type', 'application/json')]))
        server = self._server()
        response = _post(server.server_port, '/test-token/v1/messages',
                         _messages(), {'Authorization': 'Bearer subscription-secret'})
        self.assertEqual(response.status, 503)

    def test_messages_402_names_key_credit(self):
        # No separate wording fork: the shared policy names the key on
        # Messages too, as the client-visible status for the turn.
        install_fake(self, lambda: FakeUpstream(
            402, b'{"error": {"code": "insufficient_credits", "message": "out"}}',
            [('Content-Type', 'application/json')]))
        server = self._server()
        response = _post(server.server_port, '/test-token/v1/messages',
                         _messages(), {'Authorization': 'Bearer subscription-secret'})
        self.assertEqual(response.status, 400)
        body = json.loads(response.read())
        self.assertEqual(body['error']['code'], 'KEY_NO_CREDIT')
        self.assertIn('Contact IT', body['error']['message'])

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
        # An external route's transient 429 keeps the neutral wording.
        self.assertEqual(json.loads(response.read())['error']['message'],
                         'Upstream rate limited')

    def test_messages_subscription_429_names_the_claude_subscription(self):
        # The subscription row's refusal names the model and the
        # subscription; the external row above keeps the neutral text.
        install_fake(self, lambda: FakeUpstream(
            429, b'{"error": "slow"}', [('Content-Type', 'application/json')]))
        server = self._server()
        response = _post(server.server_port, '/test-token/v1/messages',
                         _messages('claude-opus-4-6'),
                         {'Authorization': 'Bearer subscription-secret'})
        self.assertEqual(response.status, 503)
        body = json.loads(response.read())
        self.assertEqual(body['error']['code'], 'UPSTREAM_RATE_LIMITED')
        self.assertIn('claude-opus-4-6 is rate limited on your Claude subscription',
                      body['error']['message'])

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
