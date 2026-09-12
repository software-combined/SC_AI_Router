"""Plan 131 step 2: the shared state-reader contract."""
import tempfile
import unittest
from pathlib import Path

from ai_router import state


class StateReadTests(unittest.TestCase):
    def _home(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def test_read_degrades_on_every_unusable_document(self):
        home = self._home()
        path = state.path(home)
        self.assertIsNone(state.read(path))
        path.write_text('{not json')
        self.assertIsNone(state.read(path))
        path.write_text('[1, 2]')
        self.assertIsNone(state.read(path))
        path.write_text('{"port": 1}')
        self.assertEqual(state.read(path), {'port': 1})

    def test_read_strict_reports_the_reason(self):
        home = self._home()
        path = state.path(home)
        with self.assertRaises(state.StateUnreadable) as missing:
            state.read_strict(path)
        self.assertEqual(missing.exception.reason, 'missing')
        path.write_text('{not json')
        with self.assertRaises(state.StateUnreadable) as invalid:
            state.read_strict(path)
        self.assertEqual((invalid.exception.reason, invalid.exception.detail),
                         ('invalid', 'JSONDecodeError'))
        path.write_text('[1]')
        with self.assertRaises(state.StateUnreadable) as scalar:
            state.read_strict(path)
        self.assertEqual(scalar.exception.detail, 'not a JSON object')

    def test_read_strict_marks_a_present_but_unreadable_path(self):
        # A path that exists but cannot be read must not be reported as
        # missing, or the operator hunts for a file that is right there.
        home = self._home()
        path = state.path(home)
        path.mkdir()
        with self.assertRaises(state.StateUnreadable) as unreadable:
            state.read_strict(path)
        self.assertEqual(unreadable.exception.reason, 'unreadable')
        self.assertTrue(unreadable.exception.detail)

    def test_required_keys_names_missing_and_mistyped(self):
        self.assertEqual(state.required_keys({}, {'port': int, 'token': str}),
                         ['port', 'token'])
        self.assertEqual(state.required_keys({'port': 'x', 'token': 't'},
                                             {'port': int, 'token': str}),
                         ['port'])
        self.assertEqual(state.required_keys({'port': 1, 'token': 't'},
                                             {'port': int}), [])
