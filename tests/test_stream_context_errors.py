"""Upstream terminal SSE refusals must reach Codex as context errors."""
import io
import json
import unittest
from unittest import mock

from ai_router import router, sse, stream_errors, upstream
from tests.fakes import FakeUpstream, install_fake
from tests.harness import post, start_server, test_state

MESSAGE = 'The prompt is too long: 4290688, model maximum context length: 1048571'
MODEL = 'deepseek/deepseek-v4.1-flash'


class StreamContextTests(unittest.TestCase):
    def setUp(self):
        self.server = start_server(test_state('unused'))
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, wire, model=MODEL):
        install_fake(self, lambda: FakeUpstream(
            200, wire, [('Content-Type', 'text/event-stream')]))
        with mock.patch.object(router, 'log_event') as logged:
            response = post(self.server.server_port, '/test-token/responses',
                            {'model': model, 'input': [], 'stream': True})
            self.assertEqual(response.status, 200)
            body = response.read()
        return body, logged.call_args_list

    def test_context_refusal_is_normalized_and_logged_as_failure(self):
        errors = [
            {'message': MESSAGE, 'code': None},
            {'code': 400, 'metadata': {'error_type': 'context_length_exceeded'}},
            {'code': 'context_length_exceeded', 'message': 'private-input'},
            {'code': 'invalid_prompt', 'metadata': {
                'raw': json.dumps({'error': {'message': MESSAGE}})}},
        ]
        for error in errors:
            with self.subTest(error=error):
                wire = sse.frame(json.dumps({'type': 'response.failed',
                    'response': {'status': 'failed', 'error': error}}).encode())
                body, logs = self.request(wire)
                event = json.loads(next(sse.blocks(io.BytesIO(body)))[1])
                self.assertEqual(event['type'], 'response.failed')
                self.assertEqual(event['response']['error']['code'], 'context_length_exceeded')
                self.assertNotIn(b'private-input', body)
                failures = [c for c in logs if c.args[0] == 'request_failed']
                self.assertEqual(len(failures), 1)
                self.assertEqual(failures[0].kwargs['code'], 'context_length_exceeded')
                self.assertEqual(failures[0].kwargs['status'], 200)
                self.assertFalse(any(c.args[0] == 'request_completed' for c in logs))
                self.assertNotIn('private-input', str(logs))
                self.assertNotIn(MESSAGE, str(logs))

    def test_unknown_terminal_errors_are_preserved_but_not_logged_as_success(self):
        for event in (
            {'type': 'response.failed', 'response': {'error': {
                'code': 'bad_schema', 'message': 'private-input'}}},
            {'type': 'response.incomplete', 'response': {
                'incomplete_details': {'reason': 'max_output_tokens'}}},
        ):
            with self.subTest(event=event):
                wire = sse.frame(json.dumps(event).encode())
                body, logs = self.request(wire)
                self.assertEqual(body, wire)
                self.assertTrue(any(c.args[0] == 'request_failed' for c in logs))
                self.assertFalse(any(c.args[0] == 'request_completed' for c in logs))
                self.assertNotIn('private-input', str(logs))

    def test_success_text_is_not_a_context_refusal(self):
        wire = sse.frame(json.dumps({'type': 'response.completed', 'response': {
            'id': 'synthetic', 'model': MODEL, 'output': [{'type': 'message',
                'content': [{'type': 'output_text', 'text': MESSAGE}]}],
            'usage': {'input_tokens': 650541, 'output_tokens': 10}}}).encode())
        body, logs = self.request(wire)
        self.assertEqual(body, wire)
        self.assertTrue(any(c.args[0] == 'request_completed' for c in logs))
        self.assertFalse(any(c.args[0] == 'request_failed' for c in logs))

    def test_incomplete_stream_records_its_reason_under_its_own_code(self):
        wire = sse.frame(json.dumps({'type': 'response.incomplete', 'response': {
            'incomplete_details': {'reason': 'max_output_tokens'}}}).encode())
        body, logs = self.request(wire)
        self.assertEqual(body, wire)  # the client still sees the provider's frame
        failures = [c for c in logs if c.args[0] == 'request_failed']
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].kwargs['code'], 'UPSTREAM_INCOMPLETE')
        self.assertEqual(failures[0].kwargs['terminal_event'], 'response.incomplete')
        self.assertEqual(failures[0].kwargs['upstream_reason'], 'max_output_tokens')
        self.assertNotIn('served_model', failures[0].kwargs)

    def test_failed_stream_records_the_bounded_provider_code_only(self):
        wire = sse.frame(json.dumps({'type': 'response.failed', 'response': {
            'error': {'code': 'provider_unavailable', 'message': 'private-input'}}}).encode())
        body, logs = self.request(wire)
        self.assertEqual(body, wire)
        failures = [c for c in logs if c.args[0] == 'request_failed']
        self.assertEqual(failures[0].kwargs['code'], 'UPSTREAM_STREAM_FAILED')
        self.assertEqual(failures[0].kwargs['terminal_event'], 'response.failed')
        self.assertEqual(failures[0].kwargs['upstream_code'], 'provider_unavailable')
        self.assertNotIn('private-input', str(logs))

    def test_non_scalar_provider_detail_is_never_recorded(self):
        wire = sse.frame(json.dumps({'type': 'response.failed', 'response': {
            'error': {'code': {'nested': 'private-input'},
                      'message': 'quoted prompt text must not be logged'}}}).encode())
        _, logs = self.request(wire)
        failures = [c for c in logs if c.args[0] == 'request_failed']
        self.assertNotIn('upstream_code', failures[0].kwargs)
        self.assertNotIn('private-input', str(logs))
        self.assertNotIn('quoted prompt text', str(logs))

    def test_oversized_provider_code_is_truncated_to_the_bound(self):
        wire = sse.frame(json.dumps({'type': 'error', 'code': 'x' * 200,
                                     'message': 'private-input'}).encode())
        _, logs = self.request(wire)
        failures = [c for c in logs if c.args[0] == 'request_failed']
        self.assertEqual(failures[0].kwargs['upstream_code'], 'x' * 64)
        self.assertNotIn('private-input', str(logs))

    def test_prose_in_provider_metadata_is_never_recorded(self):
        prose = 'the user asked about ACME payroll; token sk-or-v1-AAAABBBBCCCC'
        for event in (
            {'type': 'response.failed', 'response': {'error': {'code': prose}}},
            {'type': 'response.failed', 'response': {'error': {'error_type': prose}}},
            {'type': 'response.incomplete', 'response': {
                'incomplete_details': {'reason': prose}}},
            {'type': 'error', 'code': prose},
        ):
            with self.subTest(event=event):
                _, logs = self.request(sse.frame(json.dumps(event).encode()))
                failures = [c for c in logs if c.args[0] == 'request_failed']
                self.assertEqual(len(failures), 1)
                self.assertNotIn('upstream_code', failures[0].kwargs)
                self.assertNotIn('upstream_reason', failures[0].kwargs)
                self.assertNotIn('ACME payroll', str(logs))

    def test_subscription_stream_keeps_existing_wire_behavior(self):
        self.server.state['openai_models'] = ['gpt-6-astra']
        wire = sse.frame(json.dumps({'type': 'response.failed', 'response': {
            'error': {'message': MESSAGE}}}).encode())
        body, _ = self.request(wire, 'gpt-6-astra')
        self.assertEqual(body, wire)

    def test_http_refusal_uses_the_same_numeric_and_metadata_classifier(self):
        for error in ({'message': MESSAGE}, {'metadata': {'error_type': 'context_length_exceeded'}}):
            install_fake(self, lambda: FakeUpstream(400, json.dumps({'error': error}).encode()))
            response = post(self.server.server_port, '/test-token/responses',
                            {'model': MODEL, 'input': [], 'stream': True})
            self.assertEqual(response.status, 200)
            event = json.loads(next(sse.blocks(io.BytesIO(response.read())))[1])
            self.assertEqual(event['response']['error']['code'], 'context_length_exceeded')


class ContextClassificationTests(unittest.TestCase):
    def test_exact_numeric_message_only(self):
        for message in (MESSAGE, '  ' + MESSAGE + '\n'):
            self.assertTrue(upstream.is_context_error(json.dumps({'error': {'message': message}})))
        for message in ('Invalid input contains: ' + MESSAGE, MESSAGE + ' quoted text',
                        'context_length_exceeded',
                        'The prompt is too long: 10, model maximum context length: 20',
                        'The prompt is too long: 20, model maximum context length: 0'):
            with self.subTest(message=message):
                self.assertFalse(upstream.is_context_error(json.dumps({'error': {'message': message}})))

    def test_metadata_code_is_recognized_without_matching_arbitrary_text(self):
        self.assertTrue(upstream.is_context_error(json.dumps({'error': {
            'metadata': {'error_type': 'context_length_exceeded'}}})))
        self.assertFalse(upstream.is_context_error(json.dumps({'error': {
            'metadata': {'raw': MESSAGE}}})))


class StreamFramingTests(unittest.TestCase):
    def test_error_event_codes_and_response_error_type_are_normalized(self):
        for event in (
            {'type': 'error', 'code': 'context_length_exceeded', 'message': 'private-input'},
            {'type': 'response.failed', 'error_type': 'context_length_exceeded',
             'response': {'error': {'code': 'invalid_prompt'}}},
        ):
            wire = sse.frame(json.dumps(event).encode())
            out = b''.join(stream_errors.normalize([wire], {}))
            self.assertNotIn(b'private-input', out)
            self.assertEqual(json.loads(next(sse.blocks(io.BytesIO(out)))[1])[
                'response']['error']['code'], 'context_length_exceeded')

    def test_split_chunks_preserve_success_comments_and_usage(self):
        wire = (b': heartbeat\r\n\r\nid: 7\r\nevent: response.completed\r\n'
                b'data: {"type":"response.completed",\r\n'
                b'data: "response":{"usage":{"input_tokens":650541}}}\r\n\r\n'
                b'data: [DONE]\n\n')
        for size in (1, 7, len(wire)):
            metrics = {}
            chunks = (wire[i:i + size] for i in range(0, len(wire), size))
            self.assertEqual(b''.join(stream_errors.normalize(chunks, metrics)), wire)
            self.assertEqual(metrics, {})

    def test_top_level_error_stops_after_failure_even_with_later_completion(self):
        error = sse.frame(json.dumps({'type': 'error', 'error': {'message': MESSAGE}}).encode())
        trailing = sse.frame(b'{"type":"response.completed"}')
        metrics = {'served_model': 'must-not-report-success'}
        out = b''.join(stream_errors.normalize([error + trailing], metrics))
        frames = list(sse.blocks(io.BytesIO(out)))
        self.assertEqual(len(frames), 1)
        self.assertEqual(json.loads(frames[0][1])['response']['error']['code'], 'context_length_exceeded')
        self.assertNotIn('served_model', metrics)

    def test_chunk_parser_keeps_existing_frame_bound_and_incomplete_error(self):
        with mock.patch.object(sse, 'MAX_FRAME_BYTES', 16):
            with self.assertRaisesRegex(ValueError, 'exceeds 16'):
                list(stream_errors.normalize([b'x' * 17], {}))
        with self.assertRaisesRegex(ValueError, 'Incomplete upstream SSE event'):
            list(stream_errors.normalize([b'data: {}\n'], {}))


if __name__ == '__main__':
    unittest.main()
