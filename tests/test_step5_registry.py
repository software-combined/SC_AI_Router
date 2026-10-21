"""Pin Step 5's verified capability and picker contract."""
import unittest

from ai_router.catalogue import external_entry
from ai_router.clients import visible_for
from ai_router.registry import by_slug, upstream_id_for


class Step5RegistryTests(unittest.TestCase):
    def test_verified_step5_keeps_exact_identity_and_capabilities(self):
        row = by_slug('stepfun/step-5-preview')
        self.assertIsNotNone(row)
        self.assertEqual(row.provider, 'openrouter')
        self.assertEqual(upstream_id_for(row), 'stepfun/step-5-preview')
        self.assertEqual(row.display_name, 'StepFun: Step 5 Preview · OpenRouter')
        self.assertEqual(row.reasoning, ('low', 'medium', 'high'))
        self.assertEqual(row.default_reasoning, 'low')
        self.assertEqual(row.context_window, 1048576)
        self.assertEqual(row.max_output_tokens, 64000)
        self.assertEqual(row.modalities, ('text', 'image'))
        self.assertFalse(row.drop_images)
        self.assertEqual(row.tier, 'verified')
        self.assertTrue(row.listed)
        for client in ('codex', 'claude'):
            self.assertTrue(visible_for(row, client), client)
        projected = external_entry(row)
        self.assertEqual(projected['slug'], row.slug)
        self.assertEqual(projected['default_reasoning_level'], 'low')
        self.assertEqual(projected['context_window'], 1048576)
