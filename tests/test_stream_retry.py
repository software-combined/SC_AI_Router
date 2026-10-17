"""Retry behaviour for one failed upstream stream (0.6.49).

Fake upstream only; never opens a real network connection. The shared
ephemeral-router fixture lives in tests/test_stream_containment.py.
"""
import itertools
import json
import unittest
from unittest import mock

from ai_router import router as router_mod
from ai_router import sse, stream_errors, stream_relay
from tests.fakes import FakeUpstream, install_fake
from tests.harness import (
    auth_file as _auth_file,
    post as _post,
    start_server as _start_server,
    test_state as _test_state,
)


class _ServerFixture(unittest.TestCase):
    """Shared ephemeral-router fixture for the relay suites below."""

    def _server(self, **state_overrides):
        state = _test_state(_auth_file(self))
        state.update(state_overrides)
        server = _start_server(state)
        self.addCleanup(server.shutdown)
        return server

    def _events(self, body):
        events = []
        for block in body.split(b'\n\n'):
            for line in block.splitlines():
                if line.startswith(b'data:'):
                    events.append(json.loads(line[5:].strip()))
        return events


class UpstreamTerminalRetryTests(_ServerFixture):
    """One retry, and only while the client has received nothing at all.

    The 2026-09-13 incident: an OpenRouter row ended mid-stream with the
    provider's own `response.failed`/`server_error` frame, the desktop client
    showed "Reconnecting", and only its retry saved the turn. Before any payload
    the relay can absorb that failure itself; after any payload it must not.
    """

    MODEL = 'deepseek/deepseek-v4.1-flash-1017'

    def _failed(self, code='overloaded'):
        return sse.frame(json.dumps({'type': 'response.failed', 'response': {
            'id': 'r1', 'error': {'code': code}}}).encode())

    def _created(self):
        return sse.frame(json.dumps({'type': 'response.created', 'response': {
            'id': 'r1', 'model': self.MODEL}}).encode())

    def _completed(self):
        return sse.frame(json.dumps({'type': 'response.completed', 'response': {
            'id': 'r1', 'model': self.MODEL, 'output': [], 'usage': {}}}).encode())

    def _upstream(self, wire):
        return FakeUpstream(200, wire, [('Content-Type', 'text/event-stream')])

    def _failed_attempt(self, code='overloaded'):
        """One setup frame, then the provider's own terminal verdict."""
        return self._upstream(self._created() + self._failed(code))

    def _responder(self, *answers):
        """One answer per upstream connection, then the last one repeats."""
        upcoming = itertools.chain(answers, itertools.repeat(answers[-1]))

        def answer():
            item = next(upcoming)
            if callable(item):
                item = item()
            if isinstance(item, BaseException):  # how a test fails the retry connect
                raise item
            return item
        return answer

    def _stream_response(self, responder, model=MODEL,
                         tools=({'type': 'custom', 'name': 'exec'},)):
        recorded = install_fake(self, responder)
        server = self._server()
        with mock.patch.object(router_mod, 'log_event') as logged:
            response = _post(server.server_port, '/test-token/responses',
                             {'model': model, 'input': [], 'stream': True,
                              'tools': list(tools)})
            self.assertEqual(response.status, 200)
            body = response.read()
        return body, recorded, logged.call_args_list

    def test_provider_failure_before_any_payload_is_retried_once(self):
        body, recorded, logs = self._stream_response(self._responder(
            self._failed_attempt(),
            self._upstream(self._created() + self._completed())))
        self.assertEqual(len(recorded), 2)
        self.assertNotIn(b'response.failed', body)
        self.assertEqual([e['type'] for e in self._events(body)],
                         ['response.created', 'response.completed'])
        retries = [c for c in logs if c.args[0] == 'stream_retry']
        self.assertEqual(len(retries), 1)
        self.assertEqual(retries[0].kwargs['code'], 'overloaded')
        self.assertEqual(retries[0].kwargs['forwarded_delta_bytes'], 0)
        completed = [c for c in logs if c.args[0] == 'request_completed']
        self.assertEqual(completed[0].kwargs['stream_retry'], 1)
        self.assertEqual(completed[0].kwargs['forwarded_delta_bytes'], len(body))
        self.assertEqual(completed[0].kwargs['content_delta_bytes'], 0)
        # A clean second attempt does not inherit the first attempt's verdict.
        self.assertNotIn('terminal_source', completed[0].kwargs)
        self.assertFalse(any(c.args[0] == 'request_failed' for c in logs))

    def test_clean_eof_without_a_terminal_gets_one_router_failure(self):
        body, _, logs = self._stream_response(self._responder(
            self._upstream(self._created())))
        self.assertEqual([e['type'] for e in self._events(body)],
                         ['response.created', 'response.failed'])
        failures = [c for c in logs if c.args[0] == 'request_failed']
        self.assertEqual(failures[0].kwargs['terminal_source'], 'router')
        self.assertEqual(failures[0].kwargs['outcome'], 'unknown')

    def test_hosted_search_failure_before_output_is_not_replayed(self):
        # The provider may have run the search before its first frame, so a
        # replay could run it twice: the client keeps the provider's verdict.
        search = ({'type': 'custom', 'name': 'exec'}, {'type': 'web_search'})
        body, recorded, logs = self._stream_response(self._responder(
            self._failed_attempt(),
            self._upstream(self._created() + self._completed())),
            model='z-ai/glm-5.3', tools=search)
        self.assertEqual(len(recorded), 1)
        self.assertEqual(body, self._created() + self._failed())
        self.assertNotIn('stream_retry', [c.args[0] for c in logs])
        failures = [c for c in logs if c.args[0] == 'request_failed']
        self.assertEqual(failures[0].kwargs['terminal_source'], 'upstream')
        self.assertEqual(failures[0].kwargs['stream_retry'], 0)
        # The rule reads the prepared body, not the model: a row that strips
        # the search tool before sending it keeps the retry.
        _body, recorded, _logs = self._stream_response(self._responder(
            self._failed_attempt(),
            self._upstream(self._created() + self._completed())), tools=search)
        self.assertEqual(len(recorded), 2)

    def test_provider_failure_after_a_delta_is_surfaced_not_retried(self):
        delta = sse.frame(json.dumps({'type': 'response.output_text.delta',
                                      'delta': 'partial answer'}).encode())
        body, recorded, logs = self._stream_response(self._responder(
            self._upstream(self._created() + delta + self._failed())))
        self.assertEqual(len(recorded), 1)
        self.assertIn(b'partial answer', body)
        self.assertEqual(self._events(body)[-1]['type'], 'response.failed')
        failures = [c for c in logs if c.args[0] == 'request_failed']
        self.assertEqual(failures[0].kwargs['terminal_source'], 'upstream')
        self.assertEqual(failures[0].kwargs['forwarded_delta_bytes'], len(body))
        self.assertEqual(failures[0].kwargs['stream_retry'], 0)
        self.assertGreater(failures[0].kwargs['content_delta_bytes'], 0)
        # The per-frame answer marker is loop state, not a log fact.
        self.assertNotIn('answer_frame', failures[0].kwargs)

    def test_deterministic_provider_refusal_is_not_retried(self):
        body, recorded, logs = self._stream_response(
            self._responder(self._failed_attempt('invalid_prompt')))
        self.assertEqual(len(recorded), 1)
        # The merged rewrite replaces the frame with one actionable line.
        # The emitted code stays `invalid_prompt` so Codex ends the turn.
        self.assertEqual(self._events(body)[-1]['response']['error']['code'],
                         'invalid_prompt')
        failures = [c for c in logs if c.args[0] == 'request_failed']
        self.assertEqual(failures[0].kwargs['code'], 'UPSTREAM_INVALID_PROMPT')
        self.assertEqual(failures[0].kwargs['failure_class'], 'final')
        self.assertFalse(any(c.args[0] == 'stream_retry' for c in logs))

    def test_retry_refused_by_the_upstream_ends_the_stream_cleanly(self):
        # The client's status line is already 200 text/event-stream, so a
        # non-200 retry must not put a JSON error body inside the SSE stream.
        refused = FakeUpstream(500, b'{"error": {"code": "private"}}',
                               [('Content-Type', 'application/json')])
        body, recorded, logs = self._stream_response(self._responder(
            self._failed_attempt(), refused))
        self.assertEqual(len(recorded), 2)
        self.assertNotIn(b'private', body)
        events = self._events(body)
        self.assertEqual([e['type'] for e in events],
                         ['response.created', 'response.failed'])
        # The client keeps the provider's own verdict from the first attempt,
        # and the refused retry adds nothing to it.
        self.assertEqual(events[-1]['response']['error']['code'], 'overloaded')
        errors = [c for c in logs if c.args[0] == 'transport_error']
        self.assertEqual(errors[0].kwargs['retry_code'], 'retry_http_500')
        self.assertEqual(errors[0].kwargs['terminal_source'], 'upstream')

    def test_retry_answering_a_different_body_is_not_appended(self):
        json_reply = FakeUpstream(200, b'{"output": []}',
                                  [('Content-Type', 'application/json')])
        body, recorded, logs = self._stream_response(self._responder(
            self._failed_attempt(), json_reply))
        self.assertEqual(len(recorded), 2)
        self.assertNotIn(b'"output"', body)
        errors = [c for c in logs if c.args[0] == 'transport_error']
        self.assertEqual(errors[0].kwargs['retry_code'], 'retry_json_identity')
        self.assertEqual([e['type'] for e in self._events(body)],
                         ['response.created', 'response.failed'])

    def test_retry_connect_failure_keeps_one_terminal_frame(self):
        body, recorded, logs = self._stream_response(self._responder(
            self._failed_attempt(), OSError('connect failed')))
        self.assertEqual(len(recorded), 2)
        self.assertEqual([e['type'] for e in self._events(body)],
                         ['response.created', 'response.failed'])
        errors = [c for c in logs if c.args[0] == 'transport_error']
        self.assertEqual(errors[0].kwargs['terminal_source'], 'upstream')

    def test_retry_holding_a_created_frame_then_dying_still_ends_the_stream(self):
        created = self._created()

        class DyingUpstream(FakeUpstream):
            def read1(self, count):
                data = super().read1(count)
                if data:
                    return data
                raise OSError('upstream closed')

        body, _, logs = self._stream_response(self._responder(
            self._failed_attempt(),
            DyingUpstream(200, created, [('Content-Type', 'text/event-stream')])))
        # The retry died without a verdict of its own, so the router replaces
        # the failed attempt's dropped verdict with its own terminal frame.
        events = self._events(body)
        self.assertEqual([e['type'] for e in events],
                         ['response.created', 'response.failed'])
        self.assertEqual(events[-1]['response']['error']['code'],
                         'UPSTREAM_FAILED')
        failures = [c for c in logs if c.args[0] == 'transport_error']
        self.assertEqual(failures[0].kwargs['terminal_source'], 'router')
        self.assertNotIn(b'overloaded', body)

    def test_both_attempts_failing_leaves_one_verdict(self):
        # The at-most-one-retry and replay-idempotency boundary: two upstream
        # calls, one retry event, one terminal frame for the client.
        body, recorded, logs = self._stream_response(
            self._responder(lambda: self._failed_attempt()))
        self.assertEqual(len(recorded), 2)
        events = self._events(body)
        self.assertEqual([e['type'] for e in events],
                         ['response.created', 'response.failed'])
        # The second attempt's own verdict is the one the client keeps; the
        # first attempt's held verdict was dropped with the retry.
        self.assertEqual(events[-1]['response']['error']['code'], 'overloaded')
        self.assertEqual([c.args[0] for c in logs].count('stream_retry'), 1)
        failures = [c for c in logs if c.args[0] == 'request_failed']
        self.assertEqual(failures[0].kwargs['stream_retry'], 1)
        self.assertEqual(failures[0].kwargs['upstream_code'], 'overloaded')
        self.assertEqual(failures[0].kwargs['terminal_source'], 'upstream')
        self.assertEqual(failures[0].kwargs['forwarded_delta_bytes'], len(body))

    def test_reasoning_before_a_failure_still_retries(self):
        # Reasoning items are replaceable, so a reasoning-capable model keeps
        # the pre-answer retry.
        reasoning = sse.frame(json.dumps({
            'type': 'response.output_item.added',
            'item': {'type': 'reasoning', 'id': 'rs_1'}}).encode())
        body, recorded, logs = self._stream_response(self._responder(
            self._upstream(self._created() + reasoning + self._failed()),
            self._upstream(self._created() + self._completed())))
        self.assertEqual(len(recorded), 2)
        self.assertEqual([e['type'] for e in self._events(body)],
                         ['response.created', 'response.completed'])
        self.assertEqual([c.args[0] for c in logs].count('stream_retry'), 1)

    def test_dead_client_is_not_reported_as_delivered(self):
        class DeadClient:
            def write(self, _):
                raise OSError('client gone')

            def flush(self):
                raise OSError('client gone')

        record = stream_relay.StreamRecord()
        failed = sse.frame(json.dumps({'type': 'response.failed', 'response': {
            'id': 'r1', 'error': {'code': 'overloaded'}}}).encode())
        held = list(stream_errors.events([self._created() + failed], {}))
        self.assertTrue(all(record.hold.take(event) for event in held))
        handler = type('H', (), {'wfile': DeadClient()})()
        self.assertFalse(record.flush(handler))
        self.assertEqual(record.forwarded_bytes, 0)
        # The verdict never left, so the client holds no terminal frame at
        # all; the relay reports that absence rather than claiming upstream.
        self.assertIsNone(record.client_terminal)
        self.assertEqual(record.hold.terminal, 'upstream')
        self.assertEqual(b''.join(record.hold.frames), self._created() + failed)
