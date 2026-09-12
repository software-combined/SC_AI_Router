"""Restart-notice delivery: showing the pending dialog, and the installer
paths that stage and trigger it.

The command construction itself lives in `test_notice.py`.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._platform import unix_only
from tests.fakes import launchd_in_sync
from tests.install_fixtures import (
    _craft_bundle,
    _ok_run,
    _patch_attrs,
    install_mod,
)
from tests.test_install_config import _fake_write_catalogue
from tests.test_install_lifecycle import _run_install
from tests.test_notice import notice_mod


def _adding_catalogue(slug):
    """A write_catalogue fake whose next install adds one picker row."""
    def fake(home, release_dir, python):
        _fake_write_catalogue(home, release_dir, python)
        path = home / 'mixed-models.json'
        doc = json.loads(path.read_text())
        doc['models'].append({'slug': slug})
        path.write_text(json.dumps(doc, indent=2))
    return fake


class ShowPendingTests(unittest.TestCase):
    def _pending(self, home, version='1.0.1'):
        (home / 'update-notice.json').write_text(
            json.dumps({'version': version}))
        return home / 'update-notice.json'

    def _with_dialog(self, test):
        real = notice_mod.dialog_command
        test.addCleanup(setattr, notice_mod, 'dialog_command', real)
        test.addCleanup(setattr, install_mod._svc.notice,
                        'dialog_command', install_mod._svc.notice.dialog_command)
        fake = lambda version, platform_name=None, which=None, icon=None, clients='codex': ['fake-dialog', version]  # noqa: E731
        setattr(notice_mod, 'dialog_command', fake)
        setattr(install_mod._svc.notice, 'dialog_command', fake)

    def test_pending_notice_spawns_once_then_stays_quiet(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            self._pending(home)
            self._with_dialog(self)
            seen = []
            self.assertTrue(
                notice_mod.show_pending(home, spawn=seen.append))
            self.assertEqual(len(seen), 1)
            doc = json.loads((home / 'update-notice.json').read_text())
            self.assertTrue(doc['shown'])
            self.assertEqual(doc['version'], '1.0.1')
            self.assertFalse(
                notice_mod.show_pending(home, spawn=seen.append))
            self.assertEqual(len(seen), 1)

    def test_spawn_failure_leaves_notice_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            self._pending(home)
            self._with_dialog(self)

            def boom(cmd):
                raise OSError('no session bus')
            self.assertFalse(notice_mod.show_pending(home, spawn=boom))
            doc = json.loads((home / 'update-notice.json').read_text())
            self.assertNotIn('shown', doc)

    def test_open_dialog_folds_the_next_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            (home / 'update-notice.json').write_text(
                json.dumps({'version': '1.0.2', 'pid': 4321}))
            self._with_dialog(self)
            seen = []
            self.assertFalse(notice_mod.show_pending(
                home, spawn=seen.append,
                pid_alive=lambda pid: pid == 4321))
            self.assertEqual(seen, [])
            doc = json.loads((home / 'update-notice.json').read_text())
            self.assertTrue(doc['shown'])
            self.assertEqual(doc['version'], '1.0.2')
            self.assertEqual(doc['pid'], 4321)

    def test_dead_dialog_pid_spawns_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            (home / 'update-notice.json').write_text(
                json.dumps({'version': '1.0.1', 'pid': 4321}))
            self._with_dialog(self)
            seen = []
            self.assertTrue(notice_mod.show_pending(
                home, spawn=lambda cmd: seen.append(cmd) or 999,
                pid_alive=lambda pid: pid == 999))
            self.assertEqual(len(seen), 1)
            doc = json.loads((home / 'update-notice.json').read_text())
            self.assertTrue(doc['shown'])
            self.assertEqual(doc['pid'], 999)

    def test_dialog_that_dies_at_once_leaves_the_notice_pending(self):
        # The scheduled updater runs as a service with no display: zenity
        # dies at once (Failed to open display, reproduced in a Debian
        # container), so the notice must stay pending for a run that can
        # draw a dialog rather than being marked shown and lost.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            self._pending(home)
            self._with_dialog(self)
            real = notice_mod.PROBE_GRACE_S
            self.addCleanup(setattr, notice_mod, 'PROBE_GRACE_S', real)
            notice_mod.PROBE_GRACE_S = 0
            seen = []
            self.assertFalse(notice_mod.show_pending(
                home, spawn=lambda cmd: seen.append(cmd) or 2357,
                pid_alive=lambda pid: False))
            self.assertEqual(len(seen), 1)
            doc = json.loads((home / 'update-notice.json').read_text())
            self.assertNotIn('shown', doc)
            # A later run that can draw the dialog still shows it, once.
            self.assertTrue(notice_mod.show_pending(
                home, spawn=lambda cmd: seen.append(cmd) or 2358,
                pid_alive=lambda pid: pid == 2358))
            doc = json.loads((home / 'update-notice.json').read_text())
            self.assertTrue(doc['shown'])
            self.assertEqual(doc['pid'], 2358)

    def test_notify_send_delivery_is_the_exit_status(self):
        # notify-send exits as soon as the daemon answers, so pid liveness
        # says nothing there: a zero exit is delivered, a non-zero one
        # leaves the notice pending for a later run.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            self._pending(home)
            for code, expected in ((0, True), (1, False)):
                (home / 'update-notice.json').write_text(
                    json.dumps({'version': '1.0.1'}))
                with mock.patch.object(
                        notice_mod, 'dialog_command',
                        lambda *a, **k: ['notify-send', 'SCG Router', 'updated']), \
                        mock.patch.object(
                            notice_mod.subprocess, 'run',
                            lambda *a, **k: mock.Mock(returncode=code)):
                    self.assertIs(notice_mod.show_pending(home), expected)
                doc = json.loads((home / 'update-notice.json').read_text())
                self.assertEqual(bool(doc.get('shown')), expected)

    def test_recycled_pid_is_not_mistaken_for_a_dialog(self):
        # A live process that is not one of our dialogs must not swallow a
        # notice: the liveness probe checks the recorded command line.
        foreign = subprocess.Popen(
            [sys.executable, '-c', 'import time; time.sleep(20)'])
        ours = subprocess.Popen(
            [sys.executable, '-c', 'import time; time.sleep(20)',
             'display dialog "SCG Router"'])
        try:
            self.assertFalse(notice_mod._pid_alive(foreign.pid))
            self.assertTrue(notice_mod._pid_alive(ours.pid))
            self.assertFalse(notice_mod._pid_alive(4 * 10 ** 9))
        finally:
            foreign.kill()
            ours.kill()
            foreign.wait()
            ours.wait()

    def test_a_wedged_liveness_probe_is_bounded(self):
        # The scheduled updater waits on this process, so a hanging
        # powershell/ps probe must time out instead of parking a healthy
        # install that already succeeded.
        def hang(*args, **kwargs):
            raise subprocess.TimeoutExpired('powershell', notice_mod.PROBE_TIMEOUT)
        real = notice_mod.subprocess.run
        self.addCleanup(setattr, notice_mod.subprocess, 'run', real)
        notice_mod.subprocess.run = hang
        self.assertFalse(notice_mod._pid_alive(os.getpid()))

    def test_pending_notice_uses_an_icon_that_outlives_the_bundle(self):
        # The scheduled updater extracts the bundle into a temporary
        # directory that is deleted before the user sees the dialog, so the
        # dialog must point at the copy in the router home.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            self._pending(home)
            self._with_dialog(self)
            seen = []
            self.assertTrue(notice_mod.show_pending(home, spawn=seen.append))
            durable = home / 'router-icon.png'
            self.assertTrue(durable.is_file())
            self.assertEqual(durable.read_bytes(), notice_mod.ICON.read_bytes())
            self.assertEqual(seen, [['fake-dialog', '1.0.1']])

    @unittest.skipUnless(sys.platform == 'darwin',
                         'compiles AppleScript; macOS only')
    def test_dialog_survives_a_vanished_bundle_icon(self):
        bundle = Path(tempfile.mkdtemp(prefix='notice-bundle-'))
        (bundle / 'assets').mkdir()
        icon = bundle / 'assets' / 'router-icon.png'
        shutil.copy(notice_mod.ICON, icon)
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            self._pending(home)
            with mock.patch.object(notice_mod, 'ICON', icon):
                commands = []
                self.assertTrue(notice_mod.show_pending(home, spawn=commands.append))
            durable = home / 'router-icon.png'
            self.assertTrue(durable.is_file())
            # The extraction directory is gone, as it is after a scheduled
            # update; the dialog must still reference a usable icon.
            shutil.rmtree(bundle)
            cmd = notice_mod.dialog_command('1.0.1', icon=str(durable))
            self.assertIn(str(durable), cmd[cmd.index('-e') + 1])
            self.assertNotIn(str(bundle), cmd[cmd.index('-e') + 1])
            with tempfile.TemporaryDirectory() as scratch:
                out = subprocess.run(
                    ['osacompile', '-e', cmd[cmd.index('-e') + 1],
                     '-o', scratch + '/notice.scpt'],
                    capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)

    def test_missing_dialog_tool_leaves_notice_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            self._pending(home)
            real = notice_mod.dialog_command
            self.addCleanup(setattr, notice_mod, 'dialog_command', real)
            self.addCleanup(setattr, install_mod._svc.notice, 'dialog_command',
                            install_mod._svc.notice.dialog_command)
            fake = lambda version, platform_name=None, which=None, icon=None, clients='codex': None  # noqa: E731
            setattr(notice_mod, 'dialog_command', fake)
            setattr(install_mod._svc.notice, 'dialog_command', fake)
            seen = []
            self.assertFalse(
                notice_mod.show_pending(home, spawn=seen.append))
            self.assertEqual(seen, [])
            doc = json.loads((home / 'update-notice.json').read_text())
            self.assertNotIn('shown', doc)

    def test_no_file_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            self.assertFalse(
                notice_mod.show_pending(home, spawn=lambda cmd: None))

    def test_silent_install_env_never_spawns(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            self._pending(home)
            self._with_dialog(self)
            seen = []
            with mock.patch.dict(os.environ, {'ROUTER_NO_NOTICE': '1'}):
                self.assertFalse(notice_mod.show_pending(home, spawn=seen.append))
            self.assertEqual(seen, [])
            doc = json.loads((home / 'update-notice.json').read_text())
            self.assertNotIn('shown', doc)

    def test_claude_only_notice_has_no_codex_restart_button(self):
        cmd = notice_mod.dialog_command('1.0.1', platform_name='darwin',
                                        which=lambda name: '/usr/bin/' + name,
                                        clients='claude')
        script = cmd[cmd.index('-e') + 1]
        self.assertIn('buttons {"OK"}', script)
        self.assertIn('Restart Claude Code', script)
        self.assertNotIn('to quit', script)

    def test_both_clients_notice_names_both(self):
        message = notice_mod._message('1.0.1', 'both')
        self.assertIn('Quit and reopen Codex', message)
        self.assertIn('restart Claude Code', message)


class InstallNoticeTests(unittest.TestCase):
    @unix_only
    def test_first_install_stages_no_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            rc, _, _, _ = _run_install(self, tmp, home, '1.0.0')
            self.assertEqual(rc, 0)
            self.assertFalse((home / 'update-notice.json').exists())

    @unix_only
    def test_upgrade_with_an_unchanged_picker_stays_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            _run_install(self, tmp, home, '1.0.0')
            rc, _, _, _ = _run_install(self, tmp, home, '1.0.1')
            self.assertEqual(rc, 0)
            self.assertFalse((home / 'update-notice.json').exists(),
                             'a version bump alone is not worth a restart')

    @unix_only
    def test_upgrade_stages_notice_when_the_picker_gains_a_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            _run_install(self, tmp, home, '1.0.0')
            rc, _, _, _ = _run_install(
                self, tmp, home, '1.0.1',
                write_catalogue=_adding_catalogue('openrouter/new-model'))
            self.assertEqual(rc, 0)
            doc = json.loads((home / 'update-notice.json').read_text())
            self.assertEqual(doc['version'], '1.0.1')
            self.assertNotIn('shown', doc)

    @unix_only
    def test_a_failed_install_does_not_lose_the_next_prompt(self):
        # A pre-swap failure has already merged the rows without activating
        # anything; the retry must still see them as additions.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            _run_install(self, tmp, home, '1.0.0')
            real_launcher = install_mod.install_launcher
            calls = []

            def flaky_launcher(home_dir, release):
                calls.append(release)
                if len(calls) == 1:
                    raise OSError('launcher write failed')
                return real_launcher(home_dir, release)

            _patch_attrs(self, install_launcher=flaky_launcher)
            with self.assertRaises(OSError):
                _run_install(self, tmp, home, '1.0.1',
                             write_catalogue=_adding_catalogue('openrouter/new-model'))
            self.assertFalse((home / 'update-notice.json').exists())
            rc, _, _, _ = _run_install(
                self, tmp, home, '1.0.1',
                write_catalogue=_adding_catalogue('openrouter/new-model'))
            self.assertEqual(rc, 0)
            doc = json.loads((home / 'update-notice.json').read_text())
            self.assertEqual(doc['version'], '1.0.1')

    @unix_only
    def test_cli_path_shows_pending_after_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            _run_install(self, tmp, home, '1.0.0')
            blob, latest = _craft_bundle('1.0.1')
            _patch_attrs(self, run=_ok_run,
                         self_test=lambda *a: None,
                         write_catalogue=_adding_catalogue('openrouter/new-model'),
                         wait_version=lambda *a, **k: True)
            launchd_in_sync(home, install_mod.LABEL, install_mod.UPDATE_LABEL)
            # main() takes no fetch injector, so the feed and bundle live
            # as real files next to the temp home (file:// URLs only).
            feed_path = Path(tmp) / 'latest.json'
            bundle_path = Path(tmp) / 'bundle.tar.gz'
            feed_doc = dict(latest, url='file://' + str(bundle_path))
            feed_path.write_text(json.dumps(feed_doc))
            bundle_path.write_bytes(blob)
            feed_url = 'file://' + str(feed_path)
            seen = []
            real_show = install_mod._svc.notice.show_pending
            self.addCleanup(setattr, install_mod._svc.notice,
                            'show_pending', real_show)
            install_mod._svc.notice.show_pending = seen.append
            env = {'HOME': str(Path(tmp) / 'fakehome'),
                   'OPENROUTER_API_KEY': 'test-key',
                   'ROUTER_NO_KEY_WINDOW': '1',
                   'ROUTER_LIVE_RUN': '1'}
            with mock.patch.dict(os.environ, env):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = install_mod.main(
                        ['--feed', feed_url, '--home', str(home)])
            self.assertEqual(rc, 0, buf.getvalue())
            self.assertEqual([str(h) for h in seen], [str(home)])
            doc = json.loads((home / 'update-notice.json').read_text())
            self.assertEqual(doc['version'], '1.0.1')




if __name__ == '__main__':
    unittest.main()
