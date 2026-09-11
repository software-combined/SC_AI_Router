import json
import re
import unittest
from ai_router.capabilities import CANONICAL_ORDER
from ai_router.catalogue import OPENROUTER_TEMPLATE, openrouter_entry
from ai_router.registry import (FIELDS, MODELS, Model, by_slug, load, picker_key,
                                openrouter_slugs)
from ai_router.clients import models_for, visible_for

CATALOGUE_FIELDS = set(OPENROUTER_TEMPLATE) | {'slug', 'display_name', 'description',
    'default_reasoning_level', 'supported_reasoning_levels', 'priority',
    'context_window', 'max_context_window', 'input_modalities',
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
            ['low'], 'low', ['text'], [], 'native', None, False, 1, 100,
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
                    {**good, 'experimental_tools': ['ok', 7]},
                    {**good, 'drop_images': 'yes'}):
            with self.subTest(bad=bad):
                with self.assertRaises(SystemExit):
                    load(json.dumps([bad]))

    def test_tier_required_and_validated(self):
        for model in MODELS:
            self.assertIn(model.tier, ('verified', 'preview'), model.slug)
        good = dict(zip(FIELDS, ['x/y', 'openrouter', 'X', 'V',
            ['low'], 'low', ['text'], [], 'native', None, False, 1, 100,
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
        from ai_router.catalogue import merge
        native = {'slug': 'gpt-6-astra', 'display_name': 'Native'}
        stale = {'slug': 'moonshotai/kimi-k3', 'display_name': 'Stale',
                 'priority': 1, 'context_window': 1, 'max_context_window': 1,
                 'input_modalities': ['text'], 'default_reasoning_level': 'low',
                 'supported_reasoning_levels': [], 'description': 'stale'}
        catalog = {'models': [native, stale]}
        out = merge(catalog)
        slugs = [m['slug'] for m in out['models']]
        self.assertEqual(slugs[0], 'gpt-6-astra')
        self.assertEqual({key: out['models'][0][key] for key in native}, native)
        self.assertTrue(CATALOGUE_FIELDS <= out['models'][0].keys())
        kimi = out['models'][slugs.index('moonshotai/kimi-k3')]
        self.assertEqual(kimi['display_name'], 'MoonshotAI: Kimi K3 · OpenRouter')
        self.assertEqual(kimi['priority'], by_slug('moonshotai/kimi-k3').priority)
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertEqual(len(slugs), 1 + len(models_for(MODELS, 'codex')))

    def test_registry_priorities_follow_picker_order(self):
        # Codex lists the picker by ascending priority, so the numbers must
        # keep each vendor's rows together: vendor A-Z, verified before
        # preview, label A-Z inside a tier.
        ordered = sorted(MODELS, key=lambda m: picker_key(
            m.vendor, m.tier, m.display_name, m.slug))
        priorities = [m.priority for m in ordered]
        self.assertEqual(priorities, sorted(priorities))
        self.assertEqual(len(set(priorities)), len(priorities))
        vendors = [m.vendor.casefold() for m in ordered]
        self.assertEqual(vendors, sorted(vendors))

    def test_catalog_name_vendor_prefix_rule(self):
        from ai_router.catalogue import catalog_name
        deepseek = by_slug('deepseek/deepseek-v4-pro-0813')
        self.assertEqual(catalog_name(deepseek), 'DeepSeek: V4 Pro 0813')
        muse = by_slug('meta/muse-spark-1.3')
        self.assertEqual(catalog_name(muse), 'Meta: Muse Spark 1.3')

    def test_display_names_follow_qualified_naming_convention(self):
        # Picker labels must read '<Vendor>: <Model> <Version?>'; the vendor
        # prefix always equals the row's vendor field, alias rows track with
        # 'Latest' instead of a pinned snapshot, and pinned rows keep any
        # version/snapshot token verbatim (AGENTS.md section 8).
        for model in MODELS:
            if model.provider != 'openrouter':
                continue
            with self.subTest(slug=model.slug):
                short = model.display_name.removesuffix(' · OpenRouter')
                self.assertTrue(model.display_name.endswith(' · OpenRouter'))
                self.assertTrue(short.startswith(model.vendor + ': '),
                                f'{model.slug}: prefix must equal vendor')
                if re.search(r'\d{4}', short):
                    self.assertNotRegex(short, r'^\S+: \d{4}$',
                                        f'{model.slug}: snapshots keep model context')
        alias_labels = {m.slug: m.display_name for m in MODELS
                        if m.slug.startswith('~')}
        self.assertTrue(alias_labels)
        for slug, label in alias_labels.items():
            with self.subTest(slug=slug):
                self.assertIn('Latest', label)
        pinned = {m.slug: m.display_name for m in MODELS
                  if not m.slug.startswith('~')}
        self.assertTrue(any(re.search(r'\(0902\)|0423|0813', label)
                            for label in pinned.values()))

    def test_by_slug_and_openrouter_slugs(self):
        self.assertEqual(by_slug('moonshotai/kimi-k3').vendor, 'MoonshotAI')
        self.assertIsNone(by_slug('unknown/model'))
        self.assertEqual(openrouter_slugs(),
                         {m.slug for m in MODELS if m.provider == 'openrouter'})

    def test_visibility_hides_only_the_claude_same_billing_rows(self):
        self.assertEqual({m.slug for m in MODELS if m.provider == 'openrouter'
                          and not visible_for(m, 'codex')}, set())
        self.assertEqual({m.slug for m in MODELS if m.provider == 'openrouter'
                          and not visible_for(m, 'claude')},
                         {'~anthropic/claude-sonnet-latest', '~anthropic/claude-fable-latest',
                          '~anthropic/claude-haiku-latest', '~anthropic/claude-opus-latest'})

    def test_visibility_keeps_subscription_and_other_vendor_rows(self):
        openai_sub = Model(slug='gpt-6-astra', provider='openai', display_name='G',
                           vendor='OpenAI', reasoning=('low',), default_reasoning='low')
        self.assertTrue(visible_for(openai_sub, 'codex'))
        self.assertTrue(visible_for(openai_sub, 'claude'))
        self.assertTrue(visible_for(by_slug('moonshotai/kimi-k3'), 'codex'))
        self.assertTrue(visible_for(by_slug('moonshotai/kimi-k3'), 'claude'))
        self.assertTrue(visible_for(by_slug('openai/gpt-6-astra'), 'claude'))
        self.assertTrue(visible_for(by_slug('~anthropic/claude-sonnet-latest'), 'codex'))

    def test_visibility_tilde_and_plain_prefixes_both_hide(self):
        self.assertFalse(visible_for(by_slug('~anthropic/claude-sonnet-latest'), 'claude'))
        plain = Model(slug='anthropic/claude-sonnet-latest', provider='openrouter',
                      display_name='X', vendor='Anthropic', reasoning=('low',),
                      default_reasoning='low')
        self.assertFalse(visible_for(plain, 'claude'))
        self.assertTrue(visible_for(plain, 'codex'))
        self.assertTrue(visible_for(by_slug('openai/gpt-6-astra'), 'codex'))

    def test_near_miss_offers_bare_tilde_alias_only(self):
        from ai_router.registry import near_miss
        self.assertEqual(near_miss('anthropic/claude-opus-latest'),
                         '~anthropic/claude-opus-latest')
        self.assertIsNone(near_miss('nobody/none'))
        self.assertIsNone(near_miss('~anthropic/claude-opus-latest'))
        self.assertIsNone(near_miss('z-ai/glm-5.3'))
        self.assertIsNone(near_miss(None))
        self.assertIsNone(near_miss(''))

    def test_models_for_matches_visibility_and_rejects_unknown_client(self):
        for client in ('codex', 'claude'):
            self.assertEqual({m.slug for m in models_for(MODELS, client)},
                             {m.slug for m in MODELS if visible_for(m, client)})
        with self.assertRaises(ValueError):
            models_for(MODELS, 'other')
        with self.assertRaises(ValueError):
            visible_for(by_slug('moonshotai/kimi-k3'), 'other')

    def test_codex_picker_lists_openai_twins_without_include_twins(self):
        twins = {m.slug for m in models_for(MODELS, 'codex')
                 if m.slug.startswith('openai/')}
        self.assertEqual(twins, {'openai/gpt-6-astra', 'openai/gpt-5.6-sol',
                                 'openai/gpt-5.6-terra', 'openai/gpt-5.6-luna'})

if __name__ == '__main__':
    unittest.main()
