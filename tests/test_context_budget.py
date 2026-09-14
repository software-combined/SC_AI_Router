"""Output defaults and Codex's context-exhaustion wire contract, offline."""
import json
import unittest
from types import SimpleNamespace

from ai_router import providers, upstream
from tests.fakes import FakeUpstream, install_fake
from tests.harness import (
    post as _post,
    start_server as _start_server,
    test_state as _test_state,
)


def _external_responses():
    """OpenRouter Codes adapter; Plan 141 makes adapters per-provider."""
    from ai_router import provider_defs as _defs
    return providers.ExternalResponsesProvider(_defs.OPENROUTER)


MODEL = 'meta/muse-spark-1.3-contributor'


def request_of(chars):
    items = [{'type': 'message', 'role': 'user', 'content': 'x' * chars}]
    return {'model': MODEL, 'input': items}


class ContextBudgetTests(unittest.TestCase):
    def prepare(self, payload, model=MODEL):
        result = _external_responses().prepare(
            model, '/responses', payload, b'', {},
            SimpleNamespace(key_for=lambda _pid=None: 'test-key'))
        return json.loads(result.body)

    def test_long_reported_turns_forward_with_default_output(self):
        # Live 2026-09-11 (thread 01a08ba0): a 4,324,328-byte turn billed
        # 750,806 tokens upstream, but the removed chars/4 pre-flight scored
        # it 1,091,485 and refused it, ending the thread. Context size is the
        # provider's call now; the output default still applies.
        for chars in (524550 * 4, 4324328):
            with self.subTest(chars=chars):
                payload = request_of(chars)
                original = json.loads(json.dumps(payload['input']))
                sent = self.prepare(payload)
                self.assertEqual(sent['max_output_tokens'], 32000)
                self.assertEqual(sent['input'], original)

    def test_default_respects_small_window_and_provider_ceiling(self):
        for window, ceiling, expected in ((100000, 50000, 10000),
                                          (100000, 5000, 5000),
                                          (0, 100000, 32000), (0, 1000, 1000)):
            with self.subTest(window=window, ceiling=ceiling):
                model = SimpleNamespace(context_window=window, max_output_tokens=ceiling)
                sent = self.prepare({'model': 'fake/model', 'input': []}, model)
                self.assertEqual(sent['max_output_tokens'], expected)

    def test_explicit_output_keeps_existing_half_window_clamp(self):
        for requested, expected in ((900000, 524288), (8192, 8192)):
            sent = self.prepare({'model': MODEL, 'input': [],
                                 'max_output_tokens': requested})
            self.assertEqual(sent['max_output_tokens'], expected)


class ContextWireTests(unittest.TestCase):
    def setUp(self):
        self.server = _start_server(_test_state('unused'))
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, payload):
        response = _post(self.server.server_port, '/test-token/responses', payload)
        return response.status, response.getheader('Content-Type'), response.read()

    def assert_context(self, result, streaming):
        status, content_type, body = result
        if streaming:
            self.assertEqual((status, content_type), (200, 'text/event-stream'))
            data = json.loads(body.decode().split('data: ', 1)[1])
            self.assertEqual(data['type'], 'response.failed')
            error = data['response']['error']
        else:
            self.assertEqual((status, content_type), (400, 'application/json'))
            error = json.loads(body)['error']
        self.assertEqual(error['code'], 'context_length_exceeded')
        self.assertNotIn('test-key', error['message'])

    def test_upstream_context_code_uses_same_wire_contract(self):
        for streaming, nested in ((True, False), (False, False), (True, True)):
            error = {'error': {'code': 'context_length_exceeded', 'message': 'private input'}}
            body = ({'error': {'code': 400, 'metadata': {'raw': json.dumps(error)}}}
                    if nested else error)
            with self.subTest(streaming=streaming, nested=nested):
                calls = install_fake(self, lambda: FakeUpstream(400, json.dumps(body).encode()))
                result = self.post({'model': MODEL, 'input': [], 'stream': streaming})
                self.assert_context(result, streaming)
                self.assertNotIn(b'private input', result[2])
                self.assertEqual(len(calls), 1)

    def test_documented_error_type_shape_uses_same_wire_contract(self):
        # OpenRouter documents Responses failures with an explicit top-level
        # error_type while error.code stays invalid_prompt.
        body = {'status': 'failed', 'error': {'code': 'invalid_prompt'},
                'error_type': 'context_length_exceeded'}
        calls = install_fake(self, lambda: FakeUpstream(400, json.dumps(body).encode()))
        result = self.post({'model': MODEL, 'input': [], 'stream': True})
        self.assert_context(result, True)
        self.assertEqual(len(calls), 1)

    def test_explicit_error_type_fields_are_recognized(self):
        self.assertTrue(upstream.is_context_error(
            b'{"error_type":"context_length_exceeded"}'))
        self.assertTrue(upstream.is_context_error(
            b'{"error":{"error_type":"context_length_exceeded"}}'))
        self.assertFalse(upstream.is_context_error(
            b'{"error":{"code":"invalid_prompt"},"error_type":"rate_limit_exceeded"}'))

    def test_preparation_is_final_400_and_upstream_validation_is_400(self):
        self.assertEqual(self.post({'model': MODEL, 'input': [], 'stream': True,
                                    'reasoning': {'effort': 'invalid'}})[0], 400)
        install_fake(self, lambda: FakeUpstream(400, b'{"error":{"code":"bad_schema",'
                                               b'"message":"schema invalid"}}'))
        status, content_type, body = self.post({'model': MODEL, 'input': [], 'stream': True})
        self.assertEqual((status, content_type), (400, 'application/json'))
        self.assertEqual(json.loads(body)['error']['code'], 'PROVIDER_REJECTED')

    def test_subscription_context_error_keeps_existing_handling(self):
        self.server.state['openai_models'] = ['gpt-6-astra']
        install_fake(self, lambda: FakeUpstream(400, b'{"error":{"code":"context_length_exceeded",'
                                               b'"message":"context full"}}'))
        status, content_type, _ = self.post({'model': 'gpt-6-astra', 'input': [], 'stream': True})
        self.assertEqual((status, content_type), (409, 'application/json'))

    def test_unrecognized_error_shapes_are_not_context_errors(self):
        for body in (b'bad json', b'{"error":[]}', b'{"error":{"metadata":null}}',
                     b'{"error":{"message":"context_length_exceeded"}}',
                     b'{"error_type":"context_length_exceeded_extra"}'):
            self.assertFalse(upstream.is_context_error(body))


if __name__ == '__main__':
    unittest.main()
