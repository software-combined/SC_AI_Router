"""Observable races at the pair publisher, not retired helper APIs."""
import json
import os
import shutil
import unittest
from pathlib import Path
from unittest import mock

from tests.claude_profile_sync_fixtures import PairFixture


class ProfilePublishTests(PairFixture):
    @unittest.skipIf(os.name == 'nt', 'POSIX file permissions')
    def test_hardlinked_attachment_preserves_external_original_during_commit_and_recovery(self):
        for interrupted in (False, True):
            with self.subTest(interrupted=interrupted):
                self.setUp()
                original = self.root / 'original.txt'
                original.write_text('attachment contents')
                original.chmod(0o644)
                (self.bundle / 'uploads').mkdir()
                os.link(original, self.bundle / 'uploads/attachment.txt')
                (self.stage / 'uploads').mkdir()
                shutil.copy2(original, self.stage / 'uploads/attachment.txt')
                expected = (original.read_bytes(), original.stat().st_mode)
                manifest = self.manifest()
                update = self.publish.update_pair_manifest

                def interrupt(path, phase):
                    result = update(path, phase)
                    if interrupted and phase == 'bundle-published':
                        raise SystemExit('interrupted publication')
                    return result

                with mock.patch.object(self.publish, 'update_pair_manifest', side_effect=interrupt):
                    if interrupted:
                        with self.assertRaises(SystemExit):
                            self.transaction.publish_pair(manifest, self.text)
                        self.assertEqual((original.read_bytes(), original.stat().st_mode), expected)
                        self.assertEqual(self.transaction.recover_store(self.store), 1)
                    else:
                        self.transaction.publish_pair(manifest, self.text)
                self.assertEqual((original.read_bytes(), original.stat().st_mode), expected)
                self.assertEqual((self.bundle / 'uploads/attachment.txt').read_bytes(), expected[0])

    def test_publish_commits_and_cleans_exact_before_images(self):
        manifest = self.manifest()
        self.assertEqual(self.transaction.publish_pair(manifest, self.text), (True, True))
        self.assertEqual(json.loads(self.record.read_text())['title'], 'new')
        self.assertEqual((self.bundle / 'outputs/new.txt').read_text(), 'new')
        self.assertFalse(manifest.exists())
        self.assertFalse(any('.before-' in p.name for p in self.store.rglob('*')))

    def test_record_cas_rejects_concurrent_change_and_recovery_retains_it(self):
        manifest = self.manifest()
        self.record.write_text('{"sessionId":"same","title":"late"}')
        with self.assertRaises(ValueError):
            self.transaction.publish_pair(manifest, self.text)
        with self.assertRaises(ValueError):
            self.transaction.recover_store(self.store)
        self.assertEqual(json.loads(self.record.read_text())['title'], 'late')
        self.assertTrue(manifest.exists())

    def test_actual_displaced_generation_is_validated_for_record_and_bundle(self):
        for kind in ('record', 'bundle'):
            with self.subTest(kind=kind):
                self.setUp()
                manifest = self.manifest()
                move = self.publish.move_new
                target = self.record if kind == 'record' else self.bundle

                def late(source, destination):
                    if source == target:
                        if kind == 'record':
                            source.write_text('{"sessionId":"same","title":"late"}')
                        else:
                            (source / 'late.txt').write_text('late')
                    move(source, destination)

                with mock.patch.object(self.publish, 'move_new', side_effect=late):
                    with self.assertRaises(ValueError):
                        self.transaction.publish_pair(manifest, self.text)
                doc = json.loads(manifest.read_text())
                backup = self.store / doc[kind + '_before']
                self.assertTrue(backup.exists())
                self.assertTrue(self.stage.exists())
                with self.assertRaises(ValueError):
                    self.transaction.recover_store(self.store)
                self.assertIn('late', (backup.read_text() if kind == 'record'
                                      else (backup / 'late.txt').read_text()))

    def test_exclusive_publication_preserves_late_record_and_empty_directory(self):
        for kind in ('record', 'bundle'):
            with self.subTest(kind=kind):
                self.setUp()
                manifest = self.manifest()
                doc = json.loads(manifest.read_text())
                target = self.record if kind == 'record' else self.bundle
                stage = self.store / doc['record_stage' if kind == 'record' else 'stage']
                move = self.publish.move_new

                def late(source, destination):
                    if source == stage:
                        if kind == 'record':
                            destination.write_text('late writer')
                        else:
                            destination.mkdir()
                    move(source, destination)

                with mock.patch.object(self.publish, 'move_new', side_effect=late):
                    with self.assertRaises(OSError):
                        self.transaction.publish_pair(manifest, self.text)
                self.assertTrue(stage.exists())
                self.assertTrue((self.store / doc[kind + '_before']).exists())
                self.assertEqual(target.read_text() if kind == 'record' else list(target.iterdir()),
                                 'late writer' if kind == 'record' else [])

    def test_interrupted_new_record_publication_leaves_no_partial_record(self):
        self.record.unlink()
        manifest = self.manifest()
        move = self.publish.move_new

        def crash(source, target):
            if target == self.record:
                raise SystemExit('crash')
            move(source, target)

        with mock.patch.object(self.publish, 'move_new', side_effect=crash):
            with self.assertRaises(SystemExit):
                self.transaction.publish_pair(manifest, self.text)
        self.assertFalse(self.record.exists())
        self.assertEqual(self.transaction.recover_store(self.store), 1)
        self.assertFalse(self.record.exists())
        self.assertTrue((self.bundle / 'outputs/old.txt').exists())

    def test_recreated_duplicate_retains_journal_and_both_versions(self):
        duplicate = self.duplicate()
        before = {'record': self.publish.file_state(duplicate),
                  'bundle': self.publish.tree_state(duplicate.with_suffix(''))}
        manifest = self.manifest([{'record': duplicate, 'before': before}])
        move = self.publish.move_new

        def recreate(source, target):
            move(source, target)
            if source == duplicate:
                source.write_text('{"sessionId":"same","title":"late"}')

        with mock.patch.object(self.publish, 'move_new', side_effect=recreate):
            with self.assertRaises(ValueError):
                self.transaction.publish_pair(manifest, self.text)
        with self.assertRaises(ValueError):
            self.transaction.recover_store(self.store)
        self.assertEqual(json.loads(duplicate.read_text())['title'], 'late')
        doc = json.loads(manifest.read_text())
        self.assertIn('duplicate', (self.store / doc['duplicates'][0]['record_before']).read_text())

    def test_changed_before_image_is_never_deleted_after_commit(self):
        manifest = self.manifest()
        update = self.publish.update_pair_manifest

        def change(path, phase):
            result = update(path, phase)
            if phase == 'committed':
                doc = json.loads(path.read_text())
                (self.store / doc['record_before']).write_text('late backup writer')
            return result

        with mock.patch.object(self.publish, 'update_pair_manifest', side_effect=change):
            with self.assertRaises(ValueError):
                self.transaction.publish_pair(manifest, self.text)
        doc = json.loads(manifest.read_text())
        self.assertEqual((self.store / doc['record_before']).read_text(), 'late backup writer')
        self.assertTrue((self.store / doc['bundle_before']).exists())

    def test_before_images_are_private_and_flushed_before_commit(self):
        manifest = self.manifest()
        update = self.publish.update_pair_manifest
        flushed = []
        flush = self.publish.flush

        def observe(path, protect=False):
            flushed.append(Path(path))
            return flush(path, protect)

        def check(path, phase):
            if phase == 'committed':
                doc = json.loads(path.read_text())
                for key in ('record_before', 'bundle_before'):
                    artifact = self.store / doc[key]
                    self.assertIn(artifact, flushed)
                    if os.name != 'nt':
                        self.assertEqual(artifact.stat().st_mode & 0o077, 0)
                        self.assertEqual(artifact.parent.stat().st_mode & 0o077, 0)
                if os.name != 'nt':
                    self.assertEqual(path.stat().st_mode & 0o077, 0)
            return update(path, phase)

        with mock.patch.object(self.publish, 'flush', side_effect=observe), mock.patch.object(
                self.publish, 'update_pair_manifest', side_effect=check):
            self.transaction.publish_pair(manifest, self.text)

    def test_windows_private_controls_use_winacl(self):
        with mock.patch.object(self.publish.os, 'name', 'nt'), mock.patch.object(
                self.publish._winacl, 'require_owner_only') as gate:
            self.publish.private(self.record)
        gate.assert_called_once_with(self.record, windows=True)
