"""End-to-end synthetic contract for two-way Claude profile sync."""
import json

from tests import claude_profile_sync_fixtures as fixtures
from tests.claude_profile_sync_fixtures import SyncFixture, sync


class ProfileSyncTests(SyncFixture):
    def test_agent_subdirectory_round_trip_preserves_layout_and_active_outputs(self):
        fixtures.share_cowork(self)
        store = 'local-agent-mode-sessions'
        for profile, account, org, title in (
                (self.first, '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc', 'active'),
                (self.third, '87654321-4321-4567-8123-123456789abc', 'fedcbaab-4321-4567-8123-123456789abc', 'inactive')):
            record = fixtures.record(profile, store, account, org, 'agent-task',
                                     title=title, cwd='/external/workspace',
                                     bundle_files={title + '.txt': title, 'conflict.txt': title})
            doc = json.loads(record.read_bytes())
            doc['sessionType'] = 'agent'
            record.write_bytes(json.dumps(doc).encode('utf-8'))
            directory = record.parent / 'agent'
            directory.mkdir()
            record.with_suffix('').rename(directory / record.stem)
            record.rename(directory / record.name)
        report = self.sync('1p')
        self.assertEqual(report['failed'], 0, report)
        self.assertGreater(report['replaced'], 0, report)
        for profile in (self.first, self.third):
            record = self.paths(profile, store, 'agent-task')[0]
            self.assertEqual(record.parent.name, 'agent')
            doc = json.loads(record.read_bytes())
            self.assertEqual((doc['title'], doc['cwd']), ('active', '/external/workspace'))
            bundle = record.with_suffix('')
            self.assertEqual((bundle / 'conflict.txt').read_text(), 'active')
            self.assertTrue((bundle / 'active.txt').is_file())
            self.assertTrue((bundle / 'inactive.txt').is_file())
        before = (fixtures.fingerprint(self.first), fixtures.fingerprint(self.third))
        report = self.sync('1p')
        self.assertEqual((report['failed'], report['copied'], report['replaced']), (0, 0, 0))
        self.assertEqual(before, (fixtures.fingerprint(self.first), fixtures.fingerprint(self.third)))

    def test_active_namespace_record_wins_and_other_org_copies_are_untouched(self):
        other_orgs = {}
        for store in sync.STORES:
            active = fixtures.record(self.first, store, '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc', 'same',
                filename='local_active.json', title='active', bundle_files={'same.txt': 'active'})
            doc = json.loads(active.read_text())
            doc['messages'] = []
            active.write_text(json.dumps(doc))
            stale = fixtures.record(self.first, store, '12345678-1234-4567-8123-123456789abc', 'stale-org', 'same',
                filename='local_incoming.json', title='stale', bundle_files={'stale.txt': 'stale'})
            (stale.with_suffix('') / 'empty').mkdir()
            other_orgs[stale.parent] = fixtures.fingerprint(stale.parent)
            fixtures.record(self.third, store, '87654321-4321-4567-8123-123456789abc', 'fedcbaab-4321-4567-8123-123456789abc', 'same',
                filename='local_incoming.json', title='inactive', bundle_files={'same.txt': 'inactive'})
        report = self.sync()
        self.assertEqual(report['failed'], 0, report)
        self.assertEqual({path: fixtures.fingerprint(path) for path in other_orgs}, other_orgs)
        for store in sync.STORES:
            for profile in (self.first, self.third):
                paths = [path for path in self.paths(profile, store, 'same')
                         if path.parent.name != 'stale-org']
                self.assertEqual(len(paths), 1)
                doc = json.loads(paths[0].read_text())
                self.assertEqual((doc['title'], doc['messages']), ('active', []))
                self.assertEqual((paths[0].with_suffix('') / 'same.txt').read_text(), 'active')
                self.assertFalse((paths[0].with_suffix('') / 'stale.txt').exists())

    def test_tasks_sync_in_both_directions_and_keep_external_paths(self):
        source = fixtures.record(
            self.third, 'claude-code-sessions', '87654321-4321-4567-8123-123456789abc',
            'fedcbaab-4321-4567-8123-123456789abc', 'source-code', cli='cli-source',
            cwd='/Users/test/N8N', bundle_files={
                'outputs/result.txt': 'source',
                'outputs/unique.txt': 'unique',
            }, transcript='hello')
        fixtures.target_only(
            self.first, 'claude-code-sessions', '12345678-1234-4567-8123-123456789abc',
            'abcdefab-1234-4567-8123-123456789abc', 'target-local')
        report = self.sync()
        self.assertEqual(report['failed'], 0, report)
        for profile_path in (self.first, self.third):
            for identifier in ('source-code', 'target-local'):
                paths = self.paths(profile_path, 'claude-code-sessions', identifier)
                self.assertEqual(len(paths), 1, (profile_path, identifier, paths))
                doc = json.loads(paths[0].read_text())
                self.assertEqual(doc['sessionId'], identifier)
                if identifier == 'source-code':
                    self.assertEqual(doc['cwd'], '/Users/test/N8N')
                    self.assertEqual(
                        (paths[0].with_suffix('') / 'outputs' /
                         'unique.txt').read_text(), 'unique')
        self.assertTrue(source.exists())

    def test_active_profile_wins_conflicts_but_unique_files_survive(self):
        for profile_path, title, result, unique in (
                (self.first, 'active', 'active-result', 'active-unique'),
                (self.third, 'inactive', 'inactive-result', 'inactive-unique')):
            account = json.loads((profile_path / 'config.json').read_text())[
                'lastKnownAccountUuid']
            org = json.loads((profile_path / 'config.json').read_text())[
                'lastKnownOrganizationUuid']
            fixtures.record(
                profile_path, 'claude-code-sessions', account, org, 'shared',
                title=title, bundle_files={
                    'outputs/result.txt': result,
                    'outputs/' + unique + '.txt': unique,
                })
        self.sync('1p')
        for profile_path in (self.first, self.third):
            path = self.paths(
                profile_path, 'claude-code-sessions', 'shared')[0]
            self.assertEqual(json.loads(path.read_text())['title'], 'active')
            bundle = path.with_suffix('')
            self.assertEqual((bundle / 'outputs' / 'result.txt').read_text(),
                             'active-result')
            self.assertTrue((bundle / 'outputs' / 'active-unique.txt').exists())
            self.assertTrue((bundle / 'outputs' / 'inactive-unique.txt').exists())

    def test_existing_target_filename_remains_canonical(self):
        account, org = '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc'
        source_account, source_org = '87654321-4321-4567-8123-123456789abc', 'fedcbaab-4321-4567-8123-123456789abc'
        source = fixtures.record(
            self.third, 'claude-code-sessions', source_account, source_org,
            'renamed', filename='local_source.json', title='inactive',
            bundle_files={'outputs/inactive.txt': 'inactive'})
        target = fixtures.record(
            self.first, 'claude-code-sessions', account, org,
            'renamed', filename='local_target.json', title='active',
            bundle_files={'outputs/active.txt': 'active'})
        report = self.sync('1p')
        self.assertEqual(report['failed'], 0, report)
        self.assertTrue(target.exists())
        self.assertFalse(source.with_name('local_target.json').exists())
        target_bundle = target.with_suffix('')
        self.assertEqual(
            (target_bundle / 'outputs' / 'active.txt').read_text(), 'active')
        self.assertEqual(
            (target_bundle / 'outputs' / 'inactive.txt').read_text(),
            'inactive')

    def test_other_org_copy_is_neither_moved_nor_overwritten(self):
        source = fixtures.record(
            self.third, 'claude-code-sessions', '87654321-4321-4567-8123-123456789abc',
            'fedcbaab-4321-4567-8123-123456789abc', 'namespace-move',
            filename='local_source.json', title='inactive',
            bundle_files={'outputs/result.txt': 'inactive'})
        target_namespace = fixtures.namespace(
            self.first, 'claude-code-sessions', '12345678-1234-4567-8123-123456789abc', 'stale-org')
        target = fixtures.record(
            self.first, 'claude-code-sessions', '12345678-1234-4567-8123-123456789abc', 'stale-org',
            'namespace-move', filename='local_target.json', title='active',
            bundle_files={'outputs/result.txt': 'active'})
        before = fixtures.fingerprint(target_namespace), fixtures.fingerprint(source.parent)
        report = self.sync('1p')
        self.assertEqual(report['failed'], 0, report)
        self.assertEqual((fixtures.fingerprint(target_namespace),
                          fixtures.fingerprint(source.parent)), before)
        self.assertEqual(self.paths(self.first, 'claude-code-sessions', 'namespace-move'),
                         [target])

    def test_excluded_duplicate_is_not_deleted(self):
        account, org = '87654321-4321-4567-8123-123456789abc', 'fedcbaab-4321-4567-8123-123456789abc'
        fixtures.duplicate(
            self.third, 'claude-code-sessions', account, org, 'excluded',
            'one', title='duplicate',
            bundle_files={'outputs/other.txt': 'other'})
        fixtures.duplicate(
            self.third, 'claude-code-sessions', account, org, 'excluded',
            'two', title='duplicate',
            bundle_files={'outputs/password.txt': 'local only'})
        report = self.sync()
        self.assertGreater(report['failed'], 0)
        paths = self.paths(
            self.third, 'claude-code-sessions', 'excluded')
        self.assertEqual(len(paths), 2, paths)
        self.assertTrue(any(
            (path.with_suffix('') / 'outputs' / 'password.txt').exists()
            for path in paths))

    def test_target_only_records_and_second_run_are_idempotent(self):
        fixtures.target_only(
            self.first, 'claude-code-sessions', '12345678-1234-4567-8123-123456789abc',
            'abcdefab-1234-4567-8123-123456789abc', 'only-target')
        first = self.sync()
        after_first = fixtures.fingerprint(self.root)
        second = self.sync()
        after_second = fixtures.fingerprint(self.root)
        self.assertEqual(first['failed'], 0)
        self.assertEqual(second['failed'], 0)
        self.assertEqual(after_first, after_second)
        self.assertEqual(second['copied'], 0)
        self.assertEqual(second['replaced'], 0)

    def test_credentials_identity_and_profile_settings_never_cross(self):
        fixtures.write_sentinels(self.third)
        fixtures.write_sentinels(self.first)
        before_third = fixtures.fingerprint(self.third / 'creds')
        before_first = fixtures.fingerprint(self.first / 'creds')
        source = fixtures.record(
            self.third, 'claude-code-sessions', '87654321-4321-4567-8123-123456789abc',
            'fedcbaab-4321-4567-8123-123456789abc', 'safe-session',
            title='safe title',
            local_secret='synthetic-target-local-value',
            bundle_files={'outputs/password.txt': 'password: synthetic-value'})
        source_doc = json.loads(source.read_text())
        source_doc['emailAddress'] = 'source@example.invalid'
        source.write_text(json.dumps(source_doc))
        report = self.sync()
        self.assertEqual((report['failed'], report['copied']), (0, 1), report)
        self.assertEqual(fixtures.fingerprint(self.third / 'creds'),
                         before_third)
        self.assertEqual(fixtures.fingerprint(self.first / 'creds'),
                         before_first)
        for path in self.first.rglob('*'):
            self.assertNotIn('source@example.invalid',
                             path.read_text(errors='ignore')
                             if path.is_file() else '')

    def test_profile_settings_in_bundles_never_cross(self):
        source = fixtures.record(
            self.third, 'claude-code-sessions', '87654321-4321-4567-8123-123456789abc',
            'fedcbaab-4321-4567-8123-123456789abc', 'settings',
            bundle_files={
                '.claude/settings.json': '{"permissions":{"allow":["Bash"]}}',
                '.claude/managed-settings.json': '{"managed":true}',
                'outputs/safe.txt': 'safe',
            })
        target = fixtures.record(
            self.first, 'claude-code-sessions', '12345678-1234-4567-8123-123456789abc',
            'abcdefab-1234-4567-8123-123456789abc', 'settings',
            bundle_files={'.claude/settings.json': '{"target":true}'})
        report = self.sync()
        self.assertEqual(report['failed'], 0, report)
        target_bundle = target.with_suffix('')
        self.assertEqual(
            (target_bundle / '.claude' / 'settings.json').read_text(),
            '{"target":true}')
        self.assertFalse(
            (target_bundle / '.claude' / 'managed-settings.json').exists())
        self.assertEqual(
            (target_bundle / 'outputs' / 'safe.txt').read_text(), 'safe')
        self.assertTrue(source.exists())

    def test_duplicate_records_converge_and_keep_unique_bundle_files(self):
        account, org = '87654321-4321-4567-8123-123456789abc', 'fedcbaab-4321-4567-8123-123456789abc'
        fixtures.duplicate(
            self.third, 'claude-code-sessions', account, org, 'duplicate',
            'one', title='duplicate',
            bundle_files={'outputs/one.txt': 'one'})
        fixtures.duplicate(
            self.third, 'claude-code-sessions', account, org, 'duplicate',
            'two', title='duplicate',
            bundle_files={'outputs/two.txt': 'two'})
        report = self.sync()
        self.assertEqual(report['failed'], 0, report)
        for profile_path in (self.first, self.third):
            paths = self.paths(
                profile_path, 'claude-code-sessions', 'duplicate')
            self.assertEqual(len(paths), 1, paths)
            bundle = paths[0].with_suffix('')
            self.assertEqual((bundle / 'outputs' / 'one.txt').read_text(), 'one')
            self.assertEqual((bundle / 'outputs' / 'two.txt').read_text(), 'two')

    def test_bad_record_fails_alone_and_valid_session_still_syncs(self):
        account, org = '87654321-4321-4567-8123-123456789abc', 'fedcbaab-4321-4567-8123-123456789abc'
        namespace = fixtures.namespace(
            self.third, 'claude-code-sessions', account, org)
        (namespace / 'local_bad.json').write_text('{')
        fixtures.record(
            self.third, 'claude-code-sessions', account, org, 'valid')
        report = self.sync()
        self.assertGreater(report['failed'], 0)
        self.assertEqual(
            len(self.paths(self.first, 'claude-code-sessions', 'valid')), 1)
