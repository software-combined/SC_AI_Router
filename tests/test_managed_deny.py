"""Plan 176 step 3: an empty allowlist denies on every route.

The managed-deny contract: when the resolved allowlist is empty - a managed
install with no readable policy - routing, the picker catalogue, the model
listing and the announcement surfaces all refuse the same external rows,
while subscription routing keeps working. Plan 176's live proof is recorded
in `docs/compatibility.md`; this pins it offline.
"""
import json
import tempfile
import unittest
from pathlib import Path

from ai_router import claude, model_prompt, protocols, providers
from ai_router.catalogue import merge
from ai_router.protocols import messages, responses


class ManagedDenyTests(unittest.TestCase):
    def test_both_protocol_families_refuse_an_external_slug(self):
        # Routing is the gate that matters: no allowlist entry, no provider.
        state = {'openai_models': ['gpt-6-astra'], 'allowed_models': []}
        with self.assertRaisesRegex(ValueError, 'not in the configured catalog'):
            responses.POLICY.select_provider(
                'z-ai/glm-5.3-flash', '/responses', state, 'subscription')
        with self.assertRaisesRegex(ValueError, 'not in the configured catalog'):
            messages.POLICY.select_provider(
                'claude/z-ai/glm-5.3-flash', '/v1/messages', state,
                'subscription')

    def test_subscription_routing_survives_an_empty_allowlist(self):
        state = {'openai_models': ['gpt-6-astra'], 'allowed_models': []}
        provider = responses.POLICY.select_provider(
            'gpt-6-astra', '/responses', state, 'subscription')
        self.assertIsInstance(provider, providers.SubscriptionProvider)

    def test_the_picker_and_the_listing_hide_every_external_row(self):
        self.assertEqual(merge({'models': []}, allowed=()), {'models': []})
        self.assertEqual(claude.models_listing(()), {'data': []})

    def test_the_discovery_route_serves_the_listing_it_computed(self):
        # The table owns the GET, so the handler path cannot bypass the gate.
        self.assertEqual(protocols.listing('GET', '/v1/models', allowed=()),
                         {'data': []})

    def test_nothing_is_announced_for_a_denied_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / 'model-policy.json'
            policy.write_text(json.dumps(
                {'portco': 'acme', 'department': None, 'allowed_models': []}))
            policy.chmod(0o600)
            # The direct projection proves the gate: a first-run `pending()`
            # seeds silently whatever is visible, so it cannot carry this on
            # its own.
            self.assertEqual(model_prompt.visible_models(tmp), [])
            self.assertEqual(model_prompt.pending(tmp), [])
            snapshot = json.loads((Path(tmp) / 'model-prompt.json').read_text())
            self.assertEqual(snapshot['seen'], [])
            self.assertEqual(model_prompt.pending(tmp), [])
            self.assertEqual(model_prompt.notice(tmp), (None, []))


if __name__ == '__main__':
    unittest.main()
