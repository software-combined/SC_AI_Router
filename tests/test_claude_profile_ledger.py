"""A task deleted in one profile is retired to the trash, never copied back or lost."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.claude_profile_sync_fixtures import load_helper

ledger = load_helper('claude_profile_ledger')
STORE = 'claude-code-sessions'
ACCOUNTS = 'a' * 64


class Crash(BaseException):
    """Stands in for the process dying: nothing in the module catches it."""


class LedgerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.home = self.root / 'router'
        self.home.mkdir()
        self.sides = tuple((self.root / name / STORE, self.root / name / STORE / 'account')
                           for name in ('Claude', 'Claude-3p'))
        for _store, account in self.sides:
            (account / 'org').mkdir(parents=True)

    def task(self, side, identifier='local_t', title='private title', filename=None):
        record = self.sides[side][1] / 'org' / ((filename or identifier) + '.json')
        record.write_text(json.dumps({'sessionId': identifier, 'title': title}))
        bundle = record.with_suffix('')
        bundle.mkdir(exist_ok=True)
        (bundle / 'notes.txt').write_text('task file %d' % side)
        return record

    def shared(self, *identifiers):
        records = [[self.task(side, name) for name in identifiers] for side in (0, 1)]
        ledger.record_shared(self.home, ACCOUNTS, [self.sides])
        return records

    def retire(self, accounts=ACCOUNTS):
        return ledger.retire_deleted(self.home, accounts, [self.sides])

    def remembered(self):
        return ledger._read(self.home, ACCOUNTS).get(STORE, {})

    def trash(self, side):
        folder = self.sides[side][0] / ledger.TRASH
        return sorted(folder.iterdir()) if folder.exists() else []

    @staticmethod
    def delete(record):
        record.unlink()
        shutil.rmtree(record.with_suffix(''))

    def test_remembers_only_tasks_both_profiles_hold_once_each_without_content(self):
        for side in (0, 1):
            self.task(side, 'local_both')
            self.task(side, 'local_unshared')
            self.task(side, 'local_twice')
        self.task(0, 'local_one_side')
        self.task(1, 'local_twice', filename='local_twice_copy')
        ledger.record_shared(self.home, None, [self.sides])
        self.assertFalse((self.home / ledger.LEDGER).exists())
        ledger.record_shared(self.home, ACCOUNTS, [self.sides],
                             exclude={(STORE, 'local_unshared')})
        self.assertEqual(set(self.remembered()), {'local_both'})
        text = (self.home / ledger.LEDGER).read_text()
        self.assertNotIn('private title', text)
        self.assertNotIn(str(self.root), text)
        if os.name != 'nt':
            self.assertEqual((self.home / ledger.LEDGER).stat().st_mode & 0o777, 0o600)
        # Another account pair never inherits this pair's memory.
        self.assertEqual(ledger._read(self.home, 'b' * 64), {})

    def test_delete_in_either_profile_moves_the_unchanged_copy_to_trash(self):
        for gone in (0, 1):
            with self.subTest(deleted_in=gone):
                self.setUp()
                records = self.shared('local_t')
                survivor = records[1 - gone][0]
                saved = survivor.read_bytes(), (survivor.with_suffix('') / 'notes.txt').read_bytes()
                self.delete(records[gone][0])
                self.assertEqual(self.retire(), (1, []))
                self.assertFalse(survivor.exists() or survivor.with_suffix('').exists())
                [entry] = self.trash(1 - gone)
                journal = json.loads((entry / ledger.JOURNAL).read_text())
                self.assertEqual(journal['phase'], 'retired')
                self.assertEqual(((entry / survivor.name).read_bytes(),
                                  (entry / 'local_t' / 'notes.txt').read_bytes()), saved)
                self.assertEqual(self.remembered(), {})
                self.assertEqual(self.retire(), (0, []))
                self.assertEqual(self.trash(1 - gone), [entry])

    def test_an_edit_since_the_last_share_wins_over_the_delete(self):
        for edit in ('record', 'bundle'):
            with self.subTest(edit=edit):
                self.setUp()
                first, third = (records[0] for records in self.shared('local_t'))
                self.delete(first)
                if edit == 'record':
                    third.write_text(json.dumps({'sessionId': 'local_t', 'title': 'continued'}))
                else:
                    (third.with_suffix('') / 'new.txt').write_text('new work')
                self.assertEqual(self.retire(), (0, []))
                self.assertTrue(third.exists())
                self.assertEqual(self.trash(1), [])
                self.assertEqual(set(self.remembered()), {'local_t'})

    def test_a_task_missing_from_both_profiles_is_forgotten(self):
        for records in self.shared('local_t'):
            self.delete(records[0])
        self.assertEqual(self.retire(), (0, []))
        self.assertEqual(self.remembered(), {})
        self.assertEqual(self.trash(0) + self.trash(1), [])

    def test_any_doubt_keeps_the_surviving_copy(self):
        cases = {
            'other account pair': lambda: ACCOUNTS.replace('a', 'b'),
            'unreadable ledger': lambda: (self.home / ledger.LEDGER).write_text('{') and ACCOUNTS,
            'unreadable record where it went missing':
                lambda: (self.sides[0][1] / 'org' / 'local_bad.json').write_text('{') and ACCOUNTS,
            'second copy of the survivor':
                lambda: self.task(1, 'local_t', filename='local_t_copy') and ACCOUNTS,
        }
        for label, prepare in cases.items():
            with self.subTest(label):
                self.setUp()
                first, third = (records[0] for records in self.shared('local_t'))
                self.delete(first)
                self.assertEqual(self.retire(prepare()), (0, []))
                self.assertTrue(third.exists())
                self.assertEqual(self.trash(1), [])

    def test_a_profile_that_lost_every_shared_task_is_a_reset_not_deletions(self):
        records = self.shared('local_a', 'local_b')
        for record in records[0]:
            self.delete(record)
        self.assertEqual(self.retire(), (0, []))
        self.assertTrue(all(record.exists() for record in records[1]))

    def test_an_interrupted_transfer_is_recovered_before_deciding(self):
        first, third = (records[0] for records in self.shared('local_t'))
        stage = first.with_name('local_t.tmp-' + 'a' * 32)
        stage.mkdir()
        (stage / 'notes.txt').write_text('incoming')
        text = json.dumps({'sessionId': 'local_t', 'title': 'incoming'})
        tx = ledger._transaction
        manifest = tx.write_pair_manifest(self.sides[0][0], first, first.with_suffix(''),
                                          text, stage)
        with mock.patch.object(tx._publish, 'update_pair_manifest', side_effect=Crash):
            with self.assertRaises(Crash):
                tx.publish_pair(manifest, text)
        self.assertFalse(first.exists())  # displaced mid-transfer, not deleted
        self.assertEqual(self.retire(), (0, []))
        self.assertTrue(first.exists() and third.exists())
        self.assertEqual(self.trash(1), [])

    def move_failing_at_bundle(self, error):
        real, calls = ledger._publish.move_new, []

        def move(source, target):
            calls.append(source)
            if len(calls) == 2:
                raise error
            return real(source, target)
        return mock.patch.object(ledger._publish, 'move_new', side_effect=move)

    def test_a_failed_move_puts_the_copy_back(self):
        first, third = (records[0] for records in self.shared('local_t'))
        self.delete(first)
        saved = third.read_bytes()
        with self.move_failing_at_bundle(OSError('disk busy')):
            self.assertEqual(self.retire(), (0, []))
        self.assertEqual(third.read_bytes(), saved)
        self.assertTrue((third.with_suffix('') / 'notes.txt').exists())
        self.assertEqual(self.trash(1), [])
        self.assertEqual(set(self.remembered()), {'local_t'})

    def test_a_crash_between_record_and_bundle_is_undone_then_finished(self):
        first, third = (records[0] for records in self.shared('local_t'))
        self.delete(first)
        with self.move_failing_at_bundle(Crash()):
            with self.assertRaises(Crash):
                self.retire()
        [entry] = self.trash(1)
        self.assertFalse(third.exists())
        self.assertTrue((entry / third.name).exists() and third.with_suffix('').exists())
        self.assertEqual(self.retire(), (1, []))
        [finished] = self.trash(1)
        self.assertNotEqual(finished, entry)
        self.assertEqual(json.loads((finished / ledger.JOURNAL).read_text())['phase'], 'retired')
        self.assertEqual((finished / 'local_t' / 'notes.txt').read_text(), 'task file 1')

    def test_an_unrestorable_retirement_is_reported_and_left_for_inspection(self):
        for conflict in ('original recreated', 'trashed copy changed'):
            with self.subTest(conflict):
                self.setUp()
                first, third = (records[0] for records in self.shared('local_t'))
                self.delete(first)
                with self.move_failing_at_bundle(Crash()):
                    with self.assertRaises(Crash):
                        self.retire()
                [entry] = self.trash(1)
                if conflict == 'original recreated':
                    self.task(1, 'local_t', title='recreated')
                else:
                    (entry / third.name).write_text(json.dumps({'sessionId': 'local_t'}))
                saved = (entry / third.name).read_bytes()
                self.assertEqual(self.retire(), (0, ['retire-conflict']))
                self.assertEqual((entry / third.name).read_bytes(), saved)
                self.assertEqual(json.loads((entry / ledger.JOURNAL).read_text())['phase'],
                                 'prepared')
                self.assertEqual(third.exists(), conflict == 'original recreated')


if __name__ == '__main__':
    unittest.main()
