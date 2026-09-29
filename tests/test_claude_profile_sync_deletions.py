"""A task deleted before a switch stays deleted; its other copy goes to the trash."""
import json
import shutil
from unittest import mock

from tests import claude_profile_sync_fixtures as fixtures
from tests.claude_profile_sync_fixtures import SyncFixture, sync

A1, O1 = '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc'
A3, O3 = '87654321-4321-4567-8123-123456789abc', 'fedcbaab-4321-4567-8123-123456789abc'
CODE = 'claude-code-sessions'


class Crash(BaseException):
    """Stands in for the process dying mid-switch."""


class DeletedTaskTests(SyncFixture):
    def task(self, name):
        return fixtures.record(self.first, CODE, A1, O1, name, bundle_files={'a.txt': name})

    def copies(self, name):
        return self.paths(self.first, CODE, name) + self.paths(self.third, CODE, name)

    def trashed(self, profile):
        folder = profile / CODE / sync._ledger.TRASH
        return sorted(folder.iterdir()) if folder.exists() else []

    @staticmethod
    def delete(record):
        record.unlink()
        shutil.rmtree(record.with_suffix(''))

    def test_a_task_deleted_in_the_outgoing_profile_is_not_copied_back(self):
        record = self.task('outgoing')
        self.assertEqual(self.sync('1p')['failed'], 0)
        shared = self.paths(self.third, CODE, 'outgoing')[0]
        saved = shared.read_bytes()
        self.delete(record)
        report = self.sync('1p')
        self.assertEqual((report['failed'], report['copied'], report['retired']), (0, 0, 1), report)
        self.assertEqual(self.copies('outgoing'), [])
        [entry] = self.trashed(self.third)
        self.assertEqual((entry / shared.name).read_bytes(), saved)

    def test_a_task_deleted_in_the_incoming_profile_is_not_copied_back(self):
        self.task('incoming')
        self.assertEqual(self.sync('1p')['failed'], 0)  # the gateway profile is now in use
        self.delete(self.paths(self.first, CODE, 'incoming')[0])
        report = self.sync('3p')
        self.assertEqual((report['failed'], report['copied'], report['retired']), (0, 0, 1), report)
        self.assertEqual(self.copies('incoming'), [])
        self.assertEqual(len(self.trashed(self.third)), 1)

    def test_an_edit_beats_a_delete_while_an_unchanged_copy_is_retired(self):
        edited = self.task('edited')
        for name in ('untouched', 'kept'):
            self.task(name)
        self.assertEqual(self.sync('1p')['failed'], 0)
        for name in ('edited', 'untouched'):
            self.delete(self.paths(self.third, CODE, name)[0])
        doc = json.loads(edited.read_text())
        doc['title'] = 'continued'
        edited.write_text(json.dumps(doc))
        report = self.sync('3p')
        self.assertEqual((report['failed'], report['retired']), (0, 1), report)
        self.assertEqual(self.copies('untouched'), [])
        self.assertEqual([json.loads(path.read_text())['title'] for path in self.copies('edited')],
                         ['continued', 'continued'])

    def test_a_deleted_task_stays_deleted_and_a_second_run_changes_nothing(self):
        record = self.task('settled')
        self.assertEqual(self.sync('1p')['failed'], 0)
        self.delete(record)
        self.assertEqual(self.sync('1p')['retired'], 1)
        roots = (self.first, self.third, self.home)
        before = [fixtures.fingerprint(root) for root in roots]
        report = self.sync('1p')
        self.assertEqual((report['failed'], report['copied'], report['replaced'], report['retired']),
                         (0, 0, 0, 0), report)
        self.assertEqual([fixtures.fingerprint(root) for root in roots], before)
        self.assertEqual(self.copies('settled'), [])

    def test_losing_every_shared_task_at_once_is_a_reset_not_deletions(self):
        records = [self.task(name) for name in ('one', 'two', 'three')]
        self.assertEqual(self.sync('1p')['failed'], 0)
        self.delete(records[0])
        self.assertEqual(self.sync('1p')['retired'], 1)
        for record in records[1:]:
            self.delete(record)
        report = self.sync('1p')
        self.assertEqual((report['failed'], report['retired']), (0, 0), report)
        self.assertTrue(all(record.exists() for record in records[1:]))
        self.assertEqual(len(self.trashed(self.third)), 1)

    def test_a_task_deleted_from_both_profiles_stays_deleted(self):
        self.task('both')
        self.assertEqual(self.sync('1p')['failed'], 0)
        for path in self.copies('both'):
            self.delete(path)
        report = self.sync('1p')
        self.assertEqual((report['failed'], report['copied']), (0, 0), report)
        self.assertEqual(self.copies('both'), [])
        self.assertEqual(self.trashed(self.first) + self.trashed(self.third), [])

    def test_a_task_left_unshared_is_never_retired(self):
        # No conversation anywhere: the sync leaves both copies unshared.
        fixtures.record(self.first, CODE, A1, O1, 'unshared', cli='unshared-cli')
        fixtures.record(self.third, CODE, A3, O3, 'unshared', cli='unshared-cli')
        report = self.sync('1p')
        self.assertEqual((report['failed'], report['pending'], report['unshared']), (0, 0, 1), report)
        self.paths(self.first, CODE, 'unshared')[0].unlink()
        self.assertEqual(self.sync('1p')['retired'], 0)
        self.assertEqual(len(self.paths(self.third, CODE, 'unshared')), 1)
        self.assertEqual(self.trashed(self.third), [])

    def test_a_switch_that_fails_does_not_update_what_was_shared(self):
        self.task('earlier')
        self.assertEqual(self.sync('1p')['failed'], 0)
        before = fixtures.fingerprint(self.home)
        self.task('later')
        (self.first / CODE / A1 / O1 / 'local_unreadable.json').write_text('{')
        self.assertGreater(self.sync('1p')['failed'], 0)
        self.assertEqual(fixtures.fingerprint(self.home), before)

    def test_a_trash_entry_that_cannot_be_put_back_stops_the_switch(self):
        record = self.task('conflict')
        self.assertEqual(self.sync('1p')['failed'], 0)
        self.delete(record)
        real, calls = sync._ledger._publish.move_new, []

        def move(source, target):
            calls.append(source)
            if len(calls) == 2:
                raise Crash()
            return real(source, target)
        with mock.patch.object(sync._ledger._publish, 'move_new', side_effect=move):
            with self.assertRaises(Crash):
                self.sync('1p')
        fixtures.record(self.third, CODE, A3, O3, 'conflict', title='recreated')
        report = self.sync('1p')
        self.assertIn('retire-conflict', report['errors'])
        self.assertGreater(report['failed'], 0)
        self.assertEqual(len(self.trashed(self.third)), 1)
