import unittest
from codex_router import providers


class _StubCredentials:
    def __init__(self, key='router-secret'):
        self.key = key

    def openrouter_key(self):
        return self.key

class SelectTests(unittest.TestCase):
    def test_select_prefers_native_paths_regardless_of_model(self):
        provider = providers.select('z-ai/glm-5.3', '/alpha/search', [])
        self.assertIsInstance(provider, providers.SubscriptionProvider)

    def test_select_rejects_unknown_model(self):
        with self.assertRaisesRegex(ValueError, 'not in the configured catalog'):
            providers.select('unknown/model', '/responses', ['gpt-6-astra'])

    def test_openrouter_prepare_emits_router_key_only(self):
        provider = providers.select('z-ai/glm-5.3', '/responses', [])
        prepared = provider.prepare('z-ai/glm-5.3', '/responses',
            {'model': 'z-ai/glm-5.3', 'input': []}, b'raw',
            {'Authorization': 'Bearer subscription-secret', 'Cookie': 'c=1',
             'ChatGPT-Account-ID': 'acct'}, _StubCredentials())
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

    def test_subscription_prepare_without_bearer_is_401(self):
        provider = providers.select('gpt-6-astra', '/responses', ['gpt-6-astra'])
        with self.assertRaisesRegex(PermissionError, 'subscription authentication'):
            provider.prepare('gpt-6-astra', '/responses', {}, b'', {}, None)

if __name__ == '__main__':
    unittest.main()
