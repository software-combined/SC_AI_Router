"""Capability-flag mapping from registry rows to catalogue entries."""
import unittest
from dataclasses import replace
from codex_router.catalogue import openrouter_entry
from codex_router.registry import by_slug


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
        from codex_router.catalogue import openrouter_entry
        from codex_router.registry import MODELS, by_slug
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


if __name__ == '__main__':
    unittest.main()
