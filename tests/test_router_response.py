"""Router response correctness: error mapping and upstream header policy."""
import json
import unittest
from tests.fakes import FakeUpstream, install_fake
from tests.harness import (
    auth_file as _auth_file,
    post as _post,
    start_server as _start_server,
    test_state as _test_state,
)


class RouterResponseTests(unittest.TestCase):
    def _server(self, **state_overrides):
        state = _test_state(_auth_file(self))
        state.update(state_overrides)
        server = _start_server(state)
        self.addCleanup(server.shutdown)
        return server

    def test_internal_bug_is_500_not_400(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server()
        response = _post(server.server_port, '/test-token/responses',
                         {'model': 'z-ai/glm-5.3', 'input': [], 'tools': 'not-a-list'})
        self.assertEqual(response.status, 500)
        self.assertEqual(recorded, [])

    def test_image_turn_to_text_only_model_is_409_with_code(self):
        # Stable code is the catalog contract; statuses/messages are pinned elsewhere.
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server()
        response = _post(server.server_port, '/test-token/responses',
                         {'model': 'z-ai/glm-5.3', 'input': [
                             {'type': 'message', 'role': 'user', 'content': [
                                 {'type': 'input_text', 'text': 'look'},
                                 {'type': 'input_image',
                                  'image_url': 'data:image/png;base64,AAA'}]}]})
        self.assertEqual(response.status, 409)
        body = json.loads(response.read())
        self.assertEqual(body['error']['code'], 'PROVIDER_REJECTED')
        self.assertIn('does not accept image input', body['error']['message'])
        self.assertEqual(recorded, [])

    def test_unknown_model_is_400_with_code(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server()
        response = _post(server.server_port, '/test-token/responses',
                         {'model': 'nobody/none', 'input': []})
        self.assertEqual(response.status, 400)
        body = json.loads(response.read())
        self.assertEqual(body['error']['code'], 'UNKNOWN_MODEL')
        self.assertEqual(body['error'].get('candidates'), [])
        self.assertEqual(recorded, [])

    def test_retired_latest_alias_is_a_strict_miss(self):
        # The ~...-latest aliases are retired from the registry, so a
        # parent echoing one back gets UNKNOWN_MODEL naming the id, with no
        # candidate and no upstream call (identity stays strict).
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server()
        response = _post(server.server_port, '/test-token/responses',
                         {'model': '~anthropic/claude-opus-latest', 'input': []})
        self.assertEqual(response.status, 400)
        body = json.loads(response.read())
        self.assertEqual(body['error']['code'], 'UNKNOWN_MODEL')
        self.assertEqual(body['error']['model'], '~anthropic/claude-opus-latest')
        self.assertEqual(body['error']['candidates'], [])
        self.assertEqual(recorded, [])

    def test_openai_model_header_is_pinned_to_requested_model(self):
        # Upstream names a different id; the router re-pins the header to
        # the requested model, so the pair must stay different.
        install_fake(self, lambda: FakeUpstream(200, b'{"output": []}', [
            ('Content-Type', 'application/json'), ('openai-model', 'x-ai/grok-4.7')]))
        server = self._server()
        response = _post(server.server_port, '/test-token/responses',
            {'model': 'x-ai/grok-4.6', 'input': [],
             'tools': [{'type': 'custom', 'name': 'exec'}]})
        self.assertEqual(response.status, 200)
        response.read()
        self.assertEqual(response.getheader('openai-model'), 'x-ai/grok-4.6')

    def test_subscription_required_classification_is_type_based(self):
        # Plan 126: the raise sites and the mapper agree on the exception
        # type, so rewording a message cannot silently reclassify the body.
        from ai_router import claude as claude_mod
        from ai_router import errors, providers
        from ai_router.subscription_roster import SUBSCRIPTION_SLUGS
        slug = SUBSCRIPTION_SLUGS[0]
        with self.assertRaises(errors.SubscriptionRequired):
            providers.select(slug, '/responses', [slug], 'none')
        with self.assertRaises(errors.ClaudeSubscriptionRequired):
            claude_mod.select(slug, '/v1/messages', 'none')
        for exc, code in ((errors.SubscriptionRequired(), 'SUBSCRIPTION_REQUIRED'),
                          (errors.ClaudeSubscriptionRequired(),
                           'CLAUDE_SUBSCRIPTION_REQUIRED')):
            mapped = errors.map_client_error(exc)
            self.assertEqual((mapped.status, mapped.code), (400, code))

        class _Reworded(errors.SubscriptionRequired):
            def __init__(self):
                ValueError.__init__(self, 'please attach a subscription first')

        self.assertEqual(errors.map_client_error(_Reworded()).code,
                         'SUBSCRIPTION_REQUIRED')


if __name__ == '__main__':
    unittest.main()
