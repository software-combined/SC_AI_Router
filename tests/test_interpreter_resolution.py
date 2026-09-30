"""Absolute interpreter resolution for launchd service definitions.

Regression: the installer persisted find_python's bare discovery token
('python3.14') into ProgramArguments[0]; launchd has no Homebrew PATH, so
every spawn failed and the router stayed dead after update. The installer
must persist the probed sys.executable and fail closed otherwise.
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests._platform import unix_only
from tests.fakes import LAUNCHD, launchd_in_sync, static_fetch as _static_fetch
from tests.install_fixtures import (
    _craft_bundle,
    _ok_run,
    _patch_attrs,
    _run_install,
    install_mod,
)

svc = install_mod._svc


def _probe_run(exe, version='3 14'):
    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout=f'{version}\n{exe}\n', stderr='')
    return fake_run


class FindPythonTests(unittest.TestCase):
    def test_returns_probed_exe_not_candidate_token(self):
        with mock.patch.object(svc, 'run', _probe_run('/opt/homebrew/bin/python3.14')):
            self.assertEqual(svc.find_python(), '/opt/homebrew/bin/python3.14')

    def test_all_fail_returns_none(self):
        with mock.patch.object(
                svc, 'run',
                lambda cmd, **kwargs: SimpleNamespace(returncode=1, stdout='', stderr='')):
            self.assertIsNone(svc.find_python())

    def test_rejects_old_python(self):
        with mock.patch.object(svc, 'run', _probe_run('/usr/bin/python3.9', version='3 9')):
            self.assertIsNone(svc.find_python('python3.9'))


class RenderGuardTests(unittest.TestCase):
    def test_render_plist_rejects_bare_token(self):
        with self.assertRaises(SystemExit):
            svc.render_plist('python3.14', Path('/tmp/hm'), {'port': 18749})

    def test_render_plist_rejects_relative(self):
        with self.assertRaises(SystemExit):
            svc.render_plist('bin/python3.14', Path('/tmp/hm'), {'port': 18749})

    @unix_only
    def test_render_plist_accepts_absolute(self):
        content = svc.render_plist('/opt/homebrew/bin/python3.14', Path('/tmp/hm'),
                                   {'port': 18749})
        self.assertEqual(content['ProgramArguments'][0], '/opt/homebrew/bin/python3.14')

    def test_render_update_plist_rejects_bare_token(self):
        with self.assertRaises(SystemExit):
            svc.render_update_plist('python3.14', Path('/tmp/hm'))


@unix_only
class LegacyReloadTests(unittest.TestCase):
    """Legacy bare-python plist heals via targeted main-only reload."""

    def test_bare_legacy_plist_triggers_main_reload_not_term(self):
        from tests.test_install_config import _fake_write_catalogue
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(list(cmd))
                return _ok_run(cmd, **kwargs)

            _patch_attrs(self, run=fake_run, self_test=lambda *a: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *a, **k: {'status': 'ok', 'version': '1.0.1'})
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'k', 'ROUTER_NO_KEY_WINDOW': '1'}
            with mock.patch.dict(os.environ, env):
                args = install_mod.build_parser().parse_args(
                    ['--feed', 'file:///latest.json', '--home', str(home)])
                blob_seed, latest_seed = _craft_bundle('1.0.0')
                self.assertEqual(
                    install_mod.do_install(
                        args, _fetch=_static_fetch(latest_seed, blob_seed),
                        _run=fake_run), 0)
                # Legacy machine: launchd is running a bare discovery token, so
                # the loaded job cannot be repaired by a TERM handover alone.
                LAUNCHD.reset(program='python3.14')
                calls.clear()  # isolate the upgrade: seed's bootout must not satisfy us
                blob1, latest1 = _craft_bundle('1.0.1')
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = install_mod.do_install(
                        args, _fetch=_static_fetch(latest1, blob1), _run=fake_run)
            self.assertEqual(rc, 0)
            main = [c for c in calls if c[:2] == ['launchctl', 'bootout']
                    and str(install_mod.LABEL) in c[-1] and 'update' not in c[-1]]
            straps = [c for c in calls if c[:2] == ['launchctl', 'bootstrap']
                      and str(install_mod.LABEL) in c[-1] and 'update' not in c[-1]]
            self.assertTrue(main, 'legacy bare plist must bootout the main agent')
            self.assertTrue(straps, 'legacy bare plist must bootstrap the main agent')
            # The updater is running the same stale interpreter, so it must be
            # reloaded too: writing its plist is not enough, launchd keeps the
            # loaded copy and would go on invoking the old command forever.
            self.assertTrue([c for c in calls if c[:2] == ['launchctl', 'bootstrap']
                             and 'update' in c[-1]],
                            'a stale updater command must be reloaded, not just rewritten')

    def _legacy_upgrade(self, tmp, bootstrap_failures, wait_version):
        """Seed 1.0.0, then upgrade 1.0.1 on a machine with a stale plist."""
        from tests.test_install_config import _fake_write_catalogue
        home = Path(tmp) / 'home'
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            return _ok_run(cmd, **kwargs)

        # The seed must succeed on its own terms; only the upgrade under test
        # gets the caller's health outcome.
        _patch_attrs(self, run=fake_run, self_test=lambda *a: None,
                     write_catalogue=_fake_write_catalogue,
                     wait_version=lambda *a, **k: {'status': 'ok'})
        env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'k', 'ROUTER_NO_KEY_WINDOW': '1'}
        with mock.patch.dict(os.environ, env):
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            blob_seed, latest_seed = _craft_bundle('1.0.0')
            self.assertEqual(
                install_mod.do_install(
                    args, _fetch=_static_fetch(latest_seed, blob_seed),
                    _run=_ok_run), 0)
            for mod in (install_mod, install_mod._svc):
                setattr(mod, 'wait_version', wait_version)
            LAUNCHD.reset(program='python3.14',
                          bootstrap_failures=bootstrap_failures)
            calls.clear()
            blob1, latest1 = _craft_bundle('1.0.1')
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                try:
                    rc = install_mod.do_install(
                        args, _fetch=_static_fetch(latest1, blob1), _run=fake_run)
                except SystemExit as exc:
                    rc = exc.code
        return home, calls, rc, buf.getvalue()

    def test_transient_bootstrap_failure_is_retried_not_fatal(self):
        # bootout returns before the job leaves the domain, so the first
        # bootstrap after it loses a race and returns error 5. Trusting that
        # single rc is what unloaded the router and left nothing to restart.
        with tempfile.TemporaryDirectory() as tmp:
            home, calls, rc, _out = self._legacy_upgrade(
                tmp, bootstrap_failures=1,
                wait_version=lambda *a, **k: {'status': 'ok', 'version': '1.0.1'})
            self.assertEqual(rc, 0, 'a retryable bootstrap race must not fail the install')
            self.assertEqual((home / 'current').read_text(), '1.0.1\n')
            straps = [c for c in calls if c[:2] == ['launchctl', 'bootstrap']
                      and 'update' not in c[-1]]
            self.assertGreaterEqual(len(straps), 2, 'bootstrap must be retried')

    def test_persistent_reload_failure_rolls_back_and_reports_not_serving(self):
        # The outage shape: the reload cannot load the job at all. Rolling the
        # pointer back and sending TERM cannot help, because KeepAlive has no
        # job to keep alive -- so the installer must say the router is down
        # instead of printing a clean rollback over a dead machine.
        with tempfile.TemporaryDirectory() as tmp:
            home, _calls, rc, out = self._legacy_upgrade(
                tmp, bootstrap_failures=99, wait_version=lambda *a, **k: None)
            self.assertEqual(rc, 1)
            self.assertEqual((home / 'current').read_text(), '1.0.0\n',
                             'a failed reload must restore the previous pointer')
            self.assertIn('NOT serving', out)


@unix_only
class HandoverTests(unittest.TestCase):
    """An ordinary upgrade hands over in place; it never bootouts."""

    def test_upgrade_hands_over_with_term_not_bootout(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            prev = home / 'releases' / '0.2.0'
            (prev / 'packaging').mkdir(parents=True)
            (prev / 'packaging' / 'VERSION').write_text('0.2.0\n')
            home.mkdir(parents=True, exist_ok=True)
            os.symlink(str(prev), home / 'current')
            blob, latest = _craft_bundle('9.9.9')
            fake_fetch = _static_fetch(latest, blob)

            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(list(cmd))
                return _ok_run(cmd, **kwargs)

            _patch_attrs(self, run=fake_run,
                         self_test=lambda *args: None,
                         health=lambda state, timeout=20: {'status': 'ok', 'version': '9.9.9'})
            # A live upgrade finds its plists already written and launchd
            # already running them. Without that the installer would rightly
            # choose a reload, so stage it to test the handover path.
            agents = Path(tmp) / 'fakehome' / 'Library' / 'LaunchAgents'
            state = install_mod.ensure_state(home)
            install_mod.write_plist(
                agents / (install_mod.LABEL + '.plist'),
                install_mod.render_plist(LAUNCHD.DEFAULT_PROGRAM, home, state))
            launchd_in_sync(home, install_mod.LABEL, install_mod.UPDATE_LABEL)
            _run_install(self, tmp, home, fake_fetch, fake_run)
            kills = [cmd for cmd in calls if cmd[:3] == ['launchctl', 'kill', 'TERM']]
            self.assertTrue(kills, 'upgrade must TERM the running router')
            bootouts = [cmd for cmd in calls if cmd[:2] == ['launchctl', 'bootout']]
            self.assertFalse(bootouts, 'upgrade must not bootout a live service')
            bootstraps = [cmd for cmd in calls if 'bootstrap' in cmd]
            self.assertFalse(bootstraps, 'upgrade must not bootstrap over a live service')
            self.assertTrue((agents / (install_mod.LABEL + '.plist')).exists())


class PortableOrderTests(unittest.TestCase):
    """find_python prefers portable interpreters over platform shims."""

    def test_sys_executable_last_resort(self):
        seen = []

        def fake_run(cmd, **kwargs):
            seen.append(cmd[0] if len(cmd) == 2 else tuple(cmd[:2]))
            if cmd[0] == sys.executable:
                return SimpleNamespace(
                    returncode=0, stdout='3 14\n/opt/homebrew/bin/python3.14\n', stderr='')
            return SimpleNamespace(returncode=1, stdout='', stderr='')

        with mock.patch.object(svc, 'run', fake_run):
            with mock.patch.object(sys, 'platform', 'darwin'):
                got = svc.find_python()
        self.assertEqual(got, '/opt/homebrew/bin/python3.14')
        # sys.executable probed only after portable candidates failed.
        self.assertEqual(seen[-1][0], sys.executable)
        self.assertIn(('python3.14', '-c'), seen)

    def test_windows_never_runs_a_drive_less_candidate(self):
        # On Windows /usr/... and /opt/... are drive-root folders any local
        # account can create, so a python3.14 planted there must never run.
        posix = ['/usr/bin/python3.14', '/usr/local/bin/python3.14',
                 '/opt/homebrew/bin/python3.14', '/opt/homebrew/bin/python3']
        exe = r'C:\Python314\python.exe'
        for platform, want in (('win32', ['python3.14', exe, 'py']),
                               ('darwin', ['python3.14'] + posix + [exe])):
            tried = []

            def fake_run(cmd, **kwargs):
                tried.append(cmd[0])
                planted = platform == 'win32' and cmd[0] in posix  # answers as 3.14
                return SimpleNamespace(returncode=0 if planted else 1,
                                       stdout=f'3 14\n{cmd[0]}\n', stderr='')

            with self.subTest(platform=platform), mock.patch.object(svc, 'run', fake_run), \
                    mock.patch.object(sys, 'platform', platform), \
                    mock.patch.object(sys, 'executable', exe), \
                    mock.patch.object(svc.shutil, 'which', lambda name: None):
                self.assertIsNone(svc.find_python())
                self.assertEqual(tried, want)


if __name__ == '__main__':
    unittest.main()
