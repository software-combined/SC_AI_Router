"""The Codex shape capture writes only what is safe and reports real drift.

Offline and synthetic: `tools/capture_codex_shapes.py` drives the real
client only when run by hand; these check the sanitiser that decides what a
committed capture may hold and the drift report read after a client upgrade.
"""
import contextlib
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import capture_codex_shapes as capture

LONG = 'x' * 200


def developer(text):
    return {'type': 'message', 'role': 'developer', 'content': [{'type': 'input_text', 'text': text}]}


def record(items, **fields):
    return {'via': 'prepare', 'path': '/responses', 'payload': {'input': items, **fields}}


class CompactionCaptureTests(unittest.TestCase):
    def test_synthetic_summary_reports_the_requested_model(self):
        from ai_router.compaction_result import extract_summary
        fake = capture.Upstream('compaction')
        response = fake.reply({'model': 'xiaomi/mimo-v2.6-flash'})
        self.assertEqual(extract_summary(response.status, json.loads(response.read()),
                         expected_model='xiaomi/mimo-v2.6-flash'), 'Synthetic summary.')

    def test_wrapper_keeps_runtime_row_context_and_policy_arguments(self):
        records = []
        provider, row, context = object(), object(), object()
        payload = {'input': [{'role': 'user', 'content': 'Synthetic task.'}]}
        original = mock.Mock(return_value=['synthetic compacted item'])
        wrapper = capture.record_compaction(original, 'compact_trigger', records)
        result = wrapper(provider, 'model', payload, 'synthetic-key', row,
                         context=context, allowed={'model'})
        original.assert_called_once_with(provider, 'model', payload, 'synthetic-key',
                                         row, context=context, allowed={'model'})
        self.assertEqual(result, ['synthetic compacted item'])
        self.assertEqual(records, [{'via': 'compact_trigger', 'path': '/responses',
                                   'payload': payload}])
        payload['input'].clear()
        self.assertEqual(len(records[0]['payload']['input']), 1)


class SanitiseTests(unittest.TestCase):
    def test_instructions_descriptions_and_work_paths(self):
        work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, work, True)
        real = str(Path(work).resolve())
        tool = {'type': 'function', 'name': 'echo', 'description': LONG, 'parameters': {
            'type': 'object', 'properties': {'value': {'type': 'string', 'description': LONG}}}}
        payload = {
            'instructions': f'Work in {real}.',
            'tools': [tool, {'type': 'namespace', 'name': 'ns', 'description': LONG,
                             'tools': [dict(tool)]}],
            'input': [developer(f'<environment_context><cwd>{work}</cwd> {real}/skills'),
                      {'type': 'additional_tools', 'role': 'developer', 'tools': [dict(tool)]},
                      {'type': 'tool_search_output', 'call_id': 's1', 'tools': [dict(tool)]},
                      {'type': 'message', 'role': 'user', 'description': LONG, 'content': 'hi'}]}
        before = json.dumps(payload)
        clean = capture.sanitise(payload, Path(work))
        self.assertEqual(json.dumps(payload), before, 'the captured body is never edited')
        digest = hashlib.sha256('Work in <work>.'.encode()).hexdigest()
        self.assertEqual(clean['instructions'], f'<instructions sha256={digest}>')
        self.assertNotIn(work, json.dumps(clean))
        self.assertNotIn(real, json.dumps(clean))
        self.assertEqual(clean['input'][0]['content'][0]['text'],
                         '<environment_context><cwd><work></cwd> <work>/skills')
        cut = [clean['tools'][0], clean['tools'][1], clean['tools'][1]['tools'][0],
               clean['input'][1]['tools'][0], clean['input'][2]['tools'][0]]
        for described in cut:
            self.assertEqual(described['description'], LONG[:80])
        self.assertEqual(clean['tools'][0]['parameters']['properties']['value']['description'],
                         LONG[:80])
        # Only tool definitions are cut; other text keeps its length.
        self.assertEqual(clean['input'][3]['description'], LONG)

    def test_a_body_without_instructions_gains_none(self):
        self.assertEqual(capture.sanitise({'input': []}), {'input': []})

    def test_values_minted_per_run_become_stable_placeholders(self):
        def run(thread, install, turn, compaction_id, started, created, flip=False):
            metadata = json.dumps({'installation_id': install, 'thread_id': thread,
                                   'window_id': thread + ':0',
                                   'turn_started_at_unix_ms': started, 'window_number': 0},
                                  separators=(',', ':'))
            client = {'thread_id': thread, 'x-codex-installation-id': install,
                      'x-codex-turn-metadata': metadata}
            if flip:  # the client emits this map in another key order on each run
                client = dict(reversed(client.items()))
            return {'prompt_cache_key': thread, 'client_metadata': client,
                    'tools': [{'type': 'function', 'name': 'echo', 'parameters': {
                        'type': 'object', 'properties': {'create_time': {'type': 'number'}}}}],
                    'input': [
                        {'type': 'function_call', 'call_id': 'call_1', 'name': 'echo',
                         'arguments': '{"value": "x"}'},
                        {'type': 'function_call_output', 'id': 'fco_' + turn, 'call_id': 'call_1',
                         'output': 'ok', 'internal_chat_message_metadata_passthrough': {
                             'turn_id': turn, 'create_time': created}},
                        {'type': 'compaction', 'id': 'cmp_' + compaction_id,
                         'encrypted_content': 'ocx1:c3VtbWFyeQ=='}]}

        first = run('aaaaaaaa-0000-4000-8000-000000000001', 'aaaaaaaa-0000-4000-8000-000000000002',
                    'aaaaaaaa-0000-4000-8000-000000000003', '0123456789abcdef',
                    1790231825393, 1790231825.4)
        clean = capture.sanitise(first)
        # Another run mints other ids and times and reorders the client's map;
        # the capture must not change.
        self.assertEqual(capture.sanitise(run(
            'bbbbbbbb-0000-4000-8000-000000000001', 'bbbbbbbb-0000-4000-8000-000000000002',
            'bbbbbbbb-0000-4000-8000-000000000003', 'fedcba9876543210',
            1790231899999, 1790231899.9, flip=True)), clean)
        self.assertEqual(clean['prompt_cache_key'], '<prompt_cache_key>')
        self.assertNotIn('aaaaaaaa', json.dumps(clean))
        self.assertEqual(clean['client_metadata'], {
            'thread_id': '<id-1>', 'x-codex-installation-id': '<id-2>',
            'x-codex-turn-metadata': '{"installation_id":"<id-2>","thread_id":"<id-1>",'
                                     '"window_id":"<id-1>:0","turn_started_at_unix_ms":0,'
                                     '"window_number":0}'})
        output = clean['input'][1]
        self.assertEqual(output['id'], 'fco_<id-3>')
        self.assertEqual(output['internal_chat_message_metadata_passthrough'],
                         {'turn_id': '<id-3>', 'create_time': 0})
        self.assertEqual(clean['input'][2]['id'], 'cmp_<id-4>')
        # Tool arguments keep their spelling and a schema property of that name survives.
        self.assertEqual(clean['input'][0]['arguments'], '{"value": "x"}')
        self.assertEqual(clean['tools'][0]['parameters']['properties']['create_time'],
                         {'type': 'number'})


class DriftTests(unittest.TestCase):
    def test_item_types_keys_and_developer_prefixes_added_or_removed(self):
        before = [record([developer('<permissions instructions>\nold'),
                          {'type': 'reasoning', 'summary': []}], store=False)]
        after = [record([developer('<permissions instructions>\nnew'),
                         developer('<model_switch>\nThe user was previously using'),
                         {'role': 'user', 'content': '<user_note> a user text is no prefix'},
                         {'type': 'compaction_trigger'}], store=False, client_metadata={})]
        # A typeless item with a role is a message, and only the first 24
        # characters of a developer text count, so a changed body is no drift.
        self.assertEqual(capture.drift(before, after), {
            'item_types': {'added': ['compaction_trigger'], 'removed': ['reasoning']},
            'top_level_keys': {'added': ['client_metadata'], 'removed': []},
            'developer_prefixes': {'added': ['<model_switch>\nThe user '], 'removed': []}})
        self.assertEqual(capture.drift(after, after)['item_types'], {'added': [], 'removed': []})

    def test_the_newest_earlier_version_is_compared(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        for name in ('0.153.4', '0.155.0-alpha.9.2', '0.155.0-alpha.16.3', '0.156.0'):
            (root / name).mkdir()
        (root / '0.155.0-alpha.12.0').write_text('a file, not a capture')
        # Numeric, not text order: alpha.9 is older than alpha.16.
        self.assertEqual(capture.earlier_capture(root, '0.155.0-alpha.16.3').name,
                         '0.155.0-alpha.9.2')
        self.assertIsNone(capture.earlier_capture(root, '0.153.4'))
        self.assertIsNone(capture.earlier_capture(root / 'absent', '0.156.0'))

    def test_report_names_the_earlier_capture_or_says_there_is_none(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        old = [record([developer('<permissions instructions>')])]
        new = [record([developer('<permissions instructions>'), {'type': 'compaction'}])]
        for version in ('0.155.0-alpha.9.2', '0.155.0-alpha.16.3'):
            (root / version).mkdir()
        (root / '0.155.0-alpha.9.2' / 'switch.json').write_text(
            json.dumps({'scenario': 'switch', 'requests': old}))
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            capture.report(root, '0.155.0-alpha.16.3', {'switch': new})
            capture.report(root, '0.155.0-alpha.9.2', {'switch': old})
        first, second = map(json.loads, printed.getvalue().splitlines())
        self.assertEqual(first['against'], '0.155.0-alpha.9.2')
        self.assertEqual(first['item_types'], {'added': ['compaction'], 'removed': []})
        self.assertEqual(second, {'codex': '0.155.0-alpha.9.2',
                                  'drift': 'no earlier capture to compare'})


if __name__ == '__main__':
    unittest.main()
