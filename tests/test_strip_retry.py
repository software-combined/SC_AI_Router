import json
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from ai_router import provider_defs, providers, rejected_repair, transport, upstream

UNNAMED = json.dumps({'error': {'message': 'Provider returned error',
                                'metadata': {'provider_name': 'Meta'}}}).encode()
CONTEXT = json.dumps({'error': {'code': 'context_length_exceeded',
                                'message': 'context length exceeded'}}).encode()
ENCRYPTED = json.dumps({'error': {'message': 'the request was rejected',
                                  'code': 'invalid_encrypted_content'}}).encode()


class StripAnnotationsTests(unittest.TestCase):
    def test_removes_annotation_only_fields_and_keeps_the_rest(self):
        body = json.dumps({'model': 'm', 'input': [], 'tools': [],
                           'client_metadata': {'a': 1},
                           'prompt_cache_options': {'mode': 'auto'},
                           'store': True, 'user': 'u',
                           'stream': True, 'max_output_tokens': 32000}).encode()
        stripped = json.loads(rejected_repair.strip_annotations(body))
        self.assertEqual(stripped, {'model': 'm', 'input': [], 'tools': [],
                                    'stream': True, 'max_output_tokens': 32000})

    def test_nothing_to_strip_returns_none(self):
        body = json.dumps({'model': 'm', 'input': []}).encode()
        self.assertIsNone(rejected_repair.strip_annotations(body))

    def test_unparseable_body_returns_none(self):
        self.assertIsNone(rejected_repair.strip_annotations(b'not json'))
        self.assertIsNone(rejected_repair.strip_annotations('a string'))

    def test_each_adapter_proposes_only_its_own_repair_and_keeps_the_request(self):
        external = providers.ExternalResponsesProvider(provider_defs.OPENROUTER)
        native = providers.SubscriptionProvider()
        unnamed = (400, 'refused', None)
        encrypted = (400, 'refused', 'invalid_encrypted_content')
        fallback, context = object(), object()
        body = json.dumps({'model': 'm', 'store': True, 'input': [
            {'type': 'reasoning', 'id': 'rs_1', 'encrypted_content': 'BLOB'}]}).encode()
        for adapter, described, raw, repair in ((external, unnamed, UNNAMED, 'annotation_strip'),
                                                (native, encrypted, ENCRYPTED, 'reasoning_blobs')):
            with self.subTest(repair=repair):
                original = transport.Prepared(
                    'upstream.example', '/responses',
                    {'Authorization': 'Bearer k', 'Connection': 'close'}, body,
                    {'tool': 'kind'}, adapter.name, fallback, 321, 654, context)
                proposal = adapter.repair_rejected(original, described, raw)
                self.assertEqual(proposal.repair, repair)
                sent = proposal.prepared
                self.assertNotEqual(sent.body, body)
                self.assertEqual(sent.decoded_body_bytes, len(sent.body))
                self.assertEqual(sent.headers, {'Authorization': 'Bearer k'})
                self.assertEqual([getattr(sent, key) for key in transport.Prepared.__slots__
                                  if key not in ('headers', 'body', 'decoded_body_bytes')],
                                 ['upstream.example', '/responses', {'tool': 'kind'},
                                  adapter.name, fallback, 321, 654, context])
                self.assertEqual((original.body, original.headers),
                                 (body, {'Authorization': 'Bearer k', 'Connection': 'close'}))
                # A context error, or the other adapter's rejection, is not repaired.
                self.assertIsNone(adapter.repair_rejected(original, described, CONTEXT))
                other = encrypted if adapter is external else unnamed
                self.assertIsNone(adapter.repair_rejected(original, other, UNNAMED))

    def test_attributed_category_keeps_refusal_wording(self):
        body = json.dumps({'error': {'message':
                                    '[invalid_client_tool_schema] t: root must be an object',
                                 'metadata': {'provider_name': 'xAI'}}}).encode()
        _, message, _ = upstream.describe_failure(
            None, {'status': 400, 'body': body},
            {'model': 'meta/muse-spark-1.3-contributor', 'provider': 'openrouter',
             'protocol': 'responses', 'elapsed_ms': 1500.0, 'timeout_s': 120,
             'has_image': False})
        self.assertIn('tool schema was rejected', message)
        self.assertIn('Do not retry it unchanged', message)


class StripRetryRelayTests(unittest.TestCase):
    def setUp(self):
        upstream.clear_refusals()
        self.addCleanup(upstream.clear_refusals)

    def _relay(self, resps, body, key_rejected=False):
        """Drive relay.relay with FakeConn returning each (status, body) in turn."""
        from ai_router import relay
        from ai_router.transport import Prepared

        dispatches = []
        queue = list(resps)
        index = [0]

        class FakeResp:
            def __init__(self):
                self.status, self._body = queue[index[0]]
                index[0] += 1

            def read(self, *a):
                if isinstance(self._body, Exception):
                    raise self._body
                return self._body

            def getheader(self, *a, **k):
                return ''

            def getheaders(self):
                return []

        class FakeConn:
            def __init__(self, *a, **k):
                pass

            def connect(self):
                pass

            def request(self, *a, **k):
                dispatches.append(1)

            def getresponse(self):
                return FakeResp()

            def close(self):
                pass

        class FakeWriter:
            def __init__(self):
                self.parts = []

            def write(self, buf):
                self.parts.append(buf)

            def flush(self):
                pass

        wfile = FakeWriter()
        errors = []
        handler = SimpleNamespace(
            server=SimpleNamespace(lock=threading.RLock(), served_models={},
                                   credentials=SimpleNamespace(
                                       home='synthetic',
                                       key_rejected=lambda provider: key_rejected)),
            error=lambda err, **k: errors.append(err),
            context_error=lambda stream: errors.append(SimpleNamespace(status='context')),
            send_response=lambda status: None,
            send_header=lambda k, v: None,
            end_headers=lambda: None,
            wfile=wfile)
        provider = SimpleNamespace(
            defn=provider_defs.OPENROUTER,
            repair_rejected=providers.ExternalResponsesProvider(
                provider_defs.OPENROUTER).repair_rejected,
            adapt=lambda response, tool_names, notes=None: iter(
                [b'event: done\ndata: {"ok":true}\n\n']))
        prepared = Prepared('openrouter.ai', '/responses', {}, body, {}, 'openrouter')
        metrics = {'provider': 'openrouter', 'protocol': 'responses',
                   'model': 'meta/muse-spark-1.3-contributor', 'path': '/responses',
                   'stream': True}
        events = []
        with mock.patch.object(relay.http.client, 'HTTPSConnection', FakeConn), \
                mock.patch.object(relay.setup, 'open_key_window'):
            relay.relay(handler, provider, prepared, metrics, 0.0,
                        log_event=lambda event, **f: events.append((event, f)))
        return dispatches, events, wfile, errors

    def test_unattributable_400_is_retried_and_the_stream_reaches_the_client(self):
        refused = json.dumps({'error': {'message': 'Provider returned error',
                                        'metadata': {'provider_name': 'Meta'}}}).encode()
        body = json.dumps({'model': 'meta/muse-spark-1.3-contributor', 'input': [],
                           'tools': [], 'client_metadata': {'x': 1}}).encode()
        dispatches, events, wfile, _ = self._relay([(400, refused), (200, b'')], body)
        self.assertEqual(len(dispatches), 2)
        self.assertIn(b'event: done', b''.join(wfile.parts))
        self.assertEqual([f['status'] for e, f in events if e == 'request_completed'], [200])
        self.assertEqual([e for e, _ in events if e == 'upstream_rejected'], [])
        self.assertEqual([f['outcome'] for e, f in events if e == 'annotation_retry'],
                         ['started', 'accepted'])

    def test_retried_400_is_reported_and_cached_against_the_original_request(self):
        refused = json.dumps({'error': {'message': 'Provider returned error',
                                        'metadata': {'provider_name': 'Meta'}}}).encode()
        body = json.dumps({'model': 'meta/muse-spark-1.3-contributor', 'input': [],
                           'tools': [], 'client_metadata': {'x': 1}}).encode()
        dispatches, events, _, errors = self._relay([(400, refused), (400, refused)], body)
        dispatches2, events2, _, errors2 = self._relay([], body)
        self.assertEqual(len(dispatches) + len(dispatches2), 2)
        self.assertEqual([err.status for err in errors], [400])
        self.assertEqual([err.status for err in errors2], [400])
        self.assertEqual([e for e, _ in events if e == 'upstream_rejected'],
                         ['upstream_rejected'])
        self.assertEqual([e for e, _ in events2 if e == 'upstream_rejected_cached'],
                         ['upstream_rejected_cached'])
        self.assertEqual([f['status'] for e, f in events
                          if e == 'annotation_retry' and f['outcome'] == 'rejected'], [400])

    def test_attributed_400_is_not_retried(self):
        raw = json.dumps({'error': {'message': '[invalid_client_tool_schema] t: root must be an object',
                                    'metadata': {'provider_name': 'xAI'}}}).encode()
        body = json.dumps({'model': 'm', 'input': [1], 'client_metadata': {'x': 1}}).encode()
        dispatches, events, _, _ = self._relay([(400, raw)], body)
        self.assertEqual(len(dispatches), 1)
        self.assertEqual([f['outcome'] for e, f in events if e == 'annotation_retry'],
                         ['ineligible'])

    def test_final_retry_failure_uses_the_same_policy_as_a_direct_failure(self):
        unknown = json.dumps({'error': {'message': 'Provider returned error',
                              'metadata': {'provider_name': 'Meta'}}}).encode()
        cases = [(401, {'message': 'Invalid API key'}),
                 (403, {'message': 'Forbidden'}),
                 (402, {'message': 'Insufficient credits'}),
                 (429, {'code': 'insufficient_quota'}),
                 (400, {'code': 'context_length_exceeded', 'message': 'context length exceeded'}),
                 (400, {'message': 'The prompt is too long: 100, model maximum context length: 50',
                        'metadata': {'provider_name': 'Meta'}}),
                 (400, {'message': '[invalid_client_tool_schema] t: root must be an object',
                        'metadata': {'provider_name': 'Meta'}})]
        body = json.dumps({'model': 'meta/muse-spark-1.3-contributor', 'input': [],
                           'client_metadata': {'private': 'never-log-this'}}).encode()
        for status, error in cases:
            with self.subTest(status=status, error=error):
                raw = json.dumps({'error': error}).encode()
                upstream.clear_refusals()
                direct, _, _, direct_errors = self._relay([(status, raw)], body, True)
                upstream.clear_refusals()
                retried, events, _, retry_errors = self._relay(
                    [(400, unknown), (status, raw)], body, True)
                self.assertEqual(len(direct), 1)
                self.assertEqual(len(retried), 2)
                self.assertTrue(direct_errors)
                self.assertEqual([vars(e) for e in retry_errors], [vars(e) for e in direct_errors])
                self.assertNotIn('never-log-this', json.dumps(events))
                self.assertEqual([f['status'] for e, f in events
                                  if e == 'annotation_retry' and f['outcome'] == 'rejected'], [status])

    def test_eligible_error_without_annotations_does_not_dispatch_again(self):
        raw = json.dumps({'error': {'message': 'Provider returned error',
                          'metadata': {'provider_name': 'Meta'}}}).encode()
        dispatches, events, _, _ = self._relay([(400, raw)], b'{"model":"m","input":[]}')
        self.assertEqual(len(dispatches), 1)
        self.assertEqual([f['outcome'] for e, f in events if e == 'annotation_retry'],
                         ['unchanged'])

    def test_failed_retry_body_read_records_transport_outcome_without_content(self):
        raw = json.dumps({'error': {'message': 'Provider returned error',
                          'metadata': {'provider_name': 'Meta'}}}).encode()
        body = b'{"model":"m","input":[],"store":false}'
        dispatches, events, _, errors = self._relay(
            [(400, raw), (400, OSError('private upstream detail'))], body)
        self.assertEqual(len(dispatches), 2)
        self.assertTrue(errors)
        self.assertEqual([f['outcome'] for e, f in events if e == 'annotation_retry'],
                         ['started', 'transport_error'])
        self.assertNotIn('private upstream detail', json.dumps(events))
