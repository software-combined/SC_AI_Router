"""Both Messages routes observe native endings without changing their wire."""
import gzip
import io
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from ai_router import claude, outcome, provider_defs, router, sse, stream_relay, transport
from tests.fakes import FakeUpstream, install_fake
from tests.harness import auth_file, post, start_server, test_state


def frame(kind, **fields):
    return sse.frame(json.dumps({'type': kind, **fields}).encode())


def message(reason=None, content=None):
    return {'type': 'message', 'role': 'assistant', 'id': 'msg_synthetic',
            'content': content or [], 'stop_reason': reason}


START = frame('message_start', message=message())
STOP = frame('message_stop')


def ending(reason):
    return frame('message_delta', delta={'stop_reason': reason}) + STOP


class MessagesStreamContractTests(unittest.TestCase):
    def _observe(self, wire, external=False, kind='sse', encoding='identity', path=None):
        provider = (claude.ExternalMessagesProvider(provider_defs.OPENROUTER) if external
                    else claude.ClaudeSubscriptionProvider())
        headers = [('Content-Type', 'application/json' if kind == 'json'
                    else 'text/event-stream'), ('Content-Encoding', encoding)]
        response = FakeUpstream(200, wire, headers)
        handler = SimpleNamespace(wfile=io.BytesIO())
        metrics = {'protocol': provider_defs.MESSAGES, 'stream': kind == 'sse',
                   'path': path or '/v1/messages', 'response_kind': kind,
                   'response_encoding': encoding}
        record = stream_relay.StreamRecord(transport.ResponseFormat(
            provider_defs.MESSAGES, path or '/v1/messages', kind == 'sse', kind, encoding))
        stream_relay.relay_stream(handler, provider, response, SimpleNamespace(tool_names=set()),
                                  metrics, 0.0, 0.0, record)
        self.assertEqual(handler.wfile.getvalue(), wire)
        self.assertEqual(record.forwarded_bytes, len(wire))
        self.assertFalse(record.hold.frames)
        return record, metrics

    def test_stop_reasons_settle_the_same_outcome_on_both_routes_and_representations(self):
        cases = {'end_turn': outcome.SUCCESS, 'stop_sequence': outcome.SUCCESS,
                 'tool_use': outcome.SUCCESS, 'max_tokens': outcome.INCOMPLETE,
                 'pause_turn': outcome.INCOMPLETE, 'refusal': outcome.REFUSED,
                 'model_context_window_exceeded': outcome.CONTEXT_OVERFLOW,
                 'future_reason': outcome.UNKNOWN}
        for external in (False, True):
            for kind in ('sse', 'json'):
                for reason, expected in cases.items():
                    with self.subTest(external=external, kind=kind, reason=reason):
                        wire = (START + ending(reason) if kind == 'sse'
                                else json.dumps(message(reason)).encode())
                        record, metrics = self._observe(wire, external, kind)
                        self.assertIsNotNone(record.outcome)
                        self.assertEqual(record.outcome.category, expected)
                        self.assertFalse(record.outcome.replayable)
                        if expected == outcome.UNKNOWN:
                            self.assertEqual(metrics['failure_class'], 'unknown')
                        elif expected == outcome.CONTEXT_OVERFLOW:
                            self.assertEqual(metrics['failure_class'], 'context')

    def test_missing_or_malformed_lifecycle_never_becomes_success(self):
        wires = (STOP, START + STOP, ending('end_turn'), START,
                 START + ending(None), START + ending([]),
                 START + START + ending('end_turn'),
                 START + ending('end_turn')[:-1],
                 frame('message_start', message=[]) + ending('end_turn'),
                 START + frame('message_delta', delta=[]) + STOP)
        for wire in wires:
            with self.subTest(wire=wire):
                record, _ = self._observe(wire)
                self.assertTrue(record.outcome is None
                                or record.outcome.category == outcome.UNKNOWN)
        for body in ({}, [], message(), {'type': 'message', 'stop_reason': 'end_turn'},
                     message('end_turn', ['malformed'])):
            with self.subTest(body=body):
                record, _ = self._observe(json.dumps(body).encode(), kind='json')
                self.assertTrue(record.outcome is None
                                or record.outcome.category == outcome.UNKNOWN)

    def test_native_signatures_tool_json_and_unknown_extensions_stay_exact(self):
        wire = START + b''.join((
            frame('ping'),
            frame('content_block_delta', index=0,
                  delta={'type': 'thinking_delta', 'thinking': 'synthetic thought'}),
            frame('content_block_delta', index=0,
                  delta={'type': 'signature_delta', 'signature': 'SYNTHETIC-SIGNATURE'}),
            frame('content_block_start', index=1,
                  content_block={'type': 'redacted_thinking', 'data': 'SYNTHETIC-OPAQUE'}),
            frame('future_extension', signature='SYNTHETIC-FUTURE'),
            frame('content_block_start', index=2,
                  content_block={'type': 'tool_use', 'id': 'toolu_original', 'input': {}}),
            frame('content_block_delta', index=2,
                  delta={'type': 'input_json_delta', 'partial_json': '{"path": "fixture"}'}),
            frame('content_block_stop', index=2))) + ending('tool_use')
        record, _ = self._observe(wire)
        self.assertEqual(record.outcome.category, outcome.SUCCESS)
        self.assertTrue(record.outcome.output)
        self.assertGreater(record.reasoning_bytes, 0)
        self.assertGreater(record.content_delta_bytes, 0)
        self.assertLess(record.content_delta_bytes + record.reasoning_bytes, len(wire))

    def test_overload_is_transient_but_late_frames_cannot_replace_the_first_verdict(self):
        error = frame('error', error={'type': 'overloaded_error', 'message': 'synthetic'})
        for prefix in (b'', START, START + frame('content_block_start', index=0,
                       content_block={'type': 'tool_use', 'id': 'toolu_original', 'input': {}})):
            record, metrics = self._observe(prefix + error + ending('end_turn'))
            self.assertEqual(record.outcome.category, outcome.TRANSIENT)
            self.assertEqual(record.outcome.output, b'tool_use' in prefix)
            self.assertEqual(metrics['terminal_source'], outcome.UPSTREAM)
        record, metrics = self._observe(START + ending('end_turn') + error)
        self.assertEqual(record.outcome.category, outcome.SUCCESS)
        self.assertNotIn('terminal_source', metrics)

    def test_encoded_messages_remain_opaque_and_count_tokens_keeps_its_eof_rule(self):
        wire = gzip.compress(START + ending('end_turn'))
        record, _ = self._observe(wire, encoding='gzip')
        self.assertIsNone(record.outcome)
        self.assertEqual(record.content_delta_bytes, 0)
        record, _ = self._observe(b'{"input_tokens":3}', kind='json',
                                  path='/v1/messages/count_tokens')
        self.assertEqual(record.outcome.category, outcome.SUCCESS)

    def test_legacy_message_error_settles_before_a_later_success(self):
        for error, expected in (({'type': 'overloaded_error'}, outcome.TRANSIENT),
                                ({'code': 'future_error'}, outcome.UNKNOWN)):
            with self.subTest(error=error):
                wire = START + frame('message_error', error=error) + ending('end_turn')
                record, metrics = self._observe(wire)
                self.assertEqual(record.outcome.category, expected)
                self.assertEqual(metrics['terminal_source'], outcome.UPSTREAM)

    def test_partial_native_frames_are_forwarded_before_the_next_read(self):
        handler = SimpleNamespace(wfile=io.BytesIO())
        first = START + b'data: {"type":"message_delta",'
        last = b'"delta":{"stop_reason":"end_turn"}}\n\n' + STOP

        def chunks(*args):
            yield first
            self.assertEqual(handler.wfile.getvalue(), first)
            yield last

        provider = SimpleNamespace(defn=provider_defs.ANTHROPIC, adapt=chunks)
        metrics = {'protocol': provider_defs.MESSAGES, 'path': '/v1/messages',
                   'response_kind': 'sse', 'response_encoding': 'identity'}
        record = stream_relay.StreamRecord(transport.ResponseFormat(
            provider_defs.MESSAGES, '/v1/messages', True, 'sse', 'identity'))
        stream_relay.relay_stream(handler, provider, None, SimpleNamespace(tool_names=set()),
                                  metrics, 0.0, 0.0, record)
        self.assertEqual(handler.wfile.getvalue(), first + last)
        self.assertEqual(record.outcome.category, outcome.SUCCESS)

    def test_oversized_terminal_requires_complete_json_and_valid_lifecycle(self):
        valid = START + ending('end_turn')
        invalid = valid[:-2] + b' trailing-garbage\n\n'
        with mock.patch.object(sse, 'MAX_FRAME_BYTES', 16):
            record, _ = self._observe(valid)
            self.assertEqual(record.outcome.category, outcome.SUCCESS)
            record, _ = self._observe(invalid)
            self.assertIsNone(record.outcome)

    def test_json_over_the_observation_bound_stays_lossless_and_unknown(self):
        wire = json.dumps(message('end_turn')).encode()
        with mock.patch.object(transport, 'MAX_UPSTREAM_BODY', 16):
            record, _ = self._observe(wire, kind='json')
        self.assertIsNone(record.outcome)

    def test_routed_messages_failures_keep_bounded_sends_and_one_logged_verdict(self):
        for model, expected_host in (('claude-sonnet-5', provider_defs.ANTHROPIC.host),
                                     ('deepseek/deepseek-v4.1-flash-1017', provider_defs.OPENROUTER.host)):
            with self.subTest(model=model):
                wire = START + frame('error', error={'type': 'overloaded_error'})
                sends = install_fake(self, lambda: FakeUpstream(
                    200, wire, [('Content-Type', 'text/event-stream')]))
                server = start_server(test_state(auth_file(self)))
                self.addCleanup(server.server_close)
                self.addCleanup(server.shutdown)
                with mock.patch.object(router, 'log_event') as logged:
                    response = post(server.server_port, '/test-token/v1/messages',
                                    {'model': model, 'messages': [], 'stream': True},
                                    {'Authorization': 'Bearer subscription-fixture'})
                    self.assertEqual(response.read(), wire)
                self.assertEqual(len(sends), 2 if expected_host == provider_defs.OPENROUTER.host else 1)
                self.assertEqual(sends[0][0], expected_host)
                ledger = [call.kwargs for call in logged.call_args_list
                          if call.args[0] == 'attempt_ledger']
                self.assertEqual(len(ledger), 1)
                self.assertEqual(ledger[0]['outcome'], outcome.TRANSIENT)
                self.assertTrue(ledger[0]['committed'])
                if expected_host == provider_defs.OPENROUTER.host:
                    self.assertNotIn('subscription-fixture', str(sends[0][4]))


if __name__ == '__main__':
    unittest.main()
