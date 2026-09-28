"""Messages preparation changes only the outgoing copy, including nested tools."""
import copy
import json
import unittest

from ai_router import claude, provider_defs
from tests.harness import stub_credentials
from tests.test_claude_compat import BILLING, PLACEHOLDER, REFERENCE, RELEASED, SEARCH_TOOL


class MessagesOutboundPurityTests(unittest.TestCase):
    def test_external_repairs_do_not_change_a_later_native_request(self):
        payload = {'model': 'claude/deepseek/deepseek-v4.1-flash', 'max_tokens': 32,
                   'system': [{'type': 'text', 'text': BILLING}],
                   'tools': copy.deepcopy([SEARCH_TOOL, PLACEHOLDER, RELEASED]),
                   'messages': [{'role': 'assistant', 'content': [
                       {'type': 'thinking', 'thinking': 'synthetic', 'signature': 'SIGNED'},
                       {'type': 'tool_use', 'id': 'toolu_capture', 'name': 'ToolSearch',
                        'input': {'query': 'fixture'}}]},
                       {'role': 'user', 'content': [copy.deepcopy(REFERENCE)]}]}
        before = copy.deepcopy(payload)
        raw = json.dumps(payload, indent=2).encode()
        external = claude.ExternalMessagesProvider(provider_defs.OPENROUTER)
        bodies = [external.prepare(payload['model'], '/v1/messages', payload, raw, {},
                                   stub_credentials()).body for _ in range(2)]
        self.assertEqual(payload, before)
        self.assertEqual(bodies[0], bodies[1])
        sent = json.loads(bodies[0])
        self.assertEqual(sent['model'], 'deepseek/deepseek-v4.1-flash')
        self.assertNotIn('system', sent)
        self.assertEqual([tool['name'] for tool in sent['tools']],
                         ['ToolSearch', 'mcp__stubtools__tool_000'])
        self.assertNotIn('defer_loading', bodies[0].decode())
        self.assertNotIn('tool_reference', bodies[0].decode())
        self.assertEqual(sent['messages'][0], before['messages'][0])
        native = claude.ClaudeSubscriptionProvider().prepare(
            payload['model'], '/v1/messages', payload, raw,
            {'Authorization': 'Bearer subscription-fixture'}, None)
        self.assertIs(native.body, raw)
        self.assertEqual(payload, before)

    def test_unchanged_external_body_retains_client_serialization(self):
        payload = {'model': 'deepseek/deepseek-v4.1-flash', 'messages': [],
                   'tools': [copy.deepcopy(SEARCH_TOOL)]}
        raw = json.dumps(payload, indent=3).encode()
        prepared = claude.ExternalMessagesProvider(provider_defs.OPENROUTER).prepare(
            payload['model'], '/v1/messages', payload, raw, {}, stub_credentials())
        self.assertIs(prepared.body, raw)


if __name__ == '__main__':
    unittest.main()
