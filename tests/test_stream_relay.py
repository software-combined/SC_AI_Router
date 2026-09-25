"""The stream leaf's two decisions: what is answer, and when a retry is safe."""
import unittest

from ai_router import stream_events, stream_relay

# A prepared body offering only a client-run tool: replay is safe.
SAFE = b'{"tools": [{"type": "function", "name": "exec"}]}'


class RetryDecisionTests(unittest.TestCase):
    def _metrics(self, **over):
        metrics = {'terminal_source': 'upstream', 'code': 'UPSTREAM_STREAM_FAILED',
                   'upstream_code': 'server_error', 'failure_class': 'transient'}
        metrics.update(over)
        return metrics

    def test_provider_failure_without_answer_is_retryable(self):
        record = stream_relay.StreamRecord()
        self.assertTrue(stream_relay.retryable_stream_failure(self._metrics(), record, SAFE))

    def test_any_forwarded_byte_blocks_the_retry(self):
        record = stream_relay.StreamRecord()
        # An answer frame is the obvious case; a flushed plumbing frame counts
        # too, because a second response.created after it would give one stream
        # two response identities.
        record.content_delta_bytes = 12
        record.forwarded_bytes = 12
        self.assertFalse(stream_relay.retryable_stream_failure(self._metrics(), record, SAFE))

    def test_flushed_plumbing_alone_blocks_the_retry(self):
        record = stream_relay.StreamRecord()
        record.forwarded_bytes = 70000
        self.assertFalse(stream_relay.retryable_stream_failure(self._metrics(), record, SAFE))

    def test_router_synthesised_frame_is_not_retried(self):
        record = stream_relay.StreamRecord()
        self.assertFalse(stream_relay.retryable_stream_failure(
            self._metrics(terminal_source='router'), record, SAFE))

    def test_deterministic_and_reason_only_failures_are_not_retried(self):
        record = stream_relay.StreamRecord()
        for metrics in (self._metrics(upstream_code='invalid_prompt'),
                        self._metrics(upstream_code=None, code='UPSTREAM_INCOMPLETE'),
                        self._metrics(upstream_code='context_length_exceeded',
                                      code='context_length_exceeded')):
            with self.subTest(metrics=metrics):
                self.assertFalse(stream_relay.retryable_stream_failure(metrics, record, SAFE))

    def test_final_or_context_class_is_not_retried(self):
        record = stream_relay.StreamRecord()
        for failure_class in ('final', 'context'):
            with self.subTest(failure_class=failure_class):
                self.assertFalse(stream_relay.retryable_stream_failure(
                    self._metrics(failure_class=failure_class), record, SAFE))

    def test_hosted_tool_blocks_an_otherwise_retryable_failure(self):
        record = stream_relay.StreamRecord()
        hosted = b'{"tools": [{"type": "function"}, {"type": "web_search"}]}'
        self.assertFalse(stream_relay.retryable_stream_failure(
            self._metrics(), record, hosted))

    def test_missing_class_is_not_retried(self):
        record = stream_relay.StreamRecord()
        metrics = self._metrics()
        del metrics['failure_class']
        self.assertFalse(stream_relay.retryable_stream_failure(metrics, record, SAFE))


class HeldFrameTests(unittest.TestCase):
    class _Client:
        def __init__(self):
            self.wfile = self
            self.written = bytearray()

        def write(self, data):
            self.written += data

        def flush(self):
            pass

    def test_flush_writes_held_bytes_once(self):
        client = self._Client()
        record = stream_relay.StreamRecord()
        held = b'data: {"type": "response.created", "response": {"id": "r"}}\n\n'
        self.assertTrue(record.hold.take(stream_events.StreamEvent(
            held, stream_events.SETUP, 'response.created')))
        record.flush(client)
        self.assertEqual(bytes(client.written), held)
        self.assertEqual(record.forwarded_bytes, len(held))
        record.flush(client)
        self.assertEqual(len(client.written), len(held))

    def test_streamed_metrics_report_every_counter(self):
        record = stream_relay.StreamRecord()
        record.forwarded_bytes, record.content_delta_bytes = 11, 4
        record.reasoning_bytes = 6
        self.assertEqual(stream_relay.streamed_metrics(record),
                         {'forwarded_delta_bytes': 11, 'content_delta_bytes': 4,
                          'reasoning_delta_bytes': 6,
                          'unattributed_delta_bytes': 1})

    def test_clear_terminal_fields_drops_only_the_verdict(self):
        metrics = {'code': 'UPSTREAM_STREAM_FAILED', 'upstream_code': 'server_error',
                   'upstream_error_type': 'server_error',
                   'upstream_provider_code': 'p1', 'failure_class': 'transient',
                   'terminal_event': 'response.failed', 'upstream_reason': 'x',
                   'model': 'z-ai/glm-5.3-flash'}
        stream_relay.clear_terminal_fields(metrics)
        self.assertEqual(metrics, {'model': 'z-ai/glm-5.3-flash'})


if __name__ == '__main__':
    unittest.main()
