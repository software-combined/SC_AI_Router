"""Task state, rather than HTTP availability, authorizes a replacement."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.install_fixtures import install_mod
from tests.test_client_choice import _home
from tests.test_windows_backend import (
    ROOT, PY, _backend, _install, _query, _state_file, _verbs, backend, service,
)


class TaskStateTests(unittest.TestCase):
    def test_install_and_real_rollback_preserve_each_update_schedule(self):
        for failure in ((backend.ROUTER_TASK, 'register'),
                        (backend.EXPRESS_TASK, 'register'), (backend.ROUTER_TASK, 'run'), None):
            for enabled in (True, False):
                with self.subTest(failure=failure, enabled=enabled), tempfile.TemporaryDirectory() as tmp:
                    home, calls = Path(tmp), []
                    state = {'query': _query(4), 'fail_once': failure,
                             backend.UPDATE_TASK: _query(3 if enabled else 1),
                             backend.EXPRESS_TASK: _query(1 if enabled else 3)}
                    obj = _backend(state, calls)
                    _state_file(home)
                    (home / 'express_launch.py').touch()
                    for version in ('1.0.0', '1.0.1'):
                        (home / 'releases' / version).mkdir(parents=True)
                    install_mod.swap_current(home, home / 'releases' / '1.0.1')
                    with mock.patch.object(install_mod, 'platform_backend', return_value=obj), \
                            mock.patch.object(service, 'health', return_value={'version': '1.0.0'}), \
                            mock.patch.object(backend, '_post_shutdown', side_effect=lambda _: state['query'].update(instances=[])):
                        if failure:
                            with self.assertRaisesRegex(SystemExit, failure[0]):
                                _install(obj, home)
                            if failure[1] == 'register':
                                self.assertNotIn('handover', _verbs(calls))
                            with self.assertRaisesRegex(SystemExit, '^1$'):
                                install_mod._rollback_failed_install(
                                    home, {'port': 1}, obj, {'version': '1.0.1'}, '1.0.0',
                                    home / 'mixed-models.json', None)
                            self.assertEqual(install_mod.current_version(home), '1.0.0')
                            self.assertTrue(obj.rollback_serving_ok(home, {}, '1.0.0'))
                        else:
                            _install(obj, home)
                    self.assertEqual(state[backend.UPDATE_TASK]['enabled'], enabled)
                    self.assertEqual(state[backend.EXPRESS_TASK]['enabled'], not enabled)
                    self.assertNotIn('delete', _verbs(calls))

    def test_fresh_installer_retry_finishes_pending_update_activation(self):
        cases = ((False, backend.EXPRESS_TASK, 'register'),
                 (False, backend.ROUTER_TASK, 'run'),
                 (True, backend.ROUTER_TASK, 'run'),
                 (False, backend.EXPRESS_TASK, 'enable'))
        for upgrade, failed_task, operation in cases:
            with self.subTest(upgrade=upgrade, failure=(failed_task, operation)), \
                    tempfile.TemporaryDirectory() as tmp:
                home, calls = Path(tmp), []
                (home / 'express_launch.py').touch()
                state = {'missing': {backend.EXPRESS_TASK},
                         'fail_once': (failed_task, operation),
                         backend.UPDATE_TASK: _query(1)}
                if not upgrade:
                    state['missing'].update((backend.ROUTER_TASK, backend.UPDATE_TASK))
                _state_file(home)
                with mock.patch.object(backend, '_post_shutdown',
                                       side_effect=lambda _: state['query'].update(instances=[])):
                    with self.assertRaises(SystemExit):
                        _install(_backend(state, calls), home)
                    _install(_backend(state, calls), home)  # A new process has no activation cache.
                    self.assertEqual(state[backend.UPDATE_TASK]['enabled'], not upgrade)
                    self.assertTrue(state[backend.EXPRESS_TASK]['enabled'])
                    self.assertNotIn('delete', _verbs(calls))
                    # Once activated, a later deliberate disable must survive another installer.
                    state[backend.EXPRESS_TASK]['enabled'] = False
                    _install(_backend(state, calls), home)
                    self.assertFalse(state[backend.EXPRESS_TASK]['enabled'])

    def test_restart_stop_and_uninstall_require_instance_exit(self):
        for action in ('restart', 'stop', 'uninstall'):
            with self.subTest(action=action):
                calls = []
                obj = _backend(calls=calls)
                with mock.patch.object(obj, '_state', return_value={}), \
                        mock.patch.object(obj._svc, 'current_version', return_value='1.0.0'), \
                        mock.patch.object(obj, '_drain', return_value=False), \
                        mock.patch.object(obj, '_wait_stopped', return_value=False):
                    with self.assertRaises(SystemExit):
                        getattr(obj, action)('unused')
                    self.assertFalse({'run', 'delete'} & set(_verbs(calls)))

    def test_query_failure_does_not_prove_process_exit(self):
        obj = _backend(fail=(backend.ROUTER_TASK,))
        with self.assertRaises(SystemExit):
            obj._running(backend.ROUTER_TASK, 'unused')

    def test_numeric_states_and_detached_instances_control_exit(self):
        for state, instances, running in ((1, [], False), (2, [], True),
                                          (3, [], False), (4, ['old'], True),
                                          (3, ['detached-old'], True)):
            with self.subTest(state=state, instances=instances):
                obj = _backend()
                with mock.patch.object(obj, '_task_state', return_value={
                        'state': state, 'instances': instances}):
                    self.assertEqual(obj._running(backend.ROUTER_TASK, 'unused'), running)

    def test_missing_unknown_malformed_and_unreadable_are_distinct(self):
        documents = ({'kind': 'missing'}, {'kind': 'denied'}, {},
                     dict(_query(3), state=0), dict(_query(3), state=True),
                     dict(_query(3), instances=None), dict(_query(3), pending='true'),
                     {'kind': 'present', 'state': 3, 'instances': [], 'enabled': True},
                     {'kind': 'present', 'state': 3, 'instances': [], 'pending': False},
                     dict(_query(3), enabled='true'), dict(_query(3), enabled=0))
        for doc in documents:
            with self.subTest(doc=doc):
                run = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(doc)))
                def query():
                    return backend._tasks.invoke(run, 'sid', 'name', 'arguments')
                if doc == {'kind': 'missing'}:
                    self.assertIsNone(query())
                else:
                    with self.assertRaises(SystemExit):
                        query()
        obj = _backend()
        with mock.patch.object(obj, '_task_state', return_value=None):
            with self.assertRaisesRegex(SystemExit, 'exit is unverified'):
                obj._running(backend.ROUTER_TASK, 'unused')


class _CurrentInstallerFixture:
    def _home(self, tmp):
        home = _home(tmp)
        service.install_task_launcher(home, ROOT)
        (home / 'express_launch.py').touch()
        return home

    def _run(self, home, tasks, calls, *, extra=(), feed='1.0.0', served='1.0.0'):
        args = install_mod.build_parser().parse_args(
            ['--home', str(home), '--feed', 'file:///latest.json', *extra])
        def health(state, timeout=20):
            calls.append({'operation': 'health', 'version': served})
            return {'status': 'ok', 'version': served}
        clock = SimpleNamespace(monotonic=iter((0, 0, 151)).__next__, sleep=lambda _: None)
        profile, output = str(home.parent / 'profile'), io.StringIO()
        with mock.patch.dict(os.environ, {'HOME': profile, 'USERPROFILE': profile}), \
                mock.patch.object(install_mod, 'PLATFORM', 'win32'), \
                mock.patch.object(install_mod, 'find_python', return_value=PY), \
                mock.patch.object(install_mod, 'platform_backend', side_effect=lambda: _backend(tasks, calls)), \
                mock.patch.object(service, 'health', side_effect=health), \
                mock.patch.object(service, 'time', clock), \
                mock.patch.object(backend, '_post_shutdown', side_effect=lambda _: tasks['query'].update(instances=[])), \
                contextlib.redirect_stdout(output):
            result = install_mod.do_install(args, _fetch=lambda _: json.dumps({'version': feed}).encode())
        return result, output.getvalue()

    def _interrupted_handover(self, home, tasks, calls, *, after_run=False):
        obj = _backend(tasks, calls)
        run = obj._run
        def interrupted(cmd, **kwargs):
            operation = json.loads(kwargs['input']).get('operation')
            if operation == 'run' and not after_run:
                raise KeyboardInterrupt('installer interrupted before Run')
            result = run(cmd, **kwargs)
            if operation == 'run':
                raise KeyboardInterrupt('installer interrupted after Run')
            return result
        obj._run = interrupted
        with mock.patch.object(backend, '_post_shutdown',
                               side_effect=lambda _: tasks['query'].update(instances=[])):
            with self.assertRaises(KeyboardInterrupt):
                obj.install(PY, home, json.loads((home / 'mixed-router-state.json').read_text()),
                            install_mod.current_release_dir(home), None)


class CurrentInstallerRecoveryTests(_CurrentInstallerFixture, unittest.TestCase):
    def test_current_installer_recovers_existing_handover_after_interruption(self):
        for after_run in (False, True):
            with self.subTest(after_run=after_run), tempfile.TemporaryDirectory() as tmp:
                home, calls = self._home(tmp), []
                tasks = {'query': _query(4), backend.UPDATE_TASK: _query(1),
                         backend.EXPRESS_TASK: _query(3)}
                self._interrupted_handover(home, tasks, [], after_run=after_run)
                interrupted = dict(tasks['query'])
                self.assertEqual(self._run(home, tasks, calls)[0], 0)
                self.assertIn('run', _verbs(calls))
                self.assertIn('health', _verbs(calls))
                self.assertTrue(interrupted['pending'])
                self.assertFalse(tasks['query']['pending'])
                self.assertEqual(tasks['query']['state'], 4)
                self.assertFalse(tasks[backend.UPDATE_TASK]['enabled'])
                self.assertTrue(tasks[backend.EXPRESS_TASK]['enabled'])

    def test_install_and_restart_verify_their_target_before_clearing_intent(self):
        for action in ('install', 'restart'):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as tmp:
                home, calls = self._home(tmp), []
                tasks = {'query': _query(4)}
                obj = _backend(tasks, calls)
                clock = SimpleNamespace(monotonic=iter((0, 0, 151)).__next__, sleep=lambda _: None)
                with mock.patch.object(service, 'health', return_value={'version': '0.9.0'}), \
                        mock.patch.object(service, 'time', clock), \
                        mock.patch.object(backend, '_post_shutdown',
                                          side_effect=lambda _: tasks['query'].update(instances=[])):
                    with self.assertRaisesRegex(SystemExit, '1.0.0'):
                        if action == 'install':
                            obj.install(PY, home, obj._state(home), install_mod.current_release_dir(home), None)
                        else:
                            obj.restart(home)
                self.assertTrue(tasks['query']['pending'])
                self.assertNotIn('complete', _verbs(calls))
                self.assertEqual(self._run(home, tasks, [])[0], 0)
                self.assertFalse(tasks['query']['pending'])

    def test_existing_handover_retry_retains_intent_until_expected_version_serves(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, calls = self._home(tmp), []
            tasks = {'query': _query(4), backend.UPDATE_TASK: _query(1),
                     backend.EXPRESS_TASK: _query(3)}
            self._interrupted_handover(home, tasks, [])
            before = dict(tasks['query'])
            self.assertEqual(self._run(home, tasks, calls, extra=('--dry-run',))[0], 0)
            self.assertEqual(tasks['query'], before)
            self.assertEqual(calls, [])
            tasks['fail_once'] = (backend.ROUTER_TASK, 'run')
            with self.assertRaises(SystemExit):
                self._run(home, tasks, calls)
            self.assertTrue(tasks['query']['pending'])
            with self.assertRaisesRegex(SystemExit, '1.0.0'):
                self._run(home, tasks, calls, served='0.9.0')
            self.assertTrue(tasks['query']['pending'])
            self.assertNotIn('complete', _verbs(calls))
            calls.clear()
            self.assertEqual(self._run(home, tasks, calls)[0], 0)
            self.assertFalse(tasks['query']['pending'])
            self.assertLess(_verbs(calls).index('health'), _verbs(calls).index('complete'))
            self.assertFalse(tasks[backend.UPDATE_TASK]['enabled'])
            self.assertTrue(tasks[backend.EXPRESS_TASK]['enabled'])
            self._interrupted_handover(home, tasks, [])
            _backend(tasks, []).stop(home)
            self.assertFalse(tasks['query']['pending'])
            calls.clear()
            self.assertEqual(self._run(home, tasks, calls)[0], 0)
            self.assertTrue(all(c['operation'] == 'query' for c in calls))

    def test_current_installer_recovers_pending_tasks_before_client_selection(self):
        for feed, extra, router_pending in (('1.0.0', (), True),
                                            ('0.9.0', ('--clients', 'none'), False)):
            with self.subTest(feed=feed, extra=extra), tempfile.TemporaryDirectory() as tmp:
                home, calls = self._home(tmp), []
                tasks = {'query': dict(_query(1 if router_pending else 4), pending=router_pending),
                         backend.UPDATE_TASK: dict(_query(1), pending=not bool(extra)),
                         backend.EXPRESS_TASK: dict(_query(1), pending=True)}
                result, output = self._run(home, tasks, calls, feed=feed, extra=extra)
                self.assertEqual(result, 0)
                self.assertEqual(install_mod.current_version(home), '1.0.0')
                self.assertEqual(tasks[backend.UPDATE_TASK]['enabled'], not bool(extra))
                self.assertTrue(tasks[backend.EXPRESS_TASK]['enabled'])
                self.assertLess(_verbs(calls).index('run'), _verbs(calls).index('health'))
                self.assertLess(_verbs(calls).index('health'), _verbs(calls).index('enable'))
                if extra:
                    self.assertIn('nothing to attach', output)

    def test_current_version_health_is_required_before_update_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, calls = self._home(tmp), []
            tasks = {'query': _query(4),
                     backend.UPDATE_TASK: dict(_query(1), pending=True),
                     backend.EXPRESS_TASK: dict(_query(1), pending=True)}
            with self.assertRaisesRegex(SystemExit, '1.0.0'):
                self._run(home, tasks, calls, feed='0.9.0', served='0.9.0')
            self.assertNotIn('enable', _verbs(calls))
            for name in (backend.UPDATE_TASK, backend.EXPRESS_TASK):
                self.assertFalse(tasks[name]['enabled'])
                self.assertTrue(tasks[name]['pending'])
            self.assertEqual(self._run(home, tasks, [], feed='0.9.0')[0], 0)
            self.assertTrue(tasks[backend.UPDATE_TASK]['enabled'])
            self.assertTrue(tasks[backend.EXPRESS_TASK]['enabled'])

    def test_dry_run_and_unmarked_current_install_do_not_mutate(self):
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run), tempfile.TemporaryDirectory() as tmp:
                home, calls = self._home(tmp), []
                tasks = {'query': dict(_query(1), pending=dry_run),
                         backend.UPDATE_TASK: dict(_query(1), pending=dry_run),
                         backend.EXPRESS_TASK: dict(_query(1), pending=dry_run)}
                before = {p: p.read_bytes() for p in home.rglob('*') if p.is_file()}
                self.assertEqual(self._run(home, tasks, calls, extra=('--dry-run',) if dry_run else ())[0], 0)
                self.assertEqual({p: p.read_bytes() for p in home.rglob('*') if p.is_file()}, before)
                self.assertTrue(all(c['operation'] == 'query' for c in calls))
                if dry_run:
                    self.assertEqual(calls, [])
