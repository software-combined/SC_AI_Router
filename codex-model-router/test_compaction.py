import unittest
import base64
from compaction import (PREFIX, TRANSCRIPT_BUDGET, build_compact_v1_output,
    compaction_text, decode_summary, extract_user_messages, rewrite_input,
    transcript_for_summary, OPAQUE_NOTE)

class CompactionTests(unittest.TestCase):
    def test_transparent_envelope_round_trips(self):
        blob = PREFIX + base64.b64encode(b'task done; next: verify').decode()
        self.assertEqual(decode_summary(blob), 'task done; next: verify')
        self.assertIsNone(decode_summary('opaque-native-blob'))
        self.assertIn('task done', compaction_text({'encrypted_content': blob}))
        self.assertEqual(compaction_text({'encrypted_content': 'opaque'}), OPAQUE_NOTE)

    def test_opaque_history_stays_visible_never_silent(self):
        items = [{'type': 'compaction', 'encrypted_content': 'opaque'}]
        rewritten = rewrite_input(items)
        self.assertEqual(len(rewritten), 1)
        self.assertIn(OPAQUE_NOTE, rewritten[0]['content'][0]['text'])

    def test_v1_output_retains_messages_and_rejects_empty_summary(self):
        out = build_compact_v1_output(['first task'], 'progress made')
        self.assertEqual(len(out), 2)
        self.assertIn('progress made', out[-1]['content'][0]['text'])
        with self.assertRaisesRegex(ValueError, 'summary'):
            build_compact_v1_output(['first task'], '  ')


class TranscriptTests(unittest.TestCase):
    def test_transcript_covers_assistant_and_tool_results(self):
        items = [
            {'type': 'message', 'role': 'user', 'content': 'do the task'},
            {'type': 'message', 'role': 'assistant', 'content': [{'type': 'text', 'text': 'decided X'}]},
            {'type': 'function_call_output', 'call_id': 'c1', 'output': 'result Y'},
            {'type': 'compaction', 'encrypted_content': 'opaque'},
        ]
        text = transcript_for_summary(items)
        for expected in ['do the task', 'decided X', 'result Y', OPAQUE_NOTE]:
            self.assertIn(expected, text)

    def test_transcript_keeps_tail_within_budget(self):
        items = [{'type': 'message', 'role': 'user', 'content': 'x' * 10000} for _ in range(5)]
        self.assertLessEqual(len(transcript_for_summary(items)), TRANSCRIPT_BUDGET)
        self.assertIn('xxxx', transcript_for_summary(items))

    def test_non_list_input_passes_through(self):
        self.assertEqual(rewrite_input('prompt'), 'prompt')
        self.assertEqual(extract_user_messages('prompt'), [])
        self.assertEqual(transcript_for_summary('prompt'), '')

    def test_over_budget_drops_oldest_without_empty_blocks(self):
        msgs = ['first-task', 'x' * 90000, 'last-task']
        out = build_compact_v1_output(msgs, 'summary')
        texts = [item['content'][0]['text'] for item in out]
        self.assertNotIn('', texts)
        self.assertTrue(any('last-task' in text for text in texts))
        self.assertTrue(any('summary' in text for text in texts))

class TranscriptBoundaryTests(unittest.TestCase):
    def test_drops_oldest_whole_items_newest_first(self):
        big = {'type': 'message', 'role': 'user', 'content': 'A' * TRANSCRIPT_BUDGET}
        small = {'type': 'message', 'role': 'user', 'content': 'B-fresh'}
        text = transcript_for_summary([big, small])
        self.assertIn('B-fresh', text)
        self.assertNotIn('A', text)
        self.assertLessEqual(len(text), TRANSCRIPT_BUDGET)

if __name__ == '__main__':
    unittest.main()
