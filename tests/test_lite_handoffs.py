"""The native Lite prefix must activate the same handoff contract as classic."""
from copy import deepcopy
from compression import zstd
import json
import unittest

from ai_router import agent_handoffs as handoffs
from ai_router.providers import SubscriptionProvider
from tests.test_agent_handoffs import alias_call, native_tools
from tests.test_agent_handoff_providers import Response


def lite(tools=None):
    return {'model': 'gpt-6-astra', 'input': [
        {'type': 'additional_tools', 'role': 'developer', 'id': 'at_synthetic',
         'tools': native_tools('spawn_agent', 'send_message', 'followup_task')
         if tools is None else tools},
        {'type': 'message', 'role': 'user', 'content': 'Synthetic control'}]}


class LiteHandoffTests(unittest.TestCase):
    def test_lite_aliases_preserve_native_schemas_and_input_order(self):
        payload = lite()
        original = deepcopy(payload)
        original_items = payload['input']
        names = handoffs.add_plaintext_tools(payload)
        self.assertEqual(names, handoffs.HANDOFF_TOOLS)
        self.assertEqual(original_items, original['input'])
        self.assertNotIn('tools', payload)
        prefix = payload['input'][0]
        self.assertEqual(prefix['tools'][0], original['input'][0]['tools'][0])
        self.assertEqual(prefix['tools'][1]['name'], 'collaboration_plaintext')
        self.assertNotEqual(prefix['id'], original['input'][0]['id'])
        self.assertTrue(prefix['id'].startswith('at_'))
        self.assertEqual(payload['input'][1:], original['input'][1:])

    def test_ids_are_stable_for_retries_and_change_with_schema(self):
        first, retry, changed = lite(), lite(), lite()
        changed['input'][0]['tools'][0]['tools'][0]['description'] = 'Changed constraint'
        for payload in (first, retry, changed):
            handoffs.add_plaintext_tools(payload)
        self.assertEqual(first, retry)
        self.assertNotEqual(first['input'][0]['id'], changed['input'][0]['id'])
        # Reapplying to an already adapted declaration is a collision, as in classic.
        with self.assertRaisesRegex(ValueError, 'collision'):
            handoffs.add_plaintext_tools(first)

    def test_only_native_declarations_grant_alias_authority(self):
        for payload in (lite([]), {'input': [{'type': 'message', 'role': 'user',
                'content': json.dumps(lite())}]}, {'input': [
                {**lite()['input'][0], 'role': 'user'}]}):
            original = deepcopy(payload)
            self.assertFalse(handoffs.add_plaintext_tools(payload))
            self.assertEqual(payload, original)

    def test_duplicate_containers_and_collisions_fail_before_mutation(self):
        duplicate = lite()
        duplicate['tools'] = native_tools('spawn_agent')
        collision = lite()
        collision['tools'] = [{'type': 'namespace', 'name': 'collaboration_plaintext'}]
        repeated = lite()
        repeated['input'].insert(0, deepcopy(repeated['input'][0]))
        malformed = lite()
        malformed['input'][0]['tools'][0]['tools'][0]['parameters']['properties']['message'] = {'type': 'object'}
        for payload in (duplicate, collision, repeated, malformed):
            original = deepcopy(payload)
            with self.assertRaises(ValueError):
                handoffs.add_plaintext_tools(payload)
            self.assertEqual(payload, original)

    def test_provider_restores_aliases_and_steers_external_spawns_on_both_frames(self):
        provider = SubscriptionProvider()
        for streaming in (False, True):
            payload = lite()
            payload['stream'] = streaming
            raw = zstd.compress(json.dumps(payload).encode())
            prepared = provider.prepare('gpt-6-astra', '/responses', payload, raw,
                {'Content-Encoding': 'zstd', 'Accept-Encoding': 'gzip'}, None)
            self.assertNotIn('Content-Encoding', prepared.headers)
            self.assertEqual(prepared.headers['Accept-Encoding'], 'identity')
            native = alias_call(namespace='collaboration', name='spawn_agent',
                arguments=json.dumps({'model': 'gpt-6-sol', 'message': 'opaque-control'}))
            external = {**native, 'arguments': json.dumps({
                'model': 'deepseek/deepseek-v4.1-flash', 'message': 'opaque-control'})}
            output = {'output': [alias_call(), native, external]}
            event = {'type': 'response.completed', 'response': output}
            encoded = json.dumps(event if streaming else output).encode()
            wire = b'data: ' + encoded + b'\n\n' if streaming else encoded
            # The actual native route can omit the SSE content-type label.
            source = Response(wire, '' if streaming else 'application/json')
            result = b''.join(provider.adapt(source, prepared.tool_names))
            decoded = json.loads(result[6:] if streaming else result)
            items = (decoded['response'] if streaming else decoded)['output']
            self.assertEqual(items[0], {**alias_call(), 'namespace': 'collaboration',
                                       'encrypted_function_args': []})
            self.assertEqual(items[1], native)
            self.assertEqual(items[2]['type'], 'function_call')
            self.assertEqual(items[2]['call_id'], external['call_id'])
            self.assertIsInstance(json.loads(items[2]['arguments']), str)
            self.assertNotIn('opaque-control', items[2]['arguments'])

    def test_lite_without_handoff_keeps_compressed_bytes(self):
        payload = lite([])
        raw = zstd.compress(json.dumps(payload).encode())
        prepared = SubscriptionProvider().prepare('gpt-6-astra', '/responses',
            payload, raw, {'Content-Encoding': 'zstd'}, None)
        self.assertEqual(prepared.body, raw)
        self.assertEqual(prepared.headers['Content-Encoding'], 'zstd')


if __name__ == '__main__':
    unittest.main()
