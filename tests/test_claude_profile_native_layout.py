"""Native full and abbreviated bundle paths preserve exact session identity."""
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

from tests import claude_profile_sync_fixtures as fixtures
from tests.claude_profile_sync_fixtures import PairFixture, SyncFixture, sync
from tests.test_claude_profile_recovery import WORKER


STORE = 'local-agent-mode-sessions'
IDENTIFIER = 'local_12345678-1234-4567-8123-123456789abc'


class NativeLayoutTests(SyncFixture):
    def record(self, profile, title, *, short=True, org=None):
        config = json.loads((profile / 'config.json').read_bytes())
        record = fixtures.record(profile, STORE, config['lastKnownAccountUuid'],
                                 org or config['lastKnownOrganizationUuid'], IDENTIFIER,
                                 filename=IDENTIFIER + '.json', title=title,
                                 cli='exact-cli', cwd='/external/workspace', transcript=title,
                                 bundle_files={title + '.txt': title, 'conflict.txt': title})
        doc = json.loads(record.read_bytes())
        doc['sessionType'] = 'agent'
        record.write_text(json.dumps(doc))
        agent = record.parent / 'agent'
        agent.mkdir(exist_ok=True)
        record.with_suffix('').rename(agent / record.stem)
        record.rename(agent / record.name)
        record = agent / record.name
        bundle = record.with_suffix('')
        if short:
            bundle.rename(agent / '12345678')
            bundle = agent / '12345678'
        (bundle / 'artifact.json').write_text(json.dumps({'path': str(bundle / 'result.txt')}))
        return record, bundle

    def test_short_and_full_bundles_round_trip_with_duplicate_cleanup(self):
        for short in (True, False):
            with self.subTest(active_short=short):
                self.setUp()
                first, first_bundle = self.record(self.first, 'active', short=short)
                third, third_bundle = self.record(self.third, 'inactive')
                stale, stale_bundle = self.record(self.third, 'stale', org='stale-org')
                for profile in (self.first, self.third):
                    fixtures.write_sentinels(profile)
                report = self.sync('1p')
                self.assertEqual((report['failed'], report['pending']), (0, 0), report)
                for record, bundle in ((first, first_bundle), (third, third_bundle)):
                    doc = json.loads(record.read_bytes())
                    self.assertEqual((doc['sessionId'], doc['cliSessionId'], doc['cwd']),
                                     (IDENTIFIER, 'exact-cli', '/external/workspace'))
                    self.assertEqual((doc['title'], record.parent.name), ('active', 'agent'))
                    self.assertEqual((bundle / 'conflict.txt').read_text(), 'active')
                    for title in ('active', 'inactive', 'stale'):
                        self.assertEqual((bundle / (title + '.txt')).read_text(), title)
                    self.assertEqual(json.loads((bundle / 'artifact.json').read_bytes()),
                                     {'path': str(bundle / 'result.txt')})
                    self.assertNotIn('creds', [path.name for path in bundle.rglob('*')])
                self.assertFalse(stale.exists())
                self.assertFalse(stale_bundle.exists())
                self.assertFalse(third.with_suffix('').exists())
                before = (fixtures.fingerprint(self.first), fixtures.fingerprint(self.third))
                report = self.sync('1p')
                self.assertEqual((report['failed'], report['copied'], report['replaced']), (0, 0, 0))
                self.assertEqual(before, (fixtures.fingerprint(self.first), fixtures.fingerprint(self.third)))

    def test_new_target_uses_full_bundle_without_abandoning_existing_short_bundle(self):
        source, short = self.record(self.third, 'source')
        report = self.sync()
        self.assertEqual(report['failed'], 0, report)
        target = self.paths(self.first, STORE, IDENTIFIER)[0]
        self.assertEqual((target.with_suffix('') / 'source.txt').read_text(), 'source')
        self.assertEqual((short / 'source.txt').read_text(), 'source')
        self.assertFalse(source.with_suffix('').exists())

    def test_two_sessions_cannot_claim_the_same_short_bundle(self):
        record, bundle = self.record(self.third, 'source')
        other = record.with_name(IDENTIFIER.replace('-1234-', '-5678-') + '.json')
        other.write_text(json.dumps({'sessionId': other.stem, 'title': 'other'}))
        before = fixtures.fingerprint(self.third / STORE)
        report = self.sync()
        self.assertEqual(report['failed'], 2, report)
        self.assertEqual(before, fixtures.fingerprint(self.third / STORE))
        self.assertEqual(self.paths(self.first, STORE, IDENTIFIER), [])
        self.assertEqual((bundle / 'source.txt').read_text(), 'source')

    def test_native_full_bundle_takes_precedence_over_unused_short_directory(self):
        record, full = self.record(self.third, 'source', short=False)
        short = record.parent / '12345678'
        short.mkdir()
        (short / 'unrelated.txt').write_text('unrelated')
        before = fixtures.fingerprint(short)
        report = self.sync()
        self.assertEqual(report['failed'], 0, report)
        target = self.paths(self.first, STORE, IDENTIFIER)[0].with_suffix('')
        self.assertEqual((target / 'source.txt').read_text(), 'source')
        self.assertFalse((target / 'unrelated.txt').exists())
        self.assertEqual(before, fixtures.fingerprint(short))
        self.assertTrue(full.exists())

    def test_late_full_bundle_is_preserved_and_prevents_short_bundle_publication(self):
        record, short = self.record(self.first, 'active')
        self.record(self.third, 'incoming')
        before = fixtures.fingerprint(short)
        stage_union = sync._stage_union

        def late(*args, **kwargs):
            stage = stage_union(*args, **kwargs)
            record.with_suffix('').mkdir()
            (record.with_suffix('') / 'late.txt').write_text('late writer')
            return stage

        with mock.patch.object(sync, '_stage_union', side_effect=late):
            report = self.sync()
        self.assertEqual(report['failed'], 1, report)
        self.assertEqual(before, fixtures.fingerprint(short))
        self.assertEqual((record.with_suffix('') / 'late.txt').read_text(), 'late writer')
        self.assertEqual(json.loads(record.read_bytes())['title'], 'active')


class NativeLayoutRecoveryTests(PairFixture):
    def setUp(self):
        super().setUp()
        self.store.rename(self.root / STORE)
        self.store = self.root / STORE
        self.ns = self.store / 'account' / 'org'
        (self.ns / 'local_same.json').rename(self.ns / (IDENTIFIER + '.json'))
        (self.ns / 'local_same').rename(self.ns / '12345678')
        (self.ns / ('local_same.tmp-' + 'a' * 32)).rename(self.ns / ('12345678.tmp-' + 'a' * 32))
        self.record = self.ns / (IDENTIFIER + '.json')
        self.bundle = self.ns / '12345678'
        self.stage = self.ns / ('12345678.tmp-' + 'a' * 32)
        self.record.write_text(json.dumps({'sessionId': IDENTIFIER, 'title': 'old'}))
        self.text = json.dumps({'sessionId': IDENTIFIER, 'title': 'new'})

    def test_short_bundle_recovers_every_publication_boundary(self):
        boundaries = [side + '-move-' + str(i) for side in ('before', 'after') for i in range(1, 5)]
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
                doc = json.loads(self.record.read_bytes())
                self.assertEqual((doc['sessionId'], doc['title']),
                                 (IDENTIFIER, 'new' if committed else 'old'))
                self.assertTrue((self.bundle / ('outputs/new.txt' if committed else 'outputs/old.txt')).exists())
                self.assertFalse(self.record.with_suffix('').exists())
                self.assertFalse(manifest.exists())

    def test_short_bundle_journal_cannot_claim_another_directory(self):
        manifest = self.manifest()
        original = json.loads(manifest.read_bytes())
        for patch in ({'bundle': 'account/org/87654321'}, {'session_id': 'different'},
                      {'record': 'account/org/local_different.json'}):
            with self.subTest(patch=patch):
                manifest.write_text(json.dumps(dict(original, **patch)))
                before = fixtures.fingerprint(self.store)
                errors = []
                self.transaction.recover_store(self.store, errors)
                self.assertTrue(errors)
                self.assertEqual(before, fixtures.fingerprint(self.store))

    def test_short_duplicate_survives_crashes_until_commit_then_is_cleaned(self):
        for boundary in ('before-move-3', 'after-move-3', 'before-move-4',
                         'after-move-4', 'committed'):
            with self.subTest(boundary=boundary):
                self.setUp()
                old = self.store / 'account' / 'old-org'
                old.mkdir()
                record, bundle = old / self.record.name, old / self.bundle.name
                record.write_bytes(self.record.read_bytes())
                bundle.mkdir()
                (bundle / 'unique.txt').write_text('unique')
                (self.stage / 'unique.txt').write_text('unique')
                before = {'record': self.publish.file_state(record),
                          'bundle': self.publish.tree_state(bundle)}
                manifest = self.manifest([{'record': record, 'bundle': bundle, 'before': before}])
                result = subprocess.run([sys.executable, '-c', WORKER,
                    str(Path(self.transaction.__file__)), str(manifest), boundary, self.text],
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 73, result.stderr)
                self.assertEqual(self.transaction.recover_store(self.store), 1)
                committed = boundary == 'committed'
                self.assertEqual(record.exists(), not committed)
                self.assertEqual(bundle.exists(), not committed)
                retained = self.bundle if committed else bundle
                self.assertEqual((retained / 'unique.txt').read_text(), 'unique')
