"""Handoff receipts must belong to the actual child, including same-model cases."""
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
import urllib.error
from unittest.mock import Mock, patch

from ai_router import provider_defs, providers
from ai_router.credentials import Credentials
from tools import probe_agent_handoffs as handoffs
from tools.probe_desktop_handoff import CaseBudget, LegacyProbe, legacy_gate, outcome
from tools.probe_handoff_matrix import MARKERS, MatrixProbe

PARENT = {'thread-id': 'synthetic-parent', 'x-codex-turn-metadata': json.dumps({'agent_name': '/root'})}
CIPHERTEXT = 'gAAAA' + 'B' * 60


def call(name, message, **fields):
    return {'type': 'function_call', 'namespace': 'collaboration', 'name': name, 'call_id': 'call_' + name,
            'arguments': json.dumps({'target': 'legacy_native', 'message': message}), **fields}


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
            probe.facts.update(child_receipts=list(MARKERS), canonical_replay=True,
                selections=[{'tool': 'spawn_agent', 'model': probe.child,
                    'reasoning_effort': probe.child_effort, 'fork_turns': 'none', 'plaintext': True},
                    {'tool': 'followup_task', 'plaintext': True}])
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

    def test_client_side_calls_are_scored_by_shape_and_refusal_codes_are_kept(self):
        # R2 restores an alias call before Codex sees it; only the client view is scored.
        raw = handoffs.sse([call('followup_task', 'reply SYNTH_LEGACY_R2', encrypted_function_args=[]),
                            call('spawn_agent', CIPHERTEXT, encrypted_function_args=['message']),
                            {**call('send_message', 'readable'), 'namespace': 'collaboration_plaintext'}], 'r1')
        failed = json.dumps({'type': 'response.failed', 'response': {
            'error': {'code': 'HANDOFF_REQUIRES_PLAINTEXT', 'message': 'private refusal text'}}})
        self.probe.observe(raw + b'data: ' + failed.encode() + b'\n\n', 'parent')
        self.assertEqual([(c['tool'], c['namespace'], c['marker'], c['message_shape']) for c in self.probe.facts['client_calls']], [
            ('followup_task', 'canonical', 'empty', 'readable'), ('spawn_agent', 'canonical', 'nonempty', 'ciphertext'),
            ('send_message', 'other', 'absent', 'readable')])
        error = urllib.error.HTTPError('http://127.0.0.1:9/synthetic', 400, 'private', {}, io.BytesIO(
            json.dumps({'error': {'code': 'UPSTREAM_INVALID_REQUEST', 'message': 'private upstream text'}}).encode()))
        with patch.object(handoffs.Probe, 'forward', side_effect=error), self.assertRaises(urllib.error.HTTPError):
            self.probe.forward({'model': self.probe.parent}, {}, role='parent')
        self.assertEqual(self.probe.facts['rejections'], [
            {'turn': 1, 'role': 'parent', 'status': 200, 'code': 'HANDOFF_REQUIRES_PLAINTEXT'},
            {'turn': 1, 'role': 'parent', 'status': 400, 'code': 'UPSTREAM_INVALID_REQUEST'}])
        self.assertNotIn('private', json.dumps(self.probe.facts))


class LegacyCaseTests(unittest.TestCase):
    def legacy(self):
        probe = LegacyProbe(False, 0, False)
        probe.parent_thread_id = 'synthetic-parent'
        return probe

    def passing(self):
        probe = self.legacy()
        first, follow, fresh = probe.markers
        readable = {'namespace': 'canonical', 'marker': 'empty', 'message_shape': 'readable'}
        probe.child_agents = {('native-thread', '/root/legacy_native'), ('external-thread', '/root/legacy_external')}
        probe.facts.update(gate_off_lookups=2, client_calls=[
            {'turn': 1, 'tool': 'spawn_agent', 'namespace': 'canonical', 'marker': 'nonempty', 'message_shape': 'ciphertext'},
            {'turn': 2, 'tool': 'followup_task', **readable}, {'turn': 2, 'tool': 'spawn_agent', **readable}],
            receipt_roles=[[first, 'child'], [follow, 'child'], [fresh, 'external']], child_briefs=[
                {'turn': 1, 'role': 'child', 'opaque': [True]}, {'turn': 2, 'role': 'child', 'opaque': [True, False]},
                {'turn': 2, 'role': 'external', 'opaque': [False]}])
        return probe

    def test_children_map_to_their_own_routes(self):
        probe = self.legacy()
        for agent, role in (('/root/legacy_native', 'child'), ('/root/legacy_external', 'external')):
            headers = {'thread-id': agent, 'x-codex-parent-thread-id': 'synthetic-parent',
                       'x-codex-turn-metadata': json.dumps({'agent_name': agent})}
            self.assertEqual(probe.role(headers), role)
        self.assertEqual(probe.routes, {'parent': (probe.parent, 'high'), 'child': (probe.parent, 'low'),
                                        'external': ('deepseek/deepseek-v4.1-flash', 'low')})

    def test_external_key_is_hidden_from_the_router_gate_only_during_parent_turn_one(self):
        probe = self.legacy()
        body = {'model': probe.parent, 'input': [], 'tools': []}
        prepare = providers.SubscriptionProvider().prepare
        with tempfile.TemporaryDirectory() as temp, legacy_gate([probe]):
            credentials = Credentials({}, home=temp, env={provider_defs.OPENROUTER.key.env: 'synthetic'})
            self.assertIsInstance(credentials.key_missing(provider_defs.OPENROUTER.id), LookupError)
            prepare(probe.parent, '/responses', body, json.dumps(body).encode(), {}, credentials)
            # The native readable gate itself consulted the patched lookup.
            looked = probe.facts['gate_off_lookups']
            self.assertGreater(looked, 1)
            probe.facts['completed_turns'] = [{'thread': 'native-thread', 'status': 'completed'}]
            self.assertTrue(probe.gate_off())
            probe.facts['completed_turns'].append({'thread': 'synthetic-parent', 'status': 'completed'})
            self.assertIsNone(credentials.key_missing(provider_defs.OPENROUTER.id))
            prepare(probe.parent, '/responses', body, json.dumps(body).encode(), {}, credentials)
            self.assertEqual(probe.facts['gate_off_lookups'], looked)

    def test_turn_two_stops_before_sending_without_turn_one_legacy_history(self):
        probe = self.legacy()
        probe.facts['completed_turns'] = [{'thread': 'synthetic-parent', 'status': 'completed'}]
        body = {'model': probe.parent, 'reasoning': {'effort': probe.parent_effort}, 'input': []}
        with patch.object(probe, 'scripted_response') as send, self.assertRaisesRegex(ValueError, 'precondition'):
            probe.respond(body, PARENT, 1)
        send.assert_not_called()
        self.assertTrue(probe.facts['setup_failed'])

    def test_every_gate_must_hold_and_each_failure_gets_a_verdict(self):
        probe, budget = self.passing(), CaseBudget(Mock())
        self.assertTrue(probe.verify())
        self.assertEqual(outcome(True, probe, budget), 'passed')
        failures = {
            'follow-up still marked encrypted': lambda p: p.facts['client_calls'][1].update(marker='nonempty'),
            'turn 2 ciphertext': lambda p: p.facts['client_calls'][2].update(message_shape='ciphertext'),
            'alias reached the client': lambda p: p.facts['client_calls'][2].update(namespace='other'),
            'receipt twice': lambda p: p.facts['receipt_roles'].append([p.markers[1], 'child']),
            'second native child': lambda p: p.child_agents.add(('other-thread', '/root/legacy_native')),
            'opaque follow-up': lambda p: p.facts['child_briefs'][1].update(opaque=[True, True]),
            'opaque external brief': lambda p: p.facts['child_briefs'][2].update(opaque=[True]),
            'parent turn 2 rejected': lambda p: p.facts['rejections'].append(
                {'turn': 2, 'role': 'parent', 'status': 400, 'code': 'UPSTREAM_INVALID_REQUEST'}),
            'tool error': lambda p: p.facts['tool_failures'].append('tool_output_reported_failure'),
            'gate never consulted': lambda p: p.facts.update(gate_off_lookups=0)}
        for name, damage in failures.items():
            with self.subTest(name):
                probe = self.passing()
                damage(probe)
                self.assertFalse(probe.verify())
        probe = self.passing()
        verdicts = (
            ({'router_rows': [{'turn': 2, 'event': 'handoff_observed', 'guard_rejected': True}]}, {}, 'refused'),
            ({'router_rows': [{'turn': 2, 'event': 'upstream_rejected', 'code': 'UPSTREAM_INVALID_REQUEST'}]}, {}, 'refused'),
            ({'router_rows': []}, {'exhausted': 'call'}, 'inconclusive_budget'),
            ({}, {'exhausted': None, 'deadline': 0}, 'inconclusive_time'),
            ({}, {'deadline': time.monotonic() + 60}, 'failed'))
        for probe_fields, budget_fields, verdict in verdicts:
            with self.subTest(verdict):
                vars(probe).update(probe_fields)
                vars(budget).update(budget_fields)
                self.assertEqual(outcome(False, probe, budget), verdict)
        probe.facts['setup_failed'] = 'turn 1 left no ciphertext spawn with receipt 1'
        self.assertEqual(outcome(False, probe, budget), 'setup_failed')


if __name__ == '__main__':
    unittest.main()
