import json
import unittest
from codex_router.capabilities import CANONICAL_ORDER
from codex_router.catalogue import OPENROUTER_TEMPLATE, openrouter_entry
from codex_router.registry import FIELDS, MODELS, Model, by_slug, load, openrouter_slugs

CATALOGUE_FIELDS = set(OPENROUTER_TEMPLATE) | {'slug', 'display_name', 'description',
    'default_reasoning_level', 'supported_reasoning_levels', 'priority',
    'context_window', 'max_context_window', 'input_modalities', 'base_instructions',
    'supports_reasoning_summary_parameter'}

class RegistryTests(unittest.TestCase):
    def test_slugs_unique(self):
        self.assertEqual(len({m.slug for m in MODELS}), len(MODELS))

    def test_default_reasoning_is_supported(self):
        for model in MODELS:
            self.assertIn(model.default_reasoning, model.reasoning, model.slug)

    def test_reasoning_in_canonical_order(self):
        for model in MODELS:
            self.assertEqual(list(model.reasoning),
                [lv for lv in CANONICAL_ORDER if lv in model.reasoning], model.slug)

    def test_excluded_efforts_not_in_reasoning(self):
        for model in MODELS:
            self.assertFalse(set(model.reasoning) & set(model.excluded_efforts), model.slug)

    def test_provider_is_known(self):
        for model in MODELS:
            self.assertIn(model.provider, {'openrouter', 'openai'}, model.slug)

    def test_openrouter_entry_has_every_catalogue_field(self):
        for model in MODELS:
            if model.provider == 'openrouter':
                self.assertEqual(set(openrouter_entry(model)), CATALOGUE_FIELDS, model.slug)

    def test_bad_row_shape_is_refused(self):
        good = dict(zip(FIELDS, ['x/y', 'openrouter', 'X', 'V',
            ['low'], 'low', ['text'], [], 'native', None, 1, 100,
            32768, 'none', 'none', [], True, 'verified']))
        for bad in ({k: v for k, v in good.items() if k != 'vendor'},
                    {k: v for k, v in good.items() if k != 'web_search'},
                    {**good, 'provider': 'other'},
                    {**good, 'default_reasoning': 'max'},
                    {**good, 'reasoning_summary': 'sometimes'},
                    {**good, 'apply_patch': 'diff'},
                    {**good, 'max_output_tokens': 0},
                    {**good, 'max_output_tokens': 'many'},
                    {**good, 'web_search': 'yes'},
                    {**good, 'experimental_tools': ['ok', 7]}):
            with self.subTest(bad=bad):
                with self.assertRaises(SystemExit):
                    load(json.dumps([bad]))

    def test_tier_required_and_validated(self):
        for model in MODELS:
            self.assertIn(model.tier, ('verified', 'preview'), model.slug)
        good = dict(zip(FIELDS, ['x/y', 'openrouter', 'X', 'V',
            ['low'], 'low', ['text'], [], 'native', None, 1, 100,
            32768, 'none', 'none', [], True, 'verified']))
        for bad in ({k: v for k, v in good.items() if k != 'tier'},
                    {**good, 'tier': 'beta'}):
            with self.subTest(bad=bad):
                with self.assertRaises(SystemExit):
                    load(json.dumps([bad]))

    def test_capability_flags_default_conservative(self):
        model = Model(slug='x/y', provider='openrouter', display_name='X',
                      vendor='V', reasoning=('low',), default_reasoning='low')
        self.assertEqual(model.max_output_tokens, 32768)
        self.assertEqual(model.reasoning_summary, 'none')
        self.assertEqual(model.apply_patch, 'none')
        self.assertEqual(model.experimental_tools, ())
        self.assertTrue(model.web_search)

    def test_merge_preserves_replaces_appends_without_dupes(self):
        from codex_router.catalogue import merge
        native = {'slug': 'gpt-6-astra', 'display_name': 'Native'}
        stale = {'slug': 'moonshotai/kimi-k3', 'display_name': 'Stale',
                 'priority': 1, 'context_window': 1, 'max_context_window': 1,
                 'input_modalities': ['text'], 'default_reasoning_level': 'low',
                 'supported_reasoning_levels': [], 'description': 'stale'}
        catalog = {'models': [native, stale]}
        out = merge(catalog)
        slugs = [m['slug'] for m in out['models']]
        self.assertEqual(slugs[0], 'gpt-6-astra')
        self.assertEqual(out['models'][0], native)
        kimi = out['models'][slugs.index('moonshotai/kimi-k3')]
        self.assertEqual(kimi['display_name'], 'Kimi K3 · OpenRouter')
        self.assertEqual(kimi['priority'], 104)
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertEqual(len(slugs), 1 + len(openrouter_slugs()))

    def test_catalog_name_vendor_prefix_rule(self):
        from codex_router.catalogue import catalog_name
        deepseek = by_slug('deepseek/deepseek-v4-pro')
        self.assertEqual(catalog_name(deepseek), 'DeepSeek V4 Pro 0423')
        muse = by_slug('meta/muse-spark-1.3')
        self.assertEqual(catalog_name(muse), 'Meta: Muse Spark 1.3')

    def test_by_slug_and_openrouter_slugs(self):
        self.assertEqual(by_slug('moonshotai/kimi-k3').vendor, 'MoonshotAI')
        self.assertIsNone(by_slug('unknown/model'))
        self.assertEqual(openrouter_slugs(),
                         {m.slug for m in MODELS if m.provider == 'openrouter'})

if __name__ == '__main__':
    unittest.main()
