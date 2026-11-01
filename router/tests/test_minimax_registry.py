"""Hold MiniMax's verified paid endpoint and its withdrawn free row apart."""
import unittest

from ai_router.catalogue import RETIRED_SLUGS, external_entry, merge
from ai_router.clients import visible_for
from ai_router.registry import by_slug, upstream_id_for

FREE = 'minimax/minimax-m3.1-flash:free'
PAID = 'minimax/minimax-m3.1-flash'


class MiniMaxRegistryTests(unittest.TestCase):
    def test_the_withdrawn_free_endpoint_leaves_every_picker(self):
        self.assertIsNone(by_slug(FREE))
        self.assertIn(FREE, RETIRED_SLUGS)
        stale = merge({'models': [{'slug': FREE}]})
        self.assertNotIn(FREE, {row['slug'] for row in stale['models']})

    def test_the_paid_endpoint_serves_the_verified_row(self):
        row = by_slug(PAID)
        self.assertIsNotNone(row)
        self.assertEqual(upstream_id_for(row), PAID)
        self.assertEqual(row.display_name, 'MiniMax: M3.1 Flash · OpenRouter')
        self.assertEqual(row.reasoning, ('low', 'medium', 'high', 'xhigh', 'max'))
        self.assertEqual(row.default_reasoning, 'low')
        self.assertEqual(row.context_window, 1048576)
        self.assertEqual(row.max_output_tokens, 524288)
        self.assertEqual(row.modalities, ('text', 'image'))
        self.assertEqual((row.tier, row.listed), ('verified', True))
        for client in ('codex', 'claude'):
            self.assertTrue(visible_for(row, client), client)
        projected = external_entry(row)
        self.assertEqual(projected['slug'], PAID)
        self.assertEqual(projected['default_reasoning_level'], 'low')
