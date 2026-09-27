"""A nullable Responses error is not a failed tool turn."""
import io
import json
import unittest
from unittest import mock

from ai_router import attempt_policy, outcome, provider_defs, sse, stream_errors
from tests.fakes import FakeUpstream
from tests.test_stream_outcome_recovery import (
    _defn, _handler, _metrics, _prepared, _provider, _relay)


class CompletedResponseErrorTests(unittest.TestCase):
    def test_nullable_error_preserves_completed_tool_turn_on_both_routes(self):
        item = {'type': 'function_call', 'id': 'fc_probe', 'call_id': 'call_probe',
                'name': 'echo_probe', 'arguments': '{"value":"probe"}'}
        done = sse.frame(json.dumps({'type': 'response.output_item.done',
                                    'output_index': 0, 'item': item}).encode())
        for route, kind, dialect in (
                ('openrouter', provider_defs.EXTERNAL, provider_defs.DIALECT_OPENROUTER),
                ('openai', provider_defs.SUBSCRIPTION, provider_defs.DIALECT_OPENAI)):
            for outer_null in (False, True):
                with self.subTest(route=route, outer_null=outer_null):
                    terminal = {'type': 'response.completed', 'response': {
                        'id': 'resp_probe', 'status': 'completed', 'error': None,
                        'incomplete_details': None, 'output': [item]}}
                    if outer_null:
                        terminal['error'] = None
                    completed = sse.frame(json.dumps(terminal).encode())
                    frames = (done, completed)
                    writer = io.BytesIO()
                    with mock.patch.object(attempt_policy.Ledger, 'reopen') as retry:
                        logs = _relay(
                            _provider(_defn(route, kind, dialect), frames),
                            FakeUpstream(200, b''.join(frames),
                                         [('Content-Type', 'text/event-stream')]),
                            _prepared('api.example.test', route), _metrics(route),
                            _handler(writer))
                    self.assertEqual(writer.getvalue(), b''.join(frames))
                    self.assertEqual([event for event, _ in logs
                                      if event in ('request_completed', 'request_failed')],
                                     ['request_completed'])
                    ledger = next(fields for event, fields in logs if event == 'attempt_ledger')
                    self.assertEqual(ledger['outcome'], outcome.SUCCESS)
                    self.assertTrue(ledger['committed'])
                    retry.assert_not_called()

    def test_nonnull_error_still_rejects_an_apparent_completion(self):
        for location in ('event', 'response'):
            with self.subTest(location=location):
                terminal = {'type': 'response.completed', 'response': {
                    'status': 'completed', 'error': None, 'output': []}}
                target = terminal if location == 'event' else terminal['response']
                target['error'] = {'code': 'server_error', 'message': 'Synthetic failure'}
                frame = sse.frame(json.dumps(terminal).encode())
                event = list(stream_errors.events([frame], {}))[0]
                self.assertNotEqual(event.outcome.category, outcome.SUCCESS)
                self.assertEqual(json.loads(event.frame.split(b'data: ', 1)[1])['type'],
                                 'response.failed')

    def test_failed_status_with_null_error_is_not_success(self):
        frame = sse.frame(json.dumps({'type': 'response.completed', 'response': {
            'status': 'failed', 'error': None, 'output': []}}).encode())
        event = list(stream_errors.events([frame], {}))[0]
        self.assertNotEqual(event.outcome.category, outcome.SUCCESS)


if __name__ == '__main__':
    unittest.main()
