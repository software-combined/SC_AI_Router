import json
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from ai_router import provider_defs, strip_retry, upstream


class StripAnnotationsTests(unittest.TestCase):
    def test_removes_annotation_only_fields_and_keeps_the_rest(self):
        body = json.dumps({'model': 'm', 'input': [], 'tools': [],
                           'client_metadata': {'a': 1},
                           'prompt_cache_options': {'mode': 'auto'},
                           'store': True, 'user': 'u',
                           'stream': True, 'max_output_tokens': 32000}).encode()
        stripped = json.loads(strip_retry.strip_annotations(body))
        self.assertEqual(stripped, {'model': 'm', 'input': [], 'tools': [],
                                    'stream': True, 'max_output_tokens': 32000})

    def test_nothing_to_strip_returns_none(self):
        body = json.dumps({'model': 'm', 'input': []}).encode()
        self.assertIsNone(strip_retry.strip_annotations(body))

    def test_unparseable_body_returns_none(self):
        self.assertIsNone(strip_retry.strip_annotations(b'not json'))
        self.assertIsNone(strip_retry.strip_annotations('a string'))

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

    def _relay(self, resps, body):
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
                                       key_rejected=lambda provider: False)),
            error=lambda err, **k: errors.append(err),
            send_response=lambda status: None,
            send_header=lambda k, v: None,
            end_headers=lambda: None,
            wfile=wfile)
        provider = SimpleNamespace(
            defn=provider_defs.OPENROUTER,
            adapt=lambda response, tool_names, notes=None: iter(
                [b'event: done\ndata: {"ok":true}\n\n']))
        prepared = Prepared('openrouter.ai', '/responses', {}, body, {}, 'openrouter')
        metrics = {'provider': 'openrouter', 'protocol': 'responses',
                   'model': 'meta/muse-spark-1.3-contributor', 'path': '/responses'}
        events = []
        with mock.patch.object(relay.http.client, 'HTTPSConnection', FakeConn):
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

    def test_retried_400_falls_back_to_the_original_failure_and_caches_once(self):
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

    def test_attributed_400_is_not_retried(self):
        raw = json.dumps({'error': {'message': '[invalid_client_tool_schema] t: root must be an object',
                                    'metadata': {'provider_name': 'xAI'}}}).encode()
        body = json.dumps({'model': 'm', 'input': [1], 'client_metadata': {'x': 1}}).encode()
        dispatches, _, _, _ = self._relay([(400, raw)], body)
        self.assertEqual(len(dispatches), 1)
