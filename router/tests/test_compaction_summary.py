import io
import json
import threading
import time
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import mock

from ai_router import (availability, compaction_result, compaction_summary,
                       provider_defs, providers)


def _external_responses():
    return providers.ExternalResponsesProvider(provider_defs.OPENROUTER)


def _summary_row(slug, ceiling=100000):
    levels = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh') \
        if slug.startswith('xiaomi/') else ('low', 'high', 'max')
    return SimpleNamespace(slug=slug, provider='openrouter',
                           max_output_tokens=ceiling, reasoning=levels,
                           provider_prefs=None, upstream_id=slug)


def _summary_rows(ceiling=100000):
    return {slug: _summary_row(slug, ceiling)
            for slug in compaction_summary.SUMMARY_MODEL_SLUGS}


class Clock:
    def __init__(self, now=0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class SummaryAvailabilityTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(
            availability, 'current',
            return_value={'key': availability.key_fingerprint('key'),
                          'region': 'global',
                          'models': frozenset(
                              compaction_summary.SUMMARY_MODEL_SLUGS)}))


class SummarizerRetryTests(SummaryAvailabilityTest):
    @staticmethod
    def _result(text='summary', status=None, **extra):
        payload = {'output': [{'type': 'message', 'content': [
            {'type': 'output_text', 'text': text}]}]}
        if status is not None:
            payload['status'] = status
        payload.update(extra)
        return 200, payload

    @classmethod
    def _truncated(cls):
        result = cls._result('partial', status='incomplete',
                             incomplete_details={'reason': 'max_output_tokens'})
        result[1]['output'][0]['status'] = 'incomplete'
        return result

    @classmethod
    def _empty_truncated(cls):
        return 200, {'output': [], 'status': 'incomplete',
                     'incomplete_details': {'reason': 'max_output_tokens'}}

    def _run(self, responses, model='z-ai/glm-5.3', ceiling=None,
             clock=None, delays=(), allowed=None):
        queue, calls, closed = list(responses), [], []
        delays = list(delays)

        class Response:
            def __init__(self, status, payload):
                self.status = status
                self.body = io.BytesIO(json.dumps(payload).encode())

            def read(self, *args):
                return self.body.read(*args)

        class Connection:
            def __init__(self, *args, **kwargs):
                calls.append({'timeout': kwargs.get('timeout')})

            def connect(self):
                pass

            def request(self, method, path, body=None, headers=None):
                calls[-1]['body'] = json.loads(body)

            def getresponse(self):
                if not queue:
                    raise AssertionError('summarizer retried beyond the fixture')
                response = queue.pop(0)
                if (isinstance(response, tuple) and len(response) == 2
                        and isinstance(response[1], dict)
                        and 'model' not in response[1]):
                    response = (response[0], dict(response[1],
                                                  model=calls[-1]['body']['model']))
                if delays:
                    clock.advance(delays.pop(0))
                if isinstance(response, BaseException):
                    raise response
                return Response(*response)

            def close(self):
                closed.append(True)

        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                compaction_summary.http.client, 'HTTPSConnection', Connection))
            rows = _summary_rows(100000 if ceiling is None else ceiling)
            stack.enter_context(mock.patch.object(
                providers, 'by_slug', side_effect=lambda slug: rows.get(slug)))
            if clock is not None:
                stack.enter_context(mock.patch.object(
                    providers.time, 'monotonic', clock))
            try:
                result = _external_responses().summarize(model, 'key', [
                    {'type': 'message', 'role': 'user', 'content': 'marker'}],
                    allowed=allowed)
            except Exception as exc:  # Return the result so every path checks closure.
                result = exc
        return result, calls, closed

    def test_truncated_summary_retries_once_and_keeps_request(self):
        with mock.patch.object(providers, 'log_event') as logged:
            result, calls, closed = self._run([
                self._truncated(), self._result('complete')])
        self.assertEqual(result, 'complete')
        self.assertEqual([call['body']['max_output_tokens'] for call in calls],
                         [4000, 8000])
        self.assertEqual(calls[0]['body']['input'], calls[1]['body']['input'])
        self.assertEqual(calls[0]['body']['reasoning'], {'effort': 'none'})
        self.assertEqual(len(calls), len(closed))
        start = next(call.kwargs for call in logged.call_args_list
                     if call.args and call.args[0] == 'compaction_summary_start')
        complete = next(call.kwargs for call in logged.call_args_list
                        if call.args and call.args[0] == 'compaction_summary_complete')
        self.assertEqual(start, {'active_model': 'z-ai/glm-5.3',
                                 'summary_model': 'xiaomi/mimo-v2.6-flash',
                                 'transcript_chars': len('user: marker')})
        self.assertEqual([event['outcome'] for event in complete['attempts']],
                         ['retry', 'completed'])
        self.assertEqual(complete['summary_model'], 'xiaomi/mimo-v2.6-flash')
        self.assertEqual(complete['outcome'], 'completed')
        self.assertEqual(complete['summary_chars'], len('complete'))
        self.assertNotIn('marker', repr(complete))

    def test_retry_budgets_stay_at_4000_and_8000(self):
        result, calls, closed = self._run([
            self._truncated(), self._truncated(), self._result('complete')],
            ceiling=8000)
        self.assertEqual(result, 'complete')
        self.assertEqual([call['body']['max_output_tokens'] for call in calls],
                         [4000, 8000, 4000])
        self.assertEqual(len(calls), len(closed))
        result, calls, closed = self._run(
            [self._truncated()] * 4, ceiling=8000)
        self.assertIsInstance(result, compaction_result.IncompleteSummary)
        self.assertEqual([call['body']['max_output_tokens'] for call in calls],
                         [4000, 8000, 4000, 8000])
        self.assertEqual(len(calls), len(closed))

    def test_incomplete_retries_before_cross_vendor_fallback(self):
        with mock.patch.object(providers, 'log_event') as logged:
            result, calls, closed = self._run([
                self._truncated(), self._truncated(), self._result('complete')])
        self.assertEqual(result, 'complete')
        self.assertEqual([call['body']['model'] for call in calls],
                         ['xiaomi/mimo-v2.6-flash',
                          'xiaomi/mimo-v2.6-flash',
                          'deepseek/deepseek-v4.1-flash-1017'])
        self.assertEqual([call['body']['max_output_tokens'] for call in calls],
                         [4000, 8000, 4000])
        complete = next(call.kwargs for call in logged.call_args_list
                        if call.args and call.args[0] == 'compaction_summary_complete')
        self.assertEqual([event['outcome'] for event in complete['attempts']],
                         ['retry', 'fallback', 'completed'])
        self.assertEqual(len(calls), len(closed))

    def test_empty_truncated_summary_retries_and_falls_back(self):
        result, calls, closed = self._run([
            self._empty_truncated(), self._empty_truncated(),
            self._result('complete')])
        self.assertEqual(result, 'complete')
        self.assertEqual([call['body']['model'] for call in calls],
                         ['xiaomi/mimo-v2.6-flash',
                          'xiaomi/mimo-v2.6-flash',
                          'deepseek/deepseek-v4.1-flash-1017'])
        self.assertEqual([call['body']['max_output_tokens'] for call in calls],
                         [4000, 8000, 4000])
        self.assertEqual(len(calls), len(closed))

    def test_incomplete_output_is_rejected_after_every_budget(self):
        result, calls, closed = self._run([self._truncated()] * 4)
        self.assertIsInstance(result, compaction_result.IncompleteSummary)
        self.assertEqual([call['body']['max_output_tokens'] for call in calls],
                         [4000, 8000, 4000, 8000])
        self.assertEqual(len(calls), len(closed))

    def test_retry_uses_one_shared_deadline(self):
        clock = Clock()
        result, calls, closed = self._run(
            [self._truncated(), self._result('complete')],
            clock=clock, delays=(35, 1))
        self.assertEqual(result, 'complete')
        self.assertLess(calls[1]['timeout'], calls[0]['timeout'])
        self.assertLessEqual(calls[0]['timeout'],
                             compaction_summary.SUMMARY_ATTEMPT_DEADLINE_S)
        self.assertLessEqual(calls[0]['timeout'],
                             compaction_summary.SUMMARY_TOTAL_DEADLINE_S)
        self.assertEqual(len(calls), len(closed))

    def test_total_deadline_after_dispatch_reports_unknown_commitment(self):
        clock = Clock()
        with mock.patch.object(providers, 'log_event') as logged:
            result, calls, closed = self._run(
                [self._truncated()], clock=clock, delays=(80,))
        self.assertIsInstance(result, TimeoutError)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls), len(closed))
        self.assertEqual(calls[0]['timeout'],
                         compaction_summary.SUMMARY_ATTEMPT_DEADLINE_S)
        complete = next(call.kwargs for call in logged.call_args_list
                        if call.args and call.args[0] == 'compaction_summary_complete')
        self.assertEqual(complete['outcome'], 'unknown')

    def test_attempt_response_timeout_cannot_fall_back(self):
        clock = Clock()
        with mock.patch.object(providers, 'log_event') as logged:
            result, calls, closed = self._run(
                [self._result('late')], clock=clock, delays=(50,))
        self.assertIsInstance(result, TimeoutError)
        self.assertEqual([call['body']['model'] for call in calls],
                         ['xiaomi/mimo-v2.6-flash'])
        self.assertLessEqual(calls[0]['timeout'],
                             compaction_summary.SUMMARY_ATTEMPT_DEADLINE_S)
        complete = next(call.kwargs for call in logged.call_args_list
                         if call.args and call.args[0] == 'compaction_summary_complete')
        self.assertEqual([(event['outcome'], event['commitment'])
                          for event in complete['attempts']],
                         [('timeout', 'unknown')])
        self.assertEqual(len(calls), len(closed))

    def test_final_attempt_deadline_raises_timeout(self):
        clock = Clock()
        result, calls, closed = self._run(
            [self._result('late')], clock=clock, delays=(50,), ceiling=8000,
            allowed={compaction_summary.SUMMARY_MODEL_SLUGS[0]})
        self.assertIsInstance(result, TimeoutError)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls), len(closed))

    def test_other_failures_do_not_retry(self):
        valid = self._result('partial')
        cases = {
            'failed status': self._result(status='failed'),
            'in progress': self._result(status='in_progress'),
            'embedded error': (200, {**valid[1], 'error': {'code': 'bad'}}),
            'empty': (200, {'output': []}),
            'malformed': (200, {'output': 'bad'}),
            'auth': (401, {'error': 'unauthorized'}),
        }
        for name, response in cases.items():
            with self.subTest(name=name):
                result, calls, closed = self._run([response])
                self.assertIsInstance(result, Exception)
                self.assertNotIsInstance(result, compaction_result.IncompleteSummary)
                self.assertEqual(len(calls), 1)
                self.assertEqual(len(calls), len(closed))

    def test_response_model_mismatch_fails_closed(self):
        result, calls, closed = self._run([
            self._result('summary', model='other/unapproved-model')])
        self.assertIsInstance(result, ValueError)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls), len(closed))

    def test_missing_response_model_fails_closed(self):
        result, calls, closed = self._run([
            self._result('summary', model=None)])
        self.assertIsInstance(result, ValueError)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls), len(closed))

    def test_summary_policy_fails_closed_before_any_http_call(self):
        with mock.patch.object(availability, 'current',
                               return_value={'key': availability.key_fingerprint('key'), 'region': 'global', 'models': frozenset()}), \
                mock.patch.object(compaction_summary.http.client,
                                  'HTTPSConnection') as conn:
            with self.assertRaisesRegex(ValueError, 'models unavailable'):
                _external_responses().summarize(
                    'z-ai/glm-5.3', 'key', [],
                    allowed=compaction_summary.SUMMARY_MODEL_SLUGS)
        conn.assert_not_called()

    def test_body_reads_cannot_extend_past_total_deadline(self):
        clock = Clock()
        chunks = [b'{"output": [{"type": "message", "content": [',
                  b'{"type": "output_text", "text": "late"}]}]}']

        class Response:
            status = 200

            def read1(self, _size):
                clock.advance(40)
                return chunks.pop(0) if chunks else b''

        class Connection:
            sock = None

            def connect(self):
                pass

            def request(self, *args, **kwargs):
                pass

            def getresponse(self):
                return Response()

            def close(self):
                pass

        with mock.patch.object(compaction_summary.http.client,
                               'HTTPSConnection', return_value=Connection()):
            with self.assertRaises(TimeoutError):
                compaction_summary._fetch_summary(
                    _external_responses(), 'key', {}, 45,
                    clock.now + compaction_summary.SUMMARY_TOTAL_DEADLINE_S,
                    clock.now + compaction_summary.SUMMARY_TOTAL_DEADLINE_S,
                    clock)


class NetworkDeadlineTests(SummaryAvailabilityTest):
    def test_connect_timeout_cannot_send_after_fallback(self):
        release, finished = threading.Event(), threading.Event()
        sent = []

        class Response:
            status = 200

            def read(self):
                return json.dumps({'model': 'deepseek/deepseek-v4.1-flash-1017',
                                   'output': [{'type': 'message', 'content': [
                                       {'type': 'output_text',
                                        'text': 'complete'}]}]}).encode()

        class FirstConnection:
            sock = None

            def connect(self):
                try:
                    release.wait(1)
                finally:
                    finished.set()

            def request(self, *args, **kwargs):
                sent.append('first')

            def getresponse(self):
                raise AssertionError('timed-out connect must not send')

            def close(self):
                pass

        class SecondConnection:
            sock = None

            def connect(self):
                pass

            def request(self, *args, **kwargs):
                sent.append('second')

            def getresponse(self):
                return Response()

            def close(self):
                pass

        connections = [FirstConnection(), SecondConnection()]
        with mock.patch.object(compaction_summary, 'SUMMARY_ATTEMPT_DEADLINE_S', 0.05), \
                mock.patch.object(compaction_summary, 'SUMMARY_TOTAL_DEADLINE_S', 0.1), \
                mock.patch.object(compaction_summary.http.client,
                                  'HTTPSConnection',
                                  side_effect=lambda *args, **kwargs: connections.pop(0)):
            result = _external_responses().summarize(
                'z-ai/glm-5.3', 'key',
                [{'type': 'message', 'role': 'user', 'content': 'marker'}])
        self.assertEqual(result, 'complete')
        self.assertEqual(sent, ['second'])
        release.set()
        self.assertTrue(finished.wait(1))
        self.assertEqual(sent, ['second'])

    def _assert_phase_timeout(self, phase):
        release, started = threading.Event(), threading.Event()

        class Response:
            status = 200

            def read(self):
                if phase == 'read':
                    started.set()
                    release.wait(1)
                return b'{}'

        class Connection:
            sock = None

            def connect(self):
                if phase == 'connect':
                    started.set()
                    release.wait(1)

            def request(self, *args, **kwargs):
                if phase == 'request':
                    started.set()
                    release.wait(1)

            def getresponse(self):
                if phase == 'getresponse':
                    started.set()
                    release.wait(1)
                return Response()

            def close(self):
                release.set()

        conn = Connection()
        with mock.patch.object(compaction_summary.http.client,
                               'HTTPSConnection', return_value=conn):
            now = time.monotonic()
            with self.assertRaises(TimeoutError):
                compaction_summary._fetch_summary(
                    _external_responses(), 'key',
                    {'model': 'xiaomi/mimo-v2.6-flash'}, 0.05,
                    now + 0.05, now + 0.05, time.monotonic)
        self.assertTrue(started.is_set())

    def test_request_response_and_fallback_read_respect_wall_clock(self):
        for phase in ('connect', 'request', 'getresponse', 'read'):
            with self.subTest(phase=phase):
                self._assert_phase_timeout(phase)


if __name__ == '__main__':
    unittest.main()
