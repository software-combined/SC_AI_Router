"""Focused tests for the subscription `invalid_encrypted_content` repair.

Defect guarded: a subscription (OpenAI-dialect) turn whose replayed
`input[]` reasoning item carries `encrypted_content` is rejected by the
ChatGPT backend with HTTP 400 `invalid_encrypted_content`, and the router
forwarded that refusal instead of repairing the one named condition.

Run from the copy root:
  <python> -m unittest discover -s tests -t . -v
"""
import json
import unittest
from unittest import mock
from compression import zstd

from ai_router import (compaction, provider_defs, providers, strip_retry,
                       subscription_history, transport)
from ai_router.registry import by_slug
from tests.harness import stub_credentials


OPENROUTER = providers.ExternalResponsesProvider(provider_defs.get(provider_defs.DEFAULT_EXTERNAL))
SUBSCRIPTION = providers.SubscriptionProvider()


def body(items):
    return json.dumps({'model': 'codex-auto-review', 'stream': True,
                       'input': items}, separators=(',', ':')).encode()


MESSAGE = {'type': 'message', 'role': 'user',
           'content': [{'type': 'input_text', 'text': 'judge this action'}]}
BLOB_ONLY = {'type': 'reasoning', 'id': 'rs_1', 'encrypted_content': 'BLOB-ONE'}
BLOB_WITH_TEXT = {'type': 'reasoning', 'id': 'rs_2', 'encrypted_content': 'BLOB-TWO',
                  'summary': [{'type': 'summary_text', 'text': 'readable trace'}]}
GUARDIAN_BODY = body([MESSAGE, BLOB_ONLY, BLOB_WITH_TEXT])

SUMMARY = 'the summary the router wrote for this thread'
# The replayed V2 compaction item: the router's own `ocx1:` summary, replayed
# by the client on a turn that holds no `reasoning` item at all.
COMPACTION = {'type': 'compaction', 'id': 'cmp_1',
              'encrypted_content': compaction.encode_summary(SUMMARY)}

ERROR_RAW = json.dumps({'error': {'message': 'the request was rejected',
                                  'code': 'invalid_encrypted_content'}}).encode()
ENCRYPTED_DESCRIBED = (400, 'codex-auto-review refused this request: the request '
                            'was rejected. Do not retry it unchanged',
                       'invalid_encrypted_content')


class Response:
    def __init__(self, status):
        self.status = status


def prepared(body_bytes):
    return transport.Prepared('api.openai.com', '/responses', {}, body_bytes,
                              set(), 'openai')


class Recorder:
    def __init__(self):
        self.events = []

    def __call__(self, event, **fields):
        self.events.append((event, fields))

    def outcomes(self):
        return [f.get('outcome') for e, f in self.events if e == 'annotation_retry']


class RetryRepairTests(unittest.TestCase):
    def setUp(self):
        self.metrics = {'protocol': provider_defs.RESPONSES, 'model': 'codex-auto-review'}
        self.log = Recorder()

    def drive(self, status, described, provider=SUBSCRIPTION, raw=ERROR_RAW,
              body_bytes=GUARDIAN_BODY):
        return strip_retry.maybe_retry_unattributable(
            described, Response(status), raw, self.metrics, provider,
            prepared(body_bytes), [], self.log)

    def test_01_healthy_request_is_untouched_and_never_stripped(self):
        called = []
        # The policy gate never asks the adapter for a repair on a healthy turn.
        with mock.patch.object(SUBSCRIPTION, 'repair_rejected',
                               lambda *a: called.append(a)):
            self.assertIsNone(self.drive(200, None))
        self.assertEqual(called, [], 'healthy turn must not reach any strip')
        self.assertEqual(self.log.outcomes(), ['ineligible'])

    def test_02_non_400_never_triggers_the_repair(self):
        called = []
        with mock.patch.object(SUBSCRIPTION, 'repair_rejected',
                               lambda *a: called.append(a)):
            for status in (500, 429, 503):
                self.assertIsNone(self.drive(status, ENCRYPTED_DESCRIBED))
        self.assertEqual(called, [], 'only a 400 may trigger the repair')

    def test_03_the_gate_safely_distinguishes_other_rejections(self):
        with mock.patch.object(
                transport, 'post_with_phases',
                lambda conn, prep, metrics: (Response(200), True)):
            # Named but unrelated provider code on the subscription route.
            self.assertIsNone(self.drive(
                400, (400, 'x refused this request: the request was rejected. ',
                      'unsupported_parameter')))
            # The same code arriving on the external route is not this condition.
            self.assertIsNone(self.drive(400, ENCRYPTED_DESCRIBED, provider=OPENROUTER))
            # Positive control: the named condition on the subscription route is
            # eligible and is repaired by stripping the blobs.
            self.assertIsNotNone(self.drive(400, ENCRYPTED_DESCRIBED))
        self.assertEqual(self.log.outcomes(),
                         ['ineligible', 'ineligible', 'started', 'accepted'])
        repairs = [f.get('repair') for e, f in self.log.events if e == 'annotation_retry']
        self.assertEqual(repairs, ['annotation_strip', 'annotation_strip',
                                   'reasoning_blobs', 'reasoning_blobs'])

    def test_04_blob_is_kept_before_failure_and_stripped_only_for_the_retry(self):
        # Pre-failure body: the deliberate preservation still holds.
        normalized = subscription_history.normalize(json.loads(GUARDIAN_BODY))
        kept = [i for i in normalized['input'] if i.get('type') == 'reasoning']
        self.assertEqual([i['encrypted_content'] for i in kept], ['BLOB-ONE', 'BLOB-TWO'])
        # The retry-only proposal removes the field, drops the blob-only item,
        # and keeps the item that still carries readable reasoning text. It is
        # pure: proposing alone opens no connection and sends nothing.
        forbidden = mock.Mock(side_effect=AssertionError('a proposal never sends'))
        with mock.patch.object(transport.http.client, 'HTTPSConnection', forbidden), \
                mock.patch.object(transport, 'post_with_phases', forbidden):
            proposal = SUBSCRIPTION.repair_rejected(
                prepared(GUARDIAN_BODY), ENCRYPTED_DESCRIBED, ERROR_RAW)
            unchanged = SUBSCRIPTION.repair_rejected(
                prepared(body([MESSAGE])), ENCRYPTED_DESCRIBED, ERROR_RAW)
        forbidden.assert_not_called()
        self.assertEqual(proposal.repair, 'reasoning_blobs')
        out = json.loads(proposal.prepared.body)
        self.assertEqual([(i.get('type'), i.get('id')) for i in out['input']],
                         [('message', None), ('reasoning', 'rs_2')])
        self.assertEqual(out['input'][1]['summary'][0]['text'], 'readable trace')
        self.assertNotIn('encrypted_content', json.dumps(out))
        # Nothing to repair means eligible but no rewrite at all.
        self.assertEqual(unchanged.repair, 'reasoning_blobs')
        self.assertIsNone(unchanged.prepared)

    def test_05_exactly_one_retry_and_no_loop(self):
        dispatches = []

        def post_with_phases(conn, prep, metrics):
            dispatches.append(prep.body)
            return Response(400 if len(dispatches) == 1 else 200), True

        with mock.patch.object(transport, 'post_with_phases', post_with_phases), \
                mock.patch.object(transport, 'read_capped',
                                  lambda r, n: ERROR_RAW):
            result = strip_retry.post_with_retry(object(), prepared(GUARDIAN_BODY),
                                                 self.metrics, [], SUBSCRIPTION, self.log)
            self.assertEqual(len(dispatches), 2, 'initial dispatch plus exactly one retry')
            self.assertNotIn(b'encrypted_content', result[2].body)
            self.assertEqual(result[0].status, 200)
            # An unrepairable rejection is not retried at all.
            dispatches.clear()
            strip_retry.post_with_retry(object(), prepared(GUARDIAN_BODY), self.metrics,
                                        [], OPENROUTER, self.log)
            self.assertEqual(len(dispatches), 1)

    def test_06_guardian_approval_semantics_are_unchanged(self):
        def prepare(provider, model, payload):
            out = provider.prepare(model, '/responses', payload, GUARDIAN_BODY, {},
                                   stub_credentials())
            return json.loads(out.body)['input']

        # The healthy subscription path must not strip blobs, neither on the
        # wire nor in the client's own payload.
        client = json.loads(GUARDIAN_BODY)
        native = prepare(providers.SubscriptionProvider(), 'codex-auto-review', client)
        for items in (native, client['input']):
            self.assertEqual([i.get('encrypted_content') for i in items
                              if i.get('type') == 'reasoning'], ['BLOB-ONE', 'BLOB-TWO'])
        # An external native-history row strips the owned blobs, drops the
        # blob-only item and keeps the readable trace.
        self.assertEqual(by_slug('z-ai/glm-5.3').history_mode, 'native')
        external = prepare(providers.ExternalResponsesProvider(provider_defs.OPENROUTER),
                           'z-ai/glm-5.3', json.loads(GUARDIAN_BODY))
        reasoning = [i for i in external if i.get('type') == 'reasoning']
        self.assertEqual([i.get('id') for i in reasoning], ['rs_2'])
        self.assertEqual(reasoning[0]['summary'][0]['text'], 'readable trace')
        self.assertNotIn('encrypted_content', json.dumps(external))


class DiagnosticFactsTests(unittest.TestCase):
    """One `annotation_retry` line must explain an `outcome=unchanged`."""

    def setUp(self):
        self.metrics = {'protocol': provider_defs.RESPONSES, 'model': 'codex-auto-review'}
        self.log = Recorder()
        self._real_post = transport.post_with_phases
        transport.post_with_phases = lambda conn, prep, metrics: (Response(200), True)

    def tearDown(self):
        transport.post_with_phases = self._real_post

    def drive(self, body_bytes, content_encoding=None):
        headers = {} if content_encoding is None else {'Content-Encoding': content_encoding}
        request = transport.Prepared('api.openai.com', '/responses', headers,
                                     body_bytes, set(), 'openai')
        strip_retry.maybe_retry_unattributable(
            ENCRYPTED_DESCRIBED, Response(400), ERROR_RAW, self.metrics, SUBSCRIPTION,
            request, [], self.log)
        # The first event is the repair decision; a successful repair adds a
        # second one for the retry's own outcome.
        return [f for e, f in self.log.events if e == 'annotation_retry'][0]

    def test_each_sub_case_is_distinguishable_from_one_log_line(self):
        cases = [
            ('compressed and repairable', zstd.compress(GUARDIAN_BODY), 'zstd',
             {'encoding': 'zstd', 'decoded': True, 'parsed': True, 'input_is_list': True,
              'items': 3, 'reasoning_items': 2, 'encrypted_fields': 2, 'removed': 2},
             'started'),
            ('undecodable compressed body', b'not-zstd-at-all', 'zstd',
             {'encoding': 'zstd', 'decoded': False, 'parsed': False, 'items': 0,
              'encrypted_fields': 0, 'removed': 0}, 'unchanged'),
            ('unsupported encoding', GUARDIAN_BODY, 'gzip',
             {'encoding': 'gzip', 'decoded': False, 'parsed': False, 'items': 0,
              'removed': 0}, 'unchanged'),
            ('unparseable body', b'{not json', None,
             {'encoding': '', 'decoded': True, 'parsed': False, 'items': 0,
              'removed': 0}, 'unchanged'),
            ('input absent', b'{"model": "codex-auto-review"}', None,
             {'parsed': True, 'input_is_list': False, 'items': 0, 'reasoning_items': 0,
              'encrypted_fields': 0, 'removed': 0}, 'unchanged'),
            ('input not a list', b'{"input": "nope"}', None,
             {'parsed': True, 'input_is_list': False, 'items': 0, 'removed': 0},
             'unchanged'),
            ('no reasoning items', body([MESSAGE]), None,
             {'input_is_list': True, 'items': 1, 'reasoning_items': 0,
              'encrypted_fields': 0, 'removed': 0}, 'unchanged'),
            ('reasoning without a blob',
             body([MESSAGE, {'type': 'reasoning', 'id': 'rs_3',
                             'summary': [{'type': 'summary_text', 'text': 'trace'}]}]),
             None,
             {'items': 2, 'reasoning_items': 1, 'encrypted_fields': 0, 'removed': 0},
             'unchanged'),
            ('blob only outside reasoning',
             body([{'type': 'message', 'role': 'user',
                    'content': [{'type': 'encrypted_content',
                                 'encrypted_content': 'BLOB-THREE'}]}]), None,
             {'items': 1, 'reasoning_items': 0, 'encrypted_fields': 1, 'removed': 0},
             'unchanged'),
            ('replayed compaction summary blob', body([COMPACTION]), None,
             {'items': 1, 'reasoning_items': 0, 'encrypted_fields': 1, 'removed': 1},
             'started'),
            # A nested block is not a shape this repair owns, so the payload
            # fails closed: nothing is removed and the turn is not retried.
            ('nested block blob on a reasoning item',
             body([{'type': 'reasoning', 'id': 'rs_4',
                    'encrypted_content': 'BLOB-FOUR',
                    'content': [{'type': 'encrypted_content',
                                 'encrypted_content': 'BLOB-FIVE'}]}]), None,
             {'items': 1, 'reasoning_items': 1, 'encrypted_fields': 2, 'removed': 0},
             'unchanged'),
        ]
        for name, payload, encoding, expected, outcome in cases:
            with self.subTest(case=name):
                self.log.events.clear()
                emitted = self.drive(payload, encoding)
                for key, value in expected.items():
                    self.assertEqual(emitted.get(key), value, name + ': ' + key)
                self.assertEqual(emitted.get('outcome'), outcome, name)

    def test_no_request_content_reaches_the_event_fields(self):
        items = [MESSAGE, BLOB_ONLY, BLOB_WITH_TEXT, COMPACTION]
        unowned = {'type': 'message', 'role': 'user',
                   'content': [{'type': 'encrypted_content',
                                'encrypted_content': 'BLOB-THREE'}]}
        for name, payload, encoding in (('identity', body(items), None),
                                        ('compressed', zstd.compress(body(items)), 'zstd'),
                                        ('undecodable', b'not-zstd-at-all', 'zstd'),
                                        ('unowned shape', body(items + [unowned]), None)):
            with self.subTest(case=name):
                self.log.events.clear()
                emitted = self.drive(payload, encoding)
                rendered = json.dumps(emitted)
                for secret in ('BLOB-ONE', 'BLOB-TWO', 'BLOB-THREE', 'judge this action',
                               SUMMARY):
                    self.assertNotIn(secret, rendered, name)
                diagnostics = {'encoding', 'decoded', 'parsed', 'input_is_list',
                               'items', 'reasoning_items', 'encrypted_fields',
                               'removed'}
                self.assertTrue(diagnostics <= set(emitted), name)
                allowed = diagnostics | {'provider', 'model', 'repair', 'request_bytes',
                                         'eligible', 'attempted', 'outcome', 'status',
                                         'reason', 'parameter', 'serving_endpoint'}
                self.assertTrue(set(emitted) <= allowed, set(emitted) - allowed)


if __name__ == '__main__':
    unittest.main()
