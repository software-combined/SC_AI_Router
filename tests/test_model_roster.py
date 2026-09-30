"""Interactive roster and request contracts for the pinned-model roster."""
import json
import unittest
from types import SimpleNamespace

from ai_router.apply_catalogue import apply
from ai_router.catalogue import RETIRED_SLUGS, merge
from ai_router.providers import ExternalResponsesProvider, PreparationError, select
from ai_router.registry import MODELS, by_slug

PINNED_CLAUDE = ('anthropic/claude-fable-5.1', 'anthropic/claude-haiku-4.5',
                 'anthropic/claude-opus-5.5', 'anthropic/claude-sonnet-5.5')
RETIRED_LATEST = ('~anthropic/claude-sonnet-latest', '~anthropic/claude-fable-latest',
                  '~anthropic/claude-haiku-latest', '~anthropic/claude-opus-latest',
                  '~google/gemini-flash-latest', '~google/gemini-pro-latest',
                  '~x-ai/grok-latest')

PINNED_DEEPSEEK = (('deepseek/deepseek-v4-pro-0813', 1048576, 384000, ('text',)),
                   ('deepseek/deepseek-v4.1-flash', 1048576, 384000,
                    ('text', 'image')))
RETIRED_DEEPSEEK = ('deepseek/deepseek-v4-pro', 'deepseek/deepseek-v4-flash',
                    'deepseek/deepseek-v4-flash-0731',
                    '~deepseek/deepseek-v4-flash-latest',
                    'deepseek/deepseek-v4-flash-vision-exp')

# The pinned roster follows Grok by exact id: 4.7 replaces 4.6, and the
# superseded pin retires the way a superseded alias does.
PINNED_GROK = 'x-ai/grok-4.7'
RETIRED_GROK = 'x-ai/grok-4.6'
# Sonnet follows the same rule: 5.5 replaces 5 by exact id.
PINNED_SONNET = 'anthropic/claude-sonnet-5.5'
RETIRED_SONNET = 'anthropic/claude-sonnet-5'
# Terra leaves the OpenRouter picker with no replacement; the ChatGPT
# subscription row keeps its place.
RETIRED_TERRA, SUBSCRIPTION_TERRA = 'openai/gpt-5.6-terra', 'gpt-5.6-terra'


class ModelRosterTests(unittest.TestCase):
    def test_only_four_pinned_claude_rows_reach_picker_and_router_after_upgrade(self):
        base = {'models': [{'slug': '~anthropic/claude-opus-latest'},
                           {'slug': '~google/gemini-pro-latest'},
                           {'slug': 'gpt-6-astra'}]}
        entries = {m['slug']: m for m in merge(base)['models']}
        self.assertEqual(entries['gpt-6-astra']['slug'], 'gpt-6-astra')
        self.assertEqual(entries['gpt-6-astra']['display_name'], 'GPT-6-Astra')
        self.assertEqual({s for s in entries if 'claude-' in s}, set(PINNED_CLAUDE))
        for slug in PINNED_CLAUDE:
            with self.subTest(slug=slug):
                self.assertIsInstance(select(slug, '/responses', []), ExternalResponsesProvider)
                self.assertIn('Anthropic', entries[slug]['description'])

    def test_roster_pins_exact_ids_and_retires_every_latest_alias(self):
        # AGENTS.md section 8: no row is a tilde alias today; the retired
        # latest ids stay in RETIRED_SLUGS so upgrades drop them from the
        # picker, and a stale catalogue cannot bring them back.
        self.assertEqual([m.slug for m in MODELS if m.slug.startswith('~')], [])
        stale = [{'slug': slug} for slug in RETIRED_LATEST]
        merged = {m['slug'] for m in merge({'models': stale})['models']}
        for slug in RETIRED_LATEST:
            with self.subTest(slug=slug):
                self.assertIn(slug, RETIRED_SLUGS)
                self.assertIsNone(by_slug(slug))
                self.assertNotIn(slug, merged)
        for slug in PINNED_CLAUDE:
            with self.subTest(pinned=slug):
                self.assertIn(slug, merged)

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

    def test_superseded_pinned_grok_id_retires_on_upgrade(self):
        # A machine whose catalogue still carries the superseded pin must
        # drop it rather than keep offering a row the roster retired.
        grok = by_slug(PINNED_GROK)
        self.assertEqual(grok.tier, 'verified')
        self.assertEqual(grok.schema_mode, 'json_text_root')
        self.assertEqual(grok.max_tools, 350)
        self.assertTrue(grok.drop_images)
        self.assertIsNone(by_slug(RETIRED_GROK))
        self.assertIn(RETIRED_GROK, RETIRED_SLUGS)
        merged = {m['slug'] for m in merge({'models': [{'slug': RETIRED_GROK}]})['models']}
        self.assertNotIn(RETIRED_GROK, merged)
        self.assertIn(PINNED_GROK, merged)

    def test_superseded_pinned_sonnet_id_retires_on_upgrade(self):
        # A picker file that still lists Sonnet 5 drops it at the next merge,
        # and the verified 5.5 row takes its place under the naming rule.
        sonnet = by_slug(PINNED_SONNET)
        self.assertEqual((sonnet.tier, sonnet.listed), ('verified', True))
        self.assertEqual(sonnet.display_name, 'Anthropic: Claude Sonnet 5.5 · OpenRouter')
        self.assertIsNone(by_slug(RETIRED_SONNET))
        self.assertIn(RETIRED_SONNET, RETIRED_SLUGS)
        merged = {m['slug'] for m in merge({'models': [{'slug': RETIRED_SONNET}]})['models']}
        self.assertNotIn(RETIRED_SONNET, merged)
        self.assertIn(PINNED_SONNET, merged)

    def test_retired_openrouter_terra_drops_on_upgrade_and_the_subscription_row_stays(self):
        # A picker file that still lists the OpenRouter row drops it at the next
        # merge; the subscription row of the same name is untouched.
        self.assertIsNone(by_slug(RETIRED_TERRA))
        self.assertIn(RETIRED_TERRA, RETIRED_SLUGS)
        stale = {'models': [{'slug': RETIRED_TERRA}, {'slug': SUBSCRIPTION_TERRA}]}
        merged = {m['slug'] for m in merge(stale)['models']}
        self.assertNotIn(RETIRED_TERRA, merged)
        self.assertIn(SUBSCRIPTION_TERRA, merged)

    def test_claude_without_effort_control_survives_refresh_and_prepares_none(self):
        slug = 'anthropic/claude-haiku-4.5'
        entries = apply(merge({'models': []}), {slug: {'reasoning': {'mandatory': False}}})
        entry = next(m for m in entries['models'] if m['slug'] == slug)
        self.assertEqual(entry['supported_reasoning_levels'],
                         [{'effort': 'none', 'description': 'No reasoning'}])
        provider = select(slug, '/responses', [])
        payload = {'model': slug, 'input': [], 'reasoning': {'effort': 'none'}}
        prepared = provider.prepare(slug, '/responses', payload, b'',
                                    {'Authorization': 'Bearer subscription-test'},
                                    SimpleNamespace(key_for=lambda _pid=None: 'router-test'))
        self.assertEqual(json.loads(prepared.body)['reasoning'], {'effort': 'none'})
        self.assertEqual(prepared.headers['Authorization'], 'Bearer router-test')
        payload['reasoning']['effort'] = 'high'
        with self.assertRaises(PreparationError):
            provider.prepare(slug, '/responses', payload, b'', {}, None)
