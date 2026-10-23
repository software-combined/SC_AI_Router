"""Kimi K3.1 Pro replaces K3 in both client pickers and stale caches."""
from dataclasses import replace
import unittest

from ai_router import catalogue, model_refresh, registry
from ai_router.clients import visible_for


NEW = 'moonshotai/kimi-k3.1-pro'
OLD = 'moonshotai/kimi-k3'


class KimiRegistryTests(unittest.TestCase):
    def test_replacement_metadata_and_both_client_pickers(self):
        row = registry.by_slug(NEW)
        self.assertIsNotNone(row)
        self.assertEqual(row.display_name, 'MoonshotAI: Kimi K3.1 Pro · OpenRouter')
        self.assertEqual(registry.upstream_id_for(row), NEW)
        self.assertEqual(row.reasoning, ('none', 'low', 'high', 'max'))
        self.assertEqual(row.default_reasoning, 'low')
        self.assertEqual(row.context_window, 1048576)
        self.assertEqual(row.max_output_tokens, 943718)
        self.assertEqual(row.modalities, ('text', 'image'))
        self.assertEqual(row.tier, 'verified')
        for client in ('codex', 'claude'):
            self.assertTrue(visible_for(row, client), client)

    def test_stale_cache_cannot_restore_k3_or_hide_its_replacement(self):
        self.assertIn(OLD, catalogue.RETIRED_SLUGS)
        self.assertIsNone(registry.by_slug(OLD))
        current = registry.by_slug(NEW)
        stale = replace(current, slug=OLD, display_name='MoonshotAI: Kimi K3 · OpenRouter')
        rows = model_refresh.overlay((current,), (stale,))
        self.assertEqual(rows, (current,))
        merged = {row['slug'] for row in catalogue.merge(
            {'models': [{'slug': OLD}]})['models']}
        self.assertNotIn(OLD, merged)
        self.assertIn(NEW, merged)
