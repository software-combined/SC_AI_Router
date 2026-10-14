"""Pin the live Argon capability projection and retained Gemini rows."""
import unittest

from ai_router.catalogue import external_entry
from ai_router.clients import visible_for
from ai_router.registry import by_slug


class GeminiArgonRegistryTests(unittest.TestCase):
    def test_argon_exposes_verified_capabilities_to_both_clients(self):
        row = by_slug('google/gemini-4-argon')
        self.assertIsNotNone(row)
        self.assertEqual(row.provider, 'openrouter')
        self.assertEqual(row.reasoning, ('low', 'medium', 'high'))
        self.assertEqual(row.default_reasoning, 'low')
        self.assertEqual(row.context_window, 1048576)
        self.assertEqual(row.max_output_tokens, 65536)
        self.assertEqual(row.modalities, ('text', 'image', 'audio'))
        self.assertFalse(row.drop_images)
        self.assertEqual(row.tier, 'verified')
        self.assertTrue(row.listed)
        for client in ('codex', 'claude'):
            self.assertTrue(visible_for(row, client), client)
        projected = external_entry(row)
        self.assertEqual(projected['slug'], row.slug)
        self.assertEqual(projected['default_reasoning_level'], 'low')
        self.assertEqual(projected['context_window'], 1048576)

    def test_existing_gemini_rows_remain_without_verified_supersession(self):
        for slug in ('google/gemini-3.1-pro-preview', 'google/gemini-3.8-flash'):
            self.assertIsNotNone(by_slug(slug), slug)
