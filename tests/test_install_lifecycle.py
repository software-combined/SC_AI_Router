"""Installer lifecycle: backup-before-replace, fail-closed uninstall, rollback.

Brief defects 4-5: config replacement must back up before truncating, a
failed restore must not stop services, --version rolls back from installed
releases (never the JSON feed), and a failed first install must not read
as up to date on retry.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_install import (
    _craft_bundle,
    _ok_run,
    _patch_attrs,
    _static_fetch,
    install_mod,
)
from tests.test_install_config import _fake_write_catalogue


def _no_fetch(url):
    raise AssertionError('rollback must not fetch anything')


def _uninstall_home(tmp):
    """Staged home with one installed release, pointer current, and plists."""
    home = Path(tmp) / 'home'
    rel = home / 'releases' / '1.0.0'
    (rel / 'tools').mkdir(parents=True)
    (rel / 'tools' / 'disable.py').write_text('# stub\n')
    (home / 'current').write_text('1.0.0\n')
    agents = Path(tmp) / 'fakehome' / 'Library' / 'LaunchAgents'
    agents.mkdir(parents=True)
    return home, agents


def _run_install(test, tmp, home, version, *extra_args, feed='file:///latest.json',
                 wait_version=True):
    blob, latest = _craft_bundle(version)
    latest = dict(latest, version=version)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return _ok_run(cmd, **kwargs)

    _patch_attrs(test, run=fake_run, self_test=lambda *args: None,
                 write_catalogue=_fake_write_catalogue,
                 wait_version=lambda *args, **kwargs: wait_version)
    argv = ['--home', str(home), *extra_args]
    if feed is not None:
        argv = ['--feed', feed, *argv]
    args = install_mod.build_parser().parse_args(argv)
    env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'test-key'}
    with mock.patch.dict(os.environ, env):
        rc = install_mod.do_install(args, _fetch=_static_fetch(latest, blob),
                                    _run=fake_run)
    return rc, calls, args, env


class InstallLifecycleTests(unittest.TestCase):
    def test_current_pointer_reports_version_and_survives_garbage(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            self.assertEqual(install_mod.current_version(home), '0.0.0')
            self.assertIsNone(install_mod.current_release_dir(home))
            (home / 'current').write_text('  \n')
            self.assertEqual(install_mod.current_version(home), '0.0.0')
            self.assertIsNone(install_mod.current_release_dir(home))
            rel = home / 'releases' / '1.2.3'
            (rel / 'packaging').mkdir(parents=True)
            self.assertIsNone(install_mod.swap_current(home, rel))
            self.assertEqual(install_mod.current_version(home), '1.2.3')
            self.assertEqual(install_mod.current_release_dir(home), rel)

    def test_absolute_pointer_resolves_inside_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            (home / 'releases' / 'passwd').mkdir(parents=True)
            (home / 'current').write_text('/etc/passwd\n')
            self.assertEqual(install_mod.current_release_dir(home),
                             home / 'releases' / 'passwd')
            self.assertEqual(install_mod.current_version(home), 'passwd')

    def test_binary_garbage_pointer_reads_as_no_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            (home / 'current').write_bytes(b'\x00\xff\xfe\x01')
            self.assertEqual(install_mod.current_version(home), '0.0.0')
            self.assertIsNone(install_mod.current_release_dir(home))

    def test_swap_current_migrates_legacy_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            prev = home / 'releases' / '0.2.0'
            (prev / 'packaging').mkdir(parents=True)
            (prev / 'packaging' / 'VERSION').write_text('0.2.0\n')
            os.symlink(str(prev), home / 'current')
            self.assertEqual(install_mod.current_version(home), '0.2.0')
            install_mod.swap_current(home, home / 'releases' / '0.3.0')
            self.assertFalse((home / 'current').is_symlink())
            self.assertEqual((home / 'current').read_text(), '0.3.0\n')

    def test_config_backup_holds_pre_replacement_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            rc, _, _, env = _run_install(self, tmp, home, '1.0.0')
            self.assertEqual(rc, 0)
            config = Path(env['HOME']) / '.codex' / 'config.toml'
            first_config = config.read_text()
            config.write_text('other = 1\n' + first_config)
            _run_install(self, tmp, home, '1.0.1')
            backups = sorted(home.glob('config-before-*.toml'))
            self.assertTrue(backups)
            self.assertEqual(backups[-1].read_text(), 'other = 1\n' + first_config)

    def test_uninstall_aborts_when_restore_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, agents = _uninstall_home(tmp)
            main_plist = agents / (install_mod.LABEL + '.plist')
            main_plist.write_text('plist\n')
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(list(cmd))
                if 'disable.py' in cmd[-1]:
                    return SimpleNamespace(returncode=1, stdout='boom', stderr='nope')
                return _ok_run(cmd, **kwargs)

            _patch_attrs(self, run=fake_run)
            args = install_mod.build_parser().parse_args(['--home', str(home)])
            with mock.patch.dict(os.environ, {'HOME': str(Path(tmp) / 'fakehome')}):
                with self.assertRaisesRegex(SystemExit, 'services left running'):
                    install_mod.do_uninstall(args)
            self.assertFalse(any(cmd[:2] == ['launchctl', 'bootout'] for cmd in calls),
                             'failed restore must not stop services')
            self.assertTrue(main_plist.exists())

    def test_uninstall_proceeds_when_restore_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, agents = _uninstall_home(tmp)
            (agents / (install_mod.LABEL + '.plist')).write_text('plist\n')
            (agents / (install_mod.UPDATE_LABEL + '.plist')).write_text('plist\n')
            seen = {}

            def fake_run(cmd, **kwargs):
                if 'disable.py' in cmd[-1]:
                    seen['env'] = kwargs.get('env')
                    return SimpleNamespace(
                        returncode=0,
                        stdout='OpenAI direct routing restored. Restart Codex.\n',
                        stderr='')
                return _ok_run(cmd, **kwargs)

            _patch_attrs(self, run=fake_run)
            args = install_mod.build_parser().parse_args(['--home', str(home)])
            with mock.patch.dict(os.environ, {'HOME': str(Path(tmp) / 'fakehome')}):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    self.assertEqual(install_mod.do_uninstall(args), 0)
            self.assertIn('OpenAI direct routing restored', buf.getvalue())
            self.assertEqual(seen['env'].get('ROUTER_HOME'), str(home))
            self.assertFalse((agents / (install_mod.LABEL + '.plist')).exists())
            self.assertFalse((agents / (install_mod.UPDATE_LABEL + '.plist')).exists())

    def test_version_rolls_back_from_installed_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            _run_install(self, tmp, home, '1.0.0')
            _, calls, _, _ = _run_install(self, tmp, home, '1.0.1')
            serial_before = (home / 'feed-serial').read_text()
            _patch_attrs(self, wait_version=lambda *args, **kwargs: True)
            args = install_mod.build_parser().parse_args(
                ['--home', str(home), '--version', '1.0.0'])
            with mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': 'k'}):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    self.assertEqual(install_mod.do_install(args, _fetch=_no_fetch), 0)
            self.assertIn('rolled back to 1.0.0', buf.getvalue())
            self.assertEqual((home / 'current').read_text(), '1.0.0\n')
            self.assertTrue(any(cmd[:3] == ['launchctl', 'kill', 'TERM'] for cmd in calls))
            self.assertEqual((home / 'feed-serial').read_text(), serial_before)

    def test_version_rollback_needs_installed_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()

            args = install_mod.build_parser().parse_args(
                ['--home', str(home), '--version', '9.9.9'])
            with self.assertRaisesRegex(SystemExit, 'not installed'):
                install_mod.do_install(args, _fetch=_no_fetch)

    def test_version_rollback_restores_previous_on_health_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            _run_install(self, tmp, home, '1.0.0')
            _run_install(self, tmp, home, '1.0.1')
            _patch_attrs(self, wait_version=lambda *args, **kwargs: None)
            args = install_mod.build_parser().parse_args(
                ['--home', str(home), '--version', '1.0.0'])
            with mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': 'k'}):
                with self.assertRaises(SystemExit):
                    install_mod.do_install(args, _fetch=_no_fetch)
            self.assertEqual((home / 'current').read_text(), '1.0.1\n')

    def test_failed_first_install_retries_instead_of_up_to_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            blob, latest = _craft_bundle('1.0.0')
            fake_fetch = _static_fetch(latest, blob)
            _patch_attrs(self, run=lambda cmd, **kwargs: _ok_run(cmd, **kwargs),
                         self_test=lambda *args: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *args, **kwargs: None)
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'test-key'}
            with mock.patch.dict(os.environ, env):
                with self.assertRaises(SystemExit):
                    install_mod.do_install(args, _fetch=fake_fetch)
            self.assertFalse((home / 'current').exists())
            _patch_attrs(self, wait_version=lambda *args, **kwargs: True)
            with mock.patch.dict(os.environ, env):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = install_mod.do_install(args, _fetch=fake_fetch)
            self.assertEqual(rc, 0)
            self.assertIn('installed 1.0.0', buf.getvalue())
            self.assertEqual((home / 'current').read_text(), '1.0.0\n')


if __name__ == '__main__':
    unittest.main()
