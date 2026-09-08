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
                          'Content-Type': 'application/json'})

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
        for model, effort in (('deepseek/deepseek-v4-flash', 'high'),
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

    def test_text_only_models_drop_image_blocks(self):
        def shapes(model):
            payload = {'model': model, 'input': [
                {'type': 'message', 'role': 'user', 'content': [
                    {'type': 'input_text', 'text': 'look'},
                    {'type': 'input_image', 'image_url': 'data:image/png;base64,AAA'}]}]}
            prepared = providers.OpenRouterProvider().prepare(
                model, '/responses', payload, b'raw', {}, _stub_credentials())
            return json.loads(prepared.body)['input'][0]['content']
        stripped = shapes('z-ai/glm-5.3')
        self.assertEqual(stripped, [{'type': 'input_text', 'text': 'look'}])
        kept = shapes('moonshotai/kimi-k3')
        self.assertEqual(len(kept), 2)


if __name__ == '__main__':
    unittest.main()
