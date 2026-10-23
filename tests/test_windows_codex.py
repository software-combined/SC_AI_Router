"""Native selection and consented shutdown of a Store app's surviving tray tree."""
import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_native_setup import module

native = module('windows_native')
desktop = module('claude_desktop_platform')


class API:
    def __init__(self, root):
        self.root, self.package = root, 'Codex_version_A'
        self.rows, self.denied, self.owners, self.ended = {}, set(), [], []
        self.now, self.closed, self.visible = 0, [], False

    def packages(self, family):
        return [self.package]

    def package_path(self, package):
        return str(self.root)

    def user(self, handle=None):
        if handle is not None:
            self.owners.append(handle)
        return self.rows[handle].get('user', 'owner') if handle else 'owner'

    def session(self, pid=None):
        return self.rows[pid]['session'] if pid else 3

    def entries(self):
        return [dict(pid=p, parent=r['parent'], name=Path(r['exe']).name)
                for p, r in self.rows.items()]

    @contextlib.contextmanager
    def opened(self, pid, terminate=False):
        if pid in self.denied:
            raise native.NativeError('process_open', code=5)
        yield pid

    def facts(self, handle, pid):
        return {k: v for k, v in self.rows[pid].items() if k not in ('user', 'parent')}

    def alive(self, handle):
        return handle in self.rows

    def windows(self, visible=False):
        return [(100, 10)] if 10 in self.rows and (not visible or self.visible) else []

    def close_window(self, window, pid):
        self.closed.append(pid)  # A tray app survives its window closing.

    def end(self, handle):
        self.ended.append(handle)
        del self.rows[handle]

    def activate(self, app):
        self.rows[10] = dict(row(10, 1, str(self.root / 'app/ChatGPT.exe')),
                             family='OpenAI.Codex_2p2nqsd0c76g0')
        self.visible = True

    def sleep(self, seconds):
        self.now += seconds


def row(pid, parent, exe, **extra):
    return dict(dict(pid=pid, parent=parent, exe=exe, born=pid * 100, user='owner',
                     family='', session=3), **extra)


class WindowsCodexTests(unittest.TestCase):
    def setUp(self):
        self.policy = module('windows_codex')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / 'Codex_version_A'
        exe = self.root / 'app/ChatGPT.exe'
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b'MZ fixture')
        (self.root / 'AppxManifest.xml').write_text(
            '<Package xmlns="urn:fixture"><Applications><Application Id="App" '
            'Executable="app\\ChatGPT.exe"/></Applications></Package>')
        self.api = API(self.root)
        self.identity = self.policy.identity(api=self.api)

    def scan(self, seen=None):
        return self.policy.snapshot(self.identity, seen or {}, (), api=self.api)

    def test_package_discovery_is_fresh_after_version_folder_changes(self):
        old = self.identity
        moved = self.root.with_name('Codex_version_B')
        self.root.rename(moved)
        self.api.root, self.api.package = moved, 'Codex_version_B'
        fresh = self.policy.identity(api=self.api)
        self.assertEqual(fresh['root'], str(moved))
        self.assertNotEqual(fresh['root'], old['root'])
        with self.assertRaises(OSError):
            self.policy.validate(old, api=self.api)

    def test_manifest_ambiguity_escape_and_non_executable_refuse(self):
        manifest = self.root / 'AppxManifest.xml'
        for executable in ('../ChatGPT.exe', 'app/resources/codex', '/ChatGPT.exe'):
            manifest.write_text('<Package><Applications><Application Id="App" '
                                'Executable="%s"/></Applications></Package>' % executable)
            with self.assertRaises(OSError):
                self.policy.identity(api=self.api)
        manifest.write_text('<Package><Applications><Application Id="A" Executable="app/ChatGPT.exe"/>'
                            '<Application Id="B" Executable="app/ChatGPT.exe"/></Applications></Package>')
        with self.assertRaises(OSError):
            self.policy.identity(api=self.api)

    def test_owners_only_for_tree_and_reparented_pids_stay_tracked(self):
        self.api.rows = {10: row(10, 1, self.identity['exe']),
                         11: row(11, 10, '/runtime/node.exe'),
                         12: row(12, 1, '/system/csrss.exe'),
                         13: row(13, 1, '/other/editor.exe')}
        self.api.denied.add(12)
        seen = {}
        rows = self.scan()
        desktop._writers(rows, self.identity, seen, 'win32', ())
        self.assertEqual(set(rows), {10, 11})
        self.assertEqual(set(self.api.owners), {10, 11})
        self.api.rows.pop(10)
        self.api.rows[11]['parent'] = 1
        self.assertEqual(set(self.policy.snapshot(self.identity, seen, (), api=self.api)), {11})
        self.api.rows[11]['born'] += 1
        with self.assertRaises(OSError):
            self.policy.snapshot(self.identity, seen, (), api=self.api)

    def test_denied_relevant_owner_refuses_unless_process_has_disappeared(self):
        self.api.rows[10] = row(10, 1, self.identity['exe'])
        self.api.denied.add(10)
        with self.assertRaises(OSError):
            self.scan()
        entries = self.api.entries()
        with mock.patch.object(self.api, 'entries', side_effect=[entries, []]):
            self.assertEqual(self.scan(), {})

    def test_tray_tree_needs_explicit_consent_then_ends_only_verified_handles(self):
        self.api.rows = {10: row(10, 1, self.identity['exe']),
                         11: row(11, 10, '/runtime/node.exe'),
                         12: row(12, 1, '/other/editor.exe')}
        def select(rows, seen):
            return desktop._writers(rows, self.identity, seen, 'win32', ())
        with mock.patch.object(self.policy.time, 'monotonic', side_effect=lambda: self.api.now), \
                mock.patch.object(self.policy.time, 'sleep', side_effect=self.api.sleep):
            self.assertFalse(self.policy.stop(self.identity, select, api=self.api))
            self.assertEqual(self.api.ended, [])
            record = {}
            self.assertTrue(self.policy.stop(self.identity, select, api=self.api,
                                             allow_terminate=True, record=record))
        self.assertEqual(set(self.api.ended), {10, 11})
        self.assertEqual(set(self.api.rows), {12})
        self.assertIn(10, self.api.closed)
        self.assertGreater(record['scan_count'], 1)
        self.assertLess(self.api.now, 20)

    def test_pid_reuse_before_termination_refuses(self):
        original = row(10, 1, self.identity['exe'])
        self.api.rows[10] = dict(original, born=99999)
        with self.assertRaises(OSError):
            self.policy.act(self.identity, original, self.api, terminate=True)
        self.assertEqual(self.api.ended, [])

    def test_stale_parent_pid_never_adopts_or_terminates_an_older_unrelated_child(self):
        parent = row(10, 1, self.identity['exe'])
        self.api.rows = {10: parent, 11: row(11, 10, '/other/editor.exe', born=500)}
        def select(rows, seen):
            return desktop._writers(rows, self.identity, seen, 'win32', ())
        with mock.patch.object(self.policy.time, 'monotonic', side_effect=lambda: self.api.now), \
                mock.patch.object(self.policy.time, 'sleep', side_effect=self.api.sleep):
            with self.assertRaises(OSError):
                self.policy.stop(self.identity, select, api=self.api, allow_terminate=True)
        self.assertEqual(self.api.ended, [])
        self.assertIn(11, self.api.rows)
        self.api.rows.pop(10, None)
        with self.assertRaises(OSError):
            self.policy.snapshot(self.identity, {10: parent}, (), api=self.api)

    def test_fifty_process_tree_includes_package_hosts_and_ignores_foreign_sessions(self):
        self.api.rows = {10: row(10, 1, self.identity['exe'])}
        self.api.rows.update({pid: row(pid, 10, '/runtime/node.exe') for pid in range(11, 60)})
        self.api.rows[60] = row(60, 1, '/system/conhost.exe', family=self.policy.FAMILY)
        self.api.rows[61] = row(61, 1, self.identity['exe'], session=4)
        self.api.rows[62] = row(62, 1, self.identity['exe'], user='other')
        rows, seen = self.scan(), {}
        desktop._writers(rows, self.identity, seen, 'win32', ())
        self.assertEqual(set(seen), set(range(10, 61)))
        self.assertNotIn(61, self.api.owners)
        self.assertNotIn(62, rows)

    def test_owner_failure_and_partial_scan_cannot_be_treated_as_shutdown(self):
        self.api.rows[10] = row(10, 1, self.identity['exe'])
        with mock.patch.object(self.api, 'user', side_effect=native.NativeError('process_owner', code=5)):
            with self.assertRaises(OSError):
                self.scan()
        with mock.patch.object(self.api, 'entries', side_effect=native.NativeError('process_snapshot', code=5)):
            with self.assertRaises(OSError):
                self.scan()

    def test_denied_same_name_process_in_a_confirmed_foreign_session_is_ignored(self):
        self.api.rows = {10: row(10, 1, self.identity['exe']),
                         61: row(61, 1, self.identity['exe'], session=4)}
        self.api.denied.add(61)
        self.assertEqual(set(self.scan()), {10})
        self.assertNotIn(61, self.api.owners)
        with mock.patch.object(self.api, 'session', side_effect=native.NativeError('process_session', code=5)):
            with self.assertRaises(OSError):
                self.scan()

    def test_post_close_native_scan_failure_reopens_but_pre_close_failure_does_not(self):
        self.api.rows[10] = row(10, 1, self.identity['exe'])
        entries, failed = self.api.entries, []
        def scan():
            if self.api.closed and not failed:
                failed.append(True)
                raise native.NativeError('process_snapshot', code=5)
            return entries()
        with mock.patch.object(self.api, 'entries', side_effect=scan), \
                mock.patch.object(self.policy.time, 'monotonic', side_effect=lambda: self.api.now), \
                mock.patch.object(self.policy.time, 'sleep', side_effect=self.api.sleep):
            with self.assertRaises(OSError):
                self.policy.stop(self.identity, lambda rows, seen: desktop._writers(
                    rows, self.identity, seen, 'win32', ()), api=self.api)
        self.assertTrue(self.api.visible)
        self.api.visible = False
        self.api.closed.clear()
        failed.clear()
        with mock.patch.object(self.api, 'entries', side_effect=scan), \
                mock.patch.object(self.api, 'activate', side_effect=native.NativeError('app_open', code=5)), \
                mock.patch.object(self.policy.time, 'monotonic', side_effect=lambda: self.api.now), \
                mock.patch.object(self.policy.time, 'sleep', side_effect=self.api.sleep):
            with self.assertRaises(OSError) as failure:
                self.policy.stop(self.identity, lambda rows, seen: desktop._writers(
                    rows, self.identity, seen, 'win32', ()), api=self.api)
        self.assertTrue(failure.exception.reopen_failed)
        self.api.visible = False
        self.api.closed.clear()
        with mock.patch.object(self.api, 'entries', side_effect=native.NativeError('process_snapshot', code=5)):
            with self.assertRaises(OSError):
                self.policy.stop(self.identity, lambda *_: None, api=self.api)
        self.assertFalse(self.api.visible)

    def test_activation_without_a_visible_window_is_a_distinct_failure(self):
        with mock.patch.object(self.api, 'activate'), \
                mock.patch.object(self.policy.time, 'monotonic', side_effect=lambda: self.api.now), \
                mock.patch.object(self.policy.time, 'sleep', side_effect=self.api.sleep):
            with self.assertRaises(OSError) as failure:
                self.policy.open_app(self.identity, api=self.api)
        self.assertEqual(failure.exception.facts['reason'], 'window_unavailable')

    def test_reopen_requires_a_visible_verified_window_and_rejects_package_change(self):
        self.policy.open_app(self.identity, api=self.api)
        self.assertTrue(self.api.visible)
        self.api.package = 'Codex_version_B'
        with self.assertRaises(OSError):
            self.policy.open_app(self.identity, api=self.api)

    def test_codex_facade_uses_native_identity_shutdown_and_reopen_without_commands(self):
        app = desktop.App('com.openai.codex', ())
        self.api.rows[10] = row(10, 1, self.identity['exe'])
        run = mock.Mock(side_effect=AssertionError('No PowerShell in native lifecycle'))
        with mock.patch.object(desktop._windows_codex, 'bindings', return_value=self.api), \
                mock.patch.object(self.policy.time, 'monotonic', side_effect=lambda: self.api.now), \
                mock.patch.object(self.policy.time, 'sleep', side_effect=self.api.sleep):
            identity = desktop.app_identity('win32', run, app)
            self.assertTrue(desktop.request_stop('win32', run, app=app, identity=identity,
                                                allow_terminate=True))
            desktop.open_app('win32', run, app, identity=identity)
        self.assertEqual(self.api.ended, [10])
        self.assertTrue(self.api.visible)
        run.assert_not_called()

    def test_claude_reopen_uses_the_shared_validated_appsfolder_uri(self):
        identity = dict(root='C:/Apps/Claude', exe='C:/Apps/Claude/Claude.exe',
                        app='Claude_family!App', user='owner')
        run = mock.Mock(return_value=mock.Mock(returncode=0))
        with mock.patch.object(desktop, 'app_identity', return_value=identity):
            desktop.open_app('win32', run=run)
        script = run.call_args.args[0][-1]
        self.assertIn('shell:AppsFolder\\Claude_family!App', script)
        self.assertNotIn('shell:AppsFolder:', script)
        self.assertEqual(run.call_args.kwargs['creationflags'], 0x08000000)


if __name__ == '__main__':
    unittest.main()
