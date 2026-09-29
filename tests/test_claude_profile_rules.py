"""Credential and path policy for cross-profile session artifacts."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'claude_profile_rules', ROOT / 'packaging' / 'claude_profile_rules.py')
rules = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rules)


class ProfileRulesTests(unittest.TestCase):
    def test_sensitive_keys_and_names_are_case_insensitive_and_nested(self):
        doc = {'AccountName': 'x', 'nested': {'CLIENT_SECRET': 'x'},
               'safe': 1}
        self.assertEqual(rules.clean(doc), {'nested': {}, 'safe': 1})
        for name in ('CLAUDE.md', 'configLibrary', 'Plugin-Cache',
                     'credentials.JSON', 'settings.json',
                     'settings.local.json', 'managed-settings.json',
                     'permissions.json', 'trust.json'):
            with self.subTest(name=name):
                self.assertTrue(rules.skip(Path('bundle') / name))

    def test_conversation_text_is_preserved_while_metadata_is_screened(self):
        raw = {'sessionId': 's', 'title': 'password: synthetic-value'}
        paths = (Path('/source/bundle'), Path('/target/bundle'),
                 Path('/source'), Path('/target'))
        self.assertEqual(json.loads(rules.project_record(raw, paths)), raw)
        with self.assertRaisesRegex(ValueError, 'credential-like'):
            rules.project_record(dict(raw, metadata='password: synthetic-value'), paths)

    def test_record_projection_preserves_only_target_local_values(self):
        raw = {'sessionId': 's', 'title': 'source',
               'emailAddress': 'source@example.invalid'}
        existing = {'sessionId': 's', 'title': 'target',
                    'targetLocalSecret': 'target-only-value'}
        paths = (Path('/source/bundle'), Path('/target/bundle'),
                 Path('/source'), Path('/target'))
        target_wins = json.loads(rules.project_record(
            raw, paths, existing=existing, target_wins=True))
        source_wins = json.loads(rules.project_record(
            raw, paths, existing=existing, target_wins=False))
        self.assertEqual(target_wins['title'], 'target')
        self.assertEqual(source_wins['title'], 'source')
        for doc in (target_wins, source_wins):
            self.assertEqual(doc['targetLocalSecret'], 'target-only-value')
            self.assertNotIn('emailAddress', doc)

    def test_path_rewriting_is_component_scoped(self):
        source = Path('/profiles/Claude-3p/store/account/org/local_s')
        target = Path('/profiles/Claude/store/account/org/local_s')
        paths = (source, target, Path('/profiles/Claude-3p'),
                 Path('/profiles/Claude'))
        self.assertEqual(rules.rewrite_path(str(source / 'outputs'), *paths),
                         str(target / 'outputs'))
        self.assertEqual(rules.rewrite_path(str(source) + '-other', *paths),
                         '/profiles/Claude/store/account/org/local_s-other')
        self.assertEqual(rules.rewrite_path('/Users/test/N8N', *paths),
                         '/Users/test/N8N')

    def test_task_files_and_opaque_artifacts_share_content_screening(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.jsonl'
            source.write_text('{"text":"bearer synthetic-token-value"}\n')
            with self.assertRaisesRegex(ValueError, 'credential-like'):
                rules.copy_file(source, root / 'target.jsonl', ())
            opaque = root / 'output.txt'
            opaque.write_text('authorization: synthetic-value')
            with self.assertRaisesRegex(ValueError, 'credential-like'):
                rules.copy_file(opaque, root / 'copy.txt', ())

    def test_invalid_transcript_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source.jsonl'
            source.write_text('not-json\n')
            with self.assertRaisesRegex(ValueError, 'invalid JSONL'):
                rules.copy_transcript(source, Path(tmp) / 'target.jsonl', ())
            self.assertFalse((Path(tmp) / 'target.jsonl').exists())

    def test_transcript_tool_payload_is_preserved_and_never_silently_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / 'source.jsonl', Path(tmp) / 'target.jsonl'
            message = {'content': [{'type': 'tool_use', 'input': {
                'accountName': 'example', 'tokens': 42, 'path': '/source/result'}}]}
            source.write_text(json.dumps({'cwd': '/source/work', 'message': message}) + '\n')
            rules.copy_transcript(source, target, (None, None, '/source', '/target'))
            copied = json.loads(target.read_text())
            self.assertEqual(copied['message'], message)
            self.assertEqual(copied['cwd'], '/target/work')
            message['content'][0]['input']['password'] = 'synthetic-value'
            source.write_text(json.dumps({'message': message}) + '\n')
            rules.copy_file(source, target, (), conversation=True)
            self.assertEqual(json.loads(target.read_text())['message'], message)

    def test_transcript_preserves_tool_and_attachment_payloads(self):
        payload = {'password': 'synthetic-value', 'path': '/source/example',
                   'text': 'authorization: synthetic-value'}
        rows = [{'type': 'assistant', 'message': {'content': 'example'},
                 'wireToolInputs': {'tool-1': payload}},
                {'type': 'attachment', 'attachment': payload, 'rendered': [payload]}]
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / 'source.jsonl', Path(tmp) / 'target.jsonl'
            source.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            rules.copy_transcript(source, target, (None, None, '/source', '/target'))
            self.assertEqual([json.loads(line) for line in target.read_text().split('\n')
                              if line], rows)

    def test_conversation_copy_screens_metadata_before_overwriting_target(self):
        row = {'message': {'content': 'password: synthetic-value'},
               'metadata': 'authorization: synthetic-value'}
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / 'source.jsonl', Path(tmp) / 'target.jsonl'
            source.write_text(json.dumps(row) + '\n')
            target.write_text('previous')
            with self.assertRaisesRegex(ValueError, 'credential-like'):
                rules.copy_transcript(source, target, ())
            self.assertEqual(target.read_text(), 'previous')

    def test_audit_log_keeps_exact_bytes_and_still_rejects_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, target = root / 'audit.jsonl', root / 'copy.jsonl'
            raw = (b'{ "organizationId":"synthetic-org", '
                   b'"path":"/source/output", "event":"file-read" }\r\n')
            source.write_bytes(raw)
            target.write_bytes(b'previous')
            target.chmod(0o600)
            rules.copy_file(source, target, (None, None, '/source', '/target'), mode=0o644)
            self.assertEqual(target.read_bytes(), raw)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            source.write_bytes(b'{"text":"bearer synthetic-token-value"}\n')
            with self.assertRaisesRegex(ValueError, 'credential-like'):
                rules.copy_file(source, target, ())
            self.assertEqual(target.read_bytes(), raw)

    def test_new_transcript_copy_is_owner_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source.jsonl'
            target = Path(tmp) / 'target.jsonl'
            source.write_text('{"safe":true}\n')
            rules.copy_transcript(source, target, ())
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_private_artifact_is_not_widened(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source.json'
            target = Path(tmp) / 'target.json'
            source.write_text('{"safe":true}')
            source.chmod(0o644)
            target.write_text('{"old":true}')
            target.chmod(0o600)
            rules.copy_file(source, target, (), mode=0o644)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_nested_control_artifacts_never_transfer(self):
        for name in ('receipt.json', 'receipt-install.json', 'receipts/one.json',
                     '.claude.json.backup', 'task.backup', 'backup/item.txt',
                     'backups/item.txt', 'local_s.tmp-123/output.txt',
                     '.tmp-123/output.txt', 'task-before', 'task-after',
                     'transaction-manifest.json', 'manifest.json', 'journal.json',
                     'local_s.journal', 'local_s.recovery', '.claude-profile-transaction-a.json',
                     '.local_s.json.pending', 'recovery/file.json'):
            with self.subTest(name=name):
                self.assertTrue(rules.skip(Path('.claude/projects/session') / name))

    def test_empty_values_are_preserved_and_active_empty_messages_win(self):
        raw = {'sessionId': 'same', 'messages': ['stale']}
        active = {'sessionId': 'same', 'messages': [], 'metadata': {}}
        projected = json.loads(rules.project_record(raw, (None,) * 4, active, True))
        self.assertEqual(projected['messages'], [])
        self.assertEqual(projected['metadata'], {})

    def test_json_task_files_keep_exact_bytes_but_transcript_rows_are_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / 'data.json', Path(tmp) / 'copy.json'
            for raw in ('[]', '[1, {"messages": []}]', '"text"', '0', 'false', 'null',
                        '{\n  // a comment\n  "emailAddress": "a@example.invalid"\n}\n'):
                source.write_text(raw)
                rules.copy_file(source, target, (None, None, '/source', '/target'))
                self.assertEqual(target.read_bytes(), source.read_bytes())
            source = source.with_suffix('.jsonl')
            source.write_text('[]\n')
            with self.assertRaises(ValueError):
                rules.copy_transcript(source, target, ())

    def test_windows_prefix_normalizes_case_and_separators_without_substrings(self):
        paths = ('C:\\Profiles\\Claude-3p\\local_s', 'D:\\Claude\\local_t', None, None)
        self.assertEqual(rules.rewrite_path('c:/profiles/CLAUDE-3P/local_s/outputs/x', *paths),
                         'D:\\Claude\\local_t\\outputs\\x')
        self.assertEqual(rules.rewrite_path('C:\\Profiles\\Claude-3p\\local_s-other\\x', *paths),
                         'C:\\Profiles\\Claude-3p\\local_s-other\\x')
        self.assertEqual(rules.rewrite_path('C:\\Work\\N8N', *paths), 'C:\\Work\\N8N')

    def test_windows_unicode_prefix_keeps_the_complete_relative_path(self):
        paths = ('C:\\Profiles\\stra\u00dfe\\local_s', 'D:\\Claude\\local_t', None, None)
        for folder in ('stra\u00dfe', 'STRASSE'):
            with self.subTest(folder=folder):
                value = 'C:/Profiles/' + folder + '/local_s/outputs/x'
                self.assertEqual(rules.rewrite_path(value, *paths),
                                 'D:\\Claude\\local_t\\outputs\\x')

    def test_existing_record_rewrites_its_original_bundle_prefix(self):
        paths = ('/inactive/local_i', '/active/local_a', '/inactive', '/active')
        existing = {'sessionId': 's', 'path': '/active/stale/local_old/outputs/x'}
        result = json.loads(rules.project_record({'sessionId': 's'}, paths, existing, True,
            ('/active/stale/local_old', '/active/local_a', '/active', '/active')))
        self.assertEqual(result['path'], '/active/local_a/outputs/x')


if __name__ == '__main__':
    unittest.main()
