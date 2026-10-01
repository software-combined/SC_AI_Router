"""Handoff receipts must belong to the actual child, including same-model cases."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import probe_agent_handoffs as handoffs
from tools.probe_handoff_matrix import MARKERS, MatrixProbe


class MatrixProbeTests(unittest.TestCase):
    def setUp(self):
        self.probe = MatrixProbe(False, 0, False)
        self.probe.parent_thread_id = 'synthetic-parent'
        self.headers = {'thread-id': 'synthetic-child',
            'x-codex-parent-thread-id': 'synthetic-parent',
            'x-codex-turn-metadata': json.dumps({'agent_name': '/root/matrix_child'})}

    def test_same_model_child_requires_its_own_thread_parent_and_agent_identity(self):
        self.assertEqual(self.probe.role(self.headers), 'child')
        for change in ({'thread-id': 'synthetic-parent'},
                       {'x-codex-parent-thread-id': 'other-parent'},
                       {'x-codex-turn-metadata': json.dumps({'agent_name': '/root'})}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.probe.role({**self.headers, **change})
        root = {'thread-id': 'synthetic-parent',
                'x-codex-turn-metadata': json.dumps({'agent_name': '/root'})}
        self.assertEqual(self.probe.role(root), 'parent')

    def test_parent_echo_never_counts_as_child_receipt(self):
        raw = handoffs.sse([handoffs.message(MARKERS[0], 'synthetic')], 'synthetic')
        self.probe.observe(raw, self.probe.role({'thread-id': 'synthetic-parent',
            'x-codex-turn-metadata': json.dumps({'agent_name': '/root'})}))
        self.assertEqual(self.probe.facts['child_receipts'], [])
        self.assertFalse(self.probe.receipt.is_set())
        self.probe.observe(raw, self.probe.role(self.headers))
        self.assertEqual(self.probe.facts['child_receipts'], [MARKERS[0]])
        self.assertTrue(self.probe.receipt.is_set())

    def test_receipts_and_replay_do_not_override_a_recorded_failure(self):
        probe = self.probe
        with tempfile.TemporaryDirectory() as temp:
            probe.home = Path(temp)
            (probe.home / 'sessions').mkdir()
            probe.call_ids = {'initial', 'followup'}
            (probe.home / 'sessions/synthetic.jsonl').write_text('\n'.join(json.dumps({
                'payload': {'type': 'function_call', 'namespace': 'collaboration', 'call_id': ident}})
                for ident in probe.call_ids))
            probe.child_agents = {('synthetic-child', '/root/matrix_child')}
            plaintext = not (probe.parent == probe.native and probe.child == probe.native)
            probe.facts.update(child_receipts=list(MARKERS), canonical_replay=True,
                selections=[{'tool': 'spawn_agent', 'model': probe.child,
                    'reasoning_effort': probe.child_effort, 'fork_turns': 'none', 'plaintext': plaintext},
                    {'tool': 'followup_task', 'plaintext': plaintext}])
            self.assertTrue(probe.verify())
            for failure in ({'retry_events': 1}, {'request_failures': [{'code': 'UPSTREAM_INCOMPLETE'}]}):
                with self.subTest(failure=failure):
                    probe.facts.update(retry_events=0, request_failures=[])
                    probe.facts.update(failure)
                    self.assertFalse(probe.verify())
            probe.facts.update(retry_events=0, request_failures=[])
            body = {'model': probe.parent, 'reasoning': {'effort': probe.parent_effort},
                'input': [{'type': 'function_call_output', 'output': 'error: unknown agent target SYNTH_PRIVATE'}]}
            headers = {'thread-id': 'synthetic-parent',
                'x-codex-turn-metadata': json.dumps({'agent_name': '/root'})}
            with patch.object(probe, 'scripted_response', return_value=b''):
                probe.respond(body, headers, 1)
            self.assertEqual(probe.facts['tool_failures'], ['tool_output_reported_failure'])
            self.assertFalse(probe.verify())


if __name__ == '__main__':
    unittest.main()
