"""Which frames count as the client's answer, and so block a retry."""
import json
import unittest

from ai_router import sse, stream_errors


def _frame(event):
    return sse.frame(json.dumps(event).encode())


class AnswerFrameTests(unittest.TestCase):
    def _answer(self, event):
        metrics = {}
        list(stream_errors.normalize([_frame(event)], metrics))
        return metrics.get('answer_frame')

    def test_reasoning_items_are_replaceable(self):
        # A reasoning item added before a failure is not answer bytes: a retry
        # supersedes it, and treating it as an answer would suppress the retry
        # for every reasoning-capable model.
        for kind in ('response.output_item.added', 'response.output_item.done'):
            for item_type in ('reasoning', None):
                with self.subTest(kind=kind, item=item_type):
                    self.assertIsNone(self._answer(
                        {'type': kind, 'item': {'type': item_type}}))

    def test_message_and_tool_items_are_answers(self):
        for item_type in ('message', 'function_call', 'custom_tool_call'):
            with self.subTest(item=item_type):
                self.assertEqual(self._answer(
                    {'type': 'response.output_item.added',
                     'item': {'type': item_type}}),
                    'response.output_item.added')

    def test_text_and_tool_argument_deltas_are_answers(self):
        for kind in ('response.output_text.delta',
                     'response.function_call_arguments.delta'):
            with self.subTest(kind=kind):
                self.assertEqual(self._answer({'type': kind, 'delta': 'x'}), kind)

    def test_setup_and_unknown_frames_are_not_answers(self):
        for kind in ('response.created', 'response.in_progress', 'unknown.kind'):
            with self.subTest(kind=kind):
                self.assertIsNone(self._answer({'type': kind}))


class RewrittenTerminalTests(unittest.TestCase):
    def test_a_router_rewritten_refusal_is_attributed_to_the_router(self):
        # The provider's own frame is replaced here, so the client reads a
        # router-written one; the bounded upstream code stays as the reason,
        # and the emitted code keeps the fatal `invalid_prompt` Codex ends on.
        metrics = {}
        wire = _frame({'type': 'response.failed', 'response': {
            'error': {'code': 'invalid_prompt'}}})
        out = b''.join(stream_errors.normalize([wire], metrics))
        self.assertIn(b'"code": "invalid_prompt"', out)
        self.assertEqual(metrics['upstream_code'], 'invalid_prompt')
        self.assertEqual(metrics['code'], 'UPSTREAM_INVALID_PROMPT')
        self.assertEqual(metrics['terminal_source'], 'router')
        self.assertEqual(metrics['failure_class'], 'final')

    def test_a_provider_verdict_is_attributed_to_the_upstream(self):
        metrics = {}
        wire = _frame({'type': 'response.failed', 'response': {
            'error': {'code': 'overloaded'}}})
        out = b''.join(stream_errors.normalize([wire], metrics))
        self.assertEqual(out, wire)
        self.assertEqual(metrics['terminal_source'], 'upstream')


if __name__ == '__main__':
    unittest.main()
