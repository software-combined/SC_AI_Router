"""Capability-flag mapping from registry rows to catalogue entries."""
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from codex_router.catalogue import check, merge, openrouter_entry
from codex_router.registry import MODELS, by_slug


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

    def test_merge_preserves_openai_entries_and_refreshes_stale_rows(self):
        slug = next(m.slug for m in MODELS if m.provider == 'openrouter')
        stale = dict(openrouter_entry(by_slug(slug)), description='stale')
        base = {'models': [{'slug': 'gpt-6-astra'}, {'slug': 'gpt-5.6-luna'}, stale]}
        merged = merge(base)
        slugs = [m['slug'] for m in merged['models']]
        self.assertEqual(slugs[:2], ['gpt-6-astra', 'gpt-5.6-luna'])
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertNotEqual(merged['models'][2]['description'], 'stale')
        for model in MODELS:
            if model.provider == 'openrouter':
                self.assertIn(model.slug, slugs)

    def test_merge_then_check_round_trips(self):
        merged = merge({'models': []})
        slugs = {m['slug'] for m in merged['models']}
        for model in MODELS:
            if model.provider == 'openrouter':
                self.assertIn(model.slug, slugs)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'catalogue.json'
            path.write_text(json.dumps(merged))
            self.assertTrue(check(str(path)))


class CatalogueRosterTests(unittest.TestCase):
    def test_merge_seeds_missing_roster_slugs_as_stubs(self):
        merged = merge({'models': []}, roster=('gpt-6-astra', 'gpt-5.6-luna'))
        by_slug = {m['slug']: m for m in merged['models']}
        self.assertEqual(by_slug['gpt-6-astra'], {'slug': 'gpt-6-astra'})
        self.assertEqual(by_slug['gpt-5.6-luna'], {'slug': 'gpt-5.6-luna'})
        for model in MODELS:
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
        import subprocess
        import sys
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
