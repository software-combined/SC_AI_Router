"""End-to-end synthetic contract for two-way Claude profile sync."""
import json
from pathlib import Path
from unittest import mock

from tests import claude_profile_sync_fixtures as fixtures
from tests.claude_profile_sync_fixtures import SyncFixture, sync


class ProfileSyncSafetyTests(SyncFixture):
    def test_short_bundle_with_mismatched_identity_is_refused_without_losing_artifacts(self):
        self.sync()  # Establish the persistent synchronization locks before the snapshot.
        store = 'local-agent-mode-sessions'
        identifier = 'local_12345678-1234-4567-8123-123456789abc'
        record = fixtures.record(self.third, store, '87654321-4321-4567-8123-123456789abc', 'fedcbaab-4321-4567-8123-123456789abc',
                                 identifier, filename=identifier + '.json',
                                 bundle_files={'result.txt': 'must survive'})
        record.write_text(json.dumps({'sessionId': 'another-session', 'title': 'task'}))
        short = record.parent / '12345678'
        record.with_suffix('').rename(short)
        before = (fixtures.fingerprint(self.first), fixtures.fingerprint(self.third))
        report = self.sync()
        self.assertEqual(report['failed'], 1, report)
        self.assertIn('session-refused', report['errors'])
        self.assertEqual(before, (fixtures.fingerprint(self.first), fixtures.fingerprint(self.third)))
        self.assertFalse(record.with_suffix('').exists())
        self.assertEqual((short / 'result.txt').read_text(), 'must survive')

    def test_utf8_task_text_survives_a_windows_legacy_locale(self):
        title = 'Caf\u00e9 Fran\u00e7ais'
        for store in fixtures.STORES:
            record = fixtures.record(self.third, store, '87654321-4321-4567-8123-123456789abc',
                                     'fedcbaab-4321-4567-8123-123456789abc', 'unicode', cli='unicode-cli')
            doc = json.loads(record.read_bytes())
            doc['title'] = title
            record.write_bytes(json.dumps(doc, ensure_ascii=False).encode('utf-8'))
            transcript = record.with_suffix('') / 'unicode-cli.jsonl'
            transcript.parent.mkdir(exist_ok=True)
            transcript.write_bytes((json.dumps({'message': title},
                                               ensure_ascii=False) + '\n').encode('utf-8'))
        original_open = Path.open

        def legacy_open(path, mode='r', buffering=-1, encoding=None,
                        errors=None, newline=None):
            if 'b' not in mode and encoding in (None, 'locale'):
                encoding = 'cp1252'
            return original_open(path, mode, buffering, encoding, errors, newline)

        with mock.patch.object(Path, 'open', legacy_open):
            report = self.sync()
        self.assertEqual(report['failed'], 0, report)
        for store in fixtures.STORES:
            record = self.paths(self.first, store, 'unicode')[0]
            self.assertEqual(json.loads(record.read_bytes())['title'], title)
            transcript = record.with_suffix('') / 'unicode-cli.jsonl'
            self.assertEqual(json.loads(transcript.read_bytes())['message'], title)

    def test_identical_profiles_are_a_closed_set_refusal(self):
        with mock.patch.object(sync, 'profile_roots', return_value=(self.first, self.first)):
            report = sync.sync_profiles(self.home, '1p', self.env)
        self.assertEqual(report['failed'], 1)
        self.assertEqual(report['errors'], ['identical-profiles'])

    def test_missing_or_invalid_required_transcript_defers_only_that_session(self):
        for store in fixtures.STORES:
            for identifier, transcript in (('missing', None), ('corrupt', '{\n'),
                                           ('array', '[]\n')):
                record = fixtures.record(self.third, store, '87654321-4321-4567-8123-123456789abc', 'fedcbaab-4321-4567-8123-123456789abc',
                                         identifier, cli='exact-cli-' + identifier)
                if transcript is not None:
                    path = record.with_suffix('') / ("exact-cli-" + identifier + '.jsonl')
                    path.parent.mkdir()
                    path.write_text(transcript)
            fixtures.record(self.third, store, '87654321-4321-4567-8123-123456789abc', 'fedcbaab-4321-4567-8123-123456789abc', 'valid',
                            cli='Exact-Cli-ID', transcript='safe message')
        report = self.sync()
        self.assertEqual(report['failed'], 6, report)
        for store in fixtures.STORES:
            for identifier in ('missing', 'corrupt', 'array'):
                self.assertEqual(self.paths(self.first, store, identifier), [])
                self.assertEqual(len(self.paths(self.third, store, identifier)), 1)
            copied = self.paths(self.first, store, 'valid')[0]
            self.assertEqual(json.loads(copied.read_text())['cliSessionId'], 'Exact-Cli-ID')

    def test_symlink_nonregular_and_corrupt_sessions_do_not_abort_valid_sessions(self):
        import os
        for store in fixtures.STORES:
            for identifier in ('link', 'fifo', 'corrupt', 'valid'):
                record = fixtures.record(self.third, store, '87654321-4321-4567-8123-123456789abc', 'fedcbaab-4321-4567-8123-123456789abc',
                                         identifier, bundle_files={'safe.txt': 'safe'})
                bundle = record.with_suffix('')
                if identifier == 'link':
                    (bundle / 'unsafe').symlink_to(self.home)
                elif identifier == 'fifo' and hasattr(os, 'mkfifo'):
                    os.mkfifo(bundle / 'pipe')
                elif identifier == 'corrupt':
                    (bundle / 'data.json').write_text('{')
        report = self.sync()
        self.assertGreaterEqual(report['failed'], 4, report)
        for store in fixtures.STORES:
            self.assertEqual(len(self.paths(self.first, store, 'valid')), 1)
            self.assertEqual(self.paths(self.first, store, 'link'), [])
            self.assertEqual(self.paths(self.first, store, 'corrupt'), [])
            self.assertTrue(self.paths(self.third, store, 'link')[0].with_suffix('').joinpath('unsafe').is_symlink())

    def test_unsigned_target_is_pending_without_identity_or_publication(self):
        (self.first / 'config.json').write_text('{"oauthAccount":[]}')
        for store in fixtures.STORES:
            fixtures.record(self.third, store, '87654321-4321-4567-8123-123456789abc', 'fedcbaab-4321-4567-8123-123456789abc', 'pending',
                            bundle_files={'result.txt': 'only source copy'})
        before = fixtures.fingerprint(self.first)
        report = self.sync()
        self.assertEqual(report['pending'], 2, report)
        self.assertIn('identity-unresolved', report['errors'])
        self.assertEqual(before, tuple(row for row in fixtures.fingerprint(self.first)
                                       if row[0] != '.claude-profile-sync.lock'))

    def test_source_edit_during_publication_is_not_overwritten(self):
        source = fixtures.record(
            self.third, 'claude-code-sessions', '87654321-4321-4567-8123-123456789abc',
            'fedcbaab-4321-4567-8123-123456789abc', 'edited-source', title='original')
        original_write = sync._transaction.write_pair_manifest

        def write(*args, **kwargs):
            result = original_write(*args, **kwargs)
            doc = json.loads(source.read_text())
            doc['title'] = 'edited during sync'
            source.write_text(json.dumps(doc))
            return result

        with mock.patch.object(sync._transaction, 'write_pair_manifest',
                               side_effect=write):
            report = self.sync()
        self.assertGreater(report['failed'], 0)
        self.assertEqual(json.loads(source.read_text())['title'],
                         'edited during sync')

    def test_target_change_after_stage_is_refused_and_preserved(self):
        source = fixtures.record(
            self.third, 'claude-code-sessions', '87654321-4321-4567-8123-123456789abc',
            'fedcbaab-4321-4567-8123-123456789abc', 'late-target', title='source',
            bundle_files={'outputs/source.txt': 'source'})
        target = fixtures.record(
            self.first, 'claude-code-sessions', '12345678-1234-4567-8123-123456789abc',
            'abcdefab-1234-4567-8123-123456789abc', 'late-target', filename='local_target.json',
            title='target', bundle_files={'outputs/target.txt': 'target'})
        original_write = sync._transaction.write_pair_manifest

        def write(*args, **kwargs):
            late = target.with_suffix('') / 'outputs' / 'late.txt'
            late.write_text('created during sync')
            return original_write(*args, **kwargs)

        with mock.patch.object(sync._transaction, 'write_pair_manifest',
                               side_effect=write):
            report = self.sync('1p')
        self.assertGreater(report['failed'], 0)
        self.assertEqual(
            (target.with_suffix('') / 'outputs' / 'late.txt').read_text(),
            'created during sync')
        self.assertEqual(
            (target.with_suffix('') / 'outputs' / 'target.txt').read_text(),
            'target')
        self.assertTrue(source.exists())

    def test_source_bundle_edit_during_stage_is_refused(self):
        source = fixtures.record(
            self.third, 'claude-code-sessions', '87654321-4321-4567-8123-123456789abc',
            'fedcbaab-4321-4567-8123-123456789abc', 'late-source',
            bundle_files={'outputs/source.txt': 'original'})
        source_file = source.with_suffix('') / 'outputs' / 'source.txt'
        original_stage = sync._stage_union

        def stage(*args, **kwargs):
            result = original_stage(*args, **kwargs)
            source_file.write_text('edited during sync')
            return result

        with mock.patch.object(sync, '_stage_union', side_effect=stage):
            report = self.sync()
        self.assertGreater(report['failed'], 0)
        self.assertEqual(source_file.read_text(), 'edited during sync')

    def test_stale_namespace_moves_the_canonical_record_to_active_identity(self):
        account, org = '87654321-4321-4567-8123-123456789abc', 'fedcbaab-4321-4567-8123-123456789abc'
        stale = fixtures.record(
            self.third, 'claude-code-sessions', account, 'stale-org',
            'stale', filename='local_stale.json', title='stale',
            bundle_files={'outputs/stale.txt': 'stale'})
        report = self.sync()
        self.assertEqual(report['failed'], 0, report)
        paths = self.paths(self.third, 'claude-code-sessions', 'stale')
        self.assertEqual(len(paths), 1, paths)
        self.assertEqual(paths[0].parent.name, org)
        self.assertFalse(stale.exists())

    def test_private_modes_are_not_widened_and_new_bundles_are_private(self):
        source = fixtures.record(
            self.third, 'claude-code-sessions', '87654321-4321-4567-8123-123456789abc',
            'fedcbaab-4321-4567-8123-123456789abc', 'modes',
            bundle_files={'outputs/private.txt': 'source'})
        source_file = source.with_suffix('') / 'outputs' / 'private.txt'
        source_file.chmod(0o644)
        target = fixtures.record(
            self.first, 'claude-code-sessions', '12345678-1234-4567-8123-123456789abc',
            'abcdefab-1234-4567-8123-123456789abc', 'modes', filename='local_target.json',
            bundle_files={'outputs/private.txt': 'target'})
        target_file = target.with_suffix('') / 'outputs' / 'private.txt'
        target_file.chmod(0o600)
        fixtures.record(
            self.third, 'claude-code-sessions', '87654321-4321-4567-8123-123456789abc',
            'fedcbaab-4321-4567-8123-123456789abc', 'new-bundle',
            bundle_files={'outputs/new.txt': 'new'})
        report = self.sync()
        self.assertEqual(report['failed'], 0, report)
        self.assertEqual(target_file.stat().st_mode & 0o777, 0o600)
        new_bundle = (self.paths(
            self.first, 'claude-code-sessions', 'new-bundle')[0].with_suffix(''))
        self.assertEqual(new_bundle.stat().st_mode & 0o777, 0o700)

    def test_inactive_private_mode_is_not_widened_by_active_source(self):
        source = fixtures.record(
            self.first, 'claude-code-sessions', '12345678-1234-4567-8123-123456789abc',
            'abcdefab-1234-4567-8123-123456789abc', 'mode-winner',
            bundle_files={'outputs/private.txt': 'active'})
        source_file = source.with_suffix('') / 'outputs' / 'private.txt'
        source_file.chmod(0o644)
        target = fixtures.record(
            self.third, 'claude-code-sessions', '87654321-4321-4567-8123-123456789abc',
            'fedcbaab-4321-4567-8123-123456789abc', 'mode-winner', filename='local_target.json',
            bundle_files={'outputs/private.txt': 'inactive'})
        target_file = target.with_suffix('') / 'outputs' / 'private.txt'
        target_file.chmod(0o600)
        report = self.sync('3p')
        self.assertEqual(report['failed'], 0, report)
        self.assertEqual(target_file.stat().st_mode & 0o777, 0o600)

    def test_fallback_transcript_rewrites_profile_paths(self):
        namespace = fixtures.namespace(
            self.third, 'claude-code-sessions', '87654321-4321-4567-8123-123456789abc',
            'fedcbaab-4321-4567-8123-123456789abc')
        record = namespace / 'local_fallback.json'
        record.write_text(json.dumps({
            'sessionId': 'fallback', 'cliSessionId': 'cli-fallback',
            'cwd': str(self.third / 'work'),
        }))
        config = self.root / 'claude-config' / 'projects' / 'external'
        config.mkdir(parents=True)
        transcript = config / 'cli-fallback.jsonl'
        transcript.write_text(json.dumps({
            'cwd': str(self.third / 'work'), 'message': 'hello'}) + '\n')
        report = self.sync()
        self.assertEqual(report['failed'], 0, report)
        for profile_path in (self.first, self.third):
            path = self.paths(
                profile_path, 'claude-code-sessions', 'fallback')[0]
            copied = (path.with_suffix('') / '.claude' / 'projects' /
                      'session' / 'cli-fallback.jsonl')
            self.assertTrue(copied.exists())
            text = copied.read_text()
            self.assertIn(str(profile_path / 'work'), text)
            if profile_path == self.first:
                self.assertNotIn(str(self.third / 'work') + '"', text)

    def test_empty_bundle_directories_survive_replacement(self):
        source = fixtures.record(
            self.third, 'claude-code-sessions', '87654321-4321-4567-8123-123456789abc',
            'fedcbaab-4321-4567-8123-123456789abc', 'empty-dirs',
            bundle_files={'outputs/keep.txt': 'keep'})
        (source.with_suffix('') / 'outputs' / 'empty').mkdir()
        target = fixtures.record(
            self.first, 'claude-code-sessions', '12345678-1234-4567-8123-123456789abc',
            'abcdefab-1234-4567-8123-123456789abc', 'empty-dirs', filename='local_target.json',
            bundle_files={'outputs/keep.txt': 'target'})
        (target.with_suffix('') / 'outputs' / 'target-empty').mkdir()
        report = self.sync('1p')
        self.assertEqual(report['failed'], 0, report)
        target_bundle = target.with_suffix('')
        self.assertTrue((target_bundle / 'outputs' / 'empty').is_dir())
        self.assertTrue((target_bundle / 'outputs' / 'target-empty').is_dir())

    def test_symlinked_profile_root_is_refused(self):
        link = self.root / 'third-link'
        link.symlink_to(self.third, target_is_directory=True)
        env = dict(self.env, CLAUDE_USER_DATA_DIR=str(link))
        with mock.patch.object(sync, 'profile_roots', return_value=(self.first, link)):
            report = sync.sync_profiles(self.home, '1p', env)
        self.assertEqual(report['failed'], 1)
        self.assertEqual(report['errors'], ['unsafe-profile'])
