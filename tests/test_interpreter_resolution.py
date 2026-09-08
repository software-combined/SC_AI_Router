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

from tests.test_install import (
    _craft_bundle,
    _ok_run,
    _patch_attrs,
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

    def test_render_plist_accepts_absolute(self):
        content = svc.render_plist('/opt/homebrew/bin/python3.14', Path('/tmp/hm'),
                                   {'port': 18749})
        self.assertEqual(content['ProgramArguments'][0], '/opt/homebrew/bin/python3.14')

    def test_render_update_plist_rejects_bare_token(self):
        with self.assertRaises(SystemExit):
            svc.render_update_plist('python3.14', Path('/tmp/hm'))


class LegacyReloadTests(unittest.TestCase):
    """Legacy bare-python plist heals via targeted main-only reload."""

    def test_bare_legacy_plist_triggers_main_reload_not_term(self):
        from tests.fakes import static_fetch as _static_fetch
        from tests.test_install_config import _fake_write_catalogue
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(list(cmd))
                return _ok_run(cmd, **kwargs)

            _patch_attrs(self, run=fake_run, self_test=lambda *a: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_idle=lambda *a, **k: True,
                         wait_version=lambda *a, **k: {'status': 'ok', 'version': '1.0.1'},
                         main_plist_exe=lambda agents=None: 'python3.14')
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'k'}
            with mock.patch.dict(os.environ, env):
                args = install_mod.build_parser().parse_args(
                    ['--feed', 'file:///latest.json', '--home', str(home)])
                blob_seed, latest_seed = _craft_bundle('1.0.0')
                self.assertEqual(
                    install_mod.do_install(
                        args, _fetch=_static_fetch(latest_seed, blob_seed),
                        _run=fake_run), 0)
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
            self.assertFalse([c for c in calls if 'update' in c[-1]],
                             'updater must never be touched by legacy repair')

    def test_reload_bootstrap_failure_restores_previous_and_reloads(self):
        from tests.fakes import static_fetch as _static_fetch
        from tests.test_install_config import _fake_write_catalogue
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            calls = []
            attempts = {'n': 0}

            def fake_run(cmd, **kwargs):
                calls.append(list(cmd))
                if cmd[:2] == ['launchctl', 'bootstrap']:
                    attempts['n'] += 1
                    if attempts['n'] == 1:
                        # Reload bootstrap fails; rollback re-bootstrap heals.
                        return SimpleNamespace(returncode=1, stdout='', stderr='boom')
                return _ok_run(cmd, **kwargs)

            _patch_attrs(self, run=fake_run, self_test=lambda *a: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_idle=lambda *a, **k: True,
                         wait_version=lambda *a, **k: {'status': 'ok', 'version': '1.0.1'},
                         main_plist_exe=lambda agents=None: 'python3.14')
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'k'}
            with mock.patch.dict(os.environ, env):
                args = install_mod.build_parser().parse_args(
                    ['--feed', 'file:///latest.json', '--home', str(home)])
                blob_seed, latest_seed = _craft_bundle('1.0.0')
                # Seed via plain ok-run (bootstrap must succeed there).
                self.assertEqual(
                    install_mod.do_install(
                        args, _fetch=_static_fetch(latest_seed, blob_seed),
                        _run=_ok_run), 0)
                blob1, latest1 = _craft_bundle('1.0.1')
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    with self.assertRaises(SystemExit) as ctx:
                        install_mod.do_install(
                            args, _fetch=_static_fetch(latest1, blob1), _run=fake_run)
            self.assertEqual(ctx.exception.code, 1)
            self.assertEqual((home / 'current').read_text(), '1.0.0\n')

            def is_main_bootstrap(cmd):
                return (cmd[:2] == ['launchctl', 'bootstrap'] and len(cmd) == 4
                        and cmd[2].startswith('gui/') and cmd[3].endswith('.plist')
                        and 'update' not in cmd[3])

            straps = [c for c in calls if is_main_bootstrap(c)]
            self.assertEqual(len(straps), 2,
                             'failed reload must retry bootstrap for the old release')
            self.assertFalse([c for c in calls if 'update' in c[-1]],
                             'updater must never be touched by reload rollback')


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


if __name__ == '__main__':
    unittest.main()
