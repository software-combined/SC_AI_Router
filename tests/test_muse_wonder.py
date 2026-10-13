"""Pin the live-proven Muse Wonder row without retiring different Muse families."""
import unittest

from ai_router.registry import by_slug


class MuseWonderTests(unittest.TestCase):
    def test_native_capabilities_and_existing_spark_rows(self):
        model = by_slug('meta/muse-wonder')
        self.assertEqual(model.default_reasoning, 'low')
        self.assertEqual(model.reasoning, ('minimal', 'low', 'medium', 'high', 'xhigh', 'max'))
        self.assertEqual(model.modalities, ('text', 'image', 'audio'))
        self.assertEqual(model.context_window, 1048576)
        self.assertEqual(model.schema_mode, 'native')
        self.assertEqual(model.history_mode, 'native')
        self.assertTrue(model.listed)
        self.assertEqual(model.tier, 'verified')
        self.assertIsNotNone(by_slug('meta/muse-spark-1.3'))
        self.assertIsNotNone(by_slug('meta/muse-spark-1.3-contributor'))
