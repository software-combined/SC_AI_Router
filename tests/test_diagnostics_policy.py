"""Diagnostics cannot decide repair, replay, or the final request outcome."""
import json
import io
import unittest
from unittest import mock

from ai_router import (attempt_policy, claude, outcome, provider_defs, providers,
                       stream_relay, strip_retry, transport)
from tests.fakes import FakeUpstream
from tests.test_strip_retry import UNNAMED
from tests.test_stream_outcome_recovery import _handler, _metrics, _prepared, _relay


class DiagnosticsPolicyTests(unittest.TestCase):
    def test_response_classification_survives_diagnostics_change_on_all_routes(self):
        responses = b'data: {"type":"response.completed","response":{"output":[]}}\n\n'
        messages = (b'data: {"type":"message_start","message":{"type":"message",'
                    b'"role":"assistant","content":[],"stop_reason":null}}\n\n'
                    b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}\n\n'
                    b'data: {"type":"message_stop"}\n\n')
        routes = (
            (providers.SubscriptionProvider(), 'responses', '/responses', responses),
            (providers.ExternalResponsesProvider(provider_defs.OPENROUTER),
             'responses', '/responses', responses),
            (claude.ClaudeSubscriptionProvider(), 'messages', '/v1/messages', messages),
            (claude.ExternalMessagesProvider(provider_defs.OPENROUTER),
             'messages', '/v1/messages', messages))
        for provider, protocol, path, wire in routes:
            for replacement in ({}, {'protocol': 'invalid', 'path': '/wrong',
                    'stream': False, 'response_kind': 'other', 'response_encoding': 'gzip'}):
                with self.subTest(route=provider.defn.id, protocol=protocol, diagnostics=replacement):
                    metrics = dict(_metrics(provider.defn.id), protocol=protocol, path=path)
                    handler = _handler(io.BytesIO())
                    def change_diagnostics():
                        metrics.clear()
                        metrics.update(replacement)
                    handler.end_headers = change_diagnostics
                    logs = _relay(provider,
                        FakeUpstream(200, wire, [('Content-Type', 'text/event-stream')]),
                        _prepared(provider.defn.host, provider.defn.id), metrics, handler)
                    ledger = next(fields for event, fields in logs if event == 'attempt_ledger')
                    self.assertEqual(handler.wfile.getvalue(), wire)
                    self.assertEqual(ledger['outcome'], outcome.SUCCESS)
                    self.assertEqual(ledger['protocol'], protocol)
                    self.assertEqual(ledger['operation'], path)
                    self.assertTrue(ledger['committed'])

    def test_lost_stream_terminal_is_rendered_after_diagnostics_change(self):
        frame = b'data: {"type":"response.output_text.delta","delta":"synthetic"}\n\n'
        results = {}
        for clear, read_error in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(clear_diagnostics=clear, read_error=read_error):
                metrics = _metrics('openrouter')
                class Response(FakeUpstream):
                    def read1(self, size):
                        data = super().read1(size)
                        if not data and read_error:
                            raise OSError('synthetic upstream read failure')
                        return data
                class Writer(io.BytesIO):
                    def write(self, data):
                        written = super().write(data)
                        if clear:
                            metrics.clear()
                        return written
                writer = Writer()
                logs = _relay(
                    providers.ExternalResponsesProvider(provider_defs.OPENROUTER),
                    Response(200, frame, [('Content-Type', 'text/event-stream')]),
                    _prepared(provider_defs.OPENROUTER.host, 'openrouter'), metrics,
                    _handler(writer))
                ledger = next(fields for event, fields in logs if event == 'attempt_ledger')
                wire = writer.getvalue()
                results[clear, read_error] = wire
                self.assertIn(frame, wire)
                self.assertEqual(wire.count(b'event: response.failed'), 1)
                self.assertEqual(ledger['outcome'], outcome.TRANSPORT if read_error else outcome.UNKNOWN)
                self.assertEqual(ledger['terminal_source'], outcome.ROUTER)
        for read_error in (False, True):
            self.assertEqual(results[False, read_error], results[True, read_error])

    def test_repair_uses_the_captured_protocol_after_diagnostics_change(self):
        provider = providers.ExternalResponsesProvider(provider_defs.OPENROUTER)
        body = json.dumps({'model': 'synthetic', 'input': [], 'store': True}).encode()
        prepared = transport.Prepared(
            provider.defn.host, '/responses', {}, body, set(), provider.defn.id)
        for replacement in ({}, {'protocol': 'messages', 'outcome': 'success'}):
            with self.subTest(diagnostics=replacement):
                metrics = {'protocol': 'responses', 'path': '/responses'}
                ledger = attempt_policy.Ledger(provider, metrics)
                metrics.clear()
                metrics.update(replacement)
                with mock.patch.object(attempt_policy.Ledger, 'send',
                        return_value=(FakeUpstream(200, b''), 0)) as send:
                    result = strip_retry.maybe_retry_unattributable(
                        (400, 'refused', None), FakeUpstream(400, UNNAMED), UNNAMED,
                        metrics, provider, prepared, ledger, lambda *a, **k: None)
                self.assertIsNotNone(result)
                self.assertEqual(send.call_count, 1)
                sent, _, reason = send.call_args.args
                self.assertEqual(reason, attempt_policy.REPAIR)
                self.assertEqual(json.loads(sent.body), {'model': 'synthetic', 'input': []})
                self.assertEqual(ledger.decisions, ['repair:approved'])
                self.assertEqual(json.loads(prepared.body)['store'], True)

    def test_replay_and_final_outcome_use_attempt_state_after_diagnostics_change(self):
        provider = providers.ExternalResponsesProvider(provider_defs.OPENROUTER)
        for category, committed, expected in (
                (outcome.TRANSIENT, False, True),
                (outcome.TRANSIENT, True, False),
                (outcome.SUCCESS, False, False),
                (outcome.UNKNOWN, False, False)):
            for replacement in ({}, {'protocol': 'messages', 'outcome': 'success',
                                      'failure_class': 'transient', 'stream_retry': 0}):
                with self.subTest(category=category, committed=committed, diagnostics=replacement):
                    metrics = {'protocol': 'responses', 'path': '/responses'}
                    ledger = attempt_policy.Ledger(provider, metrics)
                    record = stream_relay.StreamRecord()
                    record.outcome = outcome.Outcome(category, outcome.STREAM, outcome.UPSTREAM)
                    record.forwarded_bytes = 1 if committed else 0
                    metrics.clear()
                    metrics.update(replacement)
                    self.assertEqual(ledger.replay(record, b'{"tools": []}'), expected)
                    ledger.observe(record)
                    self.assertEqual(ledger.outcome.category, category)
                    self.assertEqual(ledger.committed, committed)


if __name__ == '__main__':
    unittest.main()
