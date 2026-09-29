"""Abrupt process exits and malformed journals cannot discard session data."""
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

from tests.claude_profile_sync_fixtures import PairFixture, fingerprint


WORKER = '''
import importlib.util, os, pathlib, sys
spec = importlib.util.spec_from_file_location('tx', sys.argv[1])
tx = importlib.util.module_from_spec(spec); spec.loader.exec_module(tx)
manifest, boundary = pathlib.Path(sys.argv[2]), sys.argv[3]
pub = tx._publish
original = pub.move_new
count = 0
def move(source, target):
    global count
    count += 1
    if boundary == 'before-move-' + str(count): os._exit(73)
    original(source, target)
    if boundary == 'after-move-' + str(count): os._exit(73)
pub.move_new = move
update = pub.update_pair_manifest
def phase(path, name):
    result = update(path, name)
    if boundary == name: os._exit(73)
    return result
pub.update_pair_manifest = phase
tx.publish_pair(manifest, sys.argv[4])
'''


class ProfileRecoveryTests(PairFixture):
    def test_recovery_does_not_touch_another_accounts_journal(self):
        self.manifest()
        before = fingerprint(self.store)
        errors = []
        self.assertEqual(self.transaction.recover_store(
            self.store, errors, account=self.store / 'another-account'), 0)
        self.assertEqual(errors, [])
        self.assertEqual(fingerprint(self.store), before)
        self.assertEqual(self.transaction.recover_store(
            self.store, errors, account=self.ns.parent), 1)

    def test_abrupt_crash_at_each_duplicate_displacement_boundary(self):
        for index in range(1, 7):
            for side in ('before', 'after'):
                with self.subTest(index=index, side=side):
                    self.setUp()
                    duplicate = self.duplicate()
                    before = {'record': self.publish.file_state(duplicate),
                              'bundle': self.publish.tree_state(duplicate.with_suffix(''))}
                    (self.stage / 'unique.txt').write_text('unique')
                    manifest = self.manifest([{'record': duplicate, 'before': before}])
                    result = subprocess.run([sys.executable, '-c', WORKER,
                        str(Path(self.transaction.__file__)), str(manifest),
                        side + '-move-' + str(index), self.text],
                        capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 73, result.stderr)
                    self.assertEqual(self.transaction.recover_store(self.store), 1)
                    self.assertEqual(json.loads(self.record.read_text())['title'], 'old')
                    self.assertTrue(duplicate.exists())
                    self.assertEqual((duplicate.with_suffix('') / 'unique.txt').read_text(), 'unique')

    def test_changed_duplicate_backup_is_not_deleted_during_committed_cleanup(self):
        duplicate = self.duplicate()
        before = {'record': self.publish.file_state(duplicate),
                  'bundle': self.publish.tree_state(duplicate.with_suffix(''))}
        manifest = self.manifest([{'record': duplicate, 'before': before}])
        with mock.patch.object(self.publish, 'finish', side_effect=OSError('stop')):
            with self.assertRaises(OSError):
                self.transaction.publish_pair(manifest, self.text)
        doc = json.loads(manifest.read_text())
        saved = self.store / doc['duplicates'][0]['bundle_before'] / 'unique.txt'
        saved.write_text('changed duplicate content')
        snapshot = fingerprint(self.store)
        errors = []
        self.transaction.recover_store(self.store, errors)
        self.assertEqual(errors, ['recovery-conflict'])
        self.assertEqual(fingerprint(self.store), snapshot)

    def test_abrupt_crash_before_and_after_every_pair_boundary(self):
        boundaries = ['before-move-' + str(i) for i in range(1, 5)]
        boundaries += ['after-move-' + str(i) for i in range(1, 5)]
        boundaries += ['displaced', 'bundle-published', 'record-published', 'committed']
        for boundary in boundaries:
            with self.subTest(boundary=boundary):
                self.setUp()
                manifest = self.manifest()
                result = subprocess.run([sys.executable, '-c', WORKER,
                    str(Path(self.transaction.__file__)), str(manifest), boundary, self.text],
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 73, result.stderr)
                self.assertEqual(self.transaction.recover_store(self.store), 1)
                committed = boundary == 'committed'
                self.assertEqual(json.loads(self.record.read_text())['title'], 'new' if committed else 'old')
                self.assertTrue((self.bundle / ('outputs/new.txt' if committed else 'outputs/old.txt')).exists())
                self.assertFalse(manifest.exists())

    def test_interrupted_recovery_retries_without_losing_either_generation(self):
        manifest = self.manifest()
        update = self.publish.update_pair_manifest

        def interrupt(path, phase):
            update(path, phase)
            if phase == 'record-published':
                raise SystemExit('crash')

        with mock.patch.object(self.publish, 'update_pair_manifest', side_effect=interrupt):
            with self.assertRaises(SystemExit):
                self.transaction.publish_pair(manifest, self.text)
        move = self.publish.move_new
        calls = []

        def stop(source, target):
            move(source, target)
            calls.append(target)
            if len(calls) == 2:
                raise SystemExit('recovery crash')

        with mock.patch.object(self.publish, 'move_new', side_effect=stop):
            with self.assertRaises(SystemExit):
                self.transaction.recover_store(self.store)
        self.assertEqual(self.transaction.recover_store(self.store), 1)
        self.assertEqual(json.loads(self.record.read_text())['title'], 'old')
        self.assertEqual((self.bundle / 'outputs/old.txt').read_text(), 'old')

    def test_malformed_incomplete_and_unowned_journals_cause_no_mutation(self):
        manifest = self.manifest()
        complete = json.loads(manifest.read_text())
        mutations = [[], {}, {'version': 1, 'entries': []}]
        for key in complete:
            mutations.append({k: v for k, v in complete.items() if k != key})
        mutations += [dict(complete, stage=None), dict(complete, before=[]),
                      dict(complete, phase='committed'), dict(complete, duplicates=[{}]),
                      dict(complete, record_before='account/org/local_unowned.json')]
        for doc in mutations:
            with self.subTest(doc=doc):
                manifest.write_text(json.dumps(doc))
                before = fingerprint(self.store)
                errors = []
                self.assertEqual(self.transaction.recover_store(self.store, errors), 0)
                self.assertTrue(errors)
                self.assertTrue(set(errors) <= {'invalid-journal', 'recovery-conflict'})
                self.assertEqual(fingerprint(self.store), before)
        manifest.write_text('{')
        before = fingerprint(self.store)
        errors = []
        self.assertEqual(self.transaction.recover_store(self.store, errors), 0)
        self.assertEqual(errors, ['invalid-journal'])
        self.assertEqual(fingerprint(self.store), before)

    def test_unowned_backup_names_and_symlink_manifest_are_untouched(self):
        backup = self.ns / 'local_same.duplicate-backup-user.json'
        backup.write_text('unowned')
        external = self.root / 'external.json'
        external.write_text('[]')
        marker = self.store / ('.claude-profile-transaction-' + 'b' * 32 + '.json')
        marker.symlink_to(external)
        errors = []
        self.assertEqual(self.transaction.recover_store(self.store, errors), 0)
        self.assertEqual(errors, ['invalid-journal'])
        self.assertEqual(backup.read_text(), 'unowned')
        self.assertEqual(external.read_text(), '[]')

    def test_changed_committed_pair_keeps_all_backups(self):
        manifest = self.manifest()
        finish = self.publish.finish
        with mock.patch.object(self.publish, 'finish', side_effect=OSError('stop')):
            with self.assertRaises(OSError):
                self.transaction.publish_pair(manifest, self.text)
        self.record.write_text('late writer')
        before = fingerprint(self.store)
        errors = []
        self.transaction.recover_store(self.store, errors)
        self.assertEqual(errors, ['recovery-conflict'])
        self.assertEqual(fingerprint(self.store), before)

    def test_symlink_store_and_ancestor_never_traverse_or_create(self):
        link = self.root / 'link'
        link.symlink_to(self.store, target_is_directory=True)
        for root in (link, link / 'child'):
            with self.assertRaises(ValueError):
                self.transaction.recover_store(root)
        self.assertFalse((self.store / 'child').exists())
