import unittest
import base64
from ai_router.compaction import (PREFIX, TRANSCRIPT_BUDGET, build_compact_v1_output,
    compaction_text, decode_summary, encode_summary, extract_summary, extract_user_messages,
    has_compaction_trigger, note_images, rewrite_input, scrub_tool_fragments, strip_images,
    transcript_for_summary, v2_compaction_item, OPAQUE_NOTE)

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


class ScrubFragmentsTests(unittest.TestCase):
    def test_partial_calls_are_dropped(self):
        items = [{'type': 'apply_patch_call'},
                 {'type': 'function_call', 'name': 'e', 'call_id': 'c1'},
                 {'type': 'custom_tool_call', 'name': 'e'},
                 {'type': 'message', 'role': 'user', 'content': 'hi'}]
        scrubbed = scrub_tool_fragments(items)
        self.assertEqual(scrubbed, [items[-1]])

    def test_apply_patch_call_needs_status_and_operation(self):
        good = {'type': 'apply_patch_call', 'call_id': 'c1',
                'status': 'completed', 'operation': {'op': 'create'}}
        self.assertIn(good, scrub_tool_fragments([good]))
        for bad in ({'type': 'apply_patch_call', 'call_id': 'c1',
                     'status': 'completed'},
                    {'type': 'apply_patch_call', 'call_id': 'c1',
                     'operation': {'op': 'create'}},
                    {'type': 'apply_patch_call', 'call_id': 'c1',
                     'status': 'failed', 'operation': {'op': 'x'}}):
            self.assertNotIn(bad, scrub_tool_fragments([bad]))

    def test_orphan_outputs_are_dropped_complete_pairs_survive(self):
        call = {'type': 'function_call', 'name': 'e', 'call_id': 'c1',
                'arguments': '{"v": 1}'}
        result = {'type': 'function_call_output', 'call_id': 'c1', 'output': 'ok'}
        self.assertEqual(scrub_tool_fragments([call, result]), [call, result])
        orphan = {'type': 'function_call_output', 'call_id': 'c9', 'output': 'ok'}
        self.assertEqual(scrub_tool_fragments([call, orphan]), [call])
        self.assertEqual(scrub_tool_fragments(
            [{'type': 'custom_tool_call_output', 'call_id': 'c9', 'output': 'ok'}]), [])

    def test_non_list_input_passes_through(self):
        self.assertEqual(scrub_tool_fragments('do the task'), 'do the task')

    def test_output_of_dropped_partial_call_is_dropped_too(self):
        items = [{'type': 'function_call', 'name': 'e', 'call_id': 'c1'},
                 {'type': 'function_call_output', 'call_id': 'c1', 'output': 'ok'}]
        self.assertEqual(scrub_tool_fragments(items), [])


class TriggerTests(unittest.TestCase):
    def test_trigger_detected_only_by_type(self):
        self.assertTrue(has_compaction_trigger([{'type': 'compaction_trigger'}]))
        self.assertTrue(has_compaction_trigger(
            [{'type': 'message', 'role': 'user', 'content': 'hi'},
             {'type': 'compaction_trigger', 'extra': 1}]))
        self.assertFalse(has_compaction_trigger(
            [{'type': 'message', 'role': 'user', 'content': 'hi'}]))
        self.assertFalse(has_compaction_trigger([]))
        self.assertFalse(has_compaction_trigger(None))
        self.assertFalse(has_compaction_trigger('compaction_trigger'))

    def test_v2_item_carries_exactly_one_decodable_blob(self):
        item = v2_compaction_item('progress made')
        self.assertEqual(item['type'], 'compaction')
        self.assertTrue(item['id'].startswith('cmp_'))
        self.assertEqual(decode_summary(item['encrypted_content']), 'progress made')
        self.assertEqual(encode_summary('x'), PREFIX + base64.b64encode(b'x').decode())
        with self.assertRaisesRegex(ValueError, 'summary'):
            v2_compaction_item('  ')

    def test_v2_item_replays_through_rewrite(self):
        item = v2_compaction_item('task done; next: verify')
        rewritten = rewrite_input(
            [{'type': 'message', 'role': 'user', 'content': 'older'},
             item, {'type': 'compaction_trigger'}])
        self.assertEqual(len(rewritten), 3)
        self.assertIn('task done; next: verify', rewritten[1]['content'][0]['text'])

    def test_extract_summary_rejects_explicit_incomplete(self):
        good = {'output': [{'type': 'message', 'content': [
            {'type': 'output_text', 'text': 'done'}]}]}
        self.assertEqual(extract_summary(200, good), 'done')
        self.assertEqual(
            extract_summary(200, {**good, 'incomplete_details': None}), 'done')
        self.assertEqual(
            extract_summary(200, {**good, 'incomplete_details': {'reason': None}}), 'done')
        with self.assertRaisesRegex(ValueError, 'max_output_tokens'):
            extract_summary(200, {**good,
                                  'incomplete_details': {'reason': 'max_output_tokens'}})


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

    def test_oversized_newest_message_truncates_tail_never_empty(self):
        huge = 'x' * (TRANSCRIPT_BUDGET + 5000)
        out = transcript_for_summary(
            [{'type': 'message', 'role': 'user', 'content': 'old brief'},
             {'type': 'message', 'role': 'user', 'content': huge}])
        self.assertTrue(out)
        self.assertLessEqual(len(out), TRANSCRIPT_BUDGET)
        self.assertTrue(out.endswith('x' * 100))
        self.assertNotIn('old brief', out)

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

class ImageStripTests(unittest.TestCase):
    def _item(self):
        return {'type': 'message', 'role': 'user', 'content': [
            {'type': 'input_text', 'text': 'look here'},
            {'type': 'input_image', 'image_url': 'data:image/png;base64,AAA', 'detail': 'high'}]}

    def test_image_blocks_dropped_text_kept_without_mutating(self):
        item = self._item()
        out = strip_images([item], False)
        self.assertEqual(out[0]['content'], [{'type': 'input_text', 'text': 'look here'}])
        self.assertEqual(len(item['content']), 2)

    def test_keep_images_passes_through(self):
        item = self._item()
        self.assertIs(strip_images([item], True)[0], item)
        self.assertEqual(strip_images('prompt', False), 'prompt')

    def test_noted_images_stay_text_only_without_mutating(self):
        item = self._item()
        out = note_images([item])
        self.assertEqual(out[0]['content'],
            [{'type': 'input_text', 'text': 'look here'},
             {'type': 'input_text', 'text': '[image omitted: this model runs text-only]'}])
        self.assertEqual(len(item['content']), 2)
        self.assertEqual(note_images('prompt'), 'prompt')

class TranscriptBoundaryTests(unittest.TestCase):
    def test_drops_oldest_whole_items_newest_first(self):
        big = {'type': 'message', 'role': 'user', 'content': 'A' * TRANSCRIPT_BUDGET}
        small = {'type': 'message', 'role': 'user', 'content': 'B-fresh'}
        text = transcript_for_summary([big, small])
        self.assertIn('B-fresh', text)
        self.assertNotIn('A', text)
        self.assertLessEqual(len(text), TRANSCRIPT_BUDGET)

    def test_over_budget_middle_item_does_not_punch_hole_for_oldest(self):
        oldest = {'type': 'message', 'role': 'user', 'content': 'ancient-marker'}
        middle = {'type': 'message', 'role': 'user', 'content': 'M' * TRANSCRIPT_BUDGET}
        newest = {'type': 'message', 'role': 'user', 'content': 'fresh-marker'}
        text = transcript_for_summary([oldest, middle, newest])
        self.assertIn('fresh-marker', text)
        self.assertNotIn('ancient-marker', text)
        self.assertLessEqual(len(text), TRANSCRIPT_BUDGET)

    def test_tool_call_line_names_the_tool(self):
        text = transcript_for_summary([
            {'type': 'function_call', 'name': 'send_message', 'arguments': '{"text":"hi"}'},
            {'type': 'custom_tool_call', 'namespace': 'slack', 'name': 'post', 'input': 'hi'},
        ])
        self.assertIn('send_message', text)
        self.assertIn('slack.post', text)


class ReasoningAndShapeTests(unittest.TestCase):
    def test_reasoning_plaintext_kept_encrypted_dropped(self):
        text = transcript_for_summary([
            {'type': 'reasoning', 'summary': [{'type': 'text', 'text': 'chose X'}]},
            {'type': 'reasoning', 'encrypted_content': 'opaque', 'summary': [{'type': 'text', 'text': 'leak'}]},
        ])
        self.assertIn('chose X', text)
        self.assertNotIn('leak', text)
        self.assertNotIn('opaque', text)

    def test_alternate_result_keys_extracted(self):
        for key in ('output', 'result', 'content', 'text', 'data'):
            with self.subTest(key=key):
                text = transcript_for_summary([
                    {'type': 'function_call_output', 'call_id': 'c', key: 'CODE-9'}])
                self.assertIn('CODE-9', text)

    def test_list_shaped_tool_output_extracted(self):
        text = transcript_for_summary([
            {'type': 'function_call_output', 'call_id': 'c',
             'output': [{'type': 'text', 'text': 'result CODE-1'}]},
        ])
        self.assertIn('result CODE-1', text)

    def test_prompt_demands_verbatim_values(self):
        from ai_router.compaction import COMPACT_PROMPT
        self.assertIn('verbatim', COMPACT_PROMPT)

if __name__ == '__main__':
    unittest.main()
