"""Owned task contracts and a real, disposable Windows Task Scheduler proof."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_windows_backend import _backend, _install, _query, _state_file, _verbs, backend, service
from tests.test_windows_task_state import _CurrentInstallerFixture


class OwnershipTests(unittest.TestCase):
    def test_foreign_or_inaccessible_tasks_refuse_install_and_uninstall(self):
        for kind in ('foreign', 'denied'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                state = {'query': {'kind': kind}}
                calls = []
                obj = _backend(state, calls)
                with self.assertRaises(backend._tasks.OwnershipError):
                    _install(obj, Path(tmp))
                with self.assertRaises(backend._tasks.OwnershipError):
                    obj.uninstall(Path(tmp))
                self.assertFalse({'stop', 'delete', 'disable'} & set(_verbs(calls)))


class ExplicitStopTests(_CurrentInstallerFixture, unittest.TestCase):
    def test_pending_updaters_preserve_stop_until_explicit_restart_and_health(self):
        for pending in (backend.UPDATE_TASK, backend.EXPRESS_TASK):
            for stuck in (False, True):
                with self.subTest(pending=pending, stuck=stuck), tempfile.TemporaryDirectory() as tmp:
                    home, calls = self._home(tmp), []
                    tasks = {'query': _query(4), 'stuck': stuck,
                             backend.UPDATE_TASK: _query(1), backend.EXPRESS_TASK: _query(1)}
                    tasks[pending]['pending'] = True
                    obj = _backend(tasks, calls)
                    clock = SimpleNamespace(monotonic=iter((0, 11)).__next__)
                    with mock.patch.object(backend, 'time', clock):
                        if stuck:
                            with self.assertRaisesRegex(SystemExit, 'did not exit'):
                                obj.stop(home)
                        else:
                            obj.stop(home)
                    self.assertFalse(tasks['query']['enabled'])
                    self.assertFalse(tasks['query']['pending'])
                    self.assertEqual(bool(tasks['query']['instances']), stuck)
                    before = {name: dict(tasks[name]) for name in ('query', backend.UPDATE_TASK, backend.EXPRESS_TASK)}
                    calls.clear()
                    self.assertEqual(self._run(home, tasks, calls)[0], 0)
                    self.assertTrue(all(call['operation'] == 'query' for call in calls))
                    self.assertEqual({name: tasks[name] for name in before}, before)
                    self.assertTrue(tasks[pending]['pending'])
                    tasks['stuck'] = False
                    with mock.patch.object(service, 'health', return_value={'version': '1.0.0'}), \
                            mock.patch.object(backend, '_post_shutdown',
                                              side_effect=lambda _: tasks['query'].update(instances=[])):
                        _backend(tasks, []).restart(home)
                    self.assertTrue(tasks['query']['enabled'])
                    self.assertTrue(tasks[pending]['pending'])
                    self.assertEqual(self._run(home, tasks, [])[0], 0)
                    self.assertTrue(tasks[pending]['enabled'])
                    self.assertFalse(tasks[pending]['pending'])
                    other = backend.EXPRESS_TASK if pending == backend.UPDATE_TASK else backend.UPDATE_TASK
                    self.assertFalse(tasks[other]['enabled'])


@unittest.skipUnless(sys.platform == 'win32', 'requires the real Windows Task Scheduler')
class NativeTaskTests(unittest.TestCase):
    def test_real_ownership_instances_and_parent_survival(self):
        obj = backend.Backend(service, subprocess.run)
        sid = obj._identity()
        name = 'SCG-CI-' + uuid.uuid4().hex + '-' + sid
        with tempfile.TemporaryDirectory(prefix='router é & [] $ ') as tmp:
            home = Path(tmp)
            _state_file(home)
            gate = home / 'gate'
            gate.touch()
            service.install_task_launcher(home, Path(__file__).resolve().parents[1])
            (home / 'router_launch.py').write_text(
                'import time\nfrom pathlib import Path\n'
                'home = Path(__file__).parent\nend = time.monotonic() + 40\n'
                'while (home / "gate").exists() and time.monotonic() < end:\n'
                '    (home / "alive").write_text(str(time.monotonic()))\n'
                '    time.sleep(0.1)\n', encoding='utf-8')
            arguments = backend._arguments(home, 'router_launch.py', backend.ROUTER_LOG)
            xml = backend.render_router_xml(sys.executable, home, sid).replace(
                '<Settings>', '<Settings><Hidden>true</Hidden>')
            def call(operation='query', **changes):
                return backend._tasks.invoke(obj._call, changes.get('sid', sid), name,
                                             changes.get('arguments', arguments), operation, xml)
            def wait_running():
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    result = call()
                    if result and result['instances'] and (home / 'alive').exists():
                        return result
                    time.sleep(0.2)
                self.fail('disposable task did not start')
            try:
                self.assertIsNone(call())
                self.assertEqual(call('register')['state'], 1)
                self.assertEqual(call('register')['state'], 1)
                self.assertFalse(call()['enabled'])
                self.assertTrue(call()['pending'])  # Every call starts a fresh PowerShell process.
                for changes in ({'sid': 'S-1-5-18'}, {'arguments': arguments + ' foreign'}):
                    for operation in ('register', 'handover', 'run', 'complete', 'enable', 'disable', 'stop', 'delete'):
                        with self.assertRaises(backend._tasks.OwnershipError):
                            call(operation, **changes)
                self.assertIn(call('enable')['state'], (2, 3, 4))
                self.assertTrue(call()['enabled'])
                self.assertFalse(call()['pending'])
                call('run')
                original = wait_running()['instances']
                call('register')
                self.assertTrue(set(original) & set(call()['instances']))
                with mock.patch.object(backend, 'ROUTER_TASK', name), \
                        mock.patch.object(backend, '_post_shutdown', return_value=False), \
                        mock.patch.object(backend, 'DRAIN_TIMEOUT_S', 0):
                    call('stop')
                    self.assertTrue(obj._wait_stopped(name, 10, home))
                    self.assertEqual(call()['state'], 3)  # Refresh preserved Enabled, not just instances.
                    call('disable')
                    self.assertEqual(call('register')['state'], 1)
                    self.assertFalse(call()['pending'])  # Deliberately disabled; never pending again.
                    call('run')
                    original = wait_running()['instances']
                    # Only health is simulated; marker and instance transitions use the real API.
                    with mock.patch.object(service, 'wait_version', return_value=False):
                        with self.assertRaisesRegex(SystemExit, '0.0.0'):
                            obj.restart(home)
                    self.assertTrue(call()['pending'])
                    self.assertTrue(call('run')['pending'])  # Run cannot acknowledge health.
                    with mock.patch.object(service, 'wait_version', return_value=True):
                        obj.restart(home)
                    self.assertFalse(call()['pending'])
                self.assertTrue(set(original).isdisjoint(wait_running()['instances']))
                call('handover')
                self.assertTrue(call()['pending'])
                self.assertFalse(call()['enabled'])
                self.assertTrue(call()['instances'])  # Disabled is independent of an active invocation.
                call('disable')  # An explicit stop cancels pending recovery.
                self.assertFalse(call()['pending'])
                call('run')
                # An erased definition cannot prove that its process exited.
                before = (home / 'alive').read_text()
                call('delete')
                time.sleep(0.3)
                self.assertNotEqual((home / 'alive').read_text(), before)
                for operation in ('query', 'register'):
                    with self.assertRaises(SystemExit):
                        call(operation)
                gate.unlink()
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    try:
                        self.assertIsNone(call())
                        break
                    except SystemExit:
                        pass
                    time.sleep(0.2)
                self.assertIsNone(call())
                call('register')
                # Matching home arguments cannot make a different executable ours.
                foreign = xml.replace(backend._pythonw(sys.executable), os.environ['COMSPEC'])
                replace = r'''
$ErrorActionPreference = 'Stop'
$r = [Console]::In.ReadToEnd() | ConvertFrom-Json
$s = New-Object -ComObject Schedule.Service; $s.Connect()
$d = $s.NewTask(0); $d.XmlText = $r.xml; $d.Settings.Enabled = $false
$null = $s.GetFolder('\').RegisterTaskDefinition($r.name, $d, 4, $r.sid, $null, 3, $null)
'''
                obj._call(['powershell', '-NoProfile', '-NonInteractive', '-Command', replace],
                          input=json.dumps(dict(name=name, sid=sid, xml=foreign)), text=True,
                          capture_output=True, timeout=20, check=True)
                for operation in ('query', 'register', 'handover', 'run', 'complete', 'stop', 'delete'):
                    with self.assertRaises(backend._tasks.OwnershipError):
                        call(operation)
            finally:
                gate.unlink(missing_ok=True)
                # Independent cleanup also works if the implementation under test fails.
                cleanup = r'''
$ErrorActionPreference = 'Stop'
$r = [Console]::In.ReadToEnd() | ConvertFrom-Json
$s = New-Object -ComObject Schedule.Service; $s.Connect()
foreach ($i in $s.GetRunningTasks(1)) { if ($i.Path -eq ('\' + $r.name)) { $i.Stop() } }
try { $s.GetFolder('\').DeleteTask($r.name, 0) } catch {
    if ($_.Exception.GetBaseException().HResult -ne -2147024894) { throw }
}
'''
                obj._call(['powershell', '-NoProfile', '-NonInteractive', '-Command', cleanup],
                          input=json.dumps({'name': name}), text=True, capture_output=True,
                          timeout=20, check=True)
