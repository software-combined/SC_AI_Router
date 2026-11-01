"""The native Lite prefix activates the same readable contract as classic."""
from copy import deepcopy
from compression import zstd
import json
from types import SimpleNamespace
import unittest

from ai_router import agent_handoffs as handoffs
from ai_router import provider_defs
from ai_router.providers import ExternalResponsesProvider, SubscriptionProvider
from tests.test_agent_handoffs import KEY, handoff_call, native_tools
from tests.test_agent_handoff_providers import Response


def lite(tools=None):
    return {'model': 'gpt-6-astra', 'input': [
        {'type': 'additional_tools', 'role': 'developer', 'id': 'at_synthetic',
         'tools': native_tools('spawn_agent', 'send_message', 'followup_task')
         if tools is None else tools},
        {'type': 'message', 'role': 'user', 'content': 'Synthetic control'}]}


class LiteHandoffTests(unittest.TestCase):
    def test_lite_handoffs_become_readable_aliases_and_keep_input_order(self):
        payload = lite()
        original = deepcopy(payload)
        original_prefix = payload['input'][0]
        payload, names = handoffs.native_handoffs(payload, True)
        self.assertEqual(names, handoffs.HANDOFF_TOOLS)
        self.assertEqual(names.location, 'lite')
        self.assertEqual(original_prefix, original['input'][0])
        self.assertNotIn('tools', payload)
        prefix = payload['input'][0]
        self.assertEqual([tool['name'] for tool in prefix['tools']], ['collaboration_plaintext'])
        for old, new in zip(original['input'][0]['tools'][0]['tools'], prefix['tools'][0]['tools']):
            expected = deepcopy(old['parameters'])
            expected['properties']['message'].update(
                encrypted=False, description=handoffs.READABLE_MESSAGE)
            self.assertEqual(new['parameters'], expected)
        self.assertNotEqual(prefix['id'], original['input'][0]['id'])
        self.assertTrue(prefix['id'].startswith('at_'))
        self.assertEqual(payload['input'][1:], original['input'][1:])

    def test_ids_are_stable_for_retries_and_change_with_schema(self):
        first, retry, changed = lite(), lite(), lite()
        changed['input'][0]['tools'][0]['tools'][0]['description'] = 'Changed constraint'
        first, retry, changed = (handoffs.native_handoffs(payload, True)[0]
                                 for payload in (first, retry, changed))
        self.assertEqual(first, retry)
        self.assertNotEqual(first['input'][0]['id'], changed['input'][0]['id'])
        # An already readable prefix keeps its identity rather than drifting.
        self.assertIs(handoffs.native_handoffs(first, True)[0], first)

    def test_only_developer_declarations_become_readable(self):
        for payload in (lite([]), {'input': [{'type': 'message', 'role': 'user',
                'content': json.dumps(lite())}]}, {'input': [
                {**lite()['input'][0], 'role': 'user'}]}):
            original = deepcopy(payload)
            self.assertFalse(handoffs.native_handoffs(payload, True)[1])
            self.assertEqual(payload, original)

    def test_provider_marks_readable_spawns_on_both_frames(self):
        provider = SubscriptionProvider()
        for streaming in (False, True):
            payload = lite()
            payload['stream'] = streaming
            raw = zstd.compress(json.dumps(payload).encode())
            prepared = provider.prepare('gpt-6-astra', '/responses', payload, raw,
                {'Content-Encoding': 'zstd', 'Accept-Encoding': 'gzip'}, KEY)
            self.assertNotIn('Content-Encoding', prepared.headers)
            self.assertEqual(prepared.headers['Accept-Encoding'], 'identity')
            native = handoff_call(name='spawn_agent',
                arguments=json.dumps({'model': 'gpt-6-sol', 'message': 'readable-control'}))
            output = {'output': [handoff_call(namespace='collaboration_plaintext'), native]}
            event = {'type': 'response.completed', 'response': output}
            encoded = json.dumps(event if streaming else output).encode()
            wire = b'data: ' + encoded + b'\n\n' if streaming else encoded
            # The actual native route can omit the SSE content-type label.
            source = Response(wire, '' if streaming else 'application/json')
            result = b''.join(provider.adapt(source, prepared.tool_names))
            decoded = json.loads(result[6:] if streaming else result)
            items = (decoded['response'] if streaming else decoded)['output']
            self.assertEqual(items, [{**handoff_call(), 'encrypted_function_args': []},
                                     {**native, 'encrypted_function_args': []}])

    def test_lite_without_handoff_keeps_compressed_bytes(self):
        payload = lite([])
        raw = zstd.compress(json.dumps(payload).encode())
        prepared = SubscriptionProvider().prepare('gpt-6-astra', '/responses',
            payload, raw, {'Content-Encoding': 'zstd'}, None)
        self.assertEqual(prepared.body, raw)
        self.assertEqual(prepared.headers['Content-Encoding'], 'zstd')

    def test_external_lite_declarations_restore_readable_native_calls(self):
        provider = ExternalResponsesProvider(provider_defs.OPENROUTER)
        payload = lite()
        original = deepcopy(payload)
        prepared = provider.prepare('openai/gpt-6.1-sol', '/responses', payload,
            json.dumps(payload).encode(), {}, SimpleNamespace(key_for=lambda _: 'synthetic-key'))
        self.assertTrue(prepared.tool_names)
        self.assertEqual(prepared.tool_names.handoffs, handoffs.HANDOFF_TOOLS)
        projected = json.loads(prepared.body)
        self.assertTrue(projected['tools'])
        prefix = projected['input'][0]
        self.assertNotEqual(prefix['id'], original['input'][0]['id'])
        retry = provider.prepare('openai/gpt-6.1-sol', '/responses', payload,
            json.dumps(payload).encode(), {}, SimpleNamespace(key_for=lambda _: 'synthetic-key'))
        self.assertEqual(json.loads(retry.body)['input'][0], prefix)
        for old, new in zip(original['input'][0]['tools'][0]['tools'], prefix['tools'][0]['tools']):
            expected = deepcopy(old['parameters'])
            if old['name'] in handoffs.HANDOFF_TOOLS:
                expected['properties']['message'].update(
                    encrypted=False, description=handoffs.READABLE_MESSAGE)
            self.assertEqual(expected, new['parameters'])
        native = handoff_call(arguments='{"message":"SYNTH_LITE"}')
        response = Response(json.dumps({'output': [native]}).encode(), 'application/json')
        restored = json.loads(b''.join(provider.adapt(response, prepared.tool_names)))['output'][0]
        self.assertEqual(restored, {**native, 'encrypted_function_args': []})
        self.assertEqual(payload, original)

    def test_external_lite_catalogue_pages_without_pinning_every_declaration(self):
        declarations = [{'type': 'tool_search', 'parameters': {'type': 'object'}},
            *native_tools('spawn_agent'), *[{'type': 'function', 'name': f'unused_{i}',
                'parameters': {'type': 'object'}} for i in range(130)]]
        payload = lite(declarations)
        payload['input'].extend([
            {'type': 'tool_search_call', 'call_id': 'search_fixture', 'execution': 'client',
             'arguments': {'query': 'spawn_agent'}},
            {'type': 'tool_search_output', 'call_id': 'search_fixture', 'execution': 'client',
             'tools': native_tools('spawn_agent')}])
        before = deepcopy(payload)
        provider = ExternalResponsesProvider(provider_defs.OPENROUTER)
        prepared = provider.prepare('z-ai/glm-5.3-flash', '/responses', payload,
            json.dumps(payload).encode(), {}, SimpleNamespace(key_for=lambda _: 'synthetic-key'))
        self.assertEqual(len(json.loads(prepared.body)['tools']), 2)
        self.assertEqual(prepared.tool_names.handoffs, {'spawn_agent'})
        call = handoff_call(name='spawn_agent', arguments='{"message":"SYNTH_PAGED"}')
        response = Response(json.dumps({'output': [call]}).encode(), 'application/json')
        restored = json.loads(b''.join(provider.adapt(response, prepared.tool_names)))['output'][0]
        self.assertEqual(restored, {**call, 'encrypted_function_args': []})
        self.assertEqual(payload, before)


if __name__ == '__main__':
    unittest.main()
