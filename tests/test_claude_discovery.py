"""Claude Desktop discovery and saved-session routing contracts."""
import json
import re
import unittest
from unittest import mock

from ai_router import availability, claude, registry
from ai_router.errors import UnknownModel


class DesktopDiscoveryTests(unittest.TestCase):
    def test_desktop_accepts_every_listed_model_without_renaming_it(self):
        # Desktop 2.2553.1 rejects these ID fragments even with a family tier.
        rejected = re.compile(r'deepseek|gemini|glm|gpt|grok|kimi|moonshot|openai')
        with mock.patch.object(availability, 'combined_ids', return_value=None):
            rows = claude.models_listing()['data']
        expected = {m.slug: m.display_name for m in registry.MODELS
                    if m.listed and m.provider == 'openrouter'}
        self.assertEqual(len(rows), len(expected))
        for row in rows:
            with self.subTest(model=row['display_name']):
                self.assertIsNone(rejected.search(row['id']))
                self.assertIn('claude', row['id'])
                slug = claude.resolve(row['id'])
                self.assertEqual(row['display_name'], expected[slug])

    def test_discovered_and_saved_aliases_keep_the_same_billing_and_body(self):
        slug = 'deepseek/deepseek-v4.1-flash'
        payload = {'model': slug, 'max_tokens': 64,
                   'messages': [{'role': 'user', 'content': 'synthetic probe'}]}
        credentials = mock.Mock()
        credentials.key_for.return_value = 'test-provider-key'
        for model in (claude.claude_alias(slug), 'claude/' + slug, slug):
            with self.subTest(model=model), \
                    mock.patch.object(availability, 'permitted', return_value=True):
                provider = claude.select(model, '/v1/messages', allowed=[slug])
                body = dict(payload, model=model)
                prepared = provider.prepare(model, '/v1/messages', body,
                                            json.dumps(body).encode(),
                                            {'Authorization': 'Bearer client-secret'},
                                            credentials)
                self.assertEqual(provider.name, 'openrouter')
                self.assertEqual(json.loads(prepared.body), payload)
                self.assertNotIn('client-secret', str(prepared.headers))
                with self.assertRaises(UnknownModel):
                    claude.select(model, '/v1/messages', allowed=[])

    def test_unknown_router_alias_cannot_fall_through_to_subscription(self):
        with self.assertRaises(UnknownModel):
            claude.select('claude/scg/' + '0' * 64, '/v1/messages')


if __name__ == '__main__':
    unittest.main()
