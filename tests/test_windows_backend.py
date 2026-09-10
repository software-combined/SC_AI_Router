"""Plan 057 Stage 3: Windows Task Scheduler backend, proven offline.

XML/command generation plus lifecycle control against a fake schtasks;
no Windows machine, no real tasks, no secrets. The Stage 3 gate's
real-machine install is still open; these tests pin the offline half.
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        'router_windows_backend_stage3_under_test',
        ROOT / 'packaging' / 'platforms' / 'windows.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


backend = _load()

def _query(status):
    return ('TaskName: \\CodexMixedModelRouter\nStatus: %s\n' % status)


QUERY_RUNNING = _query('Running')
QUERY_DISABLED = _query('Disabled')


def _fake_run(state=None, calls=None, fail=()):
    state = state if state is not None else {}
    def ok():
        return SimpleNamespace(returncode=0, stdout='SUCCESS', stderr='')
    def run(cmd, **kwargs):
        (calls if calls is not None else []).append(list(cmd))
        if cmd[:2] == ['schtasks', '/create']:
            xml_path = Path(cmd[cmd.index('/xml') + 1])
            state['xml_' + cmd[cmd.index('/tn') + 1]] = xml_path.read_text(
                encoding='utf-16')
            return ok()
        if cmd[:2] == ['schtasks', '/query']:
            name = cmd[cmd.index('/tn') + 1]
            if name in fail:
                return SimpleNamespace(returncode=1, stdout='', stderr='not found')
            return SimpleNamespace(
                returncode=0, stdout=state.get('query', QUERY_RUNNING), stderr='')
        if cmd[:2] in (['schtasks', '/run'], ['schtasks', '/end'],
                       ['schtasks', '/delete']):
            return ok()
        raise AssertionError('unexpected command: %r' % (cmd,))
    return run


def _assert_fragments(test, xml, fragments):
    for fragment in fragments:
        test.assertIn(fragment, xml)


_ROUTER_FRAGMENTS = ('<LogonType>InteractiveToken</LogonType>',
                     '<RunLevel>LeastPrivilege</RunLevel>',
                     '<LogonTrigger>',
                     '<Interval>PT1M</Interval>',
                     '<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>',
                     '<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>',
                     '<DisallowStartIfOnBatteries>false',
                     '<StopIfGoingOnBatteries>false')


class RouterXmlTests(unittest.TestCase):
    def test_router_task_is_interactive_logon_with_recovery_trigger(self):
        xml = backend.render_router_xml('C:\\Python314\\python.exe', 'C:\\home')
        _assert_fragments(self, xml, _ROUTER_FRAGMENTS)

    def test_router_runs_console_free_while_updater_keeps_output(self):
        router = backend.render_router_xml('C:\\Python314\\python.exe', 'C:\\home')
        self.assertIn('pythonw.exe', router)
        self.assertNotIn('python.exe</Command>', router)
        update = backend.render_update_xml('C:\\Python314\\python.exe', 'C:\\home')
        self.assertIn('<Command>C:\\Python314\\python.exe</Command>', update)
        self.assertIn('<Interval>PT15M</Interval>', update)

    def test_paths_with_spaces_are_quoted_and_xml_escaped(self):
        home = 'C:\\Users\\Some One\\router home'
        xml = backend.render_router_xml('C:\\Program Files\\Python\\python.exe', home)
        # <Command> carries a bare path (no shell there); <Arguments>
        # must quote and XML-escape each spaced argument.
        self.assertIn('<Command>C:\\Program Files\\Python\\pythonw.exe</Command>', xml)
        self.assertIn('&quot;C:\\Users\\Some One', xml)


def _install(obj, home):
    obj.install('C:\\Python314\\python.exe', home, {}, 'rel', None)


def _verbs(calls):
    return [c[1] for c in calls if c[:1] == ['schtasks']]


class InstallTests(unittest.TestCase):
    def test_install_registers_both_tasks_runs_and_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            state, calls = {}, []
            obj = backend.Backend(None, _fake_run(state, calls))
            _install(obj, home)
            self.assertIn('xml_CodexMixedModelRouter', state)
            self.assertIn('xml_CodexMixedModelRouterUpdate', state)
            for verb in ('/create', '/run', '/query'):
                self.assertIn(verb, _verbs(calls))
            created = [c for c in calls if c[:2] == ['schtasks', '/create']]
            self.assertEqual(len(created), 2)
            xml_files = [c[c.index('/xml') + 1] for c in created]
            self.assertTrue(all(f.startswith(str(home)) for f in xml_files))

    def test_install_reports_unregistered_task_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            obj = backend.Backend(
                None, _fake_run({}, fail=('CodexMixedModelRouter',)))
            with self.assertRaisesRegex(SystemExit, 'CodexMixedModelRouter'):
                _install(obj, Path(tmp) / 'home')

    def test_install_refuses_policy_disabled_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = {'query': QUERY_DISABLED}
            obj = backend.Backend(None, _fake_run(state))
            with self.assertRaisesRegex(SystemExit, 'disabled by policy'):
                _install(obj, Path(tmp) / 'home')

    def test_registration_failure_names_the_task(self):
        def run(cmd, **kwargs):
            if cmd[:2] == ['schtasks', '/create']:
                return SimpleNamespace(returncode=1, stdout='',
                                       stderr='Access is denied.')
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        with tempfile.TemporaryDirectory() as tmp:
            obj = backend.Backend(None, run)
            with self.assertRaisesRegex(SystemExit, 'CodexMixedModelRouter'):
                _install(obj, Path(tmp) / 'home')


class ControlTests(unittest.TestCase):
    def test_stop_ends_the_router_task(self):
        calls = []
        backend.Backend(None, _fake_run({}, calls)).stop('/home/x')
        self.assertIn(['schtasks', '/end', '/tn', 'CodexMixedModelRouter'],
                      calls)

    def test_stop_failure_names_the_task(self):
        def run(cmd, **kwargs):
            return SimpleNamespace(returncode=1, stdout='', stderr='nope')
        with self.assertRaisesRegex(SystemExit, 'CodexMixedModelRouter'):
            backend.Backend(None, run).stop('/home/x')

    def test_restart_without_state_still_runs_and_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            backend.Backend(None, _fake_run({}, calls)).restart(
                Path(tmp) / 'nostate')
            for verb in ('/run', '/query'):
                self.assertIn(verb, _verbs(calls))

    def test_uninstall_removes_both_tasks(self):
        calls = []
        backend.Backend(None, _fake_run({}, calls)).uninstall('/home/x')
        deleted = [c[3] for c in calls if c[:3] == ['schtasks', '/delete', '/tn']]
        self.assertEqual(deleted,
                         ['CodexMixedModelRouter', 'CodexMixedModelRouterUpdate'])


if __name__ == '__main__':
    unittest.main()
