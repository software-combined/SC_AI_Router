"""Only the selected account participates in a profile switch."""
import json

from tests import claude_profile_sync_fixtures as fixtures
from tests.claude_profile_sync_fixtures import SyncFixture


class AccountScopeTests(SyncFixture):
    def test_signing_into_a_different_account_cannot_import_the_previous_users_tasks(self):
        fixtures.record(self.first, 'claude-code-sessions',
                        '12345678-1234-4567-8123-123456789abc',
                        'abcdefab-1234-4567-8123-123456789abc', 'original-account-task')
        self.assertEqual(self.sync()['failed'], 0)
        config = self.first / 'config.json'
        doc = json.loads(config.read_text())
        doc['lastKnownAccountUuid'] = '99999999-1234-4567-8123-123456789abc'
        config.write_text(json.dumps(doc))
        before = fixtures.fingerprint(self.first), fixtures.fingerprint(self.third)
        report = self.sync()
        self.assertGreater(report['failed'] + report['pending'], 0, report)
        self.assertEqual((fixtures.fingerprint(self.first), fixtures.fingerprint(self.third)), before)

    def test_previous_accounts_are_untouched_and_do_not_block_current_tasks(self):
        previous = '99999999-1234-4567-8123-123456789abc'
        saved = {}
        for profile, account, org in (
                (self.first, '12345678-1234-4567-8123-123456789abc',
                 'abcdefab-1234-4567-8123-123456789abc'),
                (self.third, '87654321-4321-4567-8123-123456789abc',
                 'fedcbaab-4321-4567-8123-123456789abc')):
            for store in fixtures.STORES:
                fixtures.record(profile, store, account, org, 'current',
                                cli='current-cli', transcript='current messages')
                foreign = fixtures.record(profile, store, previous, org, 'current',
                                          cli='missing-cli', title='previous account',
                                          bundle_files={'old.txt': 'old output'})
                fixtures.record(profile, store, previous, org, 'previous-only')
                (foreign.parent / 'local_corrupt.json').write_text('{')
                saved[foreign.parent] = fixtures.fingerprint(foreign.parent)
        for winner in ('1p', '3p'):
            report = self.sync(winner)
            self.assertEqual((report['failed'], report['pending']), (0, 0), report)
            for directory, before in saved.items():
                self.assertEqual(fixtures.fingerprint(directory), before)
            for profile in (self.first, self.third):
                for store in fixtures.STORES:
                    self.assertEqual(len(self.paths(profile, store, 'previous-only')), 1)
                    self.assertEqual(len(self.paths(profile, store, 'current')), 2)
