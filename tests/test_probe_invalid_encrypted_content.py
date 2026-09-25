"""Offline checks for the bounded encrypted-content live probe."""
import json
import types
import unittest
from compression import zstd
from unittest import mock

from ai_router import provider_defs, providers, strip_retry, transport
from tools import probe_invalid_encrypted_content as probe


def retry_events(body):
    """The five log events one repaired request must produce, in order."""
    return [
        {'event': 'request_started', 'model': 'codex-auto-review',
         'request_bytes': len(body)},
        {'event': 'upstream_rejected', 'model': 'codex-auto-review',
         'request_bytes': len(body), 'status': 400,
         'code': 'invalid_encrypted_content'},
        {'event': 'annotation_retry', 'model': 'codex-auto-review',
         'request_bytes': len(body), 'repair': 'reasoning_blobs',
         'outcome': 'started'},
        {'event': 'annotation_retry', 'model': 'codex-auto-review',
         'request_bytes': len(body), 'repair': 'reasoning_blobs',
         'outcome': 'accepted', 'status': 200},
        {'event': 'request_completed', 'model': 'codex-auto-review',
         'request_bytes': len(body), 'status': 200},
    ]


class ProbeShapeTests(unittest.TestCase):
    def test_payload_is_small_and_bounded(self):
        payload = probe.synthetic_payload()
        self.assertEqual(payload['model'], 'codex-auto-review')
        self.assertEqual(len(payload['tools']), 3)
        self.assertEqual(len(payload['input']), 2)
        self.assertEqual(payload['input'][0]['encrypted_content'],
                         'invalid-probe-blob')
        self.assertLess(len(probe.request_body()), 8192)

    def test_sequence_requires_the_complete_repair_order(self):
        body = probe.request_body()
        self.assertEqual(json.loads(zstd.decompress(body))['metadata'],
                         {'probe_id': 'offline'})
        events = retry_events(body)
        passed, labels, ambiguous = probe.repair_sequence(
            events, 'codex-auto-review', len(body))
        self.assertTrue(passed)
        self.assertFalse(ambiguous)
        self.assertEqual(labels[1], 'upstream_rejected')
        incomplete, labels, ambiguous = probe.repair_sequence(
            events[:-1], 'codex-auto-review', len(body))
        self.assertFalse(incomplete)
        self.assertFalse(ambiguous)
        self.assertEqual(labels, [
            'request_started', 'upstream_rejected',
            'annotation_retry:started', 'annotation_retry:accepted'])
        duplicate = [events[0], *events[1:], dict(events[0])]
        passed, labels, ambiguous = probe.repair_sequence(
            duplicate, 'codex-auto-review', len(body))
        self.assertFalse(passed)
        self.assertTrue(ambiguous)
        self.assertEqual(labels, ['ambiguous_request_started'])

    def test_sequence_polls_for_a_late_completion_event(self):
        body = probe.request_body()
        events = retry_events(body)
        with mock.patch.object(probe, 'read_new_events',
                               side_effect=[events[:-1], events]), \
                mock.patch.object(probe.time, 'sleep') as sleep:
            passed, labels, ambiguous = probe.wait_for_sequence(
                'router.jsonl', 0, 'codex-auto-review', len(body))
        self.assertTrue(passed)
        self.assertFalse(ambiguous)
        self.assertEqual(labels[-1], 'request_completed')
        sleep.assert_called_once_with(0.05)


class RetryEventTests(unittest.TestCase):
    def test_initial_rejection_is_logged_before_the_repair(self):
        raw = json.dumps({'error': {
            'message': 'the request was rejected',
            'code': 'invalid_encrypted_content'}}).encode()
        body = probe.request_body()
        prepared = transport.Prepared(
            'api.openai.com', '/responses', {'Content-Encoding': 'zstd'},
            body, set(), 'openai')
        response = types.SimpleNamespace(status=400)
        provider = providers.SubscriptionProvider()
        metrics = {'protocol': provider_defs.RESPONSES,
                   'model': 'codex-auto-review'}
        events = []

        def post_with_phases(conn, prep, metrics):
            return (types.SimpleNamespace(status=200), True)

        with mock.patch.object(strip_retry.transport, 'post_with_phases',
                               post_with_phases), \
                mock.patch.object(strip_retry.transport, 'read_capped',
                                  return_value=raw):
            result = strip_retry.maybe_retry_unattributable(
                (400, 'refused', 'invalid_encrypted_content'), response, raw,
                {**metrics, 'request_bytes': len(body)}, provider, prepared, [],
                lambda event, **fields: events.append((event, fields)))
        self.assertIsNotNone(result)
        self.assertEqual([event for event, _ in events],
                         ['upstream_rejected', 'annotation_retry',
                          'annotation_retry'])
        self.assertEqual(events[0][1]['code'], 'invalid_encrypted_content')
        self.assertEqual(events[1][1]['repair'], 'reasoning_blobs')
        self.assertEqual(events[1][1]['request_bytes'], len(body))
        self.assertNotIn('Content-Encoding', result[2].headers)
        retry_payload = json.loads(result[2].body)
        self.assertNotIn('encrypted_content', json.dumps(retry_payload))

    def test_compressed_retry_is_bounded_to_exactly_one_dispatch(self):
        raw = json.dumps({'error': {
            'message': 'the request was rejected',
            'code': 'invalid_encrypted_content'}}).encode()
        body = zstd.compress(json.dumps({
            'model': 'codex-auto-review',
            'input': [{'type': 'reasoning', 'encrypted_content': 'BLOB'}],
        }).encode())
        prepared = transport.Prepared(
            'api.openai.com', '/responses', {'Content-Encoding': 'zstd'},
            body, set(), 'openai')
        provider = providers.SubscriptionProvider()
        metrics = {'protocol': provider_defs.RESPONSES,
                   'model': 'codex-auto-review', 'request_bytes': len(body)}
        dispatches = []

        def post_with_phases(conn, prep, metrics):
            dispatches.append(prep)
            return (types.SimpleNamespace(
                status=400 if len(dispatches) == 1 else 200), True)

        with mock.patch.object(strip_retry.transport, 'post_with_phases',
                               post_with_phases), \
                mock.patch.object(strip_retry.transport, 'read_capped',
                                  return_value=raw):
            result = strip_retry.post_with_retry(
                object(), prepared, metrics, [], provider,
                lambda event, **fields: None)
        self.assertEqual(len(dispatches), 2)
        self.assertEqual(result[0].status, 200)
        self.assertNotIn(b'encrypted_content', dispatches[1].body)
        self.assertNotIn('Content-Encoding', dispatches[1].headers)

    def test_unchanged_repair_leaves_the_relay_to_log_one_rejection(self):
        body = b'{"model":"codex-auto-review","input":[]}'
        prepared = transport.Prepared('api.openai.com', '/responses', {},
                                      body, set(), 'openai')
        events = []
        result = strip_retry.maybe_retry_unattributable(
            (400, 'refused', 'invalid_encrypted_content'),
            types.SimpleNamespace(status=400), b'{}',
            {'protocol': provider_defs.RESPONSES,
             'model': 'codex-auto-review'},
            providers.SubscriptionProvider(),
            prepared, [], lambda event, **fields: events.append(event))
        self.assertIsNone(result)
        self.assertEqual(events, ['annotation_retry'])


if __name__ == '__main__':
    unittest.main()
