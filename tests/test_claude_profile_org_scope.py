"""Only the subscription's current organization shares tasks; others stay put."""
import json

from tests import claude_profile_sync_fixtures as fixtures
from tests.claude_profile_sync_fixtures import SyncFixture

A1, O1 = '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc'
A3, O3 = '87654321-4321-4567-8123-123456789abc', 'fedcbaab-4321-4567-8123-123456789abc'
O1B = 'bbbbbbbb-1234-4567-8123-123456789abc'
CODE = 'claude-code-sessions'


class OrganizationScopeTests(SyncFixture):
    def use_organization(self, organization):
        """Sign the subscription profile into another organization of the same account."""
        config = self.first / 'config.json'
        doc = json.loads(config.read_text())
        doc['lastKnownOrganizationUuid'] = organization
        config.write_text(json.dumps(doc))
        fixtures.namespace(self.first, CODE, A1, organization)

    def test_other_org_task_is_neither_moved_nor_copied(self):
        record = fixtures.record(self.first, CODE, A1, O1, 'org-a', cli='org-a-cli',
                                 transcript='hello', bundle_files={'out.txt': 'only org A'})
        before = fixtures.fingerprint(record.parent)
        self.use_organization(O1B)
        for winner in ('3p', '1p'):
            report = self.sync(winner)
            self.assertEqual((report['failed'], report['pending']), (0, 0), report)
            self.assertEqual(fixtures.fingerprint(record.parent), before)
            self.assertEqual(self.paths(self.first, CODE, 'org-a'), [record])
            self.assertEqual(self.paths(self.third, CODE, 'org-a'), [])

    def test_task_shared_before_an_org_change_stays_in_its_org(self):
        record = fixtures.record(self.first, CODE, A1, O1, 'org-a-shared')
        self.assertEqual(self.sync('1p')['failed'], 0)
        gateway = self.paths(self.third, CODE, 'org-a-shared')
        self.assertEqual(len(gateway), 1)
        before = fixtures.fingerprint(record.parent), fixtures.fingerprint(gateway[0].parent)
        self.use_organization(O1B)
        for winner in ('1p', '3p'):
            report = self.sync(winner)
            self.assertEqual((report['failed'], report['pending']), (0, 0), report)
            self.assertEqual((fixtures.fingerprint(record.parent),
                              fixtures.fingerprint(gateway[0].parent)), before)
            self.assertEqual(self.paths(self.first, CODE, 'org-a-shared'), [record])

    def test_other_org_damage_does_not_block_the_current_org(self):
        (fixtures.namespace(self.first, CODE, A1, O1) / 'local_bad.json').write_text('{')
        self.use_organization(O1B)
        fixtures.record(self.first, CODE, A1, O1B, 'org-b')
        report = self.sync('1p')
        self.assertEqual((report['failed'], report['pending'], report['copied']), (0, 0, 1), report)

    def test_new_gateway_task_joins_the_current_org(self):
        self.use_organization(O1B)
        fixtures.record(self.third, CODE, A3, O3, 'gateway-task')
        report = self.sync('3p')
        self.assertEqual((report['failed'], report['pending']), (0, 0), report)
        self.assertEqual([path.parent.name for path in self.paths(self.first, CODE, 'gateway-task')],
                         [O1B])
