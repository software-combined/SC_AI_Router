"""Which frames count as the client's answer, and which as reasoning."""
import json
import unittest
from unittest import mock

from ai_router import router as router_mod
from ai_router import sse, stream_errors, stream_events
from tests.fakes import FakeUpstream, install_fake
from tests.harness import post as _post, start_auth_server as _start_auth_server


def _frame(event):
    return sse.frame(json.dumps(event).encode())


def _kind(event):
    """The lifecycle kind `stream_errors.events` gives one frame."""
    (only,) = stream_errors.events([_frame(event)], {})
    return only.kind


class AnswerFrameTests(unittest.TestCase):
    def test_reasoning_items_are_replaceable(self):
        # A reasoning item added before a failure is not answer bytes: a retry
        # supersedes it, and treating it as an answer would suppress the retry
        # for every reasoning-capable model. An item with no type is neither,
        # so it commits the attempt without counting as answer.
        for kind in ('response.output_item.added', 'response.output_item.done'):
            for item_type, expected in (('reasoning', stream_events.REASONING),
                                        (None, stream_events.OPAQUE)):
                with self.subTest(kind=kind, item=item_type):
                    self.assertEqual(_kind({'type': kind, 'item': {'type': item_type}}),
                                     expected)

    def test_message_and_tool_items_are_answers(self):
        for item_type in ('message', 'function_call', 'custom_tool_call'):
            with self.subTest(item=item_type):
                self.assertEqual(_kind({'type': 'response.output_item.added',
                                        'item': {'type': item_type}}),
                                 stream_events.ANSWER)

    def test_text_and_tool_argument_deltas_are_answers(self):
        for kind in ('response.output_text.delta',
                     'response.function_call_arguments.delta'):
            with self.subTest(kind=kind):
                self.assertEqual(_kind({'type': kind, 'delta': 'x'}), stream_events.ANSWER)

    def test_setup_and_unknown_frames_are_not_answers(self):
        for kind in ('response.created', 'response.in_progress'):
            with self.subTest(kind=kind):
                self.assertEqual(_kind({'type': kind, 'response': {'id': 'r'}}),
                                 stream_events.SETUP)
        self.assertEqual(_kind({'type': 'unknown.kind'}), stream_events.OPAQUE)


class ReasoningFrameTests(unittest.TestCase):
    """The reasoning kind names replaceable bytes without calling them answer."""

    def test_reasoning_text_deltas_are_reasoning_not_answer(self):
        # The plan 177 capture: deepseek-v4.1-flash streams reasoning as text,
        # and those bytes reached the log unattributed until this kind.
        for kind in ('response.reasoning_text.delta', 'response.reasoning_text.done'):
            with self.subTest(kind=kind):
                self.assertEqual(_kind({'type': kind, 'delta': 'x'}),
                                 stream_events.REASONING)

    def test_the_two_frame_sets_are_disjoint(self):
        # A kind in both sets would be counted as content and as reasoning in
        # the same frame, so forwarded bytes would stop being their sum.
        self.assertEqual(stream_events.ANSWER_FRAME_TYPES
                         & stream_events.REASONING_FRAME_TYPES, frozenset())


class ReasoningBytesTests(unittest.TestCase):
    """End to end through the relay: reasoning bytes are counted, never answer.

    The 2026-09-15 incident: a stream ended on the prepared output cap after
    forwarding megabytes the log called unattributed, because nothing said
    which cap was sent or that the bytes were reasoning.
    """

    MODEL = 'deepseek/deepseek-v4.1-flash'

    def test_reasoning_then_cap_limited_incomplete_is_read_from_the_log(self):
        reasoning = _frame({'type': 'response.output_item.added',
                            'item': {'type': 'reasoning', 'id': 'rs_1'}})
        wire = (_frame({'type': 'response.created', 'response': {
                    'id': 'r1', 'model': self.MODEL}})
                + reasoning
                + _frame({'type': 'response.incomplete', 'response': {
                    'id': 'r1', 'incomplete_details': {'reason': 'max_output_tokens'}}}))
        recorded = install_fake(self, lambda: FakeUpstream(
            200, wire, [('Content-Type', 'text/event-stream')]))
        server = _start_auth_server(self)
        with mock.patch.object(router_mod, 'log_event') as logged:
            response = _post(server.server_port, '/test-token/responses',
                             {'model': self.MODEL, 'input': [], 'stream': True,
                              'tools': [{'type': 'custom', 'name': 'exec'}]})
            self.assertEqual(response.status, 200)
            body = response.read()
        self.assertIn(b'response.incomplete', body)
        failures = [c for c in logged.call_args_list if c.args[0] == 'request_failed']
        self.assertEqual(len(failures), 1)
        kwargs = failures[0].kwargs
        self.assertGreater(kwargs['reasoning_delta_bytes'], 0)
        self.assertLess(kwargs['reasoning_delta_bytes'], kwargs['forwarded_delta_bytes'])
        self.assertEqual(kwargs['content_delta_bytes'], 0)
        self.assertEqual(kwargs['upstream_reason'], 'max_output_tokens')
        # The cap the log names is the cap the request actually sent.
        self.assertEqual(kwargs['max_output_tokens'],
                         json.loads(recorded[0][3])['max_output_tokens'])


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
