"""A setup echo larger than the reasoning hold still leaves one retry (0.6.125).

The 2026-09-25 MiMo capture: with 53 tools, xiaomi/mimo-v2.6-pro echoed the
whole tool list in `response.created` (about 84 KiB) and again in
`response.in_progress`, past `stream_attempt.PENDING_LIMIT`. The setup frames
reached the client before any answer, so a later `server_error`/`timeout`
could not be retried. Every frame is forwarded byte for byte: the fix holds
setup and the terminal in their own bounded slots rather than trimming them.
The same wire runs against two model rows, so no model condition can pass.
Fake upstream only; never opens a network connection.
"""
import itertools
import json
from unittest import mock

from ai_router import router as router_mod
from ai_router import sse, stream_attempt
from tests.fakes import FakeUpstream, install_fake
from tests.harness import post as _post
from tests.test_stream_retry import _ServerFixture

MODELS = ('xiaomi/mimo-v2.6-pro', 'deepseek/deepseek-v4.1-flash')
TOOLS = [{'type': 'function', 'name': f'inert_{n}', 'description': 'd' * 1500,
          'parameters': {'type': 'object', 'properties': {}}} for n in range(53)]
INSTRUCTIONS = 'synthetic instructions ' * 200
MESSAGE = {'type': 'message', 'id': 'msg_1', 'role': 'assistant',
           'content': [{'type': 'output_text', 'text': 'hello'}]}
CALL = {'type': 'function_call', 'id': 'fc_1', 'call_id': 'call_1',
        'name': 'inert_0', 'arguments': '{}'}


def _frame(event):
    return sse.frame(json.dumps(event).encode())


def _response(rid, model, status, echo=True, **extra):
    """The Response object as the provider echoes it: request fields included."""
    body = {'id': rid, 'object': 'response', 'created_at': 1, 'model': model,
            'status': status, 'output': [], 'usage': None,
            'tools': TOOLS if echo else [], 'instructions': INSTRUCTIONS if echo else None}
    body.update(extra)
    return body


def _setup(rid, model, echo=True):
    return (_frame({'type': 'response.created',
                    'response': _response(rid, model, 'in_progress', echo)})
            + _frame({'type': 'response.in_progress',
                      'response': _response(rid, model, 'in_progress', echo)}))


def _timeout(rid, model, echo=True, **extra):
    return _frame({'type': 'response.failed', 'error_type': 'timeout',
                   'response': _response(rid, model, 'failed', echo,
                                         error={'code': 'server_error'}, **extra)})


def _answer(rid, model):
    return (_frame({'type': 'response.output_item.added', 'item': MESSAGE})
            + _frame({'type': 'response.output_text.delta', 'delta': 'hello'})
            + _frame({'type': 'response.completed', 'response': _response(
                rid, model, 'completed', output=[MESSAGE],
                usage={'input_tokens': 21000, 'output_tokens': 3})}))


class Trickle(FakeUpstream):
    """Hands the relay at most `step` bytes per read, splitting every frame."""

    def __init__(self, body, step):
        super().__init__(200, body, [('Content-Type', 'text/event-stream')])
        self.step = step

    def read1(self, count):
        return self.read(min(count, self.step))


class SetupEchoRetryTests(_ServerFixture):
    def _stream(self, model, *answers):
        """Stream one request; each upstream connection takes the next answer."""
        upcoming = itertools.chain(answers, itertools.repeat(answers[-1]))

        def respond():
            item = next(upcoming)
            if isinstance(item, BaseException):
                raise item
            if isinstance(item, bytes):
                return FakeUpstream(200, item, [('Content-Type', 'text/event-stream')])
            return item
        recorded = install_fake(self, respond)
        server = self._server()
        with mock.patch.object(router_mod, 'log_event') as logged:
            response = _post(server.server_port, '/test-token/responses',
                             {'model': model, 'input': [], 'stream': True,
                              'tools': TOOLS, 'instructions': INSTRUCTIONS})
            self.assertEqual(response.status, 200)
            body = response.read()
        names = [c.args[0] for c in logged.call_args_list]
        final = [c.kwargs for c in logged.call_args_list if c.args[0] in (
            'request_completed', 'request_failed', 'transport_error')]
        self.assertEqual(len(final), 1)
        return body, len(recorded), names, final[0]

    def test_each_captured_setup_frame_exceeds_the_reasoning_hold(self):
        # The shape under test, not a tuning constant: one echoing frame alone
        # is past the small hold, so only a lifecycle slot can keep it.
        created = _setup('resp_a', MODELS[0]).split(b'\n\n')[0]
        self.assertGreater(len(created), stream_attempt.PENDING_LIMIT)
        self.assertGreater(len(_timeout('resp_a', MODELS[0])), stream_attempt.PENDING_LIMIT)

    def test_large_setup_then_transient_failure_retries_once(self):
        for model in MODELS:
            with self.subTest(model=model):
                retry = _setup('resp_b', model) + _answer('resp_b', model)
                body, calls, names, final = self._stream(
                    model, _setup('resp_a', model) + _timeout('resp_a', model), retry)
                self.assertEqual(calls, 2)
                self.assertEqual(names.count('stream_retry'), 1)
                # Only the successful attempt reaches the client, byte for byte.
                self.assertEqual(body, retry)
                self.assertEqual((final['stream_retry'], final['forwarded_delta_bytes']),
                                 (1, len(retry)))

    def test_small_setup_then_large_failure_retries_once(self):
        for model in MODELS:
            with self.subTest(model=model):
                retry = _setup('resp_b', model, echo=False) + _answer('resp_b', model)
                body, calls, names, _ = self._stream(
                    model, _setup('resp_a', model, echo=False) + _timeout('resp_a', model),
                    retry)
                self.assertEqual((calls, names.count('stream_retry')), (2, 1))
                self.assertEqual(body, retry)

    def test_both_attempts_failing_stop_at_two_calls_with_the_raw_verdict(self):
        second = _setup('resp_b', MODELS[0]) + _timeout('resp_b', MODELS[0])
        body, calls, names, final = self._stream(
            MODELS[0], _setup('resp_a', MODELS[0]) + _timeout('resp_a', MODELS[0]), second)
        self.assertEqual((calls, names.count('stream_retry')), (2, 1))
        self.assertEqual(body, second)
        self.assertEqual((final['upstream_code'], final['upstream_error_type'],
                          final['terminal_source']), ('server_error', 'timeout', 'upstream'))

    def test_failed_retry_opening_keeps_the_original_attempt(self):
        first = _setup('resp_a', MODELS[1]) + _timeout('resp_a', MODELS[1])
        body, calls, _, final = self._stream(MODELS[1], first, OSError('connect failed'))
        self.assertEqual(calls, 2)
        self.assertEqual(body, first)
        self.assertEqual(final['terminal_source'], 'upstream')

    def test_a_large_successful_stream_is_byte_identical(self):
        wire = _setup('resp_a', MODELS[0]) + _answer('resp_a', MODELS[0])
        body, calls, _, final = self._stream(MODELS[0], wire)
        self.assertEqual((body, calls, final['stream_retry']), (wire, 1, 0))

    def test_arbitrary_chunk_splits_give_the_same_result(self):
        model = MODELS[1]
        first = _setup('resp_a', model) + _timeout('resp_a', model)
        retry = _setup('resp_b', model) + _answer('resp_b', model)
        for step in (7, 4093, 65537):
            with self.subTest(step=step):
                body, calls, _, _ = self._stream(
                    model, Trickle(first, step), Trickle(retry, step))
                self.assertEqual((body, calls), (retry, 2))


class CommittedAttemptTests(_ServerFixture):
    """Bytes the client could act on, or cannot be classified, end the replay."""

    _stream = SetupEchoRetryTests._stream
    MODEL = MODELS[0]

    def _not_retried(self, wire):
        body, calls, names, final = self._stream(self.MODEL, wire)
        self.assertEqual((calls, names.count('stream_retry'), final['stream_retry']),
                         (1, 0, 0))
        self.assertEqual(body, wire)
        return final

    def test_tool_call_before_the_failure_is_not_retried(self):
        final = self._not_retried(
            _setup('resp_a', self.MODEL) + _frame({'type': 'response.output_item.added',
                                                   'item': CALL})
            + _frame({'type': 'response.output_item.done', 'item': CALL})
            + _timeout('resp_a', self.MODEL))
        self.assertGreater(final['content_delta_bytes'], 0)

    def test_opaque_event_before_the_failure_is_not_retried(self):
        for opaque in (_frame({'type': 'response.unclassified', 'x': 1}),
                       _frame({'type': []}), b'data: not json\n\n'):
            with self.subTest(frame=opaque[:24]):
                self._not_retried(_setup('resp_a', self.MODEL) + opaque
                                  + _timeout('resp_a', self.MODEL))

    def test_setup_carrying_output_is_preserved_not_retried(self):
        created = _frame({'type': 'response.created', 'response': _response(
            'resp_a', self.MODEL, 'in_progress', output=[MESSAGE])})
        self._not_retried(created + _timeout('resp_a', self.MODEL))

    def test_terminal_carrying_output_is_preserved_not_retried(self):
        self._not_retried(_setup('resp_a', self.MODEL)
                          + _timeout('resp_a', self.MODEL, output=[CALL]))

    def test_duplicate_setup_commits_instead_of_growing_the_hold(self):
        created = _setup('resp_a', self.MODEL).split(b'\n\n')[0] + b'\n\n'
        self._not_retried(created * 3 + _timeout('resp_a', self.MODEL))

    def test_completed_frame_is_not_mistaken_for_setup(self):
        completed = _frame({'type': 'response.created', 'response': _response(
            'resp_a', self.MODEL, 'completed')})
        self._not_retried(completed + _timeout('resp_a', self.MODEL))

    def test_unhashable_setup_status_is_opaque_not_retried(self):
        created = _frame({'type': 'response.created', 'response': {'status': {}}})
        self._not_retried(created + _timeout('resp_a', self.MODEL))
