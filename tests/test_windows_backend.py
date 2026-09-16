"""Plan 116 Stage 3: Windows Task Scheduler backend, proven offline against a
fake schtasks. Pins real-machine facts (Windows 11, 2026-09-10): a repeating
trigger needs a StartBoundary, an unscoped logon trigger needs elevation,
deleting a task leaves its instance running, console tasks show a window."""
import importlib.util
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
USER = 'CORP\\cyril'


def _query(status):
    return ('TaskName: \\CodexMixedModelRouter\nStatus: %s\n' % status)


QUERY_READY = _query('Ready')
QUERY_RUNNING = _query('Running')
QUERY_DISABLED = _query('Disabled')
QUERY_LOCALISED = 'Taaknaam: \\CodexMixedModelRouter\nStatus: Wordt uitgevoerd\n'


def _fake_run(state=None, calls=None, fail=(), end_fails=False):
    """schtasks/whoami stand-in; state['query'] is the /query readback."""
    state = state if state is not None else {}
    state.setdefault('query', QUERY_READY)
    ok = lambda: SimpleNamespace(returncode=0, stdout='SUCCESS', stderr='')  # noqa: E731

    def run(cmd, **kwargs):
        (calls if calls is not None else []).append(list(cmd))
        if cmd[:1] == ['whoami']:
            return SimpleNamespace(returncode=0, stdout=USER + '\n', stderr='')
        if cmd[:2] == ['schtasks', '/create']:
            xml_path = Path(cmd[cmd.index('/xml') + 1])
            state['xml_' + cmd[cmd.index('/tn') + 1]] = xml_path.read_text(
                encoding='utf-16')
            return ok()
        if cmd[:2] == ['schtasks', '/query']:
            if cmd[cmd.index('/tn') + 1] in fail:
                return SimpleNamespace(returncode=1, stdout='', stderr='not found')
            return SimpleNamespace(returncode=0, stdout=state['query'], stderr='')
        if cmd[:2] == ['schtasks', '/run']:
            if state['query'] != QUERY_DISABLED:  # /run cannot start a disabled task
                state['query'] = QUERY_RUNNING
            return ok()
        if cmd[:2] == ['schtasks', '/end']:
            if end_fails:
                return SimpleNamespace(returncode=1, stdout='', stderr='nope')
            if not state.get('stuck'):
                state['query'] = QUERY_READY
            return ok()
        if cmd[:2] == ['schtasks', '/delete']:
            return ok()
        raise AssertionError('unexpected command: %r' % (cmd,))
    return run


def _backend(state=None, calls=None, fail=(), end_fails=False):
    obj = backend.Backend(service, _fake_run(state, calls, fail, end_fails))
    obj._sleep = lambda seconds: None
    return obj


def _verbs(calls):
    return [c[1] for c in calls if c[:1] == ['schtasks']]


def _install(obj, home):
    home.mkdir(parents=True, exist_ok=True)  # the installer creates it first
    obj.install(PY, home, {}, ROOT, None)


def _state_file(home):
    Path(home).mkdir(parents=True, exist_ok=True)
    (Path(home) / 'mixed-router-state.json').write_text('{"port": 1, "token": "t"}')


_ROUTER_FRAGMENTS = ('<LogonType>InteractiveToken</LogonType>',
                     '<RunLevel>LeastPrivilege</RunLevel>',
                     # Scoped to the installing user: unscoped needs elevation.
                     '<LogonTrigger><UserId>CORP\\cyril</UserId>',
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
            state, calls = {}, []
            with mock.patch.object(backend, '_post_shutdown') as shutdown:
                _install(_backend(state, calls), home)
            # This fixture has no state file, so there is nothing to address a
            # drain to. A real fresh install does post /shutdown, to a port
            # nothing serves yet; the connection is refused and ignored.
            shutdown.assert_not_called()
            self.assertEqual((home / 'task_launch.py').read_text(encoding='utf-8'),
                             (ROOT / 'packaging' / 'task_launch.py'
                              ).read_text(encoding='utf-8'))
            self.assertIn('<UserId>CORP\\cyril</UserId>', state['xml_CodexMixedModelRouter'])
            self.assertIn('xml_CodexMixedModelRouterUpdate', state)
            for verb in ('/create', '/run', '/query'):
                self.assertIn(verb, _verbs(calls))
            self.assertNotIn('/end', _verbs(calls))
            created = [c for c in calls if c[:2] == ['schtasks', '/create']]
            self.assertEqual(len(created), 2)
            self.assertTrue(all(c[c.index('/xml') + 1].startswith(str(home))
                                for c in created))

    def test_upgrade_drains_the_running_router_before_running_the_task(self):
        # IgnoreNew makes /run a no-op while the old release is serving, so
        # the handover must ask it to leave first and wait until it has.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _state_file(home)
            state, calls = {'query': QUERY_RUNNING}, []

            def shutdown(router_state):
                self.assertEqual(router_state['token'], 't')
                state['query'] = QUERY_READY
                return True
            with mock.patch.object(backend, '_post_shutdown', side_effect=shutdown) as posted:
                _install(_backend(state, calls), home)
            posted.assert_called_once()
            verbs = _verbs(calls)
            self.assertNotIn('/end', verbs)
            self.assertLess(verbs.index('/create'), verbs.index('/run'))
            self.assertEqual(state['query'], QUERY_RUNNING)

    def test_drain_is_posted_even_when_the_status_readback_is_localised(self):
        # A non-English Status line reads as "not running"; the drain must
        # not depend on it or the old release keeps serving after /run.
        with tempfile.TemporaryDirectory() as tmp:
            _state_file(tmp)
            with mock.patch.object(backend, '_post_shutdown', return_value=True) as posted:
                _backend({'query': QUERY_LOCALISED}).restart(Path(tmp))
            posted.assert_called_once()

    def test_localised_status_falls_back_to_the_health_probe(self):
        # Non-English Status must not read a serving router as stopped.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _state_file(home)
            obj = _backend({'query': QUERY_LOCALISED})
            with mock.patch.object(service, 'health',
                                   return_value={'status': 'ok'}):
                self.assertTrue(obj._running('CodexMixedModelRouter', home))
            with mock.patch.object(service, 'health', return_value=None):
                self.assertFalse(obj._running('CodexMixedModelRouter', home))

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
            state, calls = {'query': QUERY_RUNNING}, []
            with mock.patch.object(backend, '_post_shutdown', return_value=False), \
                    mock.patch.object(backend, 'DRAIN_TIMEOUT_S', 0):
                _backend(state, calls).restart(Path(tmp))
            verbs = _verbs(calls)
            self.assertIn('/end', verbs)
            self.assertLess(verbs.index('/end'), verbs.index('/run'))

    def test_install_reports_unregistered_task_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SystemExit, 'CodexMixedModelRouter'):
                _install(_backend(fail=('CodexMixedModelRouter',)), Path(tmp) / 'home')

    def test_install_refuses_policy_disabled_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SystemExit, 'disabled by policy'):
                _install(_backend({'query': QUERY_DISABLED}), Path(tmp) / 'home')

    def test_registration_failure_names_the_task(self):
        def run(cmd, **kwargs):
            if cmd[:2] == ['schtasks', '/create']:
                return SimpleNamespace(returncode=1, stdout='', stderr='Access is denied.')
            return SimpleNamespace(returncode=0, stdout=USER, stderr='')
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SystemExit, 'CodexMixedModelRouter'):
                _install(backend.Backend(service, run), Path(tmp) / 'home')

    def test_registration_recovers_from_a_cross_principal_denied_create(self):
        # A task first registered under a different principal (e.g. a local
        # account) is "Access is denied" to `/create /f` from this token. The
        # backend must delete the stale task, then re-create so it lands under
        # the current principal. First /create per task is denied, the delete
        # clears it, the retry succeeds.
        calls, denied = [], set()

        def run(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[:1] == ['whoami']:
                return SimpleNamespace(returncode=0, stdout=USER + '\n', stderr='')
            if cmd[:2] == ['schtasks', '/create']:
                name = cmd[cmd.index('/tn') + 1]
                if name not in denied:
                    denied.add(name)
                    return SimpleNamespace(returncode=1, stdout='',
                                           stderr='ERROR: Access is denied.')
                xml_path = Path(cmd[cmd.index('/xml') + 1])
                xml_path.read_text(encoding='utf-16')
                return SimpleNamespace(returncode=0, stdout='SUCCESS', stderr='')
            if cmd[:2] == ['schtasks', '/query']:
                return SimpleNamespace(returncode=0, stdout=QUERY_READY, stderr='')
            return SimpleNamespace(returncode=0, stdout='SUCCESS', stderr='')

        with tempfile.TemporaryDirectory() as tmp:
            _install(backend.Backend(service, run), Path(tmp) / 'home')
        # The router task was denied once, deleted, then created again.
        def _for(name):
            return [c[:2] for c in calls if c[:1] == ['schtasks']
                    and '/tn' in c and c[c.index('/tn') + 1] == name]
        router = _for('CodexMixedModelRouter')
        self.assertIn(['schtasks', '/delete'], router)
        creates = [c for c in router if c == ['schtasks', '/create']]
        self.assertEqual(len(creates), 2, 'denied create is retried once')

    def test_every_console_child_is_spawned_windowless(self):
        seen = []

        def run(cmd, **kwargs):
            seen.append(kwargs.get('creationflags'))
            out = USER if cmd[:1] == ['whoami'] else QUERY_READY
            return SimpleNamespace(returncode=0, stdout=out, stderr='')
        with tempfile.TemporaryDirectory() as tmp:
            backend.Backend(service, run).install(PY, Path(tmp), {}, ROOT, None)
        self.assertTrue(seen)
        self.assertTrue(all(flag == backend._NO_WINDOW['creationflags'] for flag in seen))


class ControlTests(unittest.TestCase):
    def test_stop_ends_the_router_task(self):
        calls = []
        _backend({}, calls).stop('/home/x')
        self.assertIn(['schtasks', '/end', '/tn', 'CodexMixedModelRouter'], calls)

    def test_stop_tolerates_only_a_task_that_was_never_registered(self):
        # /end is always attempted; a failed /end is forgiven solely when
        # the task does not exist (a failed first install never registered
        # it), so the real failure message is not masked.
        calls = []
        _backend({}, calls, fail=('CodexMixedModelRouter',), end_fails=True).stop('/home/x')
        self.assertIn('/end', _verbs(calls))
        with self.assertRaisesRegex(SystemExit, 'failed to stop CodexMixedModelRouter'):
            _backend({'query': QUERY_RUNNING}, end_fails=True).stop('/home/x')

    def test_restart_without_state_still_runs_and_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            _backend({}, calls).restart(Path(tmp) / 'nostate')
            for verb in ('/run', '/query'):
                self.assertIn(verb, _verbs(calls))

    def test_uninstall_ends_each_task_before_deleting_it(self):
        # /delete leaves a running instance alive: end first, or the old
        # router keeps serving until sign-out.
        calls = []
        _backend({}, calls).uninstall('/home/x')
        ended = [c[3] for c in calls if c[:3] == ['schtasks', '/end', '/tn']]
        deleted = [c[3] for c in calls if c[:3] == ['schtasks', '/delete', '/tn']]
        self.assertEqual(deleted, [backend.ROUTER_TASK, backend.UPDATE_TASK, backend.EXPRESS_TASK])
        self.assertEqual(ended, deleted)
        for task in deleted:
            self.assertLess(calls.index(['schtasks', '/end', '/tn', task]),
                            calls.index(['schtasks', '/delete', '/tn', task, '/f']))

    def test_uninstall_drains_a_serving_router_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            _state_file(tmp)
            state = {'query': QUERY_RUNNING}

            def shutdown(router_state):
                state['query'] = QUERY_READY
                return True
            with mock.patch.object(backend, '_post_shutdown', side_effect=shutdown) as posted:
                _backend(state).uninstall(Path(tmp))
            posted.assert_called_once()

    def test_uninstall_ends_a_router_still_running_after_its_drain_deadline(self):
        # The destructive branch: the drain is attempted first, the bounded
        # wait expires, and only then is the instance ended and deleted.
        with tempfile.TemporaryDirectory() as tmp:
            _state_file(tmp)
            state, calls = {'query': QUERY_RUNNING, 'stuck': True}, []
            with mock.patch.object(backend, '_post_shutdown', return_value=False) as posted, \
                    mock.patch.object(backend, 'UNINSTALL_DRAIN_S', 0):
                _backend(state, calls).uninstall(Path(tmp))
            posted.assert_called_once()
            verbs = _verbs(calls)
            self.assertLess(verbs.index('/query'), verbs.index('/end'))
            self.assertLess(verbs.index('/end'), verbs.index('/delete'))


if __name__ == '__main__':
    unittest.main()
