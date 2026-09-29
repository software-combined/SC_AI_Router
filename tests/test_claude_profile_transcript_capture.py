"""Capture continued native history instead of reusing an imported snapshot."""
import json
from pathlib import Path

from tests import claude_profile_sync_fixtures as fixtures
from tests.claude_profile_sync_fixtures import SyncFixture, sync


class TranscriptCaptureTests(SyncFixture):
    def test_complete_conversations_copy_in_both_directions_without_login_files(self):
        for active, source in (('1p', self.first), ('3p', self.third)):
            identity = json.loads((source / 'config.json').read_text())
            for store in sync.STORES:
                identifier = active + '-' + store
                cli = 'cli-' + identifier
                text = ('Example: password: synthetic-value\nAuthorization: Bearer example-token'
                        '\u0085Unicode paragraph\u2028and line\u2029separators')
                message = {'content': [{'type': 'tool_use', 'input': {
                    'password': 'synthetic-value', 'tokens': 42,
                    'path': str(source / 'example'), 'accountName': 'example'}}]}
                record = fixtures.record(
                    source, store, identity['lastKnownAccountUuid'],
                    identity['lastKnownOrganizationUuid'], identifier, cli=cli,
                    title=text, transcript=text, bundle_files={
                        'host-creds-example.json': '{"private":"source-only"}',
                        'ccd-session-secrets.json': '{"private":"source-only"}',
                        '.audit-key': 'source-only',
                        'settings.json': '{"private":"source-only"}'})
                doc = json.loads(record.read_text())
                doc.update(initialMessage=text, messages=[message])
                record.write_text(json.dumps(doc))
                live = Path(self.env['CLAUDE_CONFIG_DIR']) / 'projects/workspace' / (cli + '.jsonl')
                live.parent.mkdir(parents=True, exist_ok=True)
                rows = [{'type': 'user', 'message': {'content': text}},
                        {'type': 'assistant', 'message': message,
                         'toolUseResult': {'password': 'synthetic-value', 'output': text}}]
                live.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))
                before = live.read_bytes()
                report = self.sync(active)
                self.assertEqual((report['failed'], report['pending']), (0, 0), report)
                for target in (self.first, self.third):
                    copied = self.paths(target, store, identifier)[0]
                    saved = json.loads(copied.read_text())
                    self.assertEqual((saved['title'], saved['initialMessage'], saved['messages']),
                                     (text, text, [message]))
                    history = copied.with_suffix('') / '.claude/projects/session' / live.name
                    self.assertEqual([json.loads(row) for row in history.read_text().split('\n') if row], rows)
                    for name in ('host-creds-example.json', 'ccd-session-secrets.json',
                                 '.audit-key', 'settings.json'):
                        artifact = copied.with_suffix('') / name
                        self.assertEqual(artifact.exists(), target == source)
                self.assertEqual(live.read_bytes(), before)

    def test_foreign_diagnostics_are_repaired_in_shared_history_and_both_bundles(self):
        identity = json.loads((self.third / 'config.json').read_text())
        fixtures.record(self.third, 'claude-code-sessions',
                        identity['lastKnownAccountUuid'], identity['lastKnownOrganizationUuid'],
                        'foreign', cli='cli-foreign', transcript='old')
        live = Path(self.env['CLAUDE_CONFIG_DIR']) / 'projects/workspace/cli-foreign.jsonl'
        live.parent.mkdir(parents=True)
        row = {'type': 'assistant', 'requestId': 'provider-request',
               'message': {'id': 'provider-response', 'content': 'keep complete history'}}
        live.write_text(json.dumps(row) + '\n')
        report = self.sync('3p')
        self.assertEqual(report['failed'], 0, report)
        for profile in (self.first, self.third):
            path = self.paths(profile, 'claude-code-sessions', 'foreign')[0]
            saved = json.loads((path.with_suffix('') / '.claude/projects/session' / live.name).read_text())
            self.assertEqual(saved['message'], row['message'])
            self.assertEqual(saved['providerRequestId'], row['requestId'])
            self.assertNotIn('requestId', saved)
        self.assertNotIn('requestId', json.loads(live.read_text()))
        self.assertEqual(len(list(live.parent.glob('*.original'))), 1)
        report = self.sync('3p')
        self.assertEqual((report['failed'], report['copied'], report['replaced']), (0, 0, 0))

    def test_live_cli_history_replaces_bundle_snapshot_in_both_directions(self):
        for active in ('1p', '3p'):
            with self.subTest(active=active):
                identifier = 'continued-' + active
                cli = 'cli-' + identifier
                for profile in (self.first, self.third):
                    identity = json.loads((profile / 'config.json').read_text())
                    fixtures.record(
                        profile, 'claude-code-sessions',
                        identity['lastKnownAccountUuid'],
                        identity['lastKnownOrganizationUuid'], identifier,
                        cli=cli, transcript='original response',
                        bundle_files={profile.name + '.txt': 'keep'})
                history = [
                    {'type': 'assistant', 'message': {'content': 'original response'}},
                    {'type': 'assistant', 'message': {'content': 'continued response'}},
                ]
                live = Path(self.env['CLAUDE_CONFIG_DIR']) / 'projects' / 'workspace' / (cli + '.jsonl')
                live.parent.mkdir(parents=True, exist_ok=True)
                live.write_text(''.join(json.dumps(row) + '\n' for row in history))
                original = live.read_bytes()
                report = self.sync(active)
                self.assertEqual(report['failed'], 0, report)
                for profile in (self.first, self.third):
                    record = self.paths(profile, 'claude-code-sessions', identifier)[0]
                    bundle = record.with_suffix('')
                    captured = bundle / '.claude/projects/session' / live.name
                    self.assertEqual([json.loads(row) for row in captured.read_text().splitlines()], history)
                    self.assertEqual(json.loads(record.read_text())['cliSessionId'], cli)
                    for name in ('Claude.txt', 'Claude-3p.txt'):
                        self.assertEqual((bundle / name).read_text(), 'keep')
                self.assertEqual(live.read_bytes(), original)
                report = self.sync(active)
                self.assertEqual((report['failed'], report['copied'], report['replaced']), (0, 0, 0))
