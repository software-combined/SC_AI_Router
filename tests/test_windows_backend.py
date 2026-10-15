"""Plan 116 Stage 3: Windows Task Scheduler backend, proven offline against a
fake structured Task Scheduler API. Pins real-machine facts: a repeating
trigger needs a StartBoundary, an unscoped logon trigger needs elevation,
deleting a task leaves its instance running, console tasks show a window."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        'router_windows_backend_stage3_under_test',
        ROOT / 'packaging' / 'platforms' / 'windows.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


backend = _load()


def _load_service():
    spec = importlib.util.spec_from_file_location(
        'router_service_for_windows_backend', ROOT / 'packaging' / 'service.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


service = _load_service()
PY = 'C:\\Python314\\python.exe'
USER = 'S-1-5-21-1-2-3-1001'


def _query(status):
    return dict(kind='present', state=status, enabled=status != 1, pending=False,
                instances=['instance'] if status == 4 else [])


QUERY_READY = _query(3)
QUERY_RUNNING = _query(4)
QUERY_DISABLED = _query(1)


def _fake_run(state=None, calls=None, fail=(), end_fails=False):
    """The external JSON boundary; all process and registration state is local."""
    state = state if state is not None else {}
    state.setdefault('query', QUERY_READY)
    state.setdefault('missing', set())

    def run(cmd, **kwargs):
        request = json.loads(kwargs['input'])
        if 'path' in request:
            return SimpleNamespace(returncode=0, stdout=json.dumps({'user': USER}))
        (calls if calls is not None else []).append(request)
        name, operation = request['name'], request['operation']
        failed_once = (name, operation) == state.get('fail_once')
        if failed_once:
            state.pop('fail_once')
        if (name in fail or failed_once or operation == state.get('fail_operation')
                or (operation == 'stop' and end_fails)):
            return SimpleNamespace(returncode=1, stdout='', stderr='denied')
        key = 'query' if name == backend.ROUTER_TASK else name
        doc = {'kind': 'missing'} if name in state['missing'] else dict(state.get(key, QUERY_READY))
        if doc['kind'] in ('foreign', 'denied'):
            return SimpleNamespace(returncode=0, stdout=json.dumps(doc), stderr='')
        created = doc['kind'] == 'missing'
        if operation == 'register':
            state['xml_' + name] = request['xml']
            state['missing'].discard(name)
            doc = _query(1) if created else doc
            doc['pending'] = created or doc['pending']
        if doc['kind'] == 'present':
            if operation in ('handover', 'enable', 'disable', 'complete'):
                doc['pending'] = operation == 'handover'
            if operation in ('enable', 'disable', 'run', 'handover'):
                doc['enabled'] = operation not in ('disable', 'handover') and not state.get('policy_disabled', False)
            if operation == 'run' and doc['enabled']:
                doc['instances'] = ['instance']
            if operation == 'stop' and not state.get('stuck'):
                doc['instances'] = []
            doc['state'] = 4 if doc['instances'] else (3 if doc['enabled'] else 1)
            if operation == 'delete':
                doc = {'kind': 'missing'}
            state[key] = doc
        return SimpleNamespace(returncode=0, stdout=json.dumps(doc), stderr='')
    return run


def _backend(state=None, calls=None, fail=(), end_fails=False):
    obj = backend.Backend(service, _fake_run(state, calls, fail, end_fails))
    obj._sleep = lambda seconds: None
    return obj


def _verbs(calls):
    return [c['operation'] for c in calls]


def _install(obj, home):
    home.mkdir(parents=True, exist_ok=True)  # the installer creates it first
    with mock.patch.object(service, 'wait_version', return_value=True):
        obj.install(PY, home, {}, ROOT, None)


def _state_file(home):
    Path(home).mkdir(parents=True, exist_ok=True)
    (Path(home) / 'mixed-router-state.json').write_text('{"port": 1, "token": "t"}')


_ROUTER_FRAGMENTS = ('<LogonType>InteractiveToken</LogonType>',
                     '<RunLevel>LeastPrivilege</RunLevel>',
                     # Scoped to the installing user: unscoped needs elevation.
                     '<LogonTrigger><UserId>' + USER + '</UserId>',
                     '<Interval>PT1M</Interval>',
                     '<StartBoundary>',
                     '<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>',
                     '<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>',
                     '<DisallowStartIfOnBatteries>false',
                     '<StopIfGoingOnBatteries>false')


class RouterXmlTests(unittest.TestCase):
    def test_router_task_is_interactive_logon_with_recovery_trigger(self):
        xml = backend.render_router_xml(PY, 'C:\\home', USER)
        for fragment in _ROUTER_FRAGMENTS:
            self.assertIn(fragment, xml)

    def test_router_xml_refuses_an_unknown_installing_user(self):
        with self.assertRaisesRegex(SystemExit, 'installing user'):
            backend.render_router_xml(PY, 'C:\\home', '')

    def test_every_repeating_trigger_carries_a_start_boundary(self):
        # Task Scheduler refuses a repetition without one at registration.
        for xml in (backend.render_router_xml(PY, 'C:\\home', USER),
                    backend.render_update_xml(PY, 'C:\\home')):
            self.assertEqual(xml.count('<Repetition>'), xml.count('<StartBoundary>'))

    def test_both_tasks_run_console_free_through_the_task_launcher(self):
        router = backend.render_router_xml(PY, 'C:\\home', USER)
        update = backend.render_update_xml(PY, 'C:\\home')
        for xml, log, script in ((router, 'launchd.log', 'router_launch.py'),
                                 (update, 'update.log', 'update_launch.py')):
            self.assertIn('<Command>C:\\Python314\\pythonw.exe</Command>', xml)
            self.assertNotIn('python.exe</Command>', xml)
            self.assertIn('<Arguments>C:\\home\\task_launch.py %s %s</Arguments>'
                          % (log, script), xml)
        self.assertIn('<Interval>PT4H</Interval>', update)
        self.assertIn('<ExecutionTimeLimit>PT30M</ExecutionTimeLimit>', update)

    def test_paths_with_spaces_are_quoted_and_xml_escaped(self):
        home = 'C:\\Users\\Some One\\router home'
        xml = backend.render_router_xml('C:\\Program Files\\Python\\python.exe', home, USER)
        self.assertIn('<Command>C:\\Program Files\\Python\\pythonw.exe</Command>', xml)
        self.assertIn('<Arguments>&quot;C:\\Users\\Some One\\router home\\task_launch.py&quot;', xml)


class TaskLauncherTests(unittest.TestCase):
    def _run(self, home, log='update.log'):
        service.install_task_launcher(home, ROOT)
        return subprocess.run([sys.executable, str(home / backend.TASK_LAUNCHER),
                               log, 'update_launch.py'],
                              capture_output=True, text=True)

    def test_launcher_routes_stdout_and_stderr_to_the_home_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'update_launch.py').write_text(
                "import sys\nprint('out', sys.argv[1])\n"
                "sys.stderr.write('err\\n')\nraise SystemExit('boom')\n")
            result = self._run(home)
            self.assertEqual(result.returncode, 1)
            text = (home / 'logs' / 'update.log').read_text()
            self.assertIn('out --home=%s' % home, text)
            self.assertIn('err', text)
            self.assertIn('boom', text)

    def test_launcher_rotates_an_oversized_log_before_appending(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'update_launch.py').write_text("print('fresh')\n")
            logs = home / 'logs'
            logs.mkdir()
            (logs / 'update.log').write_bytes(b'x' * (1048576 + 1))
            self.assertEqual(self._run(home).returncode, 0)
            self.assertTrue((logs / 'update.log.1').exists())
            self.assertEqual((logs / 'update.log').read_text().strip(), 'fresh')

    def test_launcher_still_starts_when_rotation_is_refused(self):
        # A held-open or otherwise unrenamable log is hygiene lost, never a
        # router that fails to boot with nothing written anywhere.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'update_launch.py').write_text("print('started')\n")
            logs = home / 'logs'
            logs.mkdir()
            (logs / 'update.log').write_bytes(b'x' * (1048576 + 1))
            (logs / 'update.log.1').mkdir()  # os.replace onto a directory fails
            self.assertEqual(self._run(home).returncode, 0)
            self.assertIn(b'started', (logs / 'update.log').read_bytes()[-16:])


class InstallTests(unittest.TestCase):
    def test_repair_keeps_the_installed_launcher_when_the_release_lacks_it(self):
        # A repair run can name a release that predates the packaged
        # launcher; the home copy is then already the right file.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            installed = home / 'task_launch.py'
            installed.write_text('from the previous install\n')
            service.install_task_launcher(home, Path(tmp) / 'older-release')
            self.assertEqual(installed.read_text(), 'from the previous install\n')
            service.install_task_launcher(home, None)  # no release named
            self.assertEqual(installed.read_text(), 'from the previous install\n')
            # Neither a packaged member nor an installed copy: fail closed.
            installed.unlink()
            with self.assertRaisesRegex(SystemExit, 'task_launch.py'):
                service.install_task_launcher(home, None)
            with self.assertRaisesRegex(SystemExit, 'task_launch.py'):
                service.install_task_launcher(home, Path(tmp) / 'older-release')

    def test_fresh_install_writes_launcher_registers_runs_and_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            state, calls = {'missing': {backend.ROUTER_TASK, backend.UPDATE_TASK,
                                       backend.EXPRESS_TASK}}, []
            with mock.patch.object(backend, '_post_shutdown') as shutdown:
                _install(_backend(state, calls), home)
            # This fixture has no state file, so there is nothing to address a
            # drain to. A real fresh install does post /shutdown, to a port
            # nothing serves yet; the connection is refused and ignored.
            shutdown.assert_not_called()
            self.assertEqual((home / 'task_launch.py').read_text(encoding='utf-8'),
                             (ROOT / 'packaging' / 'task_launch.py'
                              ).read_text(encoding='utf-8'))
            self.assertIn('<UserId>' + USER + '</UserId>', state['xml_CodexMixedModelRouter'])
            self.assertIn('xml_CodexMixedModelRouterUpdate', state)
            self.assertTrue(state[backend.UPDATE_TASK]['enabled'])
            for verb in ('register', 'run', 'query'):
                self.assertIn(verb, _verbs(calls))
            self.assertNotIn('stop', _verbs(calls))
            created = [c for c in calls if c['operation'] == 'register']
            self.assertEqual(len(created), 2)
            self.assertTrue(all(c['sid'] == USER for c in created))
            self.assertTrue(all(str(home) in c['arguments'] for c in created))

    def test_upgrade_drains_the_running_router_before_running_the_task(self):
        # IgnoreNew makes /run a no-op while the old release is serving, so
        # the handover must ask it to leave first and wait until it has.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _state_file(home)
            state, calls = {'query': QUERY_RUNNING}, []

            def shutdown(router_state):
                self.assertEqual(router_state['token'], 't')
                state['query']['instances'] = []
                return True
            with mock.patch.object(backend, '_post_shutdown', side_effect=shutdown) as posted:
                _install(_backend(state, calls), home)
            posted.assert_called_once()
            verbs = _verbs(calls)
            self.assertNotIn('stop', verbs)
            self.assertLess(verbs.index('register'), verbs.index('run'))
            self.assertEqual(state['query'], QUERY_RUNNING)

    def test_drain_is_posted_even_when_the_task_is_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            _state_file(tmp)
            with mock.patch.object(backend, '_post_shutdown', return_value=True) as posted, \
                    mock.patch.object(service, 'wait_version', return_value=True):
                _backend({'query': QUERY_READY}).restart(Path(tmp))
            posted.assert_called_once()

    def test_task_state_is_independent_of_http_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _state_file(home)
            obj = _backend({'query': QUERY_RUNNING})
            with mock.patch.object(service, 'health',
                                   return_value={'status': 'ok'}):
                self.assertTrue(obj._running('CodexMixedModelRouter', home))
            with mock.patch.object(service, 'health', return_value=None):
                self.assertTrue(obj._running('CodexMixedModelRouter', home))

    def test_explicit_creation_flags_survive_the_windowless_default(self):
        seen = []

        def run(cmd, **kwargs):
            seen.append(kwargs)
            return SimpleNamespace(returncode=0)

        obj = backend.Backend(service, run)
        obj._call(['whoami'], creationflags=1234)
        self.assertEqual(seen[0].get('creationflags'), 1234)
        obj._call(['whoami'])
        self.assertEqual(seen[1].get('creationflags'),
                         backend._NO_WINDOW['creationflags'])

    def test_launcher_refuses_a_bare_invocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            service.install_task_launcher(home, ROOT)
            launcher = home / backend.TASK_LAUNCHER
            result = subprocess.run([sys.executable, str(launcher)],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('LOG and SCRIPT', result.stderr)

    def test_hung_router_is_ended_only_after_the_drain_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            _state_file(tmp)
            state, calls = {'query': QUERY_RUNNING}, []
            with mock.patch.object(backend, '_post_shutdown', return_value=False), \
                    mock.patch.object(service, 'wait_version', return_value=True), \
                    mock.patch.object(backend, 'DRAIN_TIMEOUT_S', 0):
                _backend(state, calls).restart(Path(tmp))
            verbs = _verbs(calls)
            self.assertIn('stop', verbs)
            self.assertLess(verbs.index('stop'), verbs.index('run'))

    def test_install_reports_unregistered_task_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SystemExit, 'CodexMixedModelRouter'):
                _install(_backend(fail=('CodexMixedModelRouter',)), Path(tmp) / 'home')

    def test_install_refuses_policy_disabled_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SystemExit, 'disabled by policy'):
                _install(_backend({'query': QUERY_DISABLED, 'policy_disabled': True}), Path(tmp) / 'home')

    def test_every_console_child_is_spawned_windowless(self):
        seen = []
        fake = _fake_run()

        def run(cmd, **kwargs):
            seen.append(kwargs.get('creationflags'))
            return fake(cmd, **kwargs)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(service, 'wait_version', return_value=True):
            backend.Backend(service, run).install(PY, Path(tmp), {}, ROOT, None)
        self.assertTrue(seen)
        self.assertTrue(all(flag == backend._NO_WINDOW['creationflags'] for flag in seen))


class ControlTests(unittest.TestCase):
    def test_stop_ends_the_router_task(self):
        calls = []
        _backend({}, calls).stop('/home/x')
        self.assertEqual([c['name'] for c in calls if c['operation'] == 'stop'],
                         [backend.ROUTER_TASK])

    def test_stop_tolerates_only_a_task_that_was_never_registered(self):
        calls = []
        _backend({'missing': {backend.ROUTER_TASK}}, calls, end_fails=True).stop('/home/x')
        self.assertNotIn('stop', _verbs(calls))
        with self.assertRaisesRegex(SystemExit, 'CodexMixedModelRouter'):
            _backend({'query': QUERY_RUNNING}, end_fails=True).stop('/home/x')

    def test_restart_without_state_refuses_before_quiescing(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            with self.assertRaises(OSError):
                _backend({}, calls).restart(Path(tmp) / 'nostate')
            self.assertEqual(calls, [])

    def test_uninstall_ends_each_task_before_deleting_it(self):
        # /delete leaves a running instance alive: end first, or the old
        # router keeps serving until sign-out.
        calls = []
        _backend({}, calls).uninstall('/home/x')
        deleted = [c['name'] for c in calls if c['operation'] == 'delete']
        self.assertEqual(deleted, [backend.ROUTER_TASK, backend.UPDATE_TASK, backend.EXPRESS_TASK])
        for task in deleted:
            operations = [c['operation'] for c in calls if c['name'] == task]
            self.assertLess(operations.index('disable'), operations.index('delete'))
            if task != backend.ROUTER_TASK:
                self.assertLess(operations.index('stop'), operations.index('delete'))

    def test_uninstall_drains_a_serving_router_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            _state_file(tmp)
            state = {'query': QUERY_RUNNING}

            def shutdown(router_state):
                state['query']['instances'] = []
                return True
            with mock.patch.object(backend, '_post_shutdown', side_effect=shutdown) as posted:
                _backend(state).uninstall(Path(tmp))
            posted.assert_called_once()

    def test_uninstall_ends_a_router_still_running_after_its_drain_deadline(self):
        # The destructive branch: the drain is attempted first, the bounded
        # wait expires, and only then is the instance ended and deleted.
        with tempfile.TemporaryDirectory() as tmp:
            _state_file(tmp)
            state, calls = {'query': QUERY_RUNNING}, []
            with mock.patch.object(backend, '_post_shutdown', return_value=False) as posted, \
                    mock.patch.object(backend, 'UNINSTALL_DRAIN_S', 0):
                _backend(state, calls).uninstall(Path(tmp))
            posted.assert_called_once()
            verbs = _verbs(calls)
            self.assertLess(verbs.index('query'), verbs.index('stop'))
            self.assertLess(verbs.index('stop'), verbs.index('delete'))


if __name__ == '__main__':
    unittest.main()
