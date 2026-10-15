"""Account isolation and resumable migration of owned Windows tasks."""
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.install_fixtures import install_mod
from tests.test_windows_backend import (
    USER, _backend, _install, _query, _verbs, backend, service,
)
from tests.test_windows_task_state import _CurrentInstallerFixture


NAMES = (backend.ROUTER_TASK, backend.UPDATE_TASK, backend.EXPRESS_TASK)


class MigrationTests(_CurrentInstallerFixture, unittest.TestCase):
    def setUp(self):
        # Model an unresponsive old router; the real bounded stop path must prove exit.
        patch = mock.patch.multiple(backend, DRAIN_TIMEOUT_S=0, UNINSTALL_DRAIN_S=0,
                                    _post_shutdown=mock.Mock(return_value=False))
        patch.start()
        self.addCleanup(patch.stop)

    def _tasks(self):
        return {'missing': set(NAMES), 'legacy': {
            NAMES[0]: _query(4), NAMES[1]: _query(4), NAMES[2]: _query(1)}}

    def test_task_names_are_distinct_for_two_accounts(self):
        calls = []
        for sid in (USER, USER + '0'):
            obj = _backend(calls=calls)
            obj._sid = sid
            obj._task_state(backend.ROUTER_TASK, 'unused')
        self.assertEqual([call['name'] for call in calls],
                         [backend.ROUTER_TASK + '-' + sid for sid in (USER, USER + '0')])

    def test_foreign_and_denied_legacy_tasks_are_untouched(self):
        for kind in ('foreign', 'denied'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                home, calls = self._home(tmp), []
                tasks = {'legacy': {name: {'kind': kind} for name in NAMES}}
                obj = _backend(tasks, calls)
                _install(obj, home)
                obj.uninstall(home)
                self.assertTrue(all(c['operation'] == 'query' for c in calls if c['name'] in NAMES))
                self.assertEqual(tasks['legacy'], {name: {'kind': kind} for name in NAMES})

    def test_malformed_or_failed_legacy_queries_abort_before_registration(self):
        documents = (dict(_query(3), enabled='true'), dict(_query(3), pending=1),
                     dict(_query(3), state=0), dict(_query(3), instances=None), None)
        for document in documents:
            with self.subTest(document=document), tempfile.TemporaryDirectory() as tmp:
                home, calls = self._home(tmp), []
                obj = _backend(self._tasks(), calls)
                run = obj._run
                def malformed(cmd, **kwargs):
                    request = json.loads(kwargs['input'])
                    if request.get('name') == NAMES[1]:
                        return SimpleNamespace(returncode=int(document is None), stdout=json.dumps(document))
                    return run(cmd, **kwargs)
                obj._run = malformed
                with self.assertRaisesRegex(SystemExit, 'cannot verify'):
                    _install(obj, home)
                self.assertTrue(all(c['operation'] == 'query' for c in calls))

    def test_each_registration_failure_preserves_old_service_and_real_rollback(self):
        for failed in NAMES:
            with self.subTest(failed=failed), tempfile.TemporaryDirectory() as tmp:
                home, calls, tasks = self._home(tmp), [], self._tasks()
                tasks['fail_once'] = (failed + '-' + USER, 'register')
                release = home / 'releases' / '1.0.1'
                release.mkdir()
                install_mod.swap_current(home, release)
                obj = _backend(tasks, calls)
                with self.assertRaises(SystemExit):
                    _install(obj, home)
                self.assertFalse({'handover', 'disable', 'stop', 'delete'} & set(_verbs(calls)))
                self.assertEqual(tasks['legacy'][NAMES[0]], _query(4))
                parent = dict(tasks['legacy'][NAMES[1]])
                with mock.patch.object(service, 'health', return_value={'version': '1.0.0'}), \
                        mock.patch.object(install_mod, 'platform_backend', return_value=obj), \
                        mock.patch.object(backend, '_post_shutdown', return_value=False):
                    with self.assertRaisesRegex(SystemExit, '^1$'):
                        install_mod._rollback_failed_install(
                            home, {'port': 1}, obj, {'version': '1.0.1'}, '1.0.0',
                            home / 'mixed-models.json', None)
                    self.assertTrue(obj.rollback_serving_ok(home, {}, '1.0.0'))
                self.assertEqual(install_mod.current_version(home), '1.0.0')
                self.assertEqual([c['name'] for c in calls if c['operation'] == 'run'], [NAMES[0]])
                self.assertEqual(tasks['legacy'][NAMES[1]], parent)
                self.assertEqual(self._run(home, tasks, [])[0], 0)
                self.assertEqual(tasks['query']['state'], 4)

    def test_legacy_and_existing_replacement_update_settings_survive_migration(self):
        cases = ((_query(3), None, True), (_query(1), None, False),
                 (dict(_query(4), enabled=False), None, False),
                 (dict(_query(1), pending=True), None, True),
                 (_query(3), _query(1), False), (_query(1), _query(3), True))
        for legacy, replacement, enabled in cases:
            with self.subTest(legacy=legacy, replacement=replacement), tempfile.TemporaryDirectory() as tmp:
                home, calls, tasks = self._home(tmp), [], self._tasks()
                tasks['legacy'][NAMES[1]] = dict(legacy)
                if replacement:
                    tasks['missing'].remove(NAMES[1])
                    tasks[NAMES[1]] = dict(replacement)
                self.assertEqual(self._run(home, tasks, calls)[0], 0)
                self.assertEqual(tasks[NAMES[1]]['enabled'], enabled)
                self.assertFalse(tasks[NAMES[1]]['pending'])
                self.assertFalse(tasks[NAMES[2]]['enabled'])
                changes = [c for c in calls if c['operation'] != 'query']
                self.assertEqual([c['operation'] for c in changes[:3]], ['register'] * 3)
                self.assertLess(_verbs(calls).index('health'), _verbs(calls).index('delete'))

    def test_actual_current_installer_completes_unmarked_partial_migration_and_health_retry(self):
        for feed in ('1.0.0', '0.9.0'):
            with self.subTest(feed=feed), tempfile.TemporaryDirectory() as tmp:
                home, calls = self._home(tmp), []
                tasks = {'query': _query(4), NAMES[1]: _query(1), NAMES[2]: _query(1),
                         'legacy': {NAMES[1]: _query(3)}}
                before = {p: p.read_bytes() for p in home.rglob('*') if p.is_file()}
                self.assertEqual(self._run(home, tasks, calls, extra=('--dry-run',), feed=feed)[0], 0)
                self.assertEqual(calls, [])
                self.assertEqual(before, {p: p.read_bytes() for p in home.rglob('*') if p.is_file()})
                with self.assertRaisesRegex(SystemExit, '1.0.0'):
                    self._run(home, tasks, calls, feed=feed, served='0.9.0')
                self.assertNotIn('delete', _verbs(calls))
                self.assertTrue(tasks['query']['pending'])
                calls.clear()
                self.assertEqual(self._run(home, tasks, calls, feed=feed)[0], 0)
                self.assertLess(_verbs(calls).index('health'), _verbs(calls).index('delete'))
                self.assertEqual(tasks['legacy'][NAMES[1]]['kind'], 'missing')
                self.assertFalse(tasks[NAMES[1]]['enabled'])
                calls.clear()
                self.assertEqual(self._run(home, tasks, calls, feed=feed)[0], 0)
                self.assertTrue(all(c['operation'] == 'query' for c in calls))

    def test_interrupted_migration_keeps_intent_for_a_fresh_installer(self):
        for after_run in (False, True):
            with self.subTest(after_run=after_run), tempfile.TemporaryDirectory() as tmp:
                home, tasks = self._home(tmp), self._tasks()
                self._interrupted_handover(home, tasks, [], after_run=after_run)
                self.assertTrue(tasks['query']['pending'])
                self.assertTrue(tasks['legacy'][NAMES[0]]['pending'])
                self.assertEqual(self._run(home, tasks, [])[0], 0)
                self.assertFalse(tasks['query']['pending'])
                self.assertEqual(tasks['legacy'][NAMES[0]]['kind'], 'missing')
                self.assertTrue(tasks['legacy'][NAMES[1]]['instances'])

    def test_active_updater_is_retained_through_verification_and_later_cleaned(self):
        for parent in (_query(2), _query(4), dict(_query(3), instances=['old-parent'])):
            with self.subTest(parent=parent), tempfile.TemporaryDirectory() as tmp:
                home, calls, tasks = self._home(tmp), [], self._tasks()
                tasks['legacy'][NAMES[1]] = dict(parent)
                self.assertEqual(self._run(home, tasks, calls)[0], 0)
                self.assertFalse(tasks['legacy'][NAMES[1]]['enabled'])
                self.assertEqual(tasks['legacy'][NAMES[1]]['instances'], parent['instances'])
                if parent['state'] == 3:
                    self.assertNotIn(tasks['legacy'][NAMES[1]]['state'], (2, 4))
                with mock.patch.object(service, 'health', return_value={'version': '1.0.0'}), \
                        mock.patch.object(backend, '_post_shutdown', side_effect=lambda _: tasks['query'].update(instances=[])):
                    obj = _backend(tasks, calls)
                    self.assertTrue(obj.ensure_serving(home, {}, '1.0.0'))
                    obj.restart(home)
                    self.assertTrue(obj.rollback_serving_ok(home, {}, '1.0.0'))
                self.assertFalse(any(c['name'] == NAMES[1] and c['operation'] in ('stop', 'delete')
                                     for c in calls if 'name' in c))
                tasks['legacy'][NAMES[1]].update(state=1, instances=[])
                self.assertEqual(self._run(home, tasks, [])[0], 0)
                self.assertEqual(tasks['legacy'][NAMES[1]]['kind'], 'missing')

    def test_explicit_stop_cancels_both_routers_and_blocks_cleanup_restart(self):
        for stuck in (False, True):
            with self.subTest(stuck=stuck), tempfile.TemporaryDirectory() as tmp:
                home, calls, tasks = self._home(tmp), [], self._tasks()
                tasks['missing'].remove(NAMES[0])
                tasks['query'] = dict(_query(1), pending=True)
                tasks['legacy'][NAMES[0]]['pending'] = True
                tasks['stuck'] = stuck
                obj = _backend(tasks, calls)
                with mock.patch.object(backend, 'time', SimpleNamespace(monotonic=iter((0, 0, 11)).__next__)):
                    if stuck:
                        with self.assertRaisesRegex(SystemExit, 'did not exit'):
                            obj.stop(home)
                    else:
                        obj.stop(home)
                for router in (tasks['query'], tasks['legacy'][NAMES[0]]):
                    self.assertFalse(router['enabled'])
                    self.assertFalse(router['pending'])
                calls.clear()
                self.assertEqual(self._run(home, tasks, calls)[0], 0)
                self.assertTrue(all(c['operation'] == 'query' for c in calls))
                self.assertEqual(bool(tasks['legacy'][NAMES[0]]['instances']), stuck)
                tasks['stuck'] = False
                with mock.patch.object(service, 'health', return_value={'version': '1.0.0'}), \
                        mock.patch.object(backend, '_post_shutdown', return_value=False):
                    _backend(tasks).restart(home)
                self.assertEqual(self._run(home, tasks, [])[0], 0)
                self.assertEqual(tasks['legacy'][NAMES[0]]['kind'], 'missing')
