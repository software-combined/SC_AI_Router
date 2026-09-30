"""Probe failures retain their cause, never raw client/provider error content."""
import json
import unittest

from tools.appserver_probe import failure_shape, request_failure_shape


class HandoffDiagnosticsTests(unittest.TestCase):
    def test_status_null_stream_cause_is_classified_without_private_details(self):
        event = {'method': 'error', 'params': {'threadId': 'synthetic', 'turnId': 'turn', 'willRetry': True}}
        for detail, cause in (
            ('Incomplete response returned, reason: max_output_tokens', 'output_cap'),
            ('failed to parse ResponseCompleted: missing field', 'completion_schema'),
            ('stream closed before response.completed', 'missing_completion'),
            ('idle timeout waiting for SSE', 'idle_timeout'),
            ('unknown failure', 'unclassified')):
            with self.subTest(cause=cause):
                failure = {'message': 'Reconnecting', 'additionalDetails': detail + ' SYNTH_PRIVATE https://private.invalid',
                           'codexErrorInfo': {'responseStreamDisconnected': {'httpStatusCode': None}}}
                shape = failure_shape(event, failure)
                self.assertEqual(shape['cause'], cause)
                self.assertTrue(shape['will_retry'])
                self.assertEqual(shape['code'], {'responseStreamDisconnected': {'httpStatusCode': None}})
                self.assertNotIn('SYNTH_PRIVATE', json.dumps(shape))
                self.assertNotIn('private.invalid', json.dumps(shape))

    def test_unknown_client_and_upstream_details_are_not_retained(self):
        shape = failure_shape({'method': 'error', 'params': {}},
                              {'codexErrorInfo': {'other': 'SYNTH_PRIVATE'}})
        self.assertEqual(shape['code'], 'other')
        self.assertEqual(request_failure_shape({'code': 'SYNTH_PRIVATE', 'upstream_reason': 'SYNTH_PRIVATE',
            'status': 'SYNTH_PRIVATE', 'terminal_event': 'SYNTH_PRIVATE'}),
            {'code': 'other', 'reason': 'other', 'status': None, 'terminal': 'other'})
        self.assertEqual(request_failure_shape({'code': 'UPSTREAM_INCOMPLETE', 'upstream_reason': 'max_output_tokens',
            'status': 200, 'terminal_event': 'response.incomplete'}),
            {'code': 'UPSTREAM_INCOMPLETE', 'reason': 'max_output_tokens', 'status': 200, 'terminal': 'response.incomplete'})
