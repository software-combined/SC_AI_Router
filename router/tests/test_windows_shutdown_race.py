"""Shutdown uses retained process objects after their one identity verification."""
import contextlib
import unittest
from unittest import mock

from tests import test_windows_codex as fixtures


class ShutdownRaceTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.WindowsCodexTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.policy, self.api, self.identity = fixture.policy, fixture.api, fixture.identity
        self.api.rows = {10: fixtures.row(10, 1, self.identity['exe']),
                         11: fixtures.row(11, 10, '/runtime/node.exe')}
        self.enterContext(mock.patch.object(self.policy.time, 'monotonic', side_effect=lambda: self.api.now))
        self.enterContext(mock.patch.object(self.policy.time, 'sleep', side_effect=self.api.sleep))

    def stop(self):
        return self.policy.stop(self.identity, lambda rows, seen: fixtures.desktop._writers(
            rows, self.identity, seen, 'win32', ()), api=self.api, allow_terminate=True)

    def test_mid_exit_identity_denial_never_requeries_verified_processes(self):
        facts, user, alive = self.api.facts, self.api.user, self.api.alive
        probes, polls, rights = [], {}, []
        opened = self.api.opened
        @contextlib.contextmanager
        def retain(pid, terminate=False):
            rights.append((pid, terminate))
            with opened(pid, terminate=terminate) as handle:
                yield handle
        def identity(handle, pid):
            if self.api.closed:
                raise fixtures.native.NativeError('process_identity', code=5)
            probes.append(('facts', pid))
            return facts(handle, pid)
        def owner(handle=None):
            if handle is not None:
                probes.append(('owner', handle))
                if self.api.closed:
                    raise fixtures.native.NativeError('process_owner', code=5)
            return user(handle)
        def live(handle):
            if self.api.closed:
                polls[handle] = polls.get(handle, 0) + 1
                if polls[handle] > (1 if handle == 10 else 3):
                    self.api.rows.pop(handle, None)
            return alive(handle)
        with mock.patch.object(self.api, 'facts', side_effect=identity), \
                mock.patch.object(self.api, 'user', side_effect=owner), \
                mock.patch.object(self.api, 'alive', side_effect=live), \
                mock.patch.object(self.api, 'opened', side_effect=retain):
            self.assertTrue(self.stop())
        self.assertEqual(probes, [('facts', 10), ('facts', 11), ('owner', 10), ('owner', 11)])
        self.assertEqual(rights, [(10, True), (11, True)])
        self.assertEqual(self.api.ended, [])

    def test_new_unqueryable_process_is_skipped_only_after_its_handle_signals(self):
        facts = self.api.facts
        def identity(handle, pid):
            if pid == 11:
                raise fixtures.native.NativeError('process_identity', code=5)
            return facts(handle, pid)
        def live(handle):
            if handle == 11 and self.api.now >= 0.2:
                self.api.rows.pop(handle, None)
            return handle in self.api.rows
        with mock.patch.object(self.api, 'facts', side_effect=identity), \
                mock.patch.object(self.api, 'alive', side_effect=live):
            self.assertTrue(self.stop())
        self.assertNotIn(11, self.api.ended)

    def test_new_live_unqueryable_writer_refuses_after_bounded_exit_observation(self):
        facts = self.api.facts
        def identity(handle, pid):
            if pid == 11:
                raise fixtures.native.NativeError('process_identity', code=5)
            return facts(handle, pid)
        with mock.patch.object(self.api, 'facts', side_effect=identity):
            with self.assertRaises(OSError) as failure:
                self.stop()
        self.assertEqual(failure.exception.facts['winerror'], 5)
        self.assertAlmostEqual(self.api.now, 0.5)
        self.assertEqual((self.api.closed, self.api.ended), ([], []))

    def test_unverified_live_child_missing_from_enumeration_still_refuses(self):
        facts, entries = self.api.facts, self.api.entries
        calls = []
        def identity(handle, pid):
            if pid == 11:
                raise fixtures.native.NativeError('process_identity', code=5)
            return facts(handle, pid)
        def scan():
            calls.append(True)
            return [r for r in entries() if len(calls) == 1 or r['pid'] != 11]
        with mock.patch.object(self.api, 'facts', side_effect=identity), \
                mock.patch.object(self.api, 'entries', side_effect=scan):
            with self.assertRaises(OSError):
                self.stop()
        self.assertAlmostEqual(self.api.now, 0.5)
        self.assertIn(11, self.api.rows)
        self.assertEqual((self.api.closed, self.api.ended), ([], []))

    def test_verified_reparented_child_uses_its_original_handle(self):
        with contextlib.ExitStack() as scope:
            retained = (scope, {})
            seen = self.policy.snapshot(self.identity, {}, (), api=self.api, retention=retained)
            entries, calls = self.api.entries, []
            def reparent():
                result = entries()
                calls.append(True)
                if len(calls) == 1:
                    self.api.rows[11]['parent'] = 1
                return result
            with mock.patch.object(self.api, 'entries', side_effect=reparent), \
                    mock.patch.object(self.api, 'facts', side_effect=AssertionError('Already verified')), \
                    mock.patch.object(self.api, 'user', side_effect=AssertionError('Already verified')):
                self.assertEqual(set(self.policy.snapshot(self.identity, seen, (), api=self.api,
                                                         retention=retained)), {10, 11})

    def test_reused_new_pid_hidden_from_second_enumeration_is_never_terminated(self):
        entries, calls = self.api.entries, []
        def replace():
            result = entries()
            calls.append(True)
            if len(calls) == 1:
                self.api.rows[11] = fixtures.row(11, 1, '/other/editor.exe', born=2000)
            else:
                result = [r for r in result if r['pid'] != 11]
            return result
        with mock.patch.object(self.api, 'entries', side_effect=replace):
            with self.assertRaises(OSError):
                self.stop()
        self.assertEqual(self.api.ended, [])
        self.assertEqual(self.api.rows[11]['exe'], '/other/editor.exe')

    def test_root_termination_allows_job_teardown_before_ending_survivors(self):
        self.api.rows = dict(reversed(list(self.api.rows.items())))
        end = self.api.end
        def end_root(handle):
            end(handle)
            if handle == 10:
                self.api.rows.pop(11, None)  # Chromium's job tears down its child.
        with mock.patch.object(self.api, 'end', side_effect=end_root):
            self.assertTrue(self.stop())
        self.assertEqual(self.api.ended, [10])

    def test_termination_denied_during_exit_only_observes_the_same_handle(self):
        end = self.api.end
        def ending(handle):
            if handle == 11:
                raise fixtures.native.NativeError('process_end', code=5)
            end(handle)
        alive = self.api.alive
        def live(handle):
            if handle == 11 and self.api.now >= 5.8:
                self.api.rows.pop(handle, None)
            return alive(handle)
        with mock.patch.object(self.api, 'end', side_effect=ending), \
                mock.patch.object(self.api, 'alive', side_effect=live):
            self.assertTrue(self.stop())
        self.assertEqual(self.api.ended, [10])

    def test_a_pinned_process_missing_from_enumeration_must_still_signal(self):
        entries = self.api.entries
        def scan():
            return [] if self.api.closed else entries()
        with mock.patch.object(self.api, 'entries', side_effect=scan):
            self.assertTrue(self.stop())
        self.assertEqual(set(self.api.ended), {10, 11})
        self.assertGreaterEqual(self.api.now, 5)

    def test_cold_reopen_waits_thirty_seconds_for_a_visible_package_window(self):
        self.api.rows.clear()
        activate = self.api.activate
        def cold_start(app):
            activate(app)
            self.api.visible = False
        windows = self.api.windows
        def visible_window(visible=False):
            self.api.visible = self.api.now >= 12
            return windows(visible=visible)
        with mock.patch.object(self.api, 'activate', side_effect=cold_start), \
                mock.patch.object(self.api, 'windows', side_effect=visible_window):
            self.policy.open_app(self.identity, api=self.api)
        self.assertGreaterEqual(self.api.now, 12)
        self.assertLess(self.api.now, 30)
