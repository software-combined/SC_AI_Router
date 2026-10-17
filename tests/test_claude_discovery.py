"""Claude Desktop discovery and saved-session routing contracts."""
import json
from dataclasses import replace
import unittest
from unittest import mock

from ai_router import availability, claude, registry
from ai_router.errors import UnknownModel


class DesktopDiscoveryTests(unittest.TestCase):
    def test_discovery_keeps_vendor_identity_even_when_a_client_filters_it(self):
        with mock.patch.object(availability, 'combined_ids', return_value=None):
            rows = claude.models_listing()['data']
        expected = {m.slug: m.display_name for m in registry.MODELS
                    if m.listed and m.provider == 'openrouter'}
        self.assertEqual(len(rows), len(expected))
        for row in rows:
            with self.subTest(model=row['display_name']):
                slug = claude.resolve(row['id'])
                self.assertEqual(row['id'], slug.removeprefix('~'))
                if not row['id'].startswith('anthropic/claude-'):
                    self.assertNotIn('anthropic_family_tier', row)
                self.assertEqual(row['display_name'], expected[slug])

    def test_truthful_tracking_id_still_resolves_to_its_registered_provider(self):
        entry = replace(registry.by_slug('deepseek/deepseek-v4.1-flash-1017'),
                        slug='~deepseek/deepseek-v4.1-flash-1017')
        rows = {entry.slug: entry}
        identifier = claude.row_alias(entry)
        self.assertEqual(identifier, 'deepseek/deepseek-v4.1-flash-1017')
        self.assertEqual(claude.resolve(identifier, rows), entry.slug)
        with mock.patch.object(availability, 'permitted', return_value=True):
            provider = claude.select(identifier, '/v1/messages',
                                     allowed=[entry.slug], catalogue=rows)
        self.assertEqual(provider.name, entry.provider)

    def test_discovered_and_saved_aliases_keep_the_same_billing_and_body(self):
        slug = 'deepseek/deepseek-v4.1-flash-1017'
        payload = {'model': slug, 'max_tokens': 64,
                   'messages': [{'role': 'user', 'content': 'synthetic probe'}]}
        credentials = mock.Mock()
        credentials.key_for.return_value = 'test-provider-key'
        for model in (claude.claude_alias(slug), slug):
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
        for model in ('claude/scg/' + '0' * 64, 'claude/deepseek/deepseek-v4.1-flash-1017'):
            with self.subTest(model=model), self.assertRaises(UnknownModel):
                claude.select(model, '/v1/messages')


if __name__ == '__main__':
    unittest.main()
