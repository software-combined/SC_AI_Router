import json
import unittest
from types import SimpleNamespace
from unittest import mock
from codex_router import providers


def _stub_credentials(key='router-secret'):
    return SimpleNamespace(openrouter_key=lambda: key)

class SelectTests(unittest.TestCase):
    def test_select_prefers_native_paths_regardless_of_model(self):
        provider = providers.select('z-ai/glm-5.3', '/alpha/search', [])
        self.assertIsInstance(provider, providers.SubscriptionProvider)

    def test_none_mode_names_subscription_for_openai_models(self):
        with self.assertRaisesRegex(ValueError, 'without a ChatGPT subscription'):
            providers.select('gpt-6-astra', '/responses', ['gpt-6-astra'], 'none')

    def test_select_rejects_unknown_model(self):
        with self.assertRaisesRegex(ValueError, 'not in the configured catalog'):
            providers.select('unknown/model', '/responses', ['gpt-6-astra'])

    def test_openrouter_prepare_emits_router_key_only(self):
        # Picker visibility never gates routing: hidden GPT slugs still route.
        hidden = providers.select('openai/gpt-6-astra', '/responses', [])
        self.assertIsInstance(hidden, providers.OpenRouterProvider)
        provider = providers.select('z-ai/glm-5.3', '/responses', [])
        prepared = provider.prepare('z-ai/glm-5.3', '/responses',
            {'model': 'z-ai/glm-5.3', 'input': []}, b'raw',
            {'Authorization': 'Bearer subscription-secret', 'Cookie': 'c=1',
             'ChatGPT-Account-ID': 'acct'}, _stub_credentials())
        self.assertEqual(prepared.headers,
                         {'Authorization': 'Bearer router-secret',
                          'Content-Type': 'application/json', 'Accept-Encoding': 'identity'})

    def test_subscription_prepare_forwards_bearer_and_strips_hop_headers(self):
        provider = providers.select('gpt-6-astra', '/responses', ['gpt-6-astra'])
        prepared = provider.prepare('gpt-6-astra', '/responses', {'model': 'x'}, b'raw',
            {'Authorization': 'Bearer subscription-secret', 'ChatGPT-Account-ID': 'acct',
             'Connection': 'keep-alive', 'Host': 'h', 'Content-Length': '3'}, None)
        self.assertEqual(prepared.headers,
                         {'Authorization': 'Bearer subscription-secret',
                          'ChatGPT-Account-ID': 'acct'})

    def test_subscription_prepare_forwards_headers_unchanged(self):
        # No Bearer header (Codex >=0.153.4 path-token auth) must forward, not 401.
        provider = providers.select('gpt-6-astra', '/responses', ['gpt-6-astra'])
        prepared = provider.prepare('gpt-6-astra', '/responses', {'model': 'x'}, b'raw',
            {'ChatGPT-Account-ID': 'acct', 'Host': 'h'}, None)
        self.assertEqual(prepared.host, 'chatgpt.com')
        self.assertNotIn('Authorization', prepared.headers)

class OutputCapTests(unittest.TestCase):
    def test_output_cap_follows_registry(self):
        provider = providers.OpenRouterProvider()
        fake = SimpleNamespace(max_output_tokens=1000, context_window=100000)
        payload = {'model': 'fake/model', 'input': [], 'max_output_tokens': 5000}
        prepared = provider.prepare(fake, '/responses', payload, b'raw', {}, _stub_credentials())
        self.assertEqual(json.loads(prepared.body)['max_output_tokens'], 1000)
        payload = {'model': 'fake/model', 'input': []}
        prepared = provider.prepare(fake, '/responses', payload, b'raw', {}, _stub_credentials())
        self.assertEqual(json.loads(prepared.body)['max_output_tokens'], 1000)

    def test_output_cap_leaves_room_for_input(self):
        # Regression: a 943718 reservation on a 1048576 window leaves ~105k
        # for input, so a ~105k-input request blows the context. The router
        # must reserve at most half the window for output.
        from codex_router.registry import by_slug
        provider = providers.OpenRouterProvider()
        entry = by_slug('meta/muse-spark-1.3-contributor')
        payload = {'model': 'meta/muse-spark-1.3-contributor', 'input': []}
        prepared = provider.prepare(entry, '/responses', payload, b'raw', {},
                                    _stub_credentials())
        sent = json.loads(prepared.body)['max_output_tokens']
        self.assertLessEqual(sent, entry.context_window // 2)

    def test_unknown_model_is_rejected(self):
        provider = providers.OpenRouterProvider()
        with self.assertRaises(providers.PreparationError):
            provider.prepare('unknown/model', '/responses',
                             {'model': 'unknown/model', 'input': []},
                             b'raw', {}, _stub_credentials())

    def test_request_over_context_window_is_rejected_before_upstream(self):
        # Live 2026-09-09: ~501k input tokens with a 524288 output
        # explicit reservation against a 1048576 window (~1050400 total).
        # Reject before forwarding, using the context-specific error so
        # Codex can distinguish exhaustion from other preparation failures.
        from codex_router.registry import by_slug
        provider = providers.OpenRouterProvider()
        entry = by_slug('meta/muse-spark-1.3-contributor')
        payload = {'model': 'meta/muse-spark-1.3-contributor',
                   'input': [{'type': 'message', 'role': 'user',
                              'content': 'x' * 2100000}],
                   'max_output_tokens': 524288}
        with self.assertRaisesRegex(providers.PreparationError, 'compact'):
            provider.prepare(entry, '/responses', payload, b'raw', {},
                             _stub_credentials())

    def test_request_within_context_window_still_passes(self):
        from codex_router.registry import by_slug
        provider = providers.OpenRouterProvider()
        entry = by_slug('meta/muse-spark-1.3-contributor')
        payload = {'model': 'meta/muse-spark-1.3-contributor',
                   'input': [{'type': 'message', 'role': 'user',
                              'content': 'y' * 400000}],
                   'max_output_tokens': 524288}
        prepared = provider.prepare(entry, '/responses', payload, b'raw', {},
                                    _stub_credentials())
        self.assertEqual(json.loads(prepared.body)['max_output_tokens'], 524288)

    def test_request_exactly_at_window_passes(self):
        # Strict > pins the boundary: estimate + reserve == window forwards.
        import json as _json
        from codex_router.registry import by_slug
        provider = providers.OpenRouterProvider()
        entry = by_slug('meta/muse-spark-1.3-contributor')
        reserved = entry.context_window // 2
        overhead = len(_json.dumps([{'type': 'message', 'role': 'user',
                                     'content': ''}]))
        pad = 'x' * (reserved * 4 - overhead)
        payload = {'model': entry.slug,
                   'input': [{'type': 'message', 'role': 'user',
                              'content': pad}],
                   'max_output_tokens': reserved}
        prepared = provider.prepare(entry, '/responses', payload, b'raw', {},
                                    _stub_credentials())
        self.assertEqual(json.loads(prepared.body)['max_output_tokens'], reserved)

    def test_unknown_window_skips_guard(self):
        # Registry default context_window=0: forward as before, endpoint enforces.
        provider = providers.OpenRouterProvider()
        fake = SimpleNamespace(max_output_tokens=1000, context_window=0,
                               slug='fake/model')
        payload = {'model': 'fake/model',
                   'input': [{'type': 'message', 'role': 'user',
                              'content': 'z' * 2000000}]}
        prepared = provider.prepare(fake, '/responses', payload, b'raw', {},
                                    _stub_credentials())
        self.assertEqual(json.loads(prepared.body)['max_output_tokens'], 1000)

    def test_non_list_input_never_escapes_as_500(self):
        # Wire input of any JSON shape is measured, never a TypeError leak.
        from codex_router.registry import by_slug
        provider = providers.OpenRouterProvider()
        entry = by_slug('meta/muse-spark-1.3-contributor')
        for shape in ('do the task', {'text': 'do the task'}, None):
            payload = {'model': entry.slug, 'input': shape}
            try:
                provider.prepare(entry, '/responses', dict(payload), b'raw', {},
                                 _stub_credentials())
            except providers.PreparationError as exc:
                self.assertNotIn('Bearer', str(exc))
                self.assertNotIn('router-secret', str(exc))


class FailureDescriptionTests(unittest.TestCase):
    def test_stall_before_headers_names_model_and_timeout(self):
        status, message = providers.describe_failure(
            TimeoutError('timed out'), None,
            {'model': '~x-ai/grok-latest', 'provider': 'openrouter',
             'elapsed_ms': 120001.0, 'timeout_s': 120, 'has_image': False})
        self.assertEqual(status, 502)
        self.assertIn('~x-ai/grok-latest', message)
        self.assertIn('120', message)
        self.assertIn('shorter', message)

    def test_grok_image_stall_suggests_text_only(self):
        status, message = providers.describe_failure(
            TimeoutError('timed out'), None,
            {'model': '~x-ai/grok-latest', 'provider': 'openrouter',
             'elapsed_ms': 120001.0, 'timeout_s': 120, 'has_image': True})
        self.assertEqual(status, 502)
        self.assertIn('text-only', message)

    def test_dns_failure_names_host(self):
        status, message = providers.describe_failure(
            OSError('Name or service not known'), None,
            {'model': 'z-ai/glm-5.3', 'provider': 'openrouter',
             'host': 'openrouter.ai', 'elapsed_ms': 12.0, 'timeout_s': 120,
             'has_image': False})
        self.assertEqual(status, 502)
        self.assertIn('openrouter.ai', message)

    def test_nested_provider_400_becomes_actionable_409(self):
        raw = ('{"code": "invalid-argument", "error": "Failed to start sampling: '
               '[invalid_client_tool_schema] ns_abc123def456_tool_update: tool parameter '
               'root must be an object type"}')
        body = json.dumps({'error': {'message': 'Provider returned error',
                                     'metadata': {'raw': raw, 'provider_name': 'xAI'}}})
        status, message = providers.describe_failure(
            None, {'status': 400, 'body': body.encode()},
            {'model': '~x-ai/grok-latest', 'provider': 'openrouter',
             'elapsed_ms': 1831.8, 'timeout_s': 120, 'has_image': False})
        self.assertEqual(status, 409)
        self.assertIn('xAI', message)
        self.assertIn('ns_abc123def456_tool_update', message)
        self.assertIn('tool schema was rejected', message)
        self.assertNotIn('Failed to start sampling', message)
        self.assertNotIn('arguments_json', message)

    def test_unparseable_upstream_body_passes_through(self):
        self.assertIsNone(providers.describe_failure(
            None, {'status': 400, 'body': b'not json at all'},
            {'model': 'z-ai/glm-5.3', 'provider': 'openrouter',
             'elapsed_ms': 500.0, 'timeout_s': 120, 'has_image': False}))
        self.assertIsNone(providers.describe_failure(
            ValueError('odd shape'), None,
            {'model': 'z-ai/glm-5.3', 'provider': 'openrouter',
             'elapsed_ms': 500.0, 'timeout_s': 120, 'has_image': False}))


class SummarizerTests(unittest.TestCase):
    def _summarize(self, model, seen):
        class FakeConn:
            def __init__(self, *a, **k):
                pass
            def request(self, method, path, body=None, headers=None):
                seen.update(json.loads(body))
            def getresponse(self):
                payload = {'output': [{'type': 'message', 'content': [
                    {'type': 'output_text', 'text': 's'}]}]}
                return SimpleNamespace(status=200, read=lambda: json.dumps(payload).encode())
            def close(self):
                pass
        with mock.patch.object(providers.http.client, 'HTTPSConnection', FakeConn):
            return providers.OpenRouterProvider().summarize(model, 'key', [])

    def test_summarizer_pins_lowest_supported_effort(self):
        for model, effort in (('~deepseek/deepseek-v4-flash-latest', 'low'),
                              ('z-ai/glm-5.3', 'low')):
            with self.subTest(model=model):
                seen = {}
                self.assertEqual(self._summarize(model, seen), 's')
                self.assertEqual(seen['reasoning'], {'effort': effort})

    def test_summarizer_raises_output_cap_and_omits_effort_when_unknown(self):
        seen = {}
        self._summarize('z-ai/glm-5.3', seen)
        self.assertEqual(seen['max_output_tokens'], 4000)
        seen = {}
        self._summarize('unknown-model-xyz', seen)
        self.assertNotIn('reasoning', seen)

    def test_compact_remembers_discovered_tools(self):
        from codex_router.tool_adapter import prepare_tools
        items = [{'type': 'message', 'role': 'user', 'content': 'do it'},
                 {'type': 'tool_search_output', 'call_id': 's1', 'status': 'completed',
                  'execution': 'client', 'tools': [
                      {'type': 'function', 'name': 'echo', 'description': 'Echo',
                       'parameters': {'type': 'object'}}]}]
        with mock.patch.object(providers.OpenRouterProvider, 'summarize', lambda *a: 'did stuff'):
            out = providers.OpenRouterProvider().compact('z-ai/glm-5.3', {'input': items}, 'key')
        payload = {'tools': [], 'input': out}
        prepare_tools(payload)
        self.assertEqual(len(payload['tools']), 1)
        self.assertEqual(payload['tools'][0]['parameters'], {'type': 'object'})

    def test_text_only_models_reject_image_blocks(self):
        # Fail closed like the effort path: a mid-thread switch to a
        # text-only model must name the image content and the remedy,
        # never silently drop the blocks.
        payload = {'model': 'z-ai/glm-5.3', 'input': [
            {'type': 'message', 'role': 'user', 'content': [
                {'type': 'input_text', 'text': 'look'},
                {'type': 'input_image', 'image_url': 'data:image/png;base64,AAA'}]}]}
        with self.assertRaisesRegex(providers.PreparationError,
                                    'does not accept image input.*image-capable'):
            providers.OpenRouterProvider().prepare(
                'z-ai/glm-5.3', '/responses', payload, b'raw', {}, _stub_credentials())

    def test_image_capable_models_keep_image_blocks(self):
        payload = {'model': 'moonshotai/kimi-k3', 'input': [
            {'type': 'message', 'role': 'user', 'content': [
                {'type': 'input_text', 'text': 'look'},
                {'type': 'input_image', 'image_url': 'data:image/png;base64,AAA'}]}]}
        prepared = providers.OpenRouterProvider().prepare(
            'moonshotai/kimi-k3', '/responses', payload, b'raw', {}, _stub_credentials())
        kept = json.loads(prepared.body)['input'][0]['content']
        self.assertEqual(len(kept), 2)
        grok_payload = {'model': '~x-ai/grok-latest', 'input': [
            {'type': 'message', 'role': 'user', 'content': [
                {'type': 'input_text', 'text': 'look'},
                {'type': 'input_image', 'image_url': 'data:image/png;base64,AAA'}]}]}
        grok_prepared = providers.OpenRouterProvider().prepare(
            '~x-ai/grok-latest', '/responses', grok_payload, b'raw', {}, _stub_credentials())
        self.assertEqual(json.loads(grok_prepared.body)['input'][0]['content'],
            [{'type': 'input_text', 'text': 'look'},
             {'type': 'input_text', 'text': '[image omitted: this model runs text-only]'}])

    def test_text_only_models_pass_without_images(self):
        payload = {'model': 'z-ai/glm-5.3', 'input': [
            {'type': 'message', 'role': 'user', 'content': 'look'}]}
        prepared = providers.OpenRouterProvider().prepare(
            'z-ai/glm-5.3', '/responses', payload, b'raw', {}, _stub_credentials())
        self.assertEqual(prepared.host, 'openrouter.ai')


if __name__ == '__main__':
    unittest.main()
