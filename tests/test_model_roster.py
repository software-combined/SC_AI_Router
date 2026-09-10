"""Interactive roster and request contracts for the pinned-model roster."""
import json
import unittest
from types import SimpleNamespace

from ai_router.apply_catalogue import apply
from ai_router.catalogue import RETIRED_SLUGS, merge
from ai_router.providers import OpenRouterProvider, PreparationError, select
from ai_router.registry import by_slug

PINNED_DEEPSEEK = (('deepseek/deepseek-v4-pro-0813', 1048576, 384000, ('text',)),
                   ('deepseek/deepseek-v4.1-flash', 1048576, 384000,
                    ('text', 'image')))
RETIRED_DEEPSEEK = ('deepseek/deepseek-v4-pro', 'deepseek/deepseek-v4-flash',
                    'deepseek/deepseek-v4-flash-0731',
                    '~deepseek/deepseek-v4-flash-latest',
                    'deepseek/deepseek-v4-flash-vision-exp')


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

    def test_pinned_deepseek_metadata_and_verified_status(self):
        for slug, context, output, modalities in PINNED_DEEPSEEK:
            model = by_slug(slug)
            with self.subTest(slug=slug):
                self.assertIsNotNone(model)
                self.assertEqual(model.reasoning, ('low', 'high', 'max'))
                self.assertEqual(model.context_window, context)
                self.assertEqual(model.max_output_tokens, output)
                self.assertEqual(model.modalities, modalities)
                self.assertEqual(model.tier, 'verified')
        # DeepSeek keeps two pinned rows; the alias and Vision rows are retired.
        for slug in RETIRED_DEEPSEEK:
            with self.subTest(slug=slug):
                self.assertIsNone(by_slug(slug))
                self.assertIn(slug, RETIRED_SLUGS)

    def test_retired_deepseek_snapshots_drop_from_merged_catalogue(self):
        stale = [{'slug': slug} for slug in RETIRED_DEEPSEEK]
        merged = merge({'models': stale})
        slugs = {m['slug'] for m in merged['models']}
        for slug in RETIRED_DEEPSEEK:
            self.assertNotIn(slug, slugs)
        self.assertIn('deepseek/deepseek-v4.1-flash', slugs)

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
