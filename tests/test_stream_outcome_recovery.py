"""Post-terminal stream recovery keeps the terminal's own outcome."""
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from ai_router import (attempt_policy, outcome, provider_defs, providers, relay, sse,
                       stream_errors, stream_relay, transport)
from tests.fakes import FakeUpstream


def _defn(id, kind, dialect):
    return SimpleNamespace(
        id=id, kind=kind, dialect=dialect,
        caches_deterministic_refusals=lambda: False,
        opens_key_window_on_auth_failure=lambda: False,
        sends_context_error_frame=lambda: False)


def _provider(defn, frames, error=None):
    def adapt(response, tool_names, metrics):
        yield from frames
        if error is not None:
            raise error
    return SimpleNamespace(defn=defn, adapt=adapt)


def _handler(writer):
    return SimpleNamespace(
        server=SimpleNamespace(
            credentials=SimpleNamespace(key_rejected=lambda provider: False),
            lock=None, served_models={}),
        wfile=writer, send_response=lambda *args: None,
        send_header=lambda *args: None, end_headers=lambda: None,
        close_connection=False, error=lambda *args, **kwargs: None)


def _prepared(host, provider):
    return transport.Prepared(host, '/responses', {}, b'{}', set(), provider)


def _metrics(provider):
    return {'provider': provider, 'protocol': provider_defs.RESPONSES,
            'model': 'm', 'path': '/responses', 'stream': True}


def _relay(provider, response, prepared, metrics, handler):
    logs = []
    with mock.patch.object(
            relay.strip_retry, 'post_with_retry',
            return_value=(response, 0.0, prepared, b'')):
        relay.relay(
            handler, provider, prepared, metrics, 0.0,
            log_event=lambda event, **fields: logs.append((event, fields)))
    return logs


class LateTerminalReadTests(unittest.TestCase):
    def _run(self, frame, expected_event, expected_category, terminal_source,
             content_type='text/event-stream'):
        provider = _provider(
            _defn('openai', provider_defs.SUBSCRIPTION,
                  provider_defs.DIALECT_OPENAI),
            (frame,), OSError('late upstream read'))
        response = FakeUpstream(200, frame, [('Content-Type', content_type)])
        prepared = _prepared('api.example.test', 'openai')
        logs = _relay(
            provider, response, prepared, _metrics('openai'),
            _handler(SimpleNamespace(write=lambda data: None, flush=lambda: None)))

        terminal_logs = [fields for event, fields in logs
                         if event in ('request_completed', 'request_failed',
                                      'transport_error')]
        self.assertEqual([event for event, _ in logs
                          if event in ('request_completed', 'request_failed',
                                       'transport_error')],
                         [expected_event])
        self.assertEqual(terminal_logs[-1]['outcome'], expected_category)
        self.assertEqual(terminal_logs[-1].get('terminal_source'), terminal_source)
        self.assertEqual([fields for event, fields in logs
                          if event == 'attempt_ledger'][-1]['outcome'],
                         expected_category)

    def test_success_terminal_survives_late_read_error(self):
        frame = sse.frame(b'{"type":"response.completed","response":{"output":[]}}')
        self._run(frame, 'request_completed', outcome.SUCCESS, None)

    def test_provider_failure_terminal_survives_late_read_error(self):
        frame = sse.frame(b'{"type":"response.failed","response":{"error":{"code":"overloaded"}}}')
        self._run(frame, 'transport_error', outcome.TRANSIENT,
                  stream_errors.TERMINAL_FROM_UPSTREAM)

    def test_non_sse_success_waits_for_eof(self):
        self._run(b'{"output": []}', 'transport_error', outcome.TRANSPORT, None,
                  content_type='application/json')


class RawOverflowHintTests(unittest.TestCase):
    def _events(self, native, protocol):
        frame = sse.frame(json.dumps({'type': native}).encode()
                          + b' ' + b'x' * sse.MAX_FRAME_BYTES)
        metrics = {'protocol': protocol, 'response_kind': 'sse',
                   'response_encoding': 'identity'}
        return frame, list(stream_relay._raw_events([frame], metrics))

    def test_protocol_mismatched_overflow_hints_are_not_observed(self):
        for native in ('message_error', 'message_stop'):
            with self.subTest(native=native):
                frame, events = self._events(native, provider_defs.RESPONSES)
                self.assertEqual(b''.join(event.frame for event in events), frame)
                self.assertTrue(all(event.outcome is None for event in events))

    def test_malformed_messages_stop_hint_cannot_supply_a_verdict(self):
        frame, events = self._events('message_stop', provider_defs.MESSAGES)
        self.assertEqual(b''.join(event.frame for event in events), frame)
        self.assertTrue(all(event.outcome is None for event in events))

    def test_payload_text_cannot_synthesize_a_raw_terminal(self):
        frame = sse.frame(json.dumps({
            'type': 'response.output_text.delta',
            'delta': '{"type":"response.completed"}'}).encode()
            + b' ' + b'x' * sse.MAX_FRAME_BYTES)
        failed = sse.frame(json.dumps({'type': 'response.failed', 'response': {
            'error': {'code': 'overloaded'}}}).encode())
        metrics = {'protocol': provider_defs.RESPONSES, 'response_kind': 'sse',
                   'response_encoding': 'identity'}
        events = list(stream_relay._raw_events([frame, failed], metrics))
        self.assertEqual(b''.join(event.frame for event in events), frame + failed)
        self.assertTrue(all(event.outcome is None for event in events[:-1]))
        self.assertEqual(events[-1].outcome.category, outcome.TRANSIENT)


class TerminalWriteTests(unittest.TestCase):
    def test_held_terminal_flush_failure_is_transport(self):
        created = sse.frame(json.dumps({
            'type': 'response.created', 'response': {'id': 'r1'}}).encode())
        failed = sse.frame(json.dumps({'type': 'response.failed', 'response': {
            'error': {'code': 'overloaded'}}}).encode())

        class Writer:
            def __init__(self):
                self.written = []

            def write(self, data):
                if b'overloaded' in data:
                    raise OSError('held terminal write failed')
                self.written.append(data)

            def flush(self):
                pass

        writer = Writer()
        response = FakeUpstream(200, created + failed,
                                [('Content-Type', 'text/event-stream')])
        prepared = transport.Prepared(
            'openrouter.ai', '/responses', {},
            b'{"tools":[{"type":"web_search"}]}', set(), 'openrouter')
        logs = _relay(
            _provider(_defn('openrouter', provider_defs.EXTERNAL,
                            provider_defs.DIALECT_OPENROUTER),
                      (created, failed)),
            response, prepared, _metrics('openrouter'), _handler(writer))

        self.assertEqual([event for event, _ in logs
                          if event in ('request_completed', 'request_failed',
                                       'transport_error')],
                         ['transport_error'])
        self.assertNotIn(b'response.failed', b''.join(writer.written))
        failure = [fields for event, fields in logs if event == 'transport_error'][-1]
        self.assertEqual(failure['outcome'], outcome.TRANSPORT)
        self.assertIsNone(failure.get('terminal_source'))
        ledger = [fields for event, fields in logs if event == 'attempt_ledger'][-1]
        self.assertEqual(ledger['outcome'], outcome.TRANSPORT)

    def test_short_terminal_write_is_transport(self):
        completed = sse.frame(json.dumps({
            'type': 'response.completed', 'response': {'output': []}}).encode())

        class Writer:
            def __init__(self):
                self.written = []

            def write(self, data):
                if b'response.completed' in data:
                    self.written.append(data[:1])
                    return 1
                self.written.append(data)
                return len(data)

            def flush(self):
                pass

        writer = Writer()
        response = FakeUpstream(200, completed,
                                [('Content-Type', 'text/event-stream')])
        prepared = _prepared('openrouter.ai', 'openrouter')
        logs = _relay(
            _provider(_defn('openrouter', provider_defs.EXTERNAL,
                            provider_defs.DIALECT_OPENROUTER), (completed,)),
            response, prepared, _metrics('openrouter'), _handler(writer))

        self.assertEqual([event for event, _ in logs
                          if event in ('request_completed', 'request_failed',
                                       'transport_error')],
                         ['transport_error'])
        self.assertNotIn(b'response.failed', b''.join(writer.written))
        failure = [fields for event, fields in logs if event == 'transport_error'][-1]
        self.assertEqual(failure['outcome'], outcome.TRANSPORT)
        self.assertIsNone(failure.get('terminal_source'))
        ledger = [fields for event, fields in logs if event == 'attempt_ledger'][-1]
        self.assertEqual(ledger['outcome'], outcome.TRANSPORT)

    def test_unheld_success_terminal_is_settled_only_after_delivery(self):
        completed = sse.frame(json.dumps({
            'type': 'response.completed', 'response': {'output': []}}).encode())

        class Writer:
            def __init__(self):
                self.written = []

            def write(self, data):
                if b'response.completed' in data:
                    raise OSError('client write failed')
                self.written.append(data)

            def flush(self):
                pass

        writer = Writer()
        response = FakeUpstream(200, completed,
                                [('Content-Type', 'text/event-stream')])
        prepared = _prepared('openrouter.ai', 'openrouter')
        logs = _relay(
            _provider(_defn('openrouter', provider_defs.EXTERNAL,
                            provider_defs.DIALECT_OPENROUTER), (completed,)),
            response, prepared, _metrics('openrouter'), _handler(writer))

        sent = b''.join(writer.written)
        self.assertNotIn(b'response.completed', sent)
        self.assertNotIn(b'response.failed', sent)
        self.assertEqual([event for event, _ in logs
                          if event in ('request_completed', 'request_failed',
                                       'transport_error')],
                         ['transport_error'])
        failure = [fields for event, fields in logs if event == 'transport_error'][-1]
        self.assertEqual(failure['outcome'], outcome.TRANSPORT)
        self.assertIsNone(failure.get('terminal_source'))
        ledger = [fields for event, fields in logs if event == 'attempt_ledger'][-1]
        self.assertEqual(ledger['outcome'], outcome.TRANSPORT)

    def test_unheld_terminal_is_attributed_only_after_successful_write(self):
        answer = sse.frame(json.dumps({
            'type': 'response.output_text.delta', 'delta': 'answer'}).encode())
        failed = sse.frame(json.dumps({'type': 'response.failed', 'response': {
            'error': {'code': 'overloaded'}}}).encode())

        class Writer:
            def __init__(self):
                self.written = []

            def write(self, data):
                if b'overloaded' in data:
                    raise BrokenPipeError('client gone')
                self.written.append(data)

            def flush(self):
                pass

        writer = Writer()
        response = FakeUpstream(200, answer + failed,
                                [('Content-Type', 'text/event-stream')])
        prepared = _prepared('openrouter.ai', 'openrouter')
        logs = _relay(
            _provider(_defn('openrouter', provider_defs.EXTERNAL,
                            provider_defs.DIALECT_OPENROUTER),
                      (answer, failed)),
            response, prepared, _metrics('openrouter'), _handler(writer))

        sent = b''.join(writer.written)
        self.assertIn(b'answer', sent)
        self.assertNotIn(b'overloaded', sent)
        self.assertNotIn(b'UPSTREAM_FAILED', sent)
        failures = [fields for event, fields in logs if event == 'transport_error']
        self.assertIsNone(failures[-1].get('terminal_source'))
        ledger = [fields for event, fields in logs if event == 'attempt_ledger'][-1]
        self.assertEqual(ledger['outcome'], outcome.TRANSPORT)


class NormalizedLateErrorTests(unittest.TestCase):
    def test_success_terminal_is_not_followed_by_a_second_terminal(self):
        completed = sse.frame(json.dumps({
            'type': 'response.completed', 'response': {'output': []}}).encode())

        written = []
        writer = SimpleNamespace(write=lambda data: written.append(data),
                                 flush=lambda: None)
        response = FakeUpstream(200, completed,
                                [('Content-Type', 'text/event-stream')])
        prepared = _prepared('openrouter.ai', 'openrouter')
        logs = _relay(
            _provider(_defn('openrouter', provider_defs.EXTERNAL,
                            provider_defs.DIALECT_OPENROUTER),
                      (completed,), OSError('late producer error')),
            response, prepared, _metrics('openrouter'), _handler(writer))

        self.assertEqual([event for event, _ in logs
                          if event in ('request_completed', 'request_failed',
                                       'transport_error')],
                         ['request_completed'])
        self.assertFalse(any(event == 'transport_error' for event, _ in logs))
        self.assertEqual([fields for event, fields in logs
                          if event == 'attempt_ledger'][-1]['outcome'],
                         outcome.SUCCESS)
        sent = b''.join(written)
        self.assertEqual(sent.count(b'response.completed'), 1)
        self.assertNotIn(b'response.failed', sent)


class BoundedRetryBodyTests(unittest.TestCase):
    def test_large_non_200_retry_body_is_not_read_whole(self):
        class Response:
            status = 500

            def __init__(self):
                self.calls = []
                self.closed = False

            def read1(self, count):
                self.calls.append(count)
                return b'x' * count

            def close(self):
                self.closed = True

        response = Response()
        prepared = transport.Prepared(
            'api.example.test', '/responses', {}, b'{}', set(), 'openai')
        ledger = attempt_policy.Ledger(
            providers.ExternalResponsesProvider(provider_defs.OPENROUTER),
            {'protocol': provider_defs.RESPONSES})
        metrics = {}
        with mock.patch.object(attempt_policy.Ledger, 'send',
                               return_value=(response, 1.0)):
            with self.assertRaises(ValueError):
                ledger.reopen(prepared, metrics, 0.0)
        self.assertEqual(metrics['retry_code'], 'retry_http_500')
        self.assertTrue(response.closed)
        self.assertTrue(all(count == 65536 for count in response.calls))
        self.assertLessEqual(sum(response.calls),
                             transport.ERROR_BODY_LIMIT + 65536)


if __name__ == '__main__':
    unittest.main()
