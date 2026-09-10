"""Output defaults and Codex's context-exhaustion wire contract, offline."""
import json
import unittest
from types import SimpleNamespace

from codex_router import context_budget, errors, providers
from tests.fakes import FakeUpstream, install_fake
from tests.test_handler import _post
from tests.test_mixed_router import _start_server, _test_state

MODEL = 'meta/muse-spark-1.3-contributor'


def request_with_estimate(tokens, **extra):
    items = [{'type': 'message', 'role': 'user', 'content': ''}]
    items[0]['content'] = 'x' * (tokens * 4 - len(json.dumps(items)))
    return {'model': MODEL, 'input': items, **extra}


class ContextBudgetTests(unittest.TestCase):
    def prepare(self, payload, model=MODEL):
        result = providers.OpenRouterProvider().prepare(
            model, '/responses', payload, b'', {},
            SimpleNamespace(openrouter_key=lambda: 'test-key'))
        return json.loads(result.body)

    def test_reported_524550_input_turn_fits_with_default_output(self):
        payload = request_with_estimate(524550)
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

    def test_exhaustion_is_typed_and_estimate_is_labelled(self):
        with self.assertRaises(errors.ContextWindowExceeded) as caught:
            self.prepare(request_with_estimate(1048576))
        self.assertIn('~1048576 input', str(caught.exception))


class EstimateTests(unittest.TestCase):
    def test_counts_tools_and_instructions(self):
        payload = {'model': MODEL, 'input': [{'content': 'x' * 4000}],
                   'instructions': 'y' * 8000,
                   'tools': [{'name': f'f{i}', 'description': 'd' * 200}
                             for i in range(92)]}
        input_only = len(json.dumps(payload['input'])) // 4
        self.assertGreater(context_budget.estimate(payload), input_only * 2)

    def test_excludes_image_payloads(self):
        img = 'data:image/png;base64,' + 'A' * 500000
        with_images = context_budget.estimate(
            {'input': [{'content': [{'type': 'input_text', 'text': 'see this'},
                                    {'type': 'input_image', 'image_url': img}]}]})
        self.assertLess(with_images, 1000)

    def test_mixed_text_and_image_counts_text_only(self):
        img = 'data:image/png;base64,' + 'A' * 500000
        mixed = context_budget.estimate(
            {'input': [{'content': [{'type': 'input_text',
                                     'text': 'x' * 4000},
                                    {'type': 'input_image',
                                     'image_url': img}]}]})
        self.assertGreater(mixed, 900)
        self.assertLess(mixed, 2000)

    def test_refusal_record_carries_model_and_estimate(self):
        prepare = ContextBudgetTests().prepare
        with self.assertRaises(errors.ContextWindowExceeded) as caught:
            prepare(request_with_estimate(1048576))
        budget = caught.exception.budget
        self.assertEqual((budget['model'], budget['path']), (MODEL, '/responses'))
        self.assertGreater(budget['used'], 1000000)
        self.assertEqual((budget['reserved'], budget['window']), (32000, 1048576))


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

    def test_local_exhaustion_never_calls_upstream(self):
        calls = install_fake(self, lambda: self.fail('must reject before upstream'))
        for streaming in (True, False):
            self.assert_context(self.post(request_with_estimate(1048576, stream=streaming)),
                                streaming)
        self.assertEqual(calls, [])

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

    def test_other_preparation_and_upstream_errors_remain_409(self):
        self.assertEqual(self.post({'model': MODEL, 'input': [], 'stream': True,
                                    'reasoning': {'effort': 'invalid'}})[0], 409)
        install_fake(self, lambda: FakeUpstream(400, b'{"error":{"code":"bad_schema",'
                                               b'"message":"schema invalid"}}'))
        status, content_type, body = self.post({'model': MODEL, 'input': [], 'stream': True})
        self.assertEqual((status, content_type), (409, 'application/json'))
        self.assertEqual(json.loads(body)['error']['code'], 'PROVIDER_REJECTED')

    def test_subscription_context_error_keeps_existing_handling(self):
        self.server.state['openai_models'] = ['gpt-6-astra']
        install_fake(self, lambda: FakeUpstream(400, b'{"error":{"code":"context_length_exceeded",'
                                               b'"message":"context full"}}'))
        status, content_type, _ = self.post({'model': 'gpt-6-astra', 'input': [], 'stream': True})
        self.assertEqual((status, content_type), (409, 'application/json'))

    def test_unrecognized_error_shapes_are_not_context_errors(self):
        for body in (b'bad json', b'{"error":[]}', b'{"error":{"metadata":null}}',
                     b'{"error":{"message":"context_length_exceeded"}}'):
            self.assertFalse(providers.is_context_error(body))


if __name__ == '__main__':
    unittest.main()
