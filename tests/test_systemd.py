"""Linux installer lifecycle with fake OS commands and an isolated home."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.install_fixtures import _craft_bundle, _ok_run, _patch_attrs, _static_fetch, install_mod
from tests._platform import unix_only


@unix_only
class SystemdTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / 'router'
        self.calls = []
        for patcher in (
                mock.patch.object(install_mod, 'PLATFORM', 'linux'),
                mock.patch.dict(os.environ, {'HOME': str(self.root / 'user'),
                    'XDG_CONFIG_HOME': str(self.root / 'config'), 'OPENROUTER_API_KEY': 'test-key'})):
            patcher.start()
            self.addCleanup(patcher.stop)
        _patch_attrs(self, run=self.run_command, self_test=lambda *a: None,
                     write_catalogue=lambda home, *a: (home / 'mixed-models.json').write_text('new'),
                     wait_version=lambda *a, **kw: True)

    def run_command(self, cmd, **kwargs):
        self.calls.append(cmd)
        self.assertNotEqual(cmd[0], 'launchctl', 'Linux must never call launchctl')
        if 'disable.py' in cmd[-1]:
            return subprocess.CompletedProcess(cmd, 0, 'OpenAI direct routing restored.', '')
        return _ok_run(cmd, **kwargs)

    def install(self, version):
        blob, latest = _craft_bundle(version)
        self.home.mkdir(parents=True, exist_ok=True)
        args = install_mod.build_parser().parse_args(
            ['--home', str(self.home), '--python', sys.executable])
        with contextlib.redirect_stdout(io.StringIO()):
            return install_mod.do_install(args, _fetch=_static_fetch(latest, blob))

    def test_fresh_install_and_legacy_symlink_upgrade(self):
        self.install('0.6.2.0')
        current = self.home / 'current'
        current.unlink()
        current.symlink_to(self.home / 'releases' / '0.6.2.0')
        before_state = (self.home / 'mixed-router-state.json').read_bytes()
        self.install('0.6.6.0')
        self.assertFalse(current.is_symlink())
        self.assertEqual(current.read_text().strip(), '0.6.6.0')
        self.assertEqual((self.home / 'mixed-router-state.json').read_bytes(), before_state)
        units = self.root / 'config' / 'systemd' / 'user'
        service = (units / install_mod._linux.SERVICE).read_text()
        self.assertIn(str(self.home / 'router_launch.py'), service)
        self.assertNotIn('WorkingDirectory=', service)
        self.assertIn('TimeoutStopSec=150', service)
        self.assertIn('WantedBy=default.target', service)
        update = (units / install_mod._linux.UPDATE).read_text()
        self.assertIn(str(self.home / 'releases' / '0.6.6.0' / 'packaging' / 'install.py'), update)
        self.assertNotIn('--feed', update)
        self.assertIn('ROUTER_UPDATE_SERVICE=1', update)
        # A detached restart dialog must outlive the oneshot unit.
        self.assertIn('KillMode=process', update)
        self.assertIn(['systemctl', '--user', 'start', install_mod._linux.TIMER], self.calls)

    def test_failed_upgrade_restores_pointer_catalogue_and_timer(self):
        self.install('0.6.2.0')
        catalogue = self.home / 'mixed-models.json'
        catalogue.write_text('previous catalogue')
        _patch_attrs(self, wait_version=lambda *a, **kw: False)
        with self.assertRaises(SystemExit):
            self.install('0.6.6.0')
        self.assertEqual(install_mod.current_version(self.home), '0.6.2.0')
        self.assertEqual(catalogue.read_text(), 'previous catalogue')
        self.assertEqual(self.calls[-1], ['systemctl', '--user', 'start', install_mod._linux.TIMER])

    def test_refused_settings_merge_leaves_the_update_timer_running(self):
        # A hand-edited Codex block refuses the settings rewrite after the
        # router swap. That used to return before start_updates(), leaving
        # the timer stopped: no scheduled check ran until a reinstall.
        self.install('0.6.2.0')
        config = self.root / 'user' / '.codex' / 'config.toml'
        config.write_text(config.read_text().replace(
            'openai_base_url', 'openai_base_url_edited'))
        with self.assertRaisesRegex(SystemExit, 'edited by hand'):
            self.install('0.6.6.0')
        self.assertEqual(self.calls[-1],
                         ['systemctl', '--user', 'start', install_mod._linux.TIMER])

    def test_rollback_and_uninstall_use_systemd_and_preserve_home(self):
        self.install('0.6.2.0')
        self.install('0.6.6.0')
        args = install_mod.build_parser().parse_args(
            ['--home', str(self.home), '--version', '0.6.2.0'])
        install_mod.do_rollback(args)
        self.assertEqual(install_mod.current_version(self.home), '0.6.2.0')
        install_mod.do_uninstall(args)
        self.assertEqual(list((self.root / 'config' / 'systemd' / 'user').iterdir()), [])
        self.assertTrue((self.home / 'mixed-router-state.json').exists())

    def test_missing_user_manager_fails_before_installation(self):
        _patch_attrs(self, run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, '', ''))
        args = ['--home', str(self.home)]
        with self.assertRaisesRegex(SystemExit, 'systemd user manager'):
            install_mod.main(args)
        self.assertFalse(self.home.exists())

    def test_scheduled_installer_does_not_stop_its_parent_service(self):
        with mock.patch.dict(os.environ, {'ROUTER_UPDATE_SERVICE': '1'}):
            self.install('0.6.6.0')
        self.assertNotIn(['systemctl', '--user', 'stop', install_mod._linux.UPDATE], self.calls)

    def test_deferred_child_keeps_etag_and_does_not_report_success(self):
        self.install('0.6.2.0')
        blob, latest = _craft_bundle('0.6.6.0')
        # check-update needs an installer member; the child invocation is mocked.
        from tests.install_fixtures import _tarball
        blob = _tarball(files=[('packaging/install.py', '# installer')])
        (self.home / 'update-etag').write_text('old')
        args = install_mod.build_parser().parse_args(['--home', str(self.home)])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            install_mod.do_check_update(args, _fetch=_static_fetch(latest, blob),
                _read_feed=lambda *a: (200, json.dumps(latest).encode(), 'new'), _sleep=lambda s: None)
        self.assertIn('deferred:', output.getvalue())
        self.assertEqual((self.home / 'update-etag').read_text(), 'old')
        self.assertFalse((self.home / 'logs' / 'update.log').exists())


if __name__ == '__main__':
    unittest.main()
