"""Interrupted cleanup and history repair resume on the next switch instead of blocking."""
import json
import os
import shutil
from pathlib import Path
from unittest import mock

from tests import claude_profile_sync_fixtures as fixtures
from tests.claude_profile_sync_fixtures import PairFixture, SyncFixture

A1, O1 = '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc'
CLI = '11111111-2222-4333-8444-555555555555'


class CommittedCleanupTests(PairFixture):
    def test_cleanup_that_stopped_partway_finishes_on_the_next_run(self):
        for name in ('old2.txt', 'old3.txt'):
            (self.bundle / 'outputs' / name).write_text(name)
        manifest, real_delete = self.manifest(), self.publish.delete_checked

        def stop_partway(path, expected, kind):
            if kind == 'tree':  # One file goes, then a scanner holds the next one.
                next(item for item in sorted(path.rglob('*')) if item.is_file()).unlink()
                raise PermissionError(13, 'locked')
            return real_delete(path, expected, kind)

        with mock.patch.object(self.publish, 'delete_checked', side_effect=stop_partway):
            with self.assertRaises(PermissionError):
                self.transaction.publish_pair(manifest, self.text)
        self.assertEqual(json.loads(self.record.read_text())['title'], 'new')
        errors = []
        self.assertEqual(self.transaction.recover_store(self.store, errors), 1)
        self.assertEqual(errors, [])
        self.assertFalse(manifest.exists())
        self.assertEqual(list(self.ns.glob('.claude-profile-control-*')), [])
        self.assertTrue((self.bundle / 'outputs/new.txt').exists())


class HistoryRepairTests(SyncFixture):
    def task(self):
        """A Code task whose live history holds a gateway reply, so a switch repairs it."""
        live = Path(self.env['CLAUDE_CONFIG_DIR']) / 'projects/-Users-me-app' / (CLI + '.jsonl')
        live.parent.mkdir(parents=True)
        live.write_text(''.join(json.dumps(row) + '\n' for row in (
            {'type': 'user', 'uuid': 'u1', 'message': {'role': 'user', 'content': 'hi'}},
            {'type': 'assistant', 'uuid': 'a1', 'requestId': 'gen-1',
             'message': {'id': 'gen-a', 'role': 'assistant', 'content': []}})))
        fixtures.record(self.first, 'claude-code-sessions', A1, O1, 'task', cli=CLI)
        return live

    def assertSwitches(self):
        report = self.sync('1p')
        self.assertEqual((report['failed'], report['pending']), (0, 0), report)

    def test_transcript_deleted_after_a_repair_does_not_block(self):
        live = self.task()
        self.assertSwitches()
        live.unlink()  # Claude Code removed an old conversation.
        self.assertSwitches()

    def test_copied_or_restored_home_does_not_block(self):
        live = self.task()
        self.assertSwitches()
        for item in list(live.parent.iterdir()):
            copy = item.with_name(item.name + '.copy')
            shutil.copy2(item, copy)  # Same bytes, mode and times; a new inode.
            os.replace(copy, item)
        self.assertSwitches()

    def test_writer_racing_the_repair_leaves_the_transcript_for_the_next_run(self):
        live, history, raced = self.task(), fixtures.sync._history, []
        real_move = history._publish.move_new

        def racing(source, target):
            if not raced and Path(source) == live:
                raced.append(True)
                with live.open('a') as out:  # A writer the switch did not see.
                    out.write(json.dumps({'type': 'user', 'uuid': 'u2', 'message': 'late'}) + '\n')
            return real_move(source, target)

        with mock.patch.object(history._publish, 'move_new', side_effect=racing):
            self.assertEqual(self.sync('1p')['failed'], 1)
        self.assertEqual(sorted(p.name for p in live.parent.iterdir()), [live.name])
        self.assertSwitches()
        self.assertIn('late', live.read_text())

    def test_journal_half_written_by_a_killed_process_does_not_block(self):
        live = self.task()
        stem = '.' + live.name + '.history-repair-' + 'a' * 64
        (live.parent / (stem + '.journal.k3x9q1ab.tmp')).write_text('{')
        (live.parent / (stem + '.stage')).write_text('staged before the journal')
        self.assertSwitches()
        self.assertFalse([p.name for p in live.parent.iterdir() if p.name.startswith(stem)])

    def test_completion_record_half_written_by_a_killed_process_does_not_block(self):
        live, history = self.task(), fixtures.sync._history

        def killed(path, journal, document):
            path.with_name(path.name + '.x1y2z3ab.tmp').write_text('{')
            raise OSError('killed while writing')

        with mock.patch.object(history, '_write_done', side_effect=killed):
            self.assertEqual(self.sync('1p')['failed'], 1)
        self.assertSwitches()
        self.assertFalse([p.name for p in live.parent.iterdir() if p.name.endswith('.tmp')])
