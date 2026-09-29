"""Foreign diagnostics must not be replayed as Anthropic response evidence."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.claude_profile_sync_fixtures import load_helper

history = load_helper('claude_profile_history')


class HistoryTests(unittest.TestCase):
    def test_projection_preserves_content_and_ids_but_separates_foreign_diagnostics(self):
        rows = [
            {'type': 'assistant', 'requestId': 'req-native',
             'message': {'id': 'msg_native', 'content': [{'type': 'text', 'text': 'first'}]}},
            {'type': 'user', 'sessionId': 'same-session', 'cliSessionId': 'same-cli',
             'message': {'content': 'continue'}},
            {'type': 'assistant', 'requestId': 'req-external',
             'message': {'id': 'gen-provider', 'content': [
                 {'type': 'text', 'text': 'second'},
                 {'type': 'tool_use', 'id': 'call_1', 'name': 'example', 'input': {}}]}},
        ]
        text = ''.join(json.dumps(row) + '\n' for row in rows)
        projected = history.portable_history(text)
        actual = [json.loads(line) for line in projected.splitlines()]
        self.assertEqual(actual[:2], rows[:2])
        self.assertEqual(actual[2]['message'], rows[2]['message'])
        self.assertNotIn('requestId', actual[2])
        self.assertEqual(actual[2]['providerRequestId'], rows[2]['requestId'])
        self.assertEqual(history.portable_history(projected), projected)

    def test_native_transcript_is_byte_identical_and_conflicting_metadata_is_refused(self):
        text = '{"type":"assistant","requestId":"req-native","message":{"id":"msg_native"}}\n\n'
        self.assertEqual(history.portable_history(text), text)
        error = json.dumps({'type': 'assistant', 'isApiErrorMessage': True,
                            'requestId': 'failed-request', 'message': {'id': 'synthetic'}})
        self.assertEqual(history.portable_history(error), error)
        with self.assertRaises(ValueError):
            history.portable_history(json.dumps({'type': 'assistant', 'requestId': 'first',
                'providerRequestId': 'second', 'message': {'id': 'external'}}))

    def test_file_repair_preserves_transcript_and_is_idempotent(self):
        rows = [
            {'type': 'assistant', 'requestId': 'req-native',
             'message': {'id': 'msg_native', 'content': [{'type': 'text', 'text': 'kept'}]}},
            {'type': 'assistant', 'requestId': 'req-foreign',
             'sessionId': 'same-session', 'cliSessionId': 'same-cli',
             'message': {'id': 'foreign-response', 'content': [
                 {'type': 'text', 'text': 'also kept'},
                 {'type': 'tool_use', 'id': 'tool_1', 'name': 'synthetic', 'input': {}}]}},
        ]
        original = ''.join(json.dumps(row) + '\n' for row in rows).encode()
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            path = Path(directory) / 'session.jsonl'
            path.write_bytes(original)
            self.assertEqual(history.repair_file(path), 'repaired')
            actual = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(actual[0], rows[0])
            self.assertEqual(actual[1]['message'], rows[1]['message'])
            self.assertEqual(actual[1]['sessionId'], rows[1]['sessionId'])
            self.assertEqual(actual[1]['cliSessionId'], rows[1]['cliSessionId'])
            self.assertNotIn('requestId', actual[1])
            self.assertEqual(actual[1]['providerRequestId'], 'req-foreign')
            backups = list(Path(directory).glob('.session.jsonl.history-repair-*.original'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            self.assertEqual(history.repair_file(path), 'unchanged')
            self.assertEqual(backups[0].read_bytes(), original)

    def test_file_repair_recovers_after_source_was_displaced(self):
        original = json.dumps({'type': 'assistant', 'requestId': 'foreign',
            'message': {'id': 'provider-response', 'content': [{'type': 'text', 'text': 'kept'}]}}
            ).encode() + b'\n'
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            path = Path(directory) / 'session.jsonl'
            path.write_bytes(original)
            real_move = history._publish.move_new
            interrupted = False

            def stop_after_displace(source, target):
                nonlocal interrupted
                real_move(source, target)
                if Path(source) == path and str(target).endswith('.original') and not interrupted:
                    interrupted = True
                    raise RuntimeError('simulated interruption')

            with mock.patch.object(history._publish, 'move_new', side_effect=stop_after_displace):
                with self.assertRaisesRegex(RuntimeError, 'simulated interruption'):
                    history.repair_file(path)
            self.assertFalse(path.exists())
            backups = list(Path(directory).glob('.session.jsonl.history-repair-*.original'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            self.assertEqual(history.repair_file(path), 'repaired')
            self.assertEqual(history.repair_file(path), 'unchanged')
            self.assertEqual(backups[0].read_bytes(), original)
            self.assertIn(b'providerRequestId', path.read_bytes())

    def test_file_repair_retains_a_competing_write_and_original(self):
        original = json.dumps({'type': 'assistant', 'requestId': 'foreign',
            'message': {'id': 'provider-response', 'content': [{'type': 'text', 'text': 'kept'}]}}
            ).encode() + b'\n'
        competing = b'{"type":"user","message":{"content":"concurrent"}}\n'
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            path = Path(directory) / 'session.jsonl'
            path.write_bytes(original)
            real_move = history._publish.move_new

            def race_after_displace(source, target):
                real_move(source, target)
                if Path(source) == path and str(target).endswith('.original'):
                    with path.open('xb') as stream:
                        stream.write(competing)

            with mock.patch.object(history._publish, 'move_new', side_effect=race_after_displace):
                with self.assertRaises(ValueError):
                    history.repair_file(path)
            self.assertEqual(path.read_bytes(), competing)
            backups = list(Path(directory).glob('.session.jsonl.history-repair-*.original'))
            stages = list(Path(directory).glob('.session.jsonl.history-repair-*.stage'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            self.assertEqual(len(stages), 1)
            with self.assertRaises(ValueError):
                history.repair_file(path)
            self.assertEqual(path.read_bytes(), competing)
            self.assertEqual(backups[0].read_bytes(), original)
            self.assertTrue(stages[0].exists())

    def test_file_repair_handles_later_appends_as_new_generations(self):
        first = json.dumps({'type': 'assistant', 'requestId': 'foreign-1',
            'message': {'id': 'provider-response-1', 'content': 'first'}}).encode() + b'\n'
        second = json.dumps({'type': 'assistant', 'requestId': 'foreign-2',
            'message': {'id': 'provider-response-2', 'content': 'second'}}).encode() + b'\n'
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            path = Path(directory) / 'session.jsonl'
            path.write_bytes(first)
            self.assertEqual(history.repair_file(path), 'repaired')
            first_repaired = path.read_bytes()
            path.write_bytes(first_repaired + second)
            before_second = path.read_bytes()
            self.assertEqual(history.repair_file(path), 'repaired')
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([row['message']['id'] for row in rows],
                             ['provider-response-1', 'provider-response-2'])
            self.assertEqual([row['providerRequestId'] for row in rows],
                             ['foreign-1', 'foreign-2'])
            backups = list(Path(directory).glob('.session.jsonl.history-repair-*.original'))
            self.assertEqual(len(backups), 2)
            self.assertEqual({backup.read_bytes() for backup in backups}, {first, before_second})
            self.assertEqual(history.repair_file(path), 'unchanged')

    @unittest.skipUnless(hasattr(os, 'link'), 'hard links are unavailable')
    def test_file_repair_rejects_a_hard_link_without_changing_source(self):
        original = json.dumps({'type': 'assistant', 'requestId': 'foreign',
            'message': {'id': 'provider-response'}}).encode() + b'\n'
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            path = Path(directory) / 'session.jsonl'
            alias = Path(directory) / 'alias.jsonl'
            path.write_bytes(original)
            os.link(path, alias)
            with self.assertRaises(ValueError):
                history.repair_file(path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(alias.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
