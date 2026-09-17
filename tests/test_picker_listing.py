"""What the Codex picker lists: subscription rows and their OpenRouter twins.

The subscription picker gate (0.6.83 to 0.6.88) hid an exhausted row and put
its twin in its place. That is withdrawn: every subscription row is listed,
the twin is listed beside it, and a leftover gate document changes nothing.
"""
import json
import tempfile
import unittest
from pathlib import Path

from ai_router.catalogue import check, merge_file


def _home(tmp, mode='subscription'):
    home = Path(tmp)
    (home / 'mixed-router-state.json').write_text(json.dumps(
        {'port': 1, 'token': 't', 'openai_models': ['gpt-5.6-luna'],
         'openai_mode': mode}) + '\n')
    return home


class PickerListingTests(unittest.TestCase):
    def test_a_subscription_row_lists_beside_its_twin(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            merged = merge_file(home / 'mixed-models.json')
            slugs = [m['slug'] for m in merged['models']]
            self.assertIn('gpt-5.6-luna', slugs)
            self.assertIn('openai/gpt-5.6-luna', slugs)
            self.assertTrue(check(str(home / 'mixed-models.json')))

    def test_none_mode_lists_the_twin_without_the_subscription_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp, mode='none')
            merged = merge_file(home / 'mixed-models.json')
            slugs = [m['slug'] for m in merged['models']]
            self.assertNotIn('gpt-5.6-luna', slugs)
            self.assertIn('openai/gpt-5.6-luna', slugs)
            self.assertTrue(check(str(home / 'mixed-models.json'), include_twins=True))

    def test_a_leftover_gate_document_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            (home / 'subscription-gate.json').write_text(json.dumps(
                {'gpt-5.6-luna': {'source': 'headers', 'until': 2 ** 31 - 1,
                                  'probed': 0, 'since': 0}}) + '\n')
            merged = merge_file(home / 'mixed-models.json')
            slugs = [m['slug'] for m in merged['models']]
            self.assertIn('gpt-5.6-luna', slugs)
            self.assertIn('openai/gpt-5.6-luna', slugs)


if __name__ == '__main__':
    unittest.main()
