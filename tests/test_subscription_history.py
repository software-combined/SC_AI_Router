"""Cross-provider replay never rewrites the client's saved history."""
import copy
import http.client
import json
import unittest
from compression import zstd
from unittest import mock

from ai_router import providers, subscription_history, upstream
from tests.fakes import FakeUpstream, install_fake
from tests.harness import isolated_home, post, start_server


def reasoning(**extra):
    return {'type': 'reasoning', 'id': 'rs_foreign', 'summary': [],
            'content': [{'type': 'reasoning_text', 'text': 'PRIVATE-CANARY'}], **extra}


class SubscriptionHistoryTests(unittest.TestCase):
    def test_mixed_history_preserves_every_other_item_and_original_payload(self):
        user = {'type': 'message', 'role': 'user', 'content': 'Remember MARKER'}
        call = {'type': 'function_call', 'call_id': 'call_1', 'name': 'echo', 'arguments': '{}'}
        result = {'type': 'function_call_output', 'call_id': 'call_1', 'output': 'MARKER'}
        delegation = {'type': 'function_call_output', 'name': 'create_thread', 'output': 'assignment'}
        compact = {'type': 'compaction', 'encrypted_content': 'opaque'}
        assistant = {'type': 'message', 'role': 'assistant', 'content': 'MARKER'}
        native = {'type': 'reasoning', 'id': 'rs_native', 'summary': [],
                  'encrypted_content': 'opaque'}
        kept = [user, call, result, delegation, compact, assistant, native]
        for count in (1, 19):
            with self.subTest(count=count):
                payload = {'input': [user, *[reasoning() for _ in range(count)], *kept[1:]]}
                before = copy.deepcopy(payload)
                normalized = subscription_history.normalize(payload)
                self.assertEqual(normalized['input'], kept)
                self.assertEqual(payload, before)
                self.assertIs(subscription_history.normalize(normalized), normalized)
                for actual, original in zip(normalized['input'], kept):
                    self.assertIs(actual, original)

    def test_encrypted_reasoning_keeps_identity_summary_and_opaque_data(self):
        item = reasoning(encrypted_content='opaque', summary=[{'type': 'summary_text', 'text': 'summary'}])
        payload = {'input': [item]}
        normalized = subscription_history.normalize(payload)
        self.assertEqual(normalized['input'], [{k: v for k, v in item.items() if k != 'content'}])
        self.assertIn('content', item)

    def test_noop_shapes_keep_identity(self):
        for items in (None, 'prompt', [], [None], [reasoning(content=[])],
                      [reasoning(content='invalid')], [{'type': 'reasoning', 'summary': []}]):
            with self.subTest(items=items):
                payload = {'input': items}
                self.assertIs(subscription_history.normalize(payload), payload)

    def test_adapter_reencodes_only_changed_history_or_aliases(self):
        provider = providers.SubscriptionProvider()
        for path in ('/responses', '/responses/compact'):
            for foreign in (False, True):
                for aliases in (False, True):
                    with self.subTest(path=path, foreign=foreign, aliases=aliases):
                        payload = {'model': 'gpt-6-astra', 'input': [reasoning()] if foreign else []}
                        raw = zstd.compress(json.dumps(payload).encode())
                        names = {'spawn_agent'} if aliases and path == '/responses' else set()
                        with mock.patch('ai_router.agent_handoffs.add_plaintext_tools', return_value=names):
                            prepared = provider.prepare('gpt-6-astra', path, payload, raw,
                                {'Content-Encoding': 'zstd', 'Accept-Encoding': 'zstd',
                                 'Authorization': 'Bearer synthetic', 'Content-Length': str(len(raw))}, None)
                        if foreign or names:
                            self.assertEqual(json.loads(prepared.body)['input'], [])
                            self.assertNotIn('Content-Encoding', prepared.headers)
                            self.assertEqual(prepared.headers['Accept-Encoding'], 'identity')
                        else:
                            self.assertIs(prepared.body, raw)
                            self.assertEqual(prepared.headers['Content-Encoding'], 'zstd')
                        self.assertNotIn('Content-Length', prepared.headers)
                        self.assertEqual(prepared.headers['Authorization'], 'Bearer synthetic')

    def test_native_service_payload_is_not_normalized(self):
        payload = {'input': [reasoning()]}
        raw = json.dumps(payload).encode()
        prepared = providers.SubscriptionProvider().prepare('gpt-6-astra', '/guardian', payload, raw, {}, None)
        self.assertIs(prepared.body, raw)


class ReplayHandlerTests(unittest.TestCase):
    def setUp(self):
        isolated_home(self)
        self.server = start_server({'port': 0, 'token': 'test-token', 'openai_models': ['gpt-6-astra']})
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_compressed_replay_and_compaction_reach_upstream_without_foreign_items(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{"output": []}', []))
        for path in ('/responses', '/responses/compact'):
            payload = {'model': 'gpt-6-astra', 'input': [reasoning(),
                {'type': 'message', 'role': 'user', 'content': 'MARKER'}]}
            conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
            self.addCleanup(conn.close)
            conn.request('POST', '/test-token' + path,
                         zstd.compress(json.dumps(payload).encode()), {'Content-Encoding': 'zstd'})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            self.assertEqual(json.loads(recorded[-1][3])['input'], payload['input'][1:])

    def test_validation_failure_is_final_and_diagnostics_are_structural(self):
        body = json.dumps({'error': {'code': 'array_above_max_length', 'param': 'input[0].content',
                                    'message': 'invalid PRIVATE-CANARY'}}).encode()
        install_fake(self, lambda: FakeUpstream(400, body, []))
        for model in ('gpt-6-astra', 'deepseek/deepseek-v4.1-flash'):
            with mock.patch('ai_router.router.log_event') as log:
                response = post(self.server.server_port, '/test-token/responses',
                                {'model': model, 'input': [], 'stream': True})
                self.assertEqual(response.status, 400)
                message = json.loads(response.read())['error']['message']
                self.assertIn('array_above_max_length', message)
                self.assertIn('input[0].content', message)
                self.assertNotIn('PRIVATE-CANARY', message + str(log.call_args_list))
                rejected = next(c.kwargs for c in log.call_args_list if c.args == ('upstream_rejected',))
                self.assertEqual(rejected['parameter'], 'input[0].content')


class RejectionParameterTests(unittest.TestCase):
    def test_direct_nested_and_untrusted_parameters(self):
        for param in ('input[0].content', 'tools[12].parameters.required', 'reasoning.effort'):
            body = json.dumps({'error': {'param': param}})
            self.assertEqual(upstream.rejection_parameter(body), param)
            nested = json.dumps({'error': {'metadata': {'raw': body}}})
            self.assertEqual(upstream.rejection_parameter(nested), param)
        for param in ('input[0].PRIVATE-CANARY', 'input[0].content\n', 'https://secret.invalid',
                      'input[9999999].content', 'input[0].content PRIVATE-CANARY', None, []):
            self.assertIsNone(upstream.rejection_parameter(json.dumps({'error': {'param': param}})))
        for body in (b'\xff', 'bad json', '[]', '{"error":null}', '{"error":{"metadata":null}}'):
            self.assertIsNone(upstream.rejection_parameter(body))

    def test_only_responses_validation_changes_status(self):
        for protocol in ('responses', 'messages', None):
            for http_status in (400, 401, 403, 500, 503):
                status, _, _ = upstream.describe_failure(None,
                    {'status': http_status, 'body': b'{"error":{"message":"rejected"}}'},
                    {'model': 'm', 'protocol': protocol})
                self.assertEqual(status, 400 if protocol == 'responses' and http_status == 400 else 409)
