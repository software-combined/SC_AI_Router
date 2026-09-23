"""Focused tests for the subscription `invalid_encrypted_content` repair.

Defect guarded: a subscription (OpenAI-dialect) turn whose replayed
`input[]` reasoning item carries `encrypted_content` is rejected by the
ChatGPT backend with HTTP 400 `invalid_encrypted_content`, and the router
forwarded that refusal instead of repairing the one named condition.

Run from the copy root:
  <python> -m unittest discover -s tests -t . -v
"""
import inspect
import json
import types
import unittest
from unittest import mock

from ai_router import (provider_defs, providers, strip_retry,
                       subscription_history, transport)


OPENROUTER = types.SimpleNamespace(defn=provider_defs.get(provider_defs.DEFAULT_EXTERNAL))
SUBSCRIPTION = types.SimpleNamespace(defn=provider_defs.get('openai'))


def body(items):
    return json.dumps({'model': 'codex-auto-review', 'stream': True,
                       'input': items}, separators=(',', ':')).encode()


MESSAGE = {'type': 'message', 'role': 'user',
           'content': [{'type': 'input_text', 'text': 'judge this action'}]}
BLOB_ONLY = {'type': 'reasoning', 'id': 'rs_1', 'encrypted_content': 'BLOB-ONE'}
BLOB_WITH_TEXT = {'type': 'reasoning', 'id': 'rs_2', 'encrypted_content': 'BLOB-TWO',
                  'summary': [{'type': 'summary_text', 'text': 'readable trace'}]}
GUARDIAN_BODY = body([MESSAGE, BLOB_ONLY, BLOB_WITH_TEXT])

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
        # Fail loudly if the repair runs where it must not: this stand-in takes
        # one argument, so a two-argument call raises TypeError.
        with mock.patch.object(strip_retry, 'strip_reasoning_blobs',
                               lambda b: called.append(b)):
            self.assertIsNone(self.drive(200, None))
        self.assertEqual(called, [], 'healthy turn must not reach any strip')
        self.assertEqual(self.log.outcomes(), ['ineligible'])

    def test_02_non_400_never_triggers_the_repair(self):
        called = []
        with mock.patch.object(strip_retry, 'strip_reasoning_blobs',
                               lambda b: called.append(b)):
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
        # The retry-only strip removes the field, drops the blob-only item,
        # and keeps the item that still carries readable reasoning text.
        out = json.loads(strip_retry.strip_reasoning_blobs(GUARDIAN_BODY))
        self.assertEqual([(i.get('type'), i.get('id')) for i in out['input']],
                         [('message', None), ('reasoning', 'rs_2')])
        self.assertEqual(out['input'][1]['summary'][0]['text'], 'readable trace')
        self.assertNotIn('encrypted_content', json.dumps(out))
        # Nothing to repair means no rewrite at all.
        self.assertIsNone(strip_retry.strip_reasoning_blobs(body([MESSAGE])))

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
        self.assertNotIn('strip_reasoning_blobs',
                         inspect.getsource(providers.SubscriptionProvider),
                         'the healthy subscription path must not strip blobs')
        self.assertIn('strip_reasoning_blobs',
                      inspect.getsource(providers.ExternalResponsesProvider))


if __name__ == '__main__':
    unittest.main()
