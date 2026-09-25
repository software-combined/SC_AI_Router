"""Focused tests for the replayed compaction summary on the subscription route.

Defect guarded: the router hands the Codex client a V2 compaction item whose
`encrypted_content` is the router's own `ocx1:` summary. The client replays
that item, the ChatGPT backend cannot read the blob, and the turn is refused
with HTTP 400 `invalid_encrypted_content` while the replayed history holds no
`type: reasoning` item for the reasoning-blob repair to take out. Measured on
this host 2026-09-23: `items=6, reasoning_items=0, encrypted_fields=1,
removed=0`, so the bounded retry never fired.

Run from the copy root:
  <python> -X utf8 -m unittest tests.test_subscription_compaction_repair -v
"""
import json
import unittest

from ai_router import (compaction, provider_defs, providers, strip_retry,
                       subscription_history, transport)


SUBSCRIPTION = providers.SubscriptionProvider()
SUMMARY = 'the summary the router wrote for this thread'
COMPACTION = {'type': 'compaction', 'id': 'cmp_1',
              'encrypted_content': compaction.encode_summary(SUMMARY)}
MESSAGE = {'type': 'message', 'role': 'user',
           'content': [{'type': 'input_text', 'text': 'judge this action'}]}
REASONING = {'type': 'reasoning', 'id': 'rs_1', 'encrypted_content': 'PROVIDER-BLOB'}
UNOWNED = {'type': 'message', 'role': 'user',
           'content': [{'type': 'encrypted_content', 'encrypted_content': 'SIDECAR-BLOB'}]}

ERROR_RAW = json.dumps({'error': {'message': 'the request was rejected',
                                  'code': 'invalid_encrypted_content'}}).encode()
DESCRIBED = (400, 'codex-auto-review refused this request: the request was '
                  'rejected. Do not retry it unchanged', 'invalid_encrypted_content')


def body(items):
    return json.dumps({'model': 'codex-auto-review', 'stream': True,
                       'input': items}, separators=(',', ':')).encode()


def prepared(items):
    return transport.Prepared('api.openai.com', '/responses', {}, body(items),
                              set(), 'openai')


class Response:
    def __init__(self, status):
        self.status = status


class Recorder:
    def __init__(self):
        self.events = []

    def __call__(self, event, **fields):
        self.events.append((event, fields))

    def outcomes(self):
        return [f.get('outcome') for e, f in self.events if e == 'annotation_retry']


class CompactionRepairTests(unittest.TestCase):
    def setUp(self):
        self.metrics = {'protocol': provider_defs.RESPONSES, 'model': 'codex-auto-review'}
        self.log = Recorder()
        self.dispatches = []
        self._post, self._read = transport.post_with_phases, transport.read_capped
        transport.post_with_phases = self.post_200
        transport.read_capped = lambda response, limit: ERROR_RAW

    def tearDown(self):
        transport.post_with_phases, transport.read_capped = self._post, self._read

    def post_200(self, conn, prep, metrics):
        self.dispatches.append(prep.body)
        return Response(200), True

    def drive(self, items, status=400, described=DESCRIBED, provider=SUBSCRIPTION):
        return strip_retry.maybe_retry_unattributable(
            described, Response(status), ERROR_RAW, self.metrics, provider,
            prepared(items), [], self.log)

    def test_01_the_replayed_compaction_summary_is_repaired_readably(self):
        self.assertIsNotNone(self.drive([MESSAGE, COMPACTION]))
        sent = self.dispatches[-1]
        self.assertNotIn(b'encrypted_content', sent)
        self.assertNotIn(compaction.encode_summary(SUMMARY).encode(), sent)
        self.assertEqual(json.loads(sent)['input'][1], {
            'type': 'message', 'role': 'user',
            'content': [{'type': 'input_text',
                         'text': compaction.SUMMARY_PREFIX + '\n\n' + SUMMARY}]})
        self.assertEqual(self.log.outcomes(), ['started', 'accepted'])

    def test_02_an_opaque_compaction_summary_is_replaced_not_forwarded(self):
        opaque = {'type': 'compaction', 'id': 'cmp_2',
                  'encrypted_content': 'NATIVE-OPAQUE-BLOB'}
        self.assertIsNotNone(self.drive([opaque]))
        sent = self.dispatches[-1]
        self.assertNotIn(b'NATIVE-OPAQUE-BLOB', sent)
        self.assertIn(compaction.OPAQUE_NOTE,
                      json.loads(sent)['input'][0]['content'][0]['text'])

    def test_03_the_reasoning_blob_repair_still_works(self):
        self.assertIsNotNone(self.drive([MESSAGE, REASONING]))
        self.assertEqual(self.log.outcomes(), ['started', 'accepted'])
        self.assertNotIn(b'PROVIDER-BLOB', self.dispatches[-1])

    def test_04_an_unowned_encrypted_shape_fails_closed(self):
        cases = (('nested sidecar block beside a compaction item',
                  [MESSAGE, COMPACTION, UNOWNED]),
                 ('item-level key on a message item',
                  [MESSAGE, {'type': 'message', 'role': 'user',
                             'encrypted_content': 'SIDECAR-BLOB'}]),
                 ('reasoning blob plus an unowned site', [REASONING, UNOWNED]))
        for name, items in cases:
            with self.subTest(case=name):
                self.log.events.clear()
                self.dispatches.clear()
                self.assertIsNone(self.drive(items))
                self.assertEqual(self.dispatches, [], 'no retry for an unowned shape')
                self.assertEqual(self.log.outcomes(), ['unchanged'])

    def test_05_healthy_and_unrelated_turns_never_reach_the_repair(self):
        self.assertIsNone(self.drive([MESSAGE, COMPACTION], status=200, described=None))
        self.assertIsNone(self.drive([MESSAGE, COMPACTION], described=(
            400, 'x refused this request: the request was rejected. ',
            'unsupported_parameter')))
        self.assertEqual(self.log.outcomes(), ['ineligible', 'ineligible'])
        self.assertEqual(self.dispatches, [])

    def test_06_exactly_one_retry(self):
        def post_400(conn, prep, metrics):
            self.dispatches.append(prep.body)
            return Response(400), True
        transport.post_with_phases = post_400
        strip_retry.post_with_retry(object(), prepared([MESSAGE, COMPACTION]),
                                    self.metrics, [], SUBSCRIPTION, self.log)
        self.assertEqual(len(self.dispatches), 2, 'initial dispatch plus one retry')
        self.assertNotIn(b'encrypted_content', self.dispatches[1])

    def test_07_the_healthy_path_projects_the_router_summary(self):
        payload = json.loads(body([MESSAGE, COMPACTION]))
        result = subscription_history.normalize(payload)
        self.assertIsNot(result, payload)
        self.assertEqual(result['input'][1], {
            'type': 'message', 'role': 'user',
            'content': [{'type': 'input_text',
                         'text': compaction.SUMMARY_PREFIX + '\n\n' + SUMMARY}]})
        self.assertNotIn(compaction.encode_summary(SUMMARY), json.dumps(result))
        # The client's own history still holds the item it stored.
        self.assertEqual(payload['input'][1]['encrypted_content'],
                         compaction.encode_summary(SUMMARY))

    def test_08_no_content_reaches_the_event_fields(self):
        self.drive([MESSAGE, COMPACTION])
        fields = [f for e, f in self.log.events if e == 'annotation_retry']
        self.assertEqual(len(fields), 2, 'repair decision plus the retry outcome')
        allowed = {'encoding', 'decoded', 'parsed', 'input_is_list', 'items',
                   'reasoning_items', 'encrypted_fields', 'removed', 'provider',
                   'model', 'repair', 'request_bytes', 'eligible', 'attempted',
                   'outcome', 'status', 'reason', 'parameter', 'serving_endpoint'}
        for emitted in fields:
            rendered = json.dumps(emitted)
            for secret in (SUMMARY, compaction.encode_summary(SUMMARY),
                           'judge this action'):
                self.assertNotIn(secret, rendered)
            self.assertTrue(set(emitted) <= allowed, set(emitted) - allowed)


if __name__ == '__main__':
    unittest.main()
