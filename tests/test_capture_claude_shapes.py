"""The shape capture reads what the client actually sends.

Offline: the bodies below are the ones Claude Code 2.1.223 produced against
the scripted sink, so a client change that stops deferring or stops returning
references shows up here rather than as a silent "no deferral" in the
evidence.
"""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import capture_claude_shapes as capture
from tools import mcp_stub_server as stub

PLACEHOLDER = {'name': 'DeferredToolPlaceholder',
               'description': 'never call this tool',
               'input_schema': {'type': 'object', 'properties': {}},
               'defer_loading': True}
SEARCH_TOOL = {'name': 'ToolSearch', 'description': 'search',
               'input_schema': {'type': 'object',
                                'properties': {'query': {'type': 'string'}}}}
RELEASED = {'name': 'mcp__stubtools__tool_000', 'description': 'stub',
            'input_schema': {'type': 'object'}, 'defer_loading': True}


def _request(**extra):
    body = {'model': 'z-ai/glm-5.3', 'stream': True, 'max_tokens': 32000,
            'system': [{'type': 'text', 'text': 'You are Claude Code.'}],
            'messages': [{'role': 'user', 'content': 'go'}]}
    body.update(extra)
    return json.dumps(body).encode()


class SummariseTests(unittest.TestCase):
    def test_capture_overrides_parent_gateway_and_uses_an_empty_private_config(self):
        with tempfile.TemporaryDirectory() as folder:
            owner = str(Path(folder) / 'owner-config')

            def client(command, **kwargs):
                env = kwargs['env']
                config = Path(env['CLAUDE_CONFIG_DIR'])
                self.assertNotEqual(str(config), owner)
                self.assertTrue(config.is_dir())
                self.assertEqual(list(config.iterdir()), [])
                self.assertTrue(env['ANTHROPIC_BASE_URL'].startswith('http://127.0.0.1:'))
                self.assertEqual(env.get('CLAUDE_CODE_EFFORT_LEVEL'), 'low')
                self.assertEqual(env.get('CLAUDE_CODE_MAX_RETRIES'), '0')
                self.assertEqual(env.get('CLAUDE_CODE_MAX_OUTPUT_TOKENS'), '2048')
                self.assertNotIn('ANTHROPIC_API_KEY', env)
                return SimpleNamespace(returncode=0, stdout='{}', stderr='')

            with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': owner,
                    'ANTHROPIC_BASE_URL': 'https://parent.invalid',
                    'ANTHROPIC_API_KEY': 'synthetic-owner', 'CLAUDE_CODE_EFFORT_LEVEL': 'max'}), \
                    patch.object(capture.subprocess, 'run', side_effect=client):
                capture.capture('synthetic/model', {}, 0, folder)

    def test_a_deferred_turn_is_reported_as_deferred(self):
        body = _request(tools=[SEARCH_TOOL, dict(PLACEHOLDER)])
        record = capture.summarise(
            body, {'anthropic-beta': 'advanced-tool-use-2025-11-20'})
        self.assertEqual(record['tools'], 2)
        self.assertEqual(record['deferred'], ['DeferredToolPlaceholder'])
        self.assertEqual(record['search_entries'],
                         ['DeferredToolPlaceholder', 'ToolSearch'])
        self.assertEqual(record['mcp_tools'], [])
        self.assertEqual(record['betas'], 'advanced-tool-use-2025-11-20')

    def test_an_undeferred_turn_shows_the_whole_catalogue(self):
        plain = dict(RELEASED)
        plain.pop('defer_loading')
        body = _request(tools=[SEARCH_TOOL, plain])
        record = capture.summarise(body, {})
        self.assertEqual(record['deferred'], [])
        self.assertEqual(record['mcp_tools'], ['mcp__stubtools__tool_000'])

    def test_a_released_tool_stays_flagged_until_the_router_flattens_it(self):
        record = capture.summarise(_request(tools=[dict(RELEASED)]), {})
        self.assertEqual(record['deferred'], ['mcp__stubtools__tool_000'])

    def test_a_released_tool_reference_is_reported(self):
        body = _request(messages=[
            {'role': 'assistant', 'content': [
                {'type': 'tool_use', 'id': 'toolu_1', 'name': 'ToolSearch',
                 'input': {'query': 'select:x'}}]},
            {'role': 'user', 'content': [
                {'type': 'tool_result', 'tool_use_id': 'toolu_1', 'content': [
                    {'type': 'tool_reference',
                     'tool_name': 'mcp__stubtools__tool_000'}]}]}])
        record = capture.summarise(body, {})
        self.assertEqual(record['tool_references'], ['mcp__stubtools__tool_000'])
        self.assertEqual(record['tool_results'][0]['kinds'], ['tool_reference'])

    def test_unreadable_bodies_never_raise(self):
        for body in (b'', b'not json', b'[]'):
            with self.subTest(body=body):
                self.assertIn('bytes', capture.summarise(body, {}))

    def test_the_stub_catalogue_is_named_for_the_client_namespace(self):
        self.assertEqual([tool['name'] for tool in stub.stub_tools(2)],
                         ['tool_000', 'tool_001'])


if __name__ == '__main__':
    unittest.main()
