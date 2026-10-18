"""Scheduler migration proves the effective command before pruning old releases."""
import os
import subprocess
import sys
import unittest
from unittest import mock

from tests._platform import unix_only
from tests import test_systemd as fixtures
from tests.install_fixtures import install_mod


@unix_only
class SystemdRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.rig = fixtures.SystemdTests()
        self.rig.setUp()
        self.addCleanup(self.rig.doCleanups)

    def test_update_job_uses_the_stable_launcher_and_reads_back_after_reload(self):
        self.rig.install('1.2.6.174')
        units = self.rig.root / 'config/systemd/user'
        text = (units / install_mod._linux.UPDATE).read_text()
        self.assertIn(str(self.rig.home / 'update_launch.py'), text)
        self.assertNotIn('/releases/', text)
        calls = self.rig.calls
        reload = calls.index(['systemctl', '--user', 'daemon-reload'])
        readback = next(i for i, cmd in enumerate(calls) if cmd[2:3] == ['show'])
        restart = calls.index(['systemctl', '--user', 'restart', install_mod._linux.SERVICE])
        self.assertLess(reload, readback)
        self.assertLess(readback, restart)

    def test_missing_launcher_refuses_before_stopping_any_job(self):
        self.rig.install('1.2.6.174')
        (self.rig.home / 'update_launch.py').unlink()
        self.rig.calls.clear()
        manager = install_mod._linux.Manager(self.rig.home, self.rig.run_command)
        with self.assertRaisesRegex(SystemExit, 'launcher'):
            manager.install(sys.executable, self.rig.home / 'releases/1.2.6.174')
        self.assertEqual(self.rig.calls, [])

    def test_stale_effective_command_refuses_even_when_the_unit_file_is_new(self):
        self.rig.install('1.2.6.174')
        self.rig.calls.clear()
        def run(command, **kwargs):
            if command[2:3] == ['show']:
                self.rig.calls.append(command)
                return subprocess.CompletedProcess(command, 0, '{ path=/old/python ; argv[]=/old/python old.py ; }', '')
            return self.rig.run_command(command, **kwargs)
        manager = install_mod._linux.Manager(self.rig.home, run)
        with self.assertRaisesRegex(SystemExit, 'scheduled updater'):
            manager.install(sys.executable, self.rig.home / 'releases/1.2.6.174')
        self.assertFalse(any(command[2:3] == ['restart'] for command in self.rig.calls))

    def test_loaded_release_is_retained_and_unknown_manager_prevents_pruning(self):
        self.rig.install('1.2.6.174')
        for version in ('1.3.0', '1.3.1', '1.3.2'):
            (self.rig.home / 'releases' / version).mkdir()
        old = str(self.rig.home / 'releases/1.2.6.174/packaging/install.py')
        def loaded(command, **kwargs):
            if command[2:3] == ['show']:
                return subprocess.CompletedProcess(command, 0, old, '')
            return self.rig.run_command(command, **kwargs)
        backend = install_mod._platforms.select('linux', install_mod._svc, loaded)
        keep = backend.pinned_release(self.rig.home)
        install_mod.prune_releases(self.rig.home, keep)
        self.assertTrue((self.rig.home / 'releases/1.2.6.174').exists())
        unavailable = install_mod._platforms.select('linux', install_mod._svc,
            lambda command, **kwargs: subprocess.CompletedProcess(command, 1, '', ''))
        keep = unavailable.pinned_release(self.rig.home)
        install_mod.prune_releases(self.rig.home, keep)
        self.assertTrue((self.rig.home / 'releases/1.2.6.174').exists())

    def test_running_legacy_updater_survives_a_successful_scheduler_reload(self):
        self.rig.install('1.2.6.174')
        manager = install_mod._linux.Manager(self.rig.home, self.rig.run_command)
        for version in ('1.3.0', '1.3.1', '1.3.2'):
            (self.rig.home / 'releases' / version).mkdir()
        for origin in (None, '1.2.6.174', 'control'):
            with self.subTest(origin=origin), mock.patch.dict(os.environ, ROUTER_UPDATE_SERVICE='1'):
                os.environ.pop('ROUTER_UPDATE_ORIGIN', None)
                if origin is not None:
                    os.environ['ROUTER_UPDATE_ORIGIN'] = origin
                keep = manager.pinned_releases()
                self.assertEqual('1.2.6.174' in keep, origin != 'control')
