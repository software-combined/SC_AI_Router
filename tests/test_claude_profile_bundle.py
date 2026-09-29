"""The validated union and duplicates belong to one recoverable transaction."""
import json
from unittest import mock

from tests.claude_profile_sync_fixtures import PairFixture, load_helper


class ProfileBundleTests(PairFixture):
    def setUp(self):
        super().setUp()
        self.helper = load_helper('claude_profile_bundle')

    def consolidate(self):
        paths = sorted(self.store.glob('*/*/local_*.json'))
        duplicates = self.helper.duplicate_states(paths, self.record)
        inputs = [{'bundle': p.with_suffix(''), 'paths': (
            p.with_suffix(''), self.bundle, None, None)}
            for p in paths if p != self.record]
        stage = self.helper.stage_union(self.bundle, True, inputs, None)
        tx = self.helper._transaction
        manifest = tx.write_pair_manifest(self.store, self.record, self.bundle,
                                          self.record.read_text(), stage, duplicates=duplicates)
        try:
            tx.publish_pair(manifest, self.record.read_text())
        except Exception:
            tx.recover_store(self.store, errors=[])
            raise
        return len(duplicates)

    def test_duplicate_unique_content_and_empty_directories_join_before_publish(self):
        duplicate = self.duplicate()
        (duplicate.with_suffix('') / 'empty').mkdir()
        publisher = self.helper._transaction
        publish = publisher.publish_pair

        def inspect(manifest, text):
            doc = json.loads(manifest.read_text())
            stage = self.store / doc['stage']
            self.assertTrue((stage / 'unique.txt').exists())
            self.assertTrue((stage / 'empty').is_dir())
            self.assertEqual(len(doc['duplicates']), 1)
            self.assertTrue(duplicate.exists())
            return publish(manifest, text)

        with mock.patch.object(publisher, 'publish_pair', side_effect=inspect):
            self.assertEqual(self.consolidate(), 1)
        self.assertFalse(duplicate.exists())
        self.assertTrue((self.bundle / 'unique.txt').exists())
        self.assertTrue((self.bundle / 'empty').is_dir())

    def test_duplicate_task_files_join_the_union_with_exact_bytes(self):
        duplicate = self.duplicate()
        unique = duplicate.with_suffix('') / 'unique.json'
        unique.write_text(json.dumps({
            'accountName': 'task data', 'emailAddress': 'synthetic@example.invalid',
            'path': str(duplicate.with_suffix('') / 'unique.txt'), 'messages': []}, indent=2))
        raw = unique.read_bytes()
        self.assertEqual(self.consolidate(), 1)
        self.assertEqual((self.bundle / 'unique.json').read_bytes(), raw)
        self.assertFalse(duplicate.exists())

    def test_same_path_active_content_wins_and_shape_conflict_preserves_originals(self):
        duplicate = self.duplicate()
        (duplicate.with_suffix('') / 'outputs').mkdir()
        (duplicate.with_suffix('') / 'outputs/old.txt').write_text('inactive')
        self.assertEqual(self.consolidate(), 1)
        self.assertEqual((self.bundle / 'outputs/old.txt').read_text(), 'old')
        other = self.duplicate('shape')
        (other.with_suffix('') / 'outputs').write_text('only copy')
        with self.assertRaises(ValueError):
            self.consolidate()
        self.assertEqual((other.with_suffix('') / 'outputs').read_text(), 'only copy')
        self.assertTrue(other.exists())

    def test_excluded_duplicate_blocks_retirement(self):
        duplicate = self.duplicate()
        excluded = duplicate.with_suffix('') / 'password.txt'
        excluded.write_text('local only')
        with self.assertRaisesRegex(ValueError, 'excluded duplicate'):
            self.consolidate()
        self.assertEqual(excluded.read_text(), 'local only')
        self.assertTrue(duplicate.exists())

    def test_irregular_bundle_enumeration_skips_and_retirement_refuses(self):
        duplicate = self.duplicate()
        unsafe = duplicate.with_suffix('') / 'link'
        unsafe.symlink_to(self.record)
        files = self.helper._files(duplicate.with_suffix(''))
        self.assertNotIn('link', files)
        self.assertIn('unique.txt', files)
        with self.assertRaises(ValueError):
            self.consolidate()
        self.assertTrue(duplicate.exists())
        self.assertTrue(unsafe.is_symlink())

    def test_cleanup_failure_restores_every_duplicate_and_canonical_pair(self):
        duplicates = [self.duplicate('one'), self.duplicate('two')]
        pub = self.helper._transaction._publish
        move = pub.move_new

        def fail(source, target):
            if source == duplicates[-1].with_suffix(''):
                raise OSError('cleanup interrupted')
            move(source, target)

        with mock.patch.object(pub, 'move_new', side_effect=fail):
            with self.assertRaises(OSError):
                self.consolidate()
        for duplicate in duplicates:
            self.assertTrue(duplicate.exists())
            self.assertEqual((duplicate.with_suffix('') / 'unique.txt').read_text(), 'unique')
        self.assertEqual((self.bundle / 'outputs/old.txt').read_text(), 'old')

    def test_committed_cleanup_error_keeps_union_and_retries_owned_cleanup(self):
        duplicate = self.duplicate()
        pub = self.helper._transaction._publish
        with mock.patch.object(pub, 'finish', side_effect=PermissionError('cleanup')):
            with self.assertRaises(PermissionError):
                self.consolidate()
        self.assertEqual((self.bundle / 'unique.txt').read_text(), 'unique')
        self.helper._transaction.recover_store(self.store)
        self.assertFalse(duplicate.exists())
        self.assertFalse(list(self.store.glob('.claude-profile-transaction-*')))
