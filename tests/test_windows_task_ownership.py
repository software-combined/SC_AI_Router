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
from tests.windows_native_fixture import NativeChild, cleanup, write_launcher


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
        base = 'SCG-CI-' + uuid.uuid4().hex
        name = base + '-' + sid
        with tempfile.TemporaryDirectory(prefix='router é & [] $ ') as tmp:
            home = Path(tmp)
            _state_file(home)
            children = []
            gate, heartbeat = write_launcher(home, 'router_launch.py', 40)
            service.install_task_launcher(home, Path(__file__).resolve().parents[1])
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
                    if result and result['instances'] and heartbeat.exists():
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
                with mock.patch.object(backend, 'ROUTER_TASK', base), \
                        mock.patch.object(backend, '_post_shutdown', return_value=False), \
                        mock.patch.object(backend, 'DRAIN_TIMEOUT_S', 0):
                    call('stop')
                    self.assertTrue(obj._wait_stopped(base, 10, home))
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
                # Start this phase with a fresh, bounded child, not an aging heartbeat.
                call('stop')
                with mock.patch.object(backend, 'ROUTER_TASK', base):
                    self.assertTrue(obj._wait_stopped(base, 10, home))
                    heartbeat.unlink(missing_ok=True)
                    call('run')
                    wait_running()
                    child = NativeChild.capture(heartbeat)
                    children.append(child)
                    child.assert_alive('before-delete')
                    call('delete')
                    child.assert_alive('before-metadata-check')
                    # Deletion need not retain Scheduler metadata. Missing data cannot prove exit.
                    with self.assertRaisesRegex(SystemExit, 'exit is unverified|cannot verify Windows task') as refused:
                        obj._wait_stopped(base, 0, home)
                    reason = 'missing' if 'disappeared' in str(refused.exception) else 'unverified'
                    print('Windows fixture metadata refusal: ' + reason, flush=True)
                    child.assert_alive('after-metadata-refusal')
                gate.unlink()
                self.assertTrue(child.wait_exit(15), 'the deleted task child did not exit')
                print('Windows fixture deleted child: exited=True', flush=True)
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
                cleanup(obj._call, [name], children)

    def test_native_migration_keeps_parent_until_exit_and_preserves_disabled_schedule(self):
        obj = backend.Backend(service, subprocess.run)
        sid = obj._identity()
        prefix = 'SCG-CI-' + uuid.uuid4().hex
        names = [prefix + suffix for suffix in ('', '-Update', '-Express')]
        with tempfile.TemporaryDirectory(prefix='router migration ') as tmp, \
                mock.patch.multiple(backend, ROUTER_TASK=names[0], UPDATE_TASK=names[1],
                                    EXPRESS_TASK=names[2], DRAIN_TIMEOUT_S=0), \
                mock.patch.object(backend, '_post_shutdown', return_value=False):
            home = Path(tmp)
            _state_file(home)
            children = []
            for script in ('router_launch.py', 'update_launch.py', 'express_launch.py'):
                # Fresh PowerShell processes can make the migration exceed three minutes.
                write_launcher(home, script, 600)
            service.install_task_launcher(home, Path(__file__).resolve().parents[1])
            def task(name, operation='query', **kwargs):
                return obj._task_state(name, home, operation, **kwargs)
            def running(name, legacy=False):
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    result = task(name, legacy=legacy)
                    if result and result['instances']:
                        return result
                    time.sleep(0.2)
                self.fail('disposable migration task did not start')
            try:
                renderers = (backend.render_router_xml, backend.render_update_xml, backend.render_express_xml)
                for index, name in enumerate(names):
                    args = (sys.executable, home, sid) if index == 0 else (sys.executable, home)
                    task(name, 'register', legacy=True, xml=renderers[index](*args))
                    if index != 2:
                        task(name, 'run', legacy=True)
                        running(name, legacy=True)
                        task(name, 'complete', legacy=True)
                router = task(names[0], legacy=True)['instances']
                parent = task(names[1], 'disable', legacy=True)['instances']
                parent_child = NativeChild.capture(home / 'update_launch.alive')
                children.append(parent_child)
                parent_child.assert_alive('before-migration')
                run = obj._run
                def failed_registration(cmd, **kwargs):
                    request = json.loads(kwargs.get('input', '{}'))
                    if request.get('name') == names[2] + '-' + sid and request['operation'] == 'register':
                        request['xml'] = '<Task>'  # The real Scheduler API must reject this definition.
                        kwargs['input'] = json.dumps(request)
                    return run(cmd, **kwargs)
                obj._run = failed_registration
                with self.assertRaises(SystemExit):
                    obj.install(sys.executable, home, {}, Path(__file__).resolve().parents[1], None)
                obj._run = run
                self.assertEqual(task(names[0], legacy=True)['instances'], router)
                self.assertEqual(task(names[1], legacy=True)['instances'], parent)
                def healthy(state, version):
                    self.assertEqual(version, '1.0.0')
                    running(names[0])
                    return True  # Native API proof; HTTP health is the external test boundary.
                with mock.patch.object(service, 'wait_version', side_effect=healthy), \
                        mock.patch.object(service, 'health', return_value={'version': '1.0.0'}):
                    obj.install(sys.executable, home, {}, Path(__file__).resolve().parents[1],
                                None, expected_version='1.0.0')
                    self.assertFalse(task(names[1])['enabled'])
                    self.assertFalse(task(names[1])['pending'])
                    self.assertTrue(task(names[2])['enabled'])
                    self.assertFalse(task(names[2])['pending'])
                    parent_child.assert_alive('after-migration')
                    self.assertFalse(task(names[1], legacy=True)['enabled'])
                    self.assertEqual(task(names[1], legacy=True)['instances'], parent)
                    heartbeat = home / 'update_launch.alive'
                    before = heartbeat.read_text()
                    time.sleep(0.3)
                    self.assertNotEqual(heartbeat.read_text(), before)
                    self.assertTrue(obj.ensure_serving(home, {}, '1.0.0'))
                    (home / 'update_launch.gate').unlink()
                    self.assertTrue(obj._wait_stopped(names[1], 15, home, legacy=True))
                    obj.recover_pending(sys.executable, home, Path(__file__).resolve().parents[1], '1.0.0')
                    self.assertIsNone(task(names[1], legacy=True))
                    self.assertFalse(task(names[1])['enabled'])
            finally:
                obj._run = subprocess.run
                for gate in home.glob('*.gate'):
                    gate.unlink(missing_ok=True)
                cleanup(obj._call, names + [name + '-' + sid for name in names], children)
