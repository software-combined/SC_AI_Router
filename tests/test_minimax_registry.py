"""Pin MiniMax's verified free endpoint without inventing a paid fallback."""
import unittest

from ai_router.catalogue import external_entry
from ai_router.clients import visible_for
from ai_router.registry import by_slug, upstream_id_for


class MiniMaxRegistryTests(unittest.TestCase):
    def test_verified_minimax_preserves_exact_free_endpoint_and_capabilities(self):
        row = by_slug('minimax/minimax-m3.1-flash:free')
        self.assertIsNotNone(row)
        self.assertEqual(row.provider, 'openrouter')
        self.assertEqual(upstream_id_for(row), 'minimax/minimax-m3.1-flash:free')
        self.assertEqual(row.display_name, 'MiniMax: M3.1 Flash (free) · OpenRouter')
        self.assertEqual(row.reasoning, ('low', 'medium', 'high', 'xhigh', 'max'))
        self.assertEqual(row.default_reasoning, 'low')
        self.assertEqual(row.context_window, 1000000)
        self.assertEqual(row.max_output_tokens, 524288)
        self.assertEqual(row.modalities, ('text', 'image'))
        self.assertFalse(row.drop_images)
        self.assertEqual((row.tier, row.listed), ('verified', True))
        for client in ('codex', 'claude'):
            self.assertTrue(visible_for(row, client), client)
        projected = external_entry(row)
        self.assertEqual(projected['slug'], row.slug)
        self.assertEqual(projected['default_reasoning_level'], 'low')
        self.assertEqual(projected['context_window'], 1000000)
        self.assertIsNone(by_slug('minimax/minimax-m3.1-flash'))
