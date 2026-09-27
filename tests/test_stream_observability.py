"""Focused outcome, delivery and raw-accounting regressions."""
import gzip
import io
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from compression import zstd

from ai_router import (attempt_policy, ingress, outcome, provider_defs, providers,
                       relay, sse, stream_relay, transport)
from tests.fakes import FakeUpstream
from tests.test_stream_outcome_recovery import (
    _defn, _handler, _metrics, _prepared, _provider, _relay)
from tests.test_strip_retry import StripRetryRelayTests


class RawAccountingTests(unittest.TestCase):
    def _raw(self, *frames):
        client = SimpleNamespace(wfile=io.BytesIO())
        provider = SimpleNamespace(
            defn=SimpleNamespace(id='openai', dialect=provider_defs.DIALECT_OPENAI),
            adapt=lambda *args: iter(frames))
        metrics = {'protocol': provider_defs.RESPONSES, 'response_kind': 'sse',
                   'response_encoding': 'identity', 'model': 'm'}
        record = stream_relay.StreamRecord()
        stream_relay.relay_stream(
            client, provider, object(), SimpleNamespace(tool_names=set()), metrics,
            0.0, 0.0, record)
        record.flush(client)
        return record

    def test_raw_setup_is_not_counted_as_model_output(self):
        setup = b'data: {"type":"response.created","response":{"id":"r","output":[]}}\n\n'
        completed = b'data: {"type":"response.completed","response":{"output":[]}}\n\n'
        record = self._raw(setup + completed)
        self.assertFalse(record.outcome.output)
        self.assertEqual(record.content_delta_bytes, 0)
        ledger = attempt_policy.Ledger(
            providers.ExternalResponsesProvider(provider_defs.OPENROUTER),
            {'protocol': provider_defs.RESPONSES})
        self.assertFalse(ledger.replay(record, b'{"tools":[]}'))
        self.assertFalse(ledger.outcome.output)

    def test_raw_text_delta_is_counted_as_model_output(self):
        delta = b'data: {"type":"response.output_text.delta","delta":"hi"}\n\n'
        completed = b'data: {"type":"response.completed","response":{"output":[]}}\n\n'
        record = self._raw(delta + completed)
        self.assertGreater(record.content_delta_bytes, 0)
        ledger = attempt_policy.Ledger(
            providers.ExternalResponsesProvider(provider_defs.OPENROUTER),
            {'protocol': provider_defs.RESPONSES})
        self.assertFalse(ledger.replay(record, b'{"tools":[]}'))
        self.assertTrue(ledger.outcome.output)


class DeliveryAndStatusTests(unittest.TestCase):
    def test_held_frame_client_disconnect_is_cancellation(self):
        created = sse.frame(json.dumps({
            'type': 'response.created', 'response': {'id': 'r1'}}).encode())
        completed = sse.frame(json.dumps({
            'type': 'response.completed', 'response': {'output': []}}).encode())

        class Writer:
            def write(self, data):
                raise BrokenPipeError('client gone')

            def flush(self):
                pass

        provider = _provider(
            _defn('openai', provider_defs.SUBSCRIPTION,
                  provider_defs.DIALECT_OPENAI), (created, completed))
        with mock.patch.object(relay.transport, 'describe_location',
                               return_value='socketserver.py:1:write'):
            logs = _relay(
                provider, FakeUpstream(200, created + completed,
                                      [('Content-Type', 'text/event-stream')]),
                _prepared('api.example.test', 'openai'), _metrics('openai'),
                _handler(Writer()))
        self.assertIn('client_disconnected', [event for event, _ in logs])
        failure = [fields for event, fields in logs
                   if event == 'client_disconnected'][-1]
        self.assertEqual(failure['outcome'], outcome.CANCELLED)
        self.assertEqual(failure['outcome_source'], outcome.CLIENT)

    def test_error_body_read_failure_keeps_status_phase(self):
        case = StripRetryRelayTests()
        case.setUp()
        try:
            with mock.patch.object(relay.transport, 'read_capped',
                                   side_effect=ValueError('unreadable error body')):
                _, events, _, _ = case._relay(
                    [(418, b'x')], b'{"model":"m","input":[]}')
        finally:
            case.doCleanups()
        fields = next(fields for event, fields in events
                      if event == 'attempt_ledger')
        self.assertEqual(fields['outcome_phase'], 'status')
        failure = next(fields for event, fields in events
                       if event == 'transport_error')
        self.assertEqual(failure['status'], 418)

    def test_raw_error_body_value_error_preserves_provider_verdict(self):
        case = StripRetryRelayTests()
        case.setUp()
        try:
            _, events, _, _ = case._relay(
                [(418, b'upstream sent an unrecognised error body')],
                b'{"model":"m","input":[]}',
                writer_error=ValueError('I/O operation on closed file'))
        finally:
            case.doCleanups()
        self.assertIn('transport_error', [event for event, _ in events])
        ledger = next(fields for event, fields in events if event == 'attempt_ledger')
        self.assertEqual((ledger['outcome'], ledger['outcome_phase'],
                          ledger['outcome_source'], ledger['outcome_code']),
                         (outcome.UNKNOWN, outcome.STATUS, outcome.UPSTREAM, None))


class ErrorDeliveryTests(unittest.TestCase):
    def test_closed_error_writer_preserves_the_provider_verdict(self):
        body = json.dumps({'error': {
            'error_type': 'invalid_prompt',
            'message': 'Provider returned error'}}).encode()

        class Writer:
            def __init__(self):
                self.written = []
            def write(self, data):
                self.written.append(data)
                return len(data)
            def flush(self):
                raise ValueError('I/O operation on closed file')

        writer = Writer()
        error_calls = []
        handler = SimpleNamespace(
            server=SimpleNamespace(
                state={'token': 'token'},
                credentials=SimpleNamespace(key_rejected=lambda provider: False),
                lock=None, served_models={}),
            path='/token/responses', wfile=writer,
            send_response=lambda *args: None,
            send_header=lambda *args: None, end_headers=lambda: None,
            close_connection=False, response_committed=False)
        handler.send_json = (
            lambda status, obj, headers=None:
            ingress.send_json(handler, status, obj, headers))
        handler.error = (
            lambda err, **kwargs:
            error_calls.append(err) or handler.send_json(err.status, err.body()))
        prepared = _prepared('openrouter.ai', 'openrouter')
        logs = []
        provider = _provider(
            _defn('openrouter', provider_defs.EXTERNAL,
                  provider_defs.DIALECT_OPENROUTER), ())
        with mock.patch.object(
                relay.strip_retry, 'post_with_retry',
                return_value=(FakeUpstream(
                    400, body, [('Content-Type', 'application/json')]),
                    0.0, prepared, body)):
            relay.relay(
                handler, provider, prepared, _metrics('openrouter'), 0.0,
                log_event=lambda event, **fields: logs.append((event, fields)))

        self.assertEqual(len(error_calls), 1)
        self.assertNotIn('transport_error', [event for event, _ in logs])
        ledger = [fields for event, fields in logs if event == 'attempt_ledger'][-1]
        self.assertEqual((ledger['outcome'], ledger['outcome_phase'],
                          ledger['outcome_source'], ledger['outcome_code']),
                         (outcome.REFUSED, outcome.STATUS, outcome.UPSTREAM,
                          'invalid_prompt'))


class EncodedToolStreamTests(unittest.TestCase):
    def test_full_relay_forwards_encoded_tool_stream_without_adaptation(self):
        raw = b'data: {"type":"response.completed","response":{"output":[]}}\n\n'
        for encode, encoding in ((gzip.compress, 'gzip'),
                                 (zstd.compress, 'zstd')):
            with self.subTest(encoding=encoding):
                body = encode(raw)

                class Response:
                    status = 200
                    def __init__(self):
                        self.raw = body
                    def getheaders(self):
                        return [('Content-Type', 'text/event-stream'),
                                ('Content-Encoding', encoding)]
                    def getheader(self, name, default=None):
                        return dict(self.getheaders()).get(name.title(), default)
                    def read1(self, count):
                        data, self.raw = self.raw[:count], self.raw[count:]
                        return data

                defn = SimpleNamespace(
                    id='openai', kind=provider_defs.SUBSCRIPTION,
                    dialect=provider_defs.DIALECT_OPENAI,
                    caches_deterministic_refusals=lambda: False,
                    opens_key_window_on_auth_failure=lambda: False,
                    sends_context_error_frame=lambda: False)
                provider = SimpleNamespace(
                    defn=defn,
                    adapt=lambda *args: self.fail('encoded raw stream was adapted'))
                writer = io.BytesIO()
                handler = SimpleNamespace(
                    server=SimpleNamespace(credentials=SimpleNamespace(
                        key_rejected=lambda provider: False), lock=None,
                        served_models={}),
                    wfile=writer, send_response=lambda *args: None,
                    send_header=lambda *args: None, end_headers=lambda: None,
                    close_connection=False,
                    error=lambda *args, **kwargs: self.fail('relay emitted an error'))
                prepared = transport.Prepared(
                    'chatgpt.com', '/backend-api/codex/responses', {},
                    b'{"input":[],"tools":[{"type":"function","name":"exec"}]}',
                    {'exec'}, 'openai')
                metrics = {'provider': 'openai',
                           'protocol': provider_defs.RESPONSES,
                           'model': 'm', 'path': '/responses', 'stream': True}
                events = []
                with mock.patch.object(
                        relay.strip_retry, 'post_with_retry',
                        return_value=(Response(), 0.0, prepared, b'')):
                    relay.relay(
                        handler, provider, prepared, metrics, 0.0,
                        log_event=lambda event, **fields: events.append(event))
                self.assertEqual(writer.getvalue(), body)
                self.assertNotIn('transport_error', events)


if __name__ == '__main__':
    unittest.main()
