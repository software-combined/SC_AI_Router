"""A rejected handoff must explain its wire authority without exposing content."""
from contextlib import nullcontext
import io
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from ai_router import (agent_handoffs, errors, events, handoff_response, provider_defs,
                       providers, sse, stream_relay, transport)
from tests.test_agent_handoff_providers import Response

REQUEST = '0123456789abcdef0123456789abcdef'


def call(namespace='collaboration', marker=('message',)):
    item = {'type': 'function_call', 'namespace': namespace, 'name': 'spawn_agent',
            'id': 'SYNTH_SECRET_ITEM', 'call_id': 'SYNTH_SECRET_CALL',
            'arguments': json.dumps({'model': 'xiaomi/mimo-v2.6-pro',
                                    'task_name': 'SYNTH_SECRET_TASK',
                                    'message': 'SYNTH_SECRET_CONTENT'})}
    if marker is not None:
        item['encrypted_function_args'] = list(marker)
    return item


def frame(item, phase='done'):
    return sse.frame(json.dumps({'type': 'response.output_item.' + phase,
                                'output_index': 0, 'item': item}).encode())


class HandoffObservationTests(unittest.TestCase):
    def adapt(self, wire, names=None, notes=None, content_type='text/event-stream', rejected=False):
        rows, chunks = [], []
        names = names or agent_handoffs.AliasTools({'spawn_agent'}, stream=True)
        with mock.patch.object(events.LOG, 'info', side_effect=lambda row: rows.append(json.loads(row))):
            with self.assertRaises(errors.ResponseRejected) if rejected else nullcontext():
                chunks.extend(providers.SubscriptionProvider().adapt(
                    Response(wire, content_type), names, notes))
        return b''.join(chunks), rows

    def test_rejected_native_handoff_records_original_authority(self):
        names = agent_handoffs.AliasTools({'spawn_agent'}, stream=True)
        notes = {'request_id': REQUEST, 'attempt': 2}
        wire, rows = self.adapt(frame(call()), names, notes, rejected=True)
        rejected = [row for row in rows if row.get('event') == 'handoff_observed']
        self.assertEqual(len(rejected), 1)
        row = rejected[0]
        self.assertEqual((row['request_id'], row['attempt']), (REQUEST, 2))
        self.assertEqual(row['upstream'], {'namespace': 'native', 'marker': 'nonempty', 'arguments': 'object'})
        self.assertTrue(row['guard_rejected'])
        self.assertIsNone(row['client'])
        self.assertIsNone(row['frame_end_offset'])
        self.assertNotIn('SYNTH_SECRET', json.dumps(rows))
        self.assertEqual(wire, b'')

    def test_changed_envelope_does_not_inherit_plaintext_authority(self):
        added = call('collaboration_plaintext', None)
        added['arguments'] = ''
        done = call('collaboration', None)
        wire, rows = self.adapt(frame(added, 'added') + frame(done), rejected=True)
        seen = [row for row in rows if row['event'] == 'handoff_observed']
        self.assertEqual([row['call_ordinal'] for row in seen], [1, 1])
        self.assertEqual([row['guard_rejected'] for row in seen], [False, True])
        self.assertEqual([row['envelope_changed'] for row in seen], [False, True])
        self.assertTrue(all(row['identity_consistent'] for row in seen))
        self.assertIsNone(seen[-1]['frame_end_offset'])
        self.assertNotIn(b'output_item.done', wire)
        self.assertEqual(rows[-1]['missing_envelopes'], ['completed'])
        self.assertNotIn('SYNTH_SECRET', json.dumps(rows))

    def test_valid_alias_records_restoration_and_keeps_plaintext_object(self):
        original = call('collaboration_plaintext', None)
        completed = sse.frame(json.dumps({'type': 'response.completed',
                             'response': {'output': [original]}}).encode())
        wire, rows = self.adapt(frame(original, 'added') + frame(original) + completed)
        seen = [row for row in rows if row['event'] == 'handoff_observed']
        self.assertEqual(len(seen), 3)
        for row in seen:
            self.assertEqual(row['upstream']['namespace'], 'plaintext')
            self.assertEqual(row['client']['marker'], 'empty')
            self.assertFalse(row['guard_rejected'])
        self.assertEqual(rows[-1]['missing_envelopes'], [])
        self.assertNotIn('SYNTH_SECRET', json.dumps(rows))
        for _, data in sse.blocks(sse.lines([wire])):
            event = json.loads(data)
            output = event.get('item', event.get('response', {}).get('output', [None])[0])
            self.assertIsInstance(json.loads(output['arguments']), dict)
            self.assertEqual(output['encrypted_function_args'], [])

    def test_observation_limit_never_changes_wire_or_fails_stream(self):
        names = agent_handoffs.AliasTools({'spawn_agent'}, stream=True)
        originals = [{**call('collaboration_plaintext', None),
                      'id': str(index), 'call_id': 'c' + str(index)}
                     for index in range(handoff_response.MAX_CALLS + 5)]
        expected = b''.join(frame(agent_handoffs.restore_item(item, names)) for item in originals)
        notes = {}
        wire, rows = self.adapt(b''.join(frame(item) for item in originals), names, notes)
        self.assertEqual(wire, expected)
        self.assertEqual(len([row for row in rows if row['event'] == 'handoff_observed']),
                         handoff_response.MAX_CALLS)
        self.assertEqual(len([row for row in rows if row['event'] == 'handoff_observation_limited']), 1)
        self.assertTrue(notes['handoff_observation_incomplete'])
        self.assertLessEqual(len(rows), handoff_response.MAX_OBSERVATIONS + handoff_response.MAX_CALLS + 1)

    def test_repeated_envelope_limit_is_bounded(self):
        original = call('collaboration_plaintext', None)
        wire = frame(original) * (handoff_response.MAX_OBSERVATIONS + 4)
        result, rows = self.adapt(wire)
        self.assertEqual(len([row for row in rows if row['event'] == 'handoff_observed']),
                         handoff_response.MAX_OBSERVATIONS)
        self.assertEqual(result.count(b'output_item.done'), handoff_response.MAX_OBSERVATIONS + 4)
        self.assertTrue(rows[-1]['incomplete'])

    def test_native_encrypted_control_and_unrelated_bytes_are_unchanged(self):
        native = call()
        native['arguments'] = json.dumps({'model': 'gpt-6-luna', 'message': 'SYNTH_CIPHERTEXT'})
        raw = frame(native) + b': signed SSE comment\r\n\r\ndata: [DONE]\r\n\r\n'
        wire, rows = self.adapt(raw)
        self.assertEqual(wire, raw)
        observed = next(row for row in rows if row['event'] == 'handoff_observed')
        self.assertFalse(observed['guard_rejected'])
        self.assertEqual(observed['client']['marker'], 'nonempty')
        self.assertNotIn('SYNTH_CIPHERTEXT', json.dumps(rows))

    def test_json_response_and_lite_declaration_are_identified(self):
        original = call('collaboration_plaintext', None)
        names = agent_handoffs.AliasTools({'spawn_agent'}, location='lite')
        raw = json.dumps({'output': [original], 'model': 'gpt-6-luna'}).encode()
        notes = {}
        wire, rows = self.adapt(raw, names, notes, 'application/json')
        self.assertEqual(rows[0]['phase'], 'json')
        self.assertEqual(rows[0]['declaration'], 'lite')
        self.assertEqual(rows[0]['schema_mode'], 'plaintext')
        self.assertEqual(rows[0]['frame_end_offset'], len(wire))
        self.assertEqual(rows[-1]['missing_envelopes'], [])
        self.assertEqual(notes['served_model'], 'gpt-6-luna')

    def test_observer_failure_cannot_disable_rejection(self):
        raw = frame(call())
        with mock.patch.object(events.LOG, 'info', side_effect=ValueError('SYNTH_SECRET_LOG')):
            with self.assertRaises(errors.ResponseRejected):
                list(providers.SubscriptionProvider().adapt(
                    Response(raw, 'text/event-stream'), agent_handoffs.AliasTools({'spawn_agent'})))

    def test_alias_with_encrypted_marker_still_refuses_before_delivery(self):
        rows = []
        with mock.patch.object(events.LOG, 'info', side_effect=lambda row: rows.append(json.loads(row))):
            with self.assertRaises(errors.ResponseRejected):
                list(providers.SubscriptionProvider().adapt(
                    Response(frame(call('collaboration_plaintext')), 'text/event-stream'),
                    agent_handoffs.AliasTools({'spawn_agent'})))
        self.assertTrue(rows[0]['restoration_rejected'])
        self.assertIsNone(rows[0]['frame_end_offset'])
        self.assertNotIn('SYNTH_SECRET', json.dumps(rows))

    def test_early_close_records_missing_final_envelopes_without_delivery_claim(self):
        names = agent_handoffs.AliasTools({'spawn_agent'}, stream=True)
        rows = []
        with mock.patch.object(events.LOG, 'info', side_effect=lambda row: rows.append(json.loads(row))):
            iterator = providers.SubscriptionProvider().adapt(
                Response(frame({**call(), 'arguments': ''}, 'added') + frame(call()), 'text/event-stream'), names)
            next(iterator)
            iterator.close()
        self.assertEqual(rows[-1]['missing_envelopes'], ['completed', 'done'])
        self.assertNotIn('delivered', json.dumps(rows))

    def test_simultaneous_responses_do_not_share_identity_or_marker_state(self):
        first = providers.SubscriptionProvider().adapt(
            Response(frame(call()), 'text/event-stream'), agent_handoffs.AliasTools({'spawn_agent'}),
            {'request_id': REQUEST, 'attempt': 1})
        second_id = 'f' * 32
        second = providers.SubscriptionProvider().adapt(
            Response(frame(call('collaboration_plaintext', None)), 'text/event-stream'),
            agent_handoffs.AliasTools({'spawn_agent'}), {'request_id': second_id, 'attempt': 3})
        rows = []
        with mock.patch.object(events.LOG, 'info', side_effect=lambda row: rows.append(json.loads(row))):
            with self.assertRaises(errors.ResponseRejected):
                next(first)
            next(second)
            first.close()
            second.close()
        observed = [row for row in rows if row['event'] == 'handoff_observed']
        self.assertEqual([row['call_ordinal'] for row in observed], [1, 1])
        self.assertEqual([row['request_id'] for row in observed], [REQUEST, second_id])
        self.assertEqual([row['attempt'] for row in observed], [1, 3])
        self.assertEqual([row['guard_rejected'] for row in observed], [True, False])

    def test_frame_offsets_and_attempt_correlate_with_actual_downstream_writes(self):
        class BrokenWriter(io.BytesIO):
            def write(self, data):
                raise BrokenPipeError('SYNTH_CLIENT_CLOSED')

        for broken in (False, True):
            with self.subTest(broken=broken):
                writer = BrokenWriter() if broken else io.BytesIO()
                metrics = {'request_id': REQUEST, 'model': 'gpt-6-luna',
                           'protocol': provider_defs.RESPONSES, 'response_kind': 'sse',
                           'response_encoding': 'identity'}
                record = stream_relay.StreamRecord(transport.ResponseFormat(
                    provider_defs.RESPONSES, '/v1/responses', True, 'sse', 'identity'))
                rows = []
                with mock.patch.object(events.LOG, 'info', side_effect=lambda row: rows.append(json.loads(row))):
                    def relay():
                        stream_relay.relay_stream(
                            SimpleNamespace(wfile=writer), providers.SubscriptionProvider(),
                            Response(frame(call('collaboration_plaintext', None)), 'text/event-stream'),
                            SimpleNamespace(tool_names=agent_handoffs.AliasTools({'spawn_agent'})),
                            metrics, 0.0, 0.0, record, attempt=3)
                    if broken:
                        with self.assertRaises(BrokenPipeError):
                            relay()
                    else:
                        relay()
                observation = next(row for row in rows if row['event'] == 'handoff_observed')
                self.assertEqual((observation['request_id'], observation['attempt']), (REQUEST, 3))
                self.assertEqual(record.forwarded_bytes >= observation['frame_end_offset'], not broken)
                self.assertEqual(record.forwarded_bytes, len(writer.getvalue()))
