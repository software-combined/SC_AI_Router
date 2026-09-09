"""Interactive roster and request contracts from the 2026-09-08 metadata refresh."""
import json
import unittest
from types import SimpleNamespace

from codex_router.apply_catalogue import apply
from codex_router.catalogue import RETIRED_SLUGS, merge
from codex_router.providers import OpenRouterProvider, PreparationError, select
from codex_router.registry import by_slug

LATEST_DEEPSEEK = (('deepseek/deepseek-v4-pro-0813', 1048576, 384000, ('text',)),
                   ('~deepseek/deepseek-v4-flash-latest', 1310720, 393216, ('text',)),
                   ('deepseek/deepseek-v4-flash-vision-exp', 1048576, 384000,
                    ('text', 'image')))


class ModelRosterTests(unittest.TestCase):
    def test_only_four_claude_aliases_reach_picker_and_router_after_upgrade(self):
        slugs = ['~anthropic/claude-' + name + '-latest'
                 for name in ('opus', 'sonnet', 'haiku', 'fable')]
        base = {'models': [{'slug': 'anthropic/claude-opus-5'},
                           {'slug': 'anthropic/claude-fable-5.1'},
                           {'slug': 'gpt-6-astra'}]}
        entries = {m['slug']: m for m in merge(base)['models']}
        self.assertEqual(entries['gpt-6-astra']['slug'], 'gpt-6-astra')
        self.assertEqual(entries['gpt-6-astra']['display_name'], 'GPT-6-Astra')
        self.assertEqual({s for s in entries if 'claude-' in s}, set(slugs))
        for slug in slugs:
            with self.subTest(slug=slug):
                self.assertIsInstance(select(slug, '/responses', []), OpenRouterProvider)
                self.assertIn('Anthropic', entries[slug]['description'])

    def test_latest_deepseek_metadata_and_preview_status(self):
        for slug, context, output, modalities in LATEST_DEEPSEEK:
            model = by_slug(slug)
            with self.subTest(slug=slug):
                self.assertIsNotNone(model)
                self.assertEqual(model.reasoning, ('low', 'high', 'max'))
                self.assertEqual(model.context_window, context)
                self.assertEqual(model.max_output_tokens, output)
                self.assertEqual(model.modalities, modalities)
                self.assertEqual(model.tier, 'preview')
        # Existing tasks retain their original upstream identity.
        self.assertIsNotNone(by_slug('deepseek/deepseek-v4-pro'))
        # The dated flash snapshots merged into the flash-latest alias.
        self.assertIsNone(by_slug('deepseek/deepseek-v4-flash'))
        self.assertIsNone(by_slug('deepseek/deepseek-v4-flash-0731'))
        self.assertIn('deepseek/deepseek-v4-flash', RETIRED_SLUGS)
        self.assertIn('deepseek/deepseek-v4-flash-0731', RETIRED_SLUGS)

    def test_retired_deepseek_snapshots_drop_from_merged_catalogue(self):
        stale_flash = {'slug': 'deepseek/deepseek-v4-flash'}
        stale_0731 = {'slug': 'deepseek/deepseek-v4-flash-0731'}
        merged = merge({'models': [stale_flash, stale_0731]})
        slugs = {m['slug'] for m in merged['models']}
        self.assertNotIn('deepseek/deepseek-v4-flash', slugs)
        self.assertNotIn('deepseek/deepseek-v4-flash-0731', slugs)
        self.assertIn('~deepseek/deepseek-v4-flash-latest', slugs)

    def test_claude_without_effort_control_survives_refresh_and_prepares_none(self):
        slug = '~anthropic/claude-haiku-latest'
        entries = apply(merge({'models': []}), {slug: {'reasoning': {'mandatory': False}}})
        entry = next(m for m in entries['models'] if m['slug'] == slug)
        self.assertEqual(entry['supported_reasoning_levels'],
                         [{'effort': 'none', 'description': 'No reasoning'}])
        provider = select(slug, '/responses', [])
        payload = {'model': slug, 'input': [], 'reasoning': {'effort': 'none'}}
        prepared = provider.prepare(slug, '/responses', payload, b'',
                                    {'Authorization': 'Bearer subscription-test'},
                                    SimpleNamespace(openrouter_key=lambda: 'router-test'))
        self.assertEqual(json.loads(prepared.body)['reasoning'], {'effort': 'none'})
        self.assertEqual(prepared.headers['Authorization'], 'Bearer router-test')
        payload['reasoning']['effort'] = 'high'
        with self.assertRaises(PreparationError):
            provider.prepare(slug, '/responses', payload, b'', {}, None)
