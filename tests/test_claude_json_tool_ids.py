"""External Messages JSON tool-ID repair."""
import gzip
import json
import unittest
from unittest.mock import Mock, patch

from tests.fakes import FakeUpstream
from ai_router import claude as claude_mod
from ai_router import claude_compat as compat
from ai_router import provider_defs, upstream


class JsonToolIdTests(unittest.TestCase):
    def test_external_messages_prefer_identity_encoding(self):
        provider = claude_mod.ExternalMessagesProvider(
            provider_defs.get('openrouter'))
        credentials = Mock()
        credentials.key_for.return_value = 'synthetic-key'
        payload = {'model': 'z-ai/glm-5.3-flash', 'messages': []}
        prepared = provider.prepare(
            payload['model'], '/v1/messages', payload,
            json.dumps(payload).encode(), {}, credentials)
        self.assertEqual(prepared.headers['Accept-Encoding'], 'identity')

    def test_compressed_json_fails_closed_before_forwarding(self):
        provider = claude_mod.ExternalMessagesProvider(
            provider_defs.get('openrouter'))
        credentials = Mock()
        credentials.key_for.return_value = 'synthetic-key'
        payload = {'model': 'z-ai/glm-5.3-flash', 'messages': []}
        prepared = provider.prepare(
            payload['model'], '/v1/messages', payload,
            json.dumps(payload).encode(), {}, credentials)
        response = FakeUpstream(
            200, gzip.compress(b'{"content":[]}'),
            [('Content-Type', 'application/json'),
             ('Content-Encoding', 'gzip')])
        with self.assertRaisesRegex(ValueError, 'encoding'):
            upstream.validate_response(response, prepared, raw_encoded=True)

    def test_duplicate_top_level_ids_are_rewritten_without_touching_nested_input(self):
        body = (b'{"id":"msg_1","type":"message","content":['
                b'{"type":"tool_use","id":"call_0","name":"Read",'
                b'"input":{"nested":{"type":"tool_use","id":"payload-id"}}},'
                b'{"type":"tool_use","id":"call_0","name":"Grep","input":{}},'
                b'{"type":"text","text":"hi"}],'
                b'"unknown":{"type":"tool_use","id":"keep-unknown"}}')
        provider = claude_mod.ExternalMessagesProvider(
            provider_defs.get('openrouter'))
        source = FakeUpstream(200, body, [('Content-Type', 'application/json')])
        with patch.object(compat, '_fresh_tool_id',
                          side_effect=('toolu_scg_a', 'toolu_scg_b')):
            shaped = b''.join(provider.adapt(source, None))
        payload = json.loads(shaped)
        self.assertEqual([block['id'] for block in payload['content'][:2]],
                         ['toolu_scg_a', 'toolu_scg_b'])
        self.assertEqual(payload['content'][0]['input']['nested']['id'],
                         'payload-id')
        self.assertEqual(payload['unknown']['id'], 'keep-unknown')


if __name__ == '__main__':
    unittest.main()
