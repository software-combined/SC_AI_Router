"""A refused or marked handoff explains its wire facts without exposing content."""
from contextlib import nullcontext
import io
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from ai_router import (agent_handoffs, errors, events, handoff_response, provider_defs,
                       providers, sse, stream_relay, transport)
from tests.test_agent_handoff_providers import Response
from tests.test_agent_handoffs import CIPHERTEXT

REQUEST = '0123456789abcdef0123456789abcdef'


def call(namespace='collaboration', marker=('message',), message='SYNTH_SECRET_CONTENT'):
    item = {'type': 'function_call', 'namespace': namespace, 'name': 'spawn_agent',
            'id': 'SYNTH_SECRET_ITEM', 'call_id': 'SYNTH_SECRET_CALL',
            'arguments': json.dumps({'model': 'xiaomi/mimo-v2.6-pro',
                                    'task_name': 'SYNTH_SECRET_TASK', 'message': message})}
    if marker is not None:
        item['encrypted_function_args'] = list(marker)
    return item


def frame(item, phase='done'):
    return sse.frame(json.dumps({'type': 'response.output_item.' + phase,
                                'output_index': 0, 'item': item}).encode())


def readable(**facts):
    return agent_handoffs.ReadableHandoffs({'spawn_agent'}, **facts)


def unreadable(**facts):
    return agent_handoffs.ReadableHandoffs({'send_message'}, **facts)


class HandoffObservationTests(unittest.TestCase):
    def adapt(self, wire, names=None, notes=None, content_type='text/event-stream', rejected=False):
        rows, chunks = [], []
        names = names or readable(stream=True)
        with mock.patch.object(events.LOG, 'info', side_effect=lambda row: rows.append(json.loads(row))):
            with self.assertRaises(errors.ResponseRejected) if rejected else nullcontext():
                chunks.extend(providers.SubscriptionProvider().adapt(
                    Response(wire, content_type), names, notes))
        return b''.join(chunks), rows

    def test_encrypted_readable_call_records_the_marker_refusal(self):
        notes = {'request_id': REQUEST, 'attempt': 2}
        wire, rows = self.adapt(frame(call()), readable(stream=True), notes, rejected=True)
        (row,) = [row for row in rows if row.get('event') == 'handoff_observed']
        self.assertEqual((row['request_id'], row['attempt']), (REQUEST, 2))
        self.assertEqual(row['upstream'], {'namespace': 'native', 'marker': 'nonempty', 'arguments': 'object'})
        self.assertEqual((row['schema_mode'], row['marker_rejected'], row['guard_rejected']),
                         ('readable', True, False))
        self.assertIsNone(row['client'])
        self.assertIsNone(row['frame_end_offset'])
        self.assertNotIn('SYNTH_SECRET', json.dumps(rows))
        self.assertEqual(wire, b'')

    def test_unreadable_external_call_records_the_guard_refusal(self):
        wire, rows = self.adapt(frame(call(marker=None)), unreadable(stream=True), rejected=True)
        (row,) = [row for row in rows if row.get('event') == 'handoff_observed']
        self.assertEqual((row['schema_mode'], row['marker_rejected'], row['guard_rejected']),
                         ('native', False, True))
        self.assertEqual((row['upstream']['marker'], row['message_shape']), ('absent', 'readable'))
        self.assertNotIn('SYNTH_SECRET', json.dumps(rows))
        self.assertEqual(wire, b'')

    def test_ciphertext_under_an_alias_records_the_marker_refusal(self):
        wire, rows = self.adapt(frame(call('collaboration_plaintext', None, CIPHERTEXT)), rejected=True)
        (row,) = [row for row in rows if row.get('event') == 'handoff_observed']
        self.assertEqual((row['upstream']['namespace'], row['message_shape'], row['marker_rejected']),
                         ('plaintext', 'ciphertext', True))
        self.assertNotIn(CIPHERTEXT, json.dumps(rows))
        self.assertEqual(wire, b'')

    def test_ciphertext_for_a_readable_tool_records_its_shape_and_the_guard(self):
        wire, rows = self.adapt(frame(call(marker=None, message=CIPHERTEXT)), rejected=True)
        (row,) = [row for row in rows if row.get('event') == 'handoff_observed']
        self.assertEqual((row['schema_mode'], row['message_shape'], row['guard_rejected']),
                         ('readable', 'ciphertext', True))
        self.assertNotIn(CIPHERTEXT, json.dumps(rows))
        self.assertEqual(wire, b'')

    def test_changed_envelope_does_not_inherit_the_earlier_marking(self):
        added = call(marker=None)
        added['arguments'] = ''
        wire, rows = self.adapt(frame(added, 'added') + frame(call()), rejected=True)
        seen = [row for row in rows if row['event'] == 'handoff_observed']
        self.assertEqual([row['call_ordinal'] for row in seen], [1, 1])
        self.assertEqual([row['marker_rejected'] for row in seen], [False, True])
        self.assertEqual([row['envelope_changed'] for row in seen], [False, True])
        self.assertTrue(all(row['identity_consistent'] for row in seen))
        self.assertIsNone(seen[-1]['frame_end_offset'])
        self.assertNotIn(b'output_item.done', wire)
        self.assertEqual(rows[-1]['missing_envelopes'], ['completed'])
        self.assertNotIn('SYNTH_SECRET', json.dumps(rows))

    def test_readable_alias_records_restoration_and_keeps_its_object_arguments(self):
        original = call('collaboration_plaintext', None)
        completed = sse.frame(json.dumps({'type': 'response.completed',
                             'response': {'output': [original]}}).encode())
        wire, rows = self.adapt(frame(original, 'added') + frame(original) + completed)
        seen = [row for row in rows if row['event'] == 'handoff_observed']
        self.assertEqual(len(seen), 3)
        for row in seen:
            self.assertEqual(row['upstream'], {'namespace': 'plaintext', 'marker': 'absent', 'arguments': 'object'})
            self.assertEqual(row['client'], {'namespace': 'native', 'marker': 'empty', 'arguments': 'object'})
            self.assertEqual(row['schema_mode'], 'readable')
            self.assertEqual(row['message_shape'], 'readable')
            self.assertFalse(row['guard_rejected'] or row['marker_rejected'])
        self.assertEqual(rows[-1]['missing_envelopes'], [])
        self.assertNotIn('SYNTH_SECRET', json.dumps(rows))
        for _, data in sse.blocks(sse.lines([wire])):
            event = json.loads(data)
            output = event.get('item', event.get('response', {}).get('output', [None])[0])
            self.assertIsInstance(json.loads(output['arguments']), dict)
            self.assertEqual((output['namespace'], output['encrypted_function_args']), ('collaboration', []))

    def test_observation_limit_never_changes_wire_or_fails_stream(self):
        originals = [{**call(marker=None), 'id': str(index), 'call_id': 'c' + str(index)}
                     for index in range(handoff_response.MAX_CALLS + 5)]
        expected = b''.join(frame({**item, 'encrypted_function_args': []}) for item in originals)
        notes = {}
        wire, rows = self.adapt(b''.join(frame(item) for item in originals), readable(stream=True), notes)
        self.assertEqual(wire, expected)
        self.assertEqual(len([row for row in rows if row['event'] == 'handoff_observed']),
                         handoff_response.MAX_CALLS)
        self.assertEqual(len([row for row in rows if row['event'] == 'handoff_observation_limited']), 1)
        self.assertTrue(notes['handoff_observation_incomplete'])
        self.assertLessEqual(len(rows), handoff_response.MAX_OBSERVATIONS + handoff_response.MAX_CALLS + 1)

    def test_repeated_envelope_limit_is_bounded(self):
        wire = frame(call(marker=None)) * (handoff_response.MAX_OBSERVATIONS + 4)
        result, rows = self.adapt(wire)
        self.assertEqual(len([row for row in rows if row['event'] == 'handoff_observed']),
                         handoff_response.MAX_OBSERVATIONS)
        self.assertEqual(result.count(b'output_item.done'), handoff_response.MAX_OBSERVATIONS + 4)
        self.assertTrue(rows[-1]['incomplete'])

    def test_native_encrypted_control_and_unrelated_bytes_are_unchanged(self):
        native = call()
        native['arguments'] = json.dumps({'model': 'gpt-6-luna', 'message': 'SYNTH_CIPHERTEXT'})
        raw = frame(native) + b': signed SSE comment\r\n\r\ndata: [DONE]\r\n\r\n'
        wire, rows = self.adapt(raw, unreadable(stream=True))
        self.assertEqual(wire, raw)
        observed = next(row for row in rows if row['event'] == 'handoff_observed')
        self.assertFalse(observed['guard_rejected'])
        self.assertEqual((observed['schema_mode'], observed['client']['marker']), ('native', 'nonempty'))
        self.assertNotIn('SYNTH_CIPHERTEXT', json.dumps(rows))

    def test_json_response_and_lite_declaration_are_identified(self):
        raw = json.dumps({'output': [call(marker=None)], 'model': 'gpt-6-luna'}).encode()
        notes = {}
        wire, rows = self.adapt(raw, readable(location='lite'), notes, 'application/json')
        self.assertEqual(rows[0]['phase'], 'json')
        self.assertEqual(rows[0]['declaration'], 'lite')
        self.assertEqual(rows[0]['schema_mode'], 'readable')
        self.assertEqual(rows[0]['frame_end_offset'], len(wire))
        self.assertEqual(rows[-1]['missing_envelopes'], [])
        self.assertEqual(notes['served_model'], 'gpt-6-luna')

    def test_observer_failure_cannot_disable_rejection(self):
        for names, item in ((readable(), call()), (unreadable(), call(marker=None))):
            with self.subTest(names=sorted(names)), mock.patch.object(
                    events.LOG, 'info', side_effect=ValueError('SYNTH_SECRET_LOG')):
                with self.assertRaises(errors.ResponseRejected):
                    list(providers.SubscriptionProvider().adapt(
                        Response(frame(item), 'text/event-stream'), names))

    def test_early_close_records_missing_final_envelopes_without_delivery_claim(self):
        rows = []
        with mock.patch.object(events.LOG, 'info', side_effect=lambda row: rows.append(json.loads(row))):
            iterator = providers.SubscriptionProvider().adapt(Response(
                frame({**call(marker=None), 'arguments': ''}, 'added') + frame(call(marker=None)),
                'text/event-stream'), readable(stream=True))
            next(iterator)
            iterator.close()
        self.assertEqual(rows[-1]['missing_envelopes'], ['completed', 'done'])
        self.assertEqual(rows[0]['message_shape'], 'absent')
        self.assertNotIn('delivered', json.dumps(rows))

    def test_simultaneous_responses_do_not_share_identity_or_marker_state(self):
        first = providers.SubscriptionProvider().adapt(
            Response(frame(call()), 'text/event-stream'), readable(),
            {'request_id': REQUEST, 'attempt': 1})
        second_id = 'f' * 32
        second = providers.SubscriptionProvider().adapt(
            Response(frame(call(marker=None)), 'text/event-stream'),
            readable(), {'request_id': second_id, 'attempt': 3})
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
        self.assertEqual([row['marker_rejected'] for row in observed], [True, False])

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
                            Response(frame(call(marker=None)), 'text/event-stream'),
                            SimpleNamespace(tool_names=readable()),
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
