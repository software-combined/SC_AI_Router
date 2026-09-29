"""A workspace's own folder name never blocks sharing; credential paths still do."""
import json
from pathlib import Path

from tests import claude_profile_sync_fixtures as fixtures
from tests.claude_profile_sync_fixtures import SyncFixture

A1, O1 = '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc'
CODE = 'claude-code-sessions'
CLI = '11111111-2222-4333-8444-555555555555'
ROWS = [{'type': 'user', 'uuid': 'u1', 'message': {'role': 'user', 'content': 'hi'}}]
NAMES = ('accounts-payable', 'email-templates', 'password-manager', 'oauth-demo',
         'token-service', 'secret-santa')


def text(rows):
    return ''.join(json.dumps(row) + '\n' for row in rows)


class WorkspaceNameTests(SyncFixture):
    def share(self, relative, live):
        """Share one task whose only transcript is at `relative`; return the gateway copy."""
        if live:
            path = Path(self.env['CLAUDE_CONFIG_DIR']) / 'projects' / relative
            path.parent.mkdir(parents=True)
            path.write_text(text(ROWS))
            fixtures.record(self.first, CODE, A1, O1, 'task', cli=CLI)
        else:
            fixtures.record(self.first, CODE, A1, O1, 'task', cli=CLI,
                            bundle_files={relative: text(ROWS)})
        report = self.sync('1p')
        copies = self.paths(self.third, CODE, 'task')
        return report, copies[0].with_suffix('') if copies else None

    def test_live_history_in_any_workspace_folder_is_shared(self):
        for name in NAMES:
            with self.subTest(name=name):
                self.setUp()
                report, copy = self.share('-Users-me-' + name + '/' + CLI + '.jsonl', True)
                self.assertEqual((report['failed'], report['unshared']), (0, 0), report)
                snapshot = copy / '.claude/projects/session' / (CLI + '.jsonl')
                self.assertEqual(snapshot.read_text(), text(ROWS))

    def test_bundle_history_in_a_mirrored_workspace_folder_is_shared(self):
        for name in NAMES:
            with self.subTest(name=name):
                self.setUp()
                relative = '.claude/projects/-Users-me-' + name + '/' + CLI + '.jsonl'
                report, copy = self.share(relative, False)
                self.assertEqual((report['failed'], report['unshared']), (0, 0), report)
                self.assertEqual((copy / relative).read_text(), text(ROWS))

    def test_credential_and_router_paths_are_still_refused(self):
        for relative, live in (('-Users-me-app/secrets/' + CLI + '.jsonl', True),
                               ('.claude-profile-control-0123/' + CLI + '.jsonl', True),
                               ('creds/' + CLI + '.jsonl', False),
                               ('secrets/' + CLI + '.jsonl', False),
                               ('.claude/projects/-Users-me-app/tokens/' + CLI + '.jsonl', False),
                               ('.claude/projects/-Users-me-app.tmp-0123/' + CLI + '.jsonl', False)):
            with self.subTest(relative=relative):
                self.setUp()
                report, copy = self.share(relative, live)
                self.assertEqual((report['failed'], report['errors'], copy),
                                 (1, ['session-refused'], None), report)
