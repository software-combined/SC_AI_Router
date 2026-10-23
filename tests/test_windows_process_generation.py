"""Process metadata must describe the same generation as the held handle."""
import contextlib
import unittest
from unittest import mock

from tests import test_windows_codex as fixtures


class ProcessGenerationTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.WindowsCodexTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.policy, self.api, self.identity = fixture.policy, fixture.api, fixture.identity

    def test_reused_child_between_enumeration_and_open_never_becomes_a_writer(self):
        self.api.rows = {10: fixtures.row(10, 1, self.identity['exe']),
                         11: fixtures.row(11, 10, '/runtime/node.exe')}
        entries = self.api.entries
        calls = 0
        def replace_after_enumeration():
            nonlocal calls
            result = entries()
            calls += 1
            if calls == 1:
                self.api.rows[11] = fixtures.row(11, 1, '/other/editor.exe', born=2000)
            return result
        def select(rows, seen):
            fixtures.desktop._writers(rows, self.identity, seen, 'win32', ())
        with mock.patch.object(self.api, 'entries', side_effect=replace_after_enumeration), \
                mock.patch.object(self.policy.time, 'monotonic', side_effect=lambda: self.api.now), \
                mock.patch.object(self.policy.time, 'sleep', side_effect=self.api.sleep):
            with self.assertRaises(OSError):
                self.policy.stop(self.identity, select, api=self.api, allow_terminate=True)
        self.assertEqual(self.api.ended, [])
        self.assertEqual(self.api.rows[11]['exe'], '/other/editor.exe')

    def test_query_handles_stay_open_until_shutdown_finishes_and_always_close(self):
        self.api.rows = {10: fixtures.row(10, 1, self.identity['exe']),
                         11: fixtures.row(11, 10, '/runtime/node.exe')}
        opened, observations = set(), []
        original_open, original_end = self.api.opened, self.api.end
        @contextlib.contextmanager
        def retain(pid, terminate=False):
            with original_open(pid, terminate=terminate) as handle:
                token = (pid, terminate, object())
                opened.add(token)
                try:
                    yield handle
                finally:
                    opened.remove(token)
        def end(handle):
            observations.append({pid for pid, terminate, _ in opened if not terminate})
            original_end(handle)
        def select(rows, seen):
            fixtures.desktop._writers(rows, self.identity, seen, 'win32', ())
        with mock.patch.object(self.api, 'opened', side_effect=retain), \
                mock.patch.object(self.api, 'end', side_effect=end), \
                mock.patch.object(self.policy.time, 'monotonic', side_effect=lambda: self.api.now), \
                mock.patch.object(self.policy.time, 'sleep', side_effect=self.api.sleep):
            self.assertTrue(self.policy.stop(self.identity, select, api=self.api, allow_terminate=True))
        self.assertTrue(observations)
        self.assertTrue(all({10, 11} <= held for held in observations))
        self.assertEqual(opened, set())
