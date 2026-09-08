"""Capability-flag mapping from registry rows to catalogue entries."""
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from codex_router.catalogue import catalog_name, check, merge, openrouter_entry
from codex_router.registry import MODELS, by_slug, models_for


class CatalogueFlagTests(unittest.TestCase):
    def test_entry_reflects_capability_flags(self):
        everything = replace(by_slug('z-ai/glm-5.3-flash'),
                             modalities=('text', 'audio'), max_output_tokens=5000,
                             reasoning_summary='auto', apply_patch='freeform',
                             experimental_tools=('clock',), web_search=False)
        entry = openrouter_entry(everything)
        self.assertEqual(entry['input_modalities'], ['text', 'audio'])
        self.assertEqual(entry['default_reasoning_summary'], 'auto')
        self.assertTrue(entry['supports_reasoning_summary_parameter'])
        self.assertEqual(entry['apply_patch_tool_type'], 'freeform')
        self.assertEqual(entry['experimental_supported_tools'], ['clock'])
        self.assertEqual(entry['web_search_tool_type'], 'text')

    def test_defaults_keep_current_catalogue_values(self):
        entry = openrouter_entry(by_slug('z-ai/glm-5.3-flash'))
        self.assertEqual(entry['default_reasoning_summary'], 'none')
        self.assertFalse(entry['supports_reasoning_summary_parameter'])
        self.assertIsNone(entry['apply_patch_tool_type'])
        self.assertEqual(entry['experimental_supported_tools'], [])
        self.assertEqual(entry['web_search_tool_type'], 'text_and_image')

    def test_preview_entry_is_labelled(self):
        preview = replace(by_slug('z-ai/glm-5.3-flash'), tier='preview')
        entry = openrouter_entry(preview)
        self.assertTrue(entry['display_name'].endswith(' · Preview'))
        self.assertTrue(entry['description'].startswith(
            'Preview, not yet verified with Codex. '))
        verified_top = max(openrouter_entry(m)['priority']
                           for m in MODELS if m.tier == 'verified')
        self.assertGreater(entry['priority'], verified_top)
        plain = openrouter_entry(by_slug('z-ai/glm-5.3-flash'))
        self.assertFalse(plain['display_name'].endswith('Preview'))
        self.assertEqual(entry['slug'], plain['slug'])
        self.assertEqual(entry['context_window'], plain['context_window'])


    def test_instructions_live_in_model_messages_template(self):
        from codex_router.catalogue import BASE_INSTRUCTIONS
        entry = openrouter_entry(by_slug('z-ai/glm-5.3-flash'))
        self.assertNotIn('base_instructions', entry)
        self.assertEqual(entry['model_messages'],
                         {'instructions_template': BASE_INSTRUCTIONS})
        self.assertTrue(BASE_INSTRUCTIONS.startswith(
            'You are Codex, a coding agent running the selected OpenRouter model.'))
        merged = merge({'models': []})
        for item in merged['models']:
            self.assertNotIn('base_instructions', item)
            self.assertIn('instructions_template', item['model_messages'])

    def test_alias_display_name_keeps_own_prefix(self):
        alias = replace(by_slug('~x-ai/grok-latest'),
                          display_name='SpaceXAI: Grok 4.6 \xb7 OpenRouter')
        self.assertEqual(catalog_name(alias), 'SpaceXAI: Grok 4.6')
        plain = replace(by_slug('z-ai/glm-5.3-flash'))
        self.assertTrue(catalog_name(plain).startswith(plain.vendor + ': '))
        self.assertEqual(alias.slug, '~x-ai/grok-latest')

    def test_merge_preserves_openai_entries_and_refreshes_stale_rows(self):
        slug = next(m.slug for m in models_for('codex') if m.provider == 'openrouter')
        stale = dict(openrouter_entry(by_slug(slug)), description='stale')
        base = {'models': [{'slug': 'gpt-6-astra'}, {'slug': 'gpt-5.6-luna'}, stale]}
        merged = merge(base)
        slugs = [m['slug'] for m in merged['models']]
        self.assertEqual(slugs[:2], ['gpt-6-astra', 'gpt-5.6-luna'])
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertNotEqual(merged['models'][2]['description'], 'stale')
        for model in models_for('codex'):
            if model.provider == 'openrouter':
                self.assertIn(model.slug, slugs)

    def test_merge_then_check_round_trips(self):
        merged = merge({'models': []})
        slugs = {m['slug'] for m in merged['models']}
        for model in models_for('codex'):
            if model.provider == 'openrouter':
                self.assertIn(model.slug, slugs)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'catalogue.json'
            path.write_text(json.dumps(merged))
            self.assertTrue(check(str(path)))

    def test_merge_drops_preexisting_hidden_rows_on_upgrade(self):
        stale = dict(openrouter_entry(by_slug('openai/gpt-6-astra')),
                     description='stale-install')
        merged = merge({'models': [stale]}, client='codex')
        self.assertNotIn('openai/gpt-6-astra',
                         {m['slug'] for m in merged['models']})
        hid = dict(openrouter_entry(by_slug('~anthropic/claude-sonnet-latest')),
                   description='stale-install')
        self.assertNotIn('~anthropic/claude-sonnet-latest',
                         {m['slug'] for m in merge({'models': [hid]},
                                                   client='claude')['models']})

    def test_check_rejects_hidden_rows_left_in_catalogue(self):
        stale = dict(openrouter_entry(by_slug('openai/gpt-6-astra')),
                     description='stale-install')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'stale.json'
            path.write_text(json.dumps({'models': [stale]}))
            self.assertFalse(check(str(path), 'codex'))

    def test_merge_is_per_client_and_round_trips(self):
        codex = merge({'models': []}, client='codex')
        claude = merge({'models': []}, client='claude')
        codex_slugs = {m['slug'] for m in codex['models']}
        claude_slugs = {m['slug'] for m in claude['models']}
        for model in models_for('codex'):
            if model.provider == 'openrouter':
                self.assertIn(model.slug, codex_slugs)
        for model in models_for('claude'):
            if model.provider == 'openrouter':
                self.assertIn(model.slug, claude_slugs)
        self.assertFalse(codex_slugs & {'openai/gpt-6-astra', 'openai/gpt-5.6-sol',
                                        'openai/gpt-5.6-luna', 'openai/gpt-5.6-terra'})
        self.assertFalse(claude_slugs & {'~anthropic/claude-sonnet-latest',
                                         '~anthropic/claude-fable-latest',
                                         '~anthropic/claude-haiku-latest',
                                         '~anthropic/claude-opus-latest'})
        self.assertIn('openai/gpt-6-astra', claude_slugs)
        self.assertIn('~anthropic/claude-sonnet-latest', codex_slugs)
        with tempfile.TemporaryDirectory() as tmp:
            for client, merged in (('codex', codex), ('claude', claude)):
                path = Path(tmp) / f'{client}.json'
                path.write_text(json.dumps(merged))
                self.assertTrue(check(str(path), client))

    def test_client_flag_round_trip_on_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            for client, hidden in (('codex', 'openai/gpt-6-astra'),
                                   ('claude', '~anthropic/claude-sonnet-latest')):
                target = Path(tmp) / f'{client}.json'
                proc = subprocess.run(
                    [sys.executable, '-m', 'codex_router.catalogue',
                     '--client', client, '--merge', str(target)],
                    capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertNotIn(hidden, {m['slug'] for m in
                                          json.loads(target.read_text())['models']})
                proc = subprocess.run(
                    [sys.executable, '-m', 'codex_router.catalogue',
                     '--client', client, '--check', str(target)],
                    capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)


class CatalogueSchemaCompatTests(unittest.TestCase):
    """Codex >=0.153.4 requires every catalogue row to carry the full schema.

    The subscription roster used to seed bare {'slug': ...} stubs and the
    OpenRouter template lacked the newer required fields; either made chat
    creation fail with 'failed to parse model_catalog_json ... missing field
    `display_name`' (2026-09-08, Codex 26.901.51231 / client 0.153.4).
    """

    REQUIRED_FIELDS = (
        'slug', 'display_name', 'description', 'shell_type', 'visibility',
        'supported_in_api', 'additional_speed_tiers', 'service_tiers',
        'availability_nux', 'upgrade', 'model_messages',
        'include_skills_usage_instructions', 'include_plugin_usage_instructions',
        'include_apps_usage_instructions', 'default_reasoning_summary',
        'supports_reasoning_summaries', 'supports_reasoning_summary_parameter',
        'support_verbosity', 'default_verbosity', 'apply_patch_tool_type',
        'web_search_tool_type', 'truncation_policy',
        'supports_image_detail_original', 'comp_hash', 'context_window',
        'max_context_window', 'default_reasoning_level',
        'supported_reasoning_levels', 'input_modalities', 'priority',
        'available_in_plans', 'prefer_websockets', 'minimal_client_version',
        'supports_parallel_tool_calls', 'default_service_tier',
        'model_specialty', 'auto_compact_token_limit',
        'auto_review_model_override', 'experimental_supported_tools',
        'supports_search_tool', 'use_responses_lite',
        'node_repl_auto_review_required', 'node_repl_disabled', 'tool_mode',
        'multi_agent_version')

    def test_every_merged_row_carries_the_required_schema(self):
        merged = merge({'models': []},
                       roster=('gpt-6-astra', 'gpt-reserve', 'codex-auto-review'))
        for row in merged['models']:
            with self.subTest(slug=row['slug']):
                for field in self.REQUIRED_FIELDS:
                    self.assertIn(field, row)
                self.assertTrue(row['display_name'])
                self.assertTrue(row['description'])

    def test_roster_stub_display_names_match_the_live_picker(self):
        merged = merge({'models': []},
                       roster=('gpt-6-astra', 'gpt-reserve', 'gpt-5.6-sol',
                               'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5',
                               'gpt-5.4-mini', 'gpt-5.3-codex-spark',
                               'codex-auto-review'))
        names = {m['slug']: m['display_name'] for m in merged['models']}
        self.assertEqual(names['gpt-6-astra'], 'GPT-6-Astra')
        self.assertEqual(names['gpt-reserve'], 'GPT-Reserve')
        self.assertEqual(names['gpt-5.6-sol'], 'GPT-5.6-Sol')
        self.assertEqual(names['gpt-5.6-terra'], 'GPT-5.6-Terra')
        self.assertEqual(names['gpt-5.6-luna'], 'GPT-5.6-Luna')
        self.assertEqual(names['gpt-5.5'], 'GPT-5.5')
        self.assertEqual(names['gpt-5.4-mini'], 'GPT-5.4-Mini')
        self.assertEqual(names['gpt-5.3-codex-spark'], 'GPT-5.3-Codex-Spark')
        self.assertEqual(names['codex-auto-review'], 'Codex Auto Review')

    def test_unknown_roster_slug_falls_back_to_slug_as_display_name(self):
        merged = merge({'models': []}, roster=('gpt-totally-new',))
        row = next(m for m in merged['models'] if m['slug'] == 'gpt-totally-new')
        self.assertEqual(row['display_name'], 'gpt-totally-new')
        self.assertTrue(row['description'])

    def test_openrouter_template_matches_codex_required_fields(self):
        entry = openrouter_entry(by_slug('z-ai/glm-5.3-flash'))
        self.assertTrue(entry['prefer_websockets'])
        self.assertTrue(entry['supports_parallel_tool_calls'])
        self.assertTrue(entry['supports_reasoning_summaries'])
        self.assertEqual(entry['minimal_client_version'], '0.153.0')
        self.assertEqual(entry['default_service_tier'], None)
        self.assertEqual(entry['model_specialty'], None)
        self.assertEqual(entry['auto_compact_token_limit'], None)
        self.assertEqual(entry['auto_review_model_override'], None)
        self.assertIn('free', entry['available_in_plans'])
        self.assertIn('enterprise', entry['available_in_plans'])


class CatalogueRosterTests(unittest.TestCase):
    def test_merge_seeds_missing_roster_slugs_as_stubs(self):
        merged = merge({'models': []}, roster=('gpt-6-astra', 'gpt-5.6-luna'))
        by_slug = {m['slug']: m for m in merged['models']}
        self.assertEqual(by_slug['gpt-6-astra']['slug'], 'gpt-6-astra')
        self.assertEqual(by_slug['gpt-5.6-luna']['slug'], 'gpt-5.6-luna')
        self.assertEqual(by_slug['gpt-6-astra']['display_name'], 'GPT-6-Astra')
        self.assertEqual(by_slug['gpt-5.6-luna']['display_name'], 'GPT-5.6-Luna')
        for model in models_for('codex'):
            if model.provider == 'openrouter':
                self.assertIn(model.slug, by_slug)

    def test_merge_never_rewrites_existing_roster_entries(self):
        rich = {'slug': 'gpt-6-astra', 'display_name': 'GPT-6-Astra'}
        merged = merge({'models': [dict(rich)]}, roster=('gpt-6-astra', 'gpt-5.6-luna'))
        by_slug = {m['slug']: m for m in merged['models']}
        self.assertEqual(by_slug['gpt-6-astra'], rich)
        self.assertIn('gpt-5.6-luna', by_slug)
        slugs = [m['slug'] for m in merged['models']]
        self.assertEqual(len(slugs), len(set(slugs)))

    def test_read_roster_from_sibling_state(self):
        from codex_router.catalogue import read_roster
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / 'mixed-models.json'
            self.assertEqual(read_roster(catalog), ())
            (Path(tmp) / 'mixed-router-state.json').write_text(
                json.dumps({'port': 1, 'token': 't',
                            'openai_models': ['gpt-6-astra']}) + '\n')
            self.assertEqual(read_roster(catalog), ('gpt-6-astra',))

    def test_read_roster_rejects_non_object_state(self):
        from codex_router.catalogue import read_roster
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'mixed-router-state.json').write_text('[1, 2]\n')
            self.assertEqual(read_roster(Path(tmp) / 'mixed-models.json'), ())

    def test_merge_cli_seeds_roster_from_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'mixed-router-state.json').write_text(
                json.dumps({'port': 1, 'token': 't',
                            'openai_models': ['gpt-6-astra']}) + '\n')
            target = home / 'mixed-models.json'
            proc = subprocess.run(
                [sys.executable, '-m', 'codex_router.catalogue', '--merge', str(target)],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            slugs = {m['slug'] for m in json.loads(target.read_text())['models']}
            self.assertIn('gpt-6-astra', slugs)


if __name__ == '__main__':
    unittest.main()
