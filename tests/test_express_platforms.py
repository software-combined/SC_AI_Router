"""Native Express job lifecycle, with isolated paths and recorded OS commands."""
import os
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._platform import unix_only
from tests.fakes import LaunchdDomain
from tests.install_fixtures import install_mod
from tests.test_windows_backend import USER, _backend, _install, backend as windows, QUERY_READY

ROOT = Path(__file__).resolve().parents[1]
darwin = install_mod._svc.load('express_test_darwin', ROOT / 'packaging/platforms/darwin.py')
systemd = install_mod._svc.load('express_test_systemd', ROOT / 'packaging/systemd.py')


class ExpressPlatforms(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / 'router'
        self.home.mkdir()
        install_mod.install_launcher(self.home, ROOT)
        self.assertEqual((self.home / 'express_launch.py').read_bytes(),
                         (ROOT / 'packaging/update_launch.py').read_bytes())
        self.calls = []

    @unix_only
    def test_macos_adopts_express_from_inside_regular_job_and_uninstalls_both(self):
        launchd = darwin._launchd
        agents = self.home / 'LaunchAgents'
        domain = LaunchdDomain().reset(
            unloaded={launchd.EXPRESS_LABEL},
            commands={launchd.LABEL: [sys.executable, str(self.home / 'router_launch.py')],
                      launchd.UPDATE_LABEL: [sys.executable, str(self.home / 'update_launch.py')]})

        def run(cmd, **kwargs):
            self.calls.append(cmd)
            return domain(cmd, **kwargs)

        backend = darwin.Backend(install_mod._svc, run)
        with mock.patch.object(backend, '_agents', return_value=agents), \
                mock.patch.dict(os.environ, {'XPC_SERVICE_NAME': launchd.UPDATE_LABEL}):
            backend.install(sys.executable, self.home, {'port': 12345}, ROOT, '1.0.0')
            regular = plistlib.loads((agents / (launchd.UPDATE_LABEL + '.plist')).read_bytes())
            urgent = plistlib.loads((agents / (launchd.EXPRESS_LABEL + '.plist')).read_bytes())
            self.assertEqual(regular['StartInterval'], 14400)
            self.assertEqual(urgent['StartInterval'], 60)
            self.assertTrue(domain.loaded(launchd.EXPRESS_LABEL))
            self.assertEqual(domain.commands[launchd.EXPRESS_LABEL],
                             [sys.executable, str(self.home / 'express_launch.py')])
            self.assertFalse(any(c[1] == 'bootout' and c[-1].endswith(launchd.UPDATE_LABEL)
                                 for c in self.calls))
            backend.uninstall(self.home)
        self.assertEqual(list(agents.iterdir()), [])
        self.assertFalse(domain.loaded(launchd.EXPRESS_LABEL))

    @unix_only
    def test_linux_enables_both_timers_without_stopping_its_installer(self):
        def run(cmd, **kwargs):
            self.calls.append(cmd)
            return mock.Mock(returncode=0, stdout='', stderr='')

        with mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.home / 'config'),
                                          'ROUTER_UPDATE_SERVICE': '1'}):
            manager = systemd.Manager(self.home, run)
            manager.install(sys.executable, ROOT)
            regular = (manager.units / systemd.TIMER).read_text()
            urgent = (manager.units / systemd.EXPRESS_TIMER).read_text()
            service = (manager.units / systemd.EXPRESS_UPDATE).read_text()
            self.assertIn('OnUnitInactiveSec=4h', regular)
            self.assertIn('OnUnitInactiveSec=1min', urgent)
            self.assertIn('AccuracySec=1s', urgent)
            self.assertIn(str(self.home / 'express_launch.py'), service)
            self.assertIn('ROUTER_UPDATE_SERVICE=1', service)
            self.assertNotIn('--feed', service)
            for name in (systemd.UPDATE, systemd.EXPRESS_UPDATE):
                self.assertNotIn(['systemctl', '--user', 'stop', name], self.calls)
            for timer in (systemd.TIMER, systemd.EXPRESS_TIMER):
                self.assertIn(['systemctl', '--user', 'start', timer], self.calls)
            manager.uninstall()
            self.assertEqual(list(manager.units.iterdir()), [])

    def test_windows_registers_minute_job_with_same_safe_task_settings(self):
        state = {}
        _install(_backend(state, self.calls), self.home)
        regular = state['xml_' + windows.UPDATE_TASK]
        urgent = state['xml_' + windows.EXPRESS_TASK]
        self.assertIn('<Interval>PT4H</Interval>', regular)
        for fragment in ('<Interval>PT1M</Interval>', 'express_launch.py',
                         'pythonw.exe', '<MultipleInstancesPolicy>IgnoreNew',
                         '<LogonType>InteractiveToken', '<RunLevel>LeastPrivilege',
                         '<ExecutionTimeLimit>PT30M', '<StartBoundary>'):
            self.assertIn(fragment, urgent)
        self.assertEqual(len([c for c in self.calls if c['operation'] == 'register']), 3)
        state['query'] = QUERY_READY  # Simulate the task's completed drain.
        _backend(state, self.calls).uninstall(self.home)
        self.assertIn(windows.EXPRESS_TASK + '-' + USER,
                      [c['name'] for c in self.calls if c['operation'] == 'delete'])

    def test_windows_uninstall_also_accepts_an_install_without_express(self):
        _backend({'missing': {windows.EXPRESS_TASK}}, calls=self.calls).uninstall(self.home)
        self.assertNotIn(windows.EXPRESS_TASK + '-' + USER,
                         [c['name'] for c in self.calls if c['operation'] == 'delete'])
