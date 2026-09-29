"""Code tasks copy faithfully; Cowork tasks stay where they are in the beta."""
import json
from pathlib import Path

from tests import claude_profile_sync_fixtures as fixtures
from tests.claude_profile_sync_fixtures import SyncFixture

A1, O1 = '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc'
A3, O3 = '87654321-4321-4567-8123-123456789abc', 'fedcbaab-4321-4567-8123-123456789abc'
CODE, COWORK = 'claude-code-sessions', 'local-agent-mode-sessions'
CLI = '11111111-2222-4333-8444-555555555555'
ROWS = [
    {'type': 'user', 'uuid': 'u1', 'cwd': '/external/work',
     'message': {'role': 'user', 'content': 'hi'}},
    {'type': 'file-history-snapshot', 'messageId': 'u1', 'isSnapshotUpdate': False,
     'snapshot': {'messageId': 'u1', 'timestamp': 't', 'trackedFileBackups': {
         name: {'backupFileName': 'b%d@v1' % index, 'version': 1}
         for index, name in enumerate((
             'src/auth/token.ts', 'src/AccountSettings.tsx', 'docs/email-template.html',
             'config/secret', 'bin/token', 'src/app.ts'))}}},
    {'type': 'system', 'subtype': 'compact_boundary', 'uuid': 'c1', 'content': 'compacted',
     'compactMetadata': {'trigger': 'auto', 'preTokens': 1234}},
]


def text(rows):
    return ''.join(json.dumps(row) + '\n' for row in rows)


def rows_of(path):
    return [json.loads(line) for line in path.read_text().split('\n') if line.strip()]


class FaithfulCopyTests(SyncFixture):
    def snapshot(self, profile, name='session'):
        record = self.paths(profile, CODE, 'task')[0]
        return record.with_suffix('') / '.claude/projects' / name / (CLI + '.jsonl')

    def test_cowork_tasks_are_left_untouched_while_code_tasks_are_shared(self):
        fixtures.record(self.first, COWORK, A1, O1, 'cowork-1p', bundle_files={'a.txt': 'a'})
        fixtures.record(self.third, COWORK, A3, O3, 'cowork-3p', bundle_files={'b.txt': 'b'})
        fixtures.record(self.third, CODE, A3, O3, 'task')
        before = [fixtures.fingerprint(root / COWORK) for root in (self.first, self.third)]
        report = self.sync('1p')
        self.assertEqual((report['failed'], report['pending'], report['copied']), (0, 0, 1), report)
        self.assertEqual(len(self.paths(self.first, CODE, 'task')), 1)
        self.assertEqual([fixtures.fingerprint(root / COWORK) for root in (self.first, self.third)],
                         before)

    def test_task_files_keep_exact_bytes_in_both_directions(self):
        data = [{'name': 'Acme', 'email': 'ap@example.invalid', 'account_code': '4000',
                 'organization': 'Acme Pty', 'amount': 12.5}]
        files = {'outputs/customers.json': json.dumps(data, indent=2),
                 'outputs/rows.jsonl': json.dumps(data[0]) + '\n',
                 'outputs/tsconfig.json': '{\n  // comments are allowed here\n}\n'}
        first = fixtures.record(self.first, CODE, A1, O1, 'task', bundle_files=files)
        only = {'outputs/data.json': json.dumps({'customer': 'Acme', 'account': '4000'}, indent=2)}
        third = fixtures.record(self.third, CODE, A3, O3, 'task', bundle_files=only)
        for winner in ('1p', '3p'):
            report = self.sync(winner)
            self.assertEqual((report['failed'], report['pending']), (0, 0), report)
            for record in (first, third):
                for name, content in list(files.items()) + list(only.items()):
                    self.assertEqual((record.with_suffix('') / name).read_text(), content)

    def test_checkpoint_rows_keep_every_key_in_both_directions(self):
        live = Path(self.env['CLAUDE_CONFIG_DIR']) / 'projects/-external-work' / (CLI + '.jsonl')
        live.parent.mkdir(parents=True)
        live.write_text(text(ROWS))
        before = live.read_bytes()
        fixtures.record(self.first, CODE, A1, O1, 'task', cli=CLI)
        for winner in ('1p', '3p'):
            report = self.sync(winner)
            self.assertEqual((report['failed'], report['pending']), (0, 0), report)
            for profile in (self.first, self.third):
                self.assertEqual(rows_of(self.snapshot(profile)), ROWS)
        self.assertEqual(live.read_bytes(), before)

    def test_transcript_inside_a_bundle_is_neither_rewritten_nor_duplicated(self):
        record = fixtures.record(self.first, CODE, A1, O1, 'task', cli=CLI, bundle_files={
            '.claude/projects/-external-work/' + CLI + '.jsonl': text(ROWS)})
        before = fixtures.fingerprint(record.with_suffix(''))
        report = self.sync('1p')
        self.assertEqual((report['failed'], report['pending']), (0, 0), report)
        self.assertEqual(fixtures.fingerprint(record.with_suffix('')), before)
        self.assertEqual(rows_of(self.snapshot(self.third, '-external-work')), ROWS)
        self.assertFalse(self.snapshot(self.third).exists())

    def test_diverged_transcripts_refuse_the_task_and_keep_both_copies(self):
        for profile, account, org, turn in ((self.first, A1, O1, 'n1'), (self.third, A3, O3, 'n3')):
            fixtures.record(profile, CODE, account, org, 'task', cli=CLI, bundle_files={
                '.claude/projects/session/' + CLI + '.jsonl': text(ROWS + [{
                    'type': 'user', 'uuid': turn, 'parentUuid': 'c1',
                    'message': {'role': 'user', 'content': 'turn ' + turn}}])})
        before = [fixtures.fingerprint(root / CODE) for root in (self.first, self.third)]
        report = self.sync('1p')
        self.assertEqual((report['failed'], report['errors']), (1, ['session-refused']), report)
        self.assertEqual([fixtures.fingerprint(root / CODE) for root in (self.first, self.third)],
                         before)

    def test_continued_shared_history_is_not_mistaken_for_divergence(self):
        live = Path(self.env['CLAUDE_CONFIG_DIR']) / 'projects/-external-work' / (CLI + '.jsonl')
        live.parent.mkdir(parents=True)
        live.write_text(text(ROWS))
        fixtures.record(self.first, CODE, A1, O1, 'task', cli=CLI)
        self.assertEqual(self.sync('1p')['failed'], 0)
        turn = {'type': 'user', 'uuid': 'u2', 'parentUuid': 'c1',
                'message': {'role': 'user', 'content': 'continued in the gateway'}}
        with live.open('a') as out:
            out.write(json.dumps(turn) + '\n')
        report = self.sync('3p')
        self.assertEqual((report['failed'], report['pending']), (0, 0), report)
        for profile in (self.first, self.third):
            self.assertEqual(rows_of(self.snapshot(profile)), ROWS + [turn])
