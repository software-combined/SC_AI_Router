"""Keep MiniMax's withdrawn free endpoint out of the pickers."""
import unittest

from ai_router.catalogue import RETIRED_SLUGS, merge
from ai_router.registry import by_slug

FREE = 'minimax/minimax-m3.1-flash:free'
PAID = 'minimax/minimax-m3.1-flash'


class MiniMaxRetirementTests(unittest.TestCase):
    def test_the_withdrawn_free_endpoint_leaves_every_picker(self):
        self.assertIsNone(by_slug(FREE))
        self.assertIn(FREE, RETIRED_SLUGS)
        stale = merge({'models': [{'slug': FREE}]})
        self.assertNotIn(FREE, {row['slug'] for row in stale['models']})

    def test_the_unverified_paid_endpoint_stays_unregistered(self):
        # Onboarding the paid id needs fresh availability and real-client checks.
        self.assertIsNone(by_slug(PAID))
