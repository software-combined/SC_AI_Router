"""Paid handoff checks cannot exceed their upstream send or output budgets."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from ai_router.transport import Prepared
from tools import probe_agent_handoffs as handoffs
from tools.probe_review_handoffs import Budget, CHILD, EFFORT, MAX_CALLS, MAX_INPUT, MAX_OUTPUT, PARENT, ReviewProbe


def prepared(payload=None):
    return Prepared('synthetic.invalid', '/responses', {}, json.dumps(
        payload or {'model': CHILD, 'max_output_tokens': MAX_OUTPUT}).encode(), {}, 'openrouter')


class ReviewProbeTests(unittest.TestCase):
    def test_replays_consume_the_same_cap_and_exhaustion_never_sends(self):
        send = Mock(return_value='synthetic response')
        budget = Budget(send)
        conn = SimpleNamespace(timeout=120, sock=None)
        for _ in range(MAX_CALLS):
            self.assertEqual(budget(conn, prepared(), {}), 'synthetic response')
        with self.assertRaisesRegex(ValueError, 'call budget'):
            budget(conn, prepared(), {})
        self.assertEqual(send.call_count, MAX_CALLS)

    def test_missing_or_oversized_output_limits_refuse_before_send(self):
        send = Mock()
        for limit in (None, MAX_OUTPUT + 1):
            with self.subTest(limit=limit), self.assertRaisesRegex(ValueError, 'output budget'):
                Budget(send)(SimpleNamespace(timeout=120, sock=None), prepared({'max_output_tokens': limit}), {})
        send.assert_not_called()

    def test_oversized_input_or_expired_deadline_refuse_before_send(self):
        send = Mock()
        conn = SimpleNamespace(timeout=120, sock=None)
        with self.assertRaisesRegex(ValueError, 'input budget'):
            Budget(send)(conn, prepared({'max_output_tokens': MAX_OUTPUT, 'input': 'x' * MAX_INPUT}), {})
        budget = Budget(send)
        budget.deadline = 0
        with self.assertRaisesRegex(ValueError, 'time or input budget'):
            budget(conn, prepared(), {})
        send.assert_not_called()

    def test_client_wait_uses_the_remaining_overall_deadline(self):
        probe = ReviewProbe.__new__(ReviewProbe)
        probe.deadline = 300
        with patch('tools.probe_review_handoffs.time.monotonic', return_value=240):
            self.assertEqual(probe.timeout, 60)
        with patch('tools.probe_review_handoffs.time.monotonic', return_value=301):
            self.assertEqual(probe.timeout, 0)

    def test_acceptance_requires_child_replies_and_explicit_readable_selection(self):
        probe = ReviewProbe.__new__(ReviewProbe)
        probe.errors = []
        selection = {'model': CHILD, 'reasoning_effort': EFFORT, 'fork_turns': 'none', 'plaintext': True}
        probe.facts = {'tool_failures': [], 'request_failures': [], 'retry_events': 0, 'selections': [selection],
                       'replies': list(probe.expected_replies), 'canonical_replay': True, 'served': [], 'calls': [
                           {'model': PARENT, 'name': 'spawn_agent', 'task': 'review_probe', 'encrypted_fields': 'empty'},
                           {'model': PARENT, 'name': 'followup_task', 'target': '/root/review_probe', 'encrypted_fields': 'empty'}]}
        self.assertTrue(probe.verify())  # Missing served identity is unverified.
        for changes in ({'replies': []}, {'selections': [{**selection, 'model': 'other'}]},
                        {'selections': [{**selection, 'plaintext': False}]},
                        {'served': [{'model': 'other', 'effort': EFFORT}]},
                        {'request_failures': [{'code': 'UPSTREAM_INCOMPLETE'}]}, {'retry_events': 1},
                        {'calls': []}, {'calls': probe.facts['calls'][:1]},
                        {'calls': [probe.facts['calls'][0], {**probe.facts['calls'][1], 'target': '/root/other'}]}):
            with self.subTest(changes=changes), patch.dict(probe.facts, changes):
                self.assertFalse(probe.verify())

    def test_two_fresh_children_cannot_substitute_for_a_same_child_followup(self):
        probe = ReviewProbe.__new__(ReviewProbe)
        handoffs.Probe.__init__(probe, False, MAX_CALLS, live_children=True)
        probe.facts.update(selections=[], served=[])
        def spawn(task, ident):
            return {'type': 'function_call', 'namespace': 'collaboration', 'name': 'spawn_agent',
                    'call_id': ident, 'arguments': json.dumps({'task_name': task, 'model': CHILD,
                    'reasoning_effort': EFFORT, 'fork_turns': 'none'}), 'encrypted_function_args': []}
        initial = spawn('review_probe', 'initial')
        replacement = spawn('review_probe_followup', 'replacement')
        for inputs, item in (([], initial), ([initial], replacement)):
            with patch.object(probe, 'forward', return_value=handoffs.sse([item], item['call_id'])):
                probe.respond({'model': PARENT, 'input': inputs}, {}, 1)
        for marker in handoffs.MARKERS[:2]:
            body = {'model': CHILD, 'reasoning': {'effort': EFFORT}, 'input': [
                {'type': 'agent_message', 'content': [{'type': 'input_text', 'text': marker}]}]}
            with patch.object(probe, 'forward', return_value=handoffs.sse([handoffs.message(marker, marker)], marker)):
                probe.respond(body, {}, 2)
        self.assertEqual(set(probe.facts['replies']), probe.expected_replies)
        self.assertTrue(probe.facts['canonical_replay'])
        self.assertFalse(probe.verify())

    def test_task_prompts_do_not_prescribe_tool_names_or_model_arguments(self):
        for prompt in ReviewProbe.live_prompts:
            self.assertNotIn('collaboration', prompt)
            self.assertNotIn('fork_turns', prompt)
            self.assertNotIn(CHILD, prompt)

if __name__ == '__main__':
    unittest.main()
