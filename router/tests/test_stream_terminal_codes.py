"""Shared terminal-code mapping for raw and normalized streams."""
import json
import io
import unittest
from types import SimpleNamespace

from ai_router import outcome, provider_defs, sse, stream_errors, stream_relay, transport


class TerminalCodeTests(unittest.TestCase):
    def test_raw_terminal_code_matches_normalized_policy(self):
        cases = (
            ({'type': 'response.failed', 'response': {'error': {
                'error_type': 'invalid_request', 'code': 'invalid_request'}}},
             'UPSTREAM_STREAM_FAILED'),
            ({'type': 'response.failed', 'response': {'error': {
                'code': 'invalid_prompt'}}}, 'UPSTREAM_INVALID_PROMPT'),
            ({'type': 'error', 'code': 'invalid_prompt'},
             'UPSTREAM_INVALID_PROMPT'),
            ({'type': 'response.failed', 'response': {'error': {
                'code': 'context_length_exceeded'}}}, 'context_length_exceeded'),
            ({'type': 'response.incomplete', 'response': {
                'incomplete_details': {'reason': 'max_output_tokens'}}},
             'UPSTREAM_INCOMPLETE'),
        )
        for event, expected in cases:
            with self.subTest(expected=expected):
                frame = sse.frame(json.dumps(event).encode())
                raw_metrics = {'protocol': provider_defs.RESPONSES,
                               'response_kind': 'sse',
                               'response_encoding': 'identity'}
                list(stream_relay._raw_events([frame], raw_metrics, provider_defs.RESPONSES))
                normalized_metrics = {}
                list(stream_errors.events([frame], normalized_metrics))
                self.assertEqual(raw_metrics['code'], expected)
                self.assertEqual(normalized_metrics['code'], expected)
                self.assertEqual(raw_metrics.get('upstream_reason'),
                                 normalized_metrics.get('upstream_reason'))

    def test_incomplete_failure_class_matches_raw_and_normalized(self):
        frame = sse.frame(json.dumps({'type': 'response.incomplete', 'response': {
            'incomplete_details': {'reason': 'max_output_tokens'}}}).encode())
        raw_metrics = {'protocol': provider_defs.RESPONSES,
                       'response_kind': 'sse',
                       'response_encoding': 'identity'}
        list(stream_relay._raw_events([frame], raw_metrics, provider_defs.RESPONSES))
        normalized_metrics = {}
        list(stream_errors.events([frame], normalized_metrics))
        self.assertEqual(raw_metrics['failure_class'], 'final')
        self.assertEqual(normalized_metrics['failure_class'], 'final')
        self.assertEqual(raw_metrics['upstream_reason'], 'max_output_tokens')
        self.assertEqual(normalized_metrics['upstream_reason'], 'max_output_tokens')


class RawTerminalOwnershipTests(unittest.TestCase):
    def _raw(self, frames, protocol):
        client = SimpleNamespace(wfile=io.BytesIO())
        provider = SimpleNamespace(
            defn=(provider_defs.ANTHROPIC if protocol == provider_defs.MESSAGES
                  else provider_defs.OPENAI),
            adapt=lambda *args: iter((frames,)))
        metrics = {'protocol': protocol, 'response_kind': 'sse',
                   'response_encoding': 'identity', 'model': 'm'}
        operation = '/v1/messages' if protocol == provider_defs.MESSAGES else '/v1/responses'
        record = stream_relay.StreamRecord(transport.ResponseFormat(
            protocol, operation, True, 'sse', 'identity'))
        stream_relay.relay_stream(
            client, provider, object(), SimpleNamespace(tool_names=set()), metrics,
            0.0, 0.0, record)
        record.flush(client)
        return client.wfile.getvalue(), metrics, record

    def test_responses_first_terminal_keeps_ownership(self):
        completed = b'data: {"type":"response.completed","response":{"output":[]}}\n\n'
        failed = b'data: {"type":"response.failed","response":{"error":{"code":"bad"}}}\n\n'
        written, metrics, record = self._raw(completed + failed, provider_defs.RESPONSES)
        self.assertEqual(written, completed + failed)
        self.assertEqual(record.outcome.category, outcome.SUCCESS)
        self.assertIsNone(record.client_terminal)
        self.assertNotIn('terminal_source', metrics)
        self.assertNotIn('code', metrics)

    def test_messages_first_terminal_keeps_ownership(self):
        stopped = (b'data: {"type":"message_start","message":{"type":"message",'
                   b'"role":"assistant","content":[],"stop_reason":null}}\n\n'
                   b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}\n\n'
                   b'data: {"type":"message_stop"}\n\n')
        failed = b'data: {"type":"message_error","error":{"code":"bad"}}\n\n'
        written, metrics, record = self._raw(stopped + failed, provider_defs.MESSAGES)
        self.assertEqual(written, stopped + failed)
        self.assertEqual(record.outcome.category, outcome.SUCCESS)
        self.assertIsNone(record.client_terminal)
        self.assertNotIn('terminal_source', metrics)
        self.assertNotIn('code', metrics)


if __name__ == '__main__':
    unittest.main()
