"""Handoff declarations and marked calls agree on readable messages on both routes."""
from copy import deepcopy
import json
import unittest

from ai_router import errors, provider_defs, request_context
from ai_router.providers import ExternalResponsesProvider, SubscriptionProvider
from ai_router.tool_merge import tool_entries
from tests.test_agent_handoff_providers import Response
from tests.test_agent_handoffs import KEY, NO_KEY, native_tools

HANDOFFS = ('spawn_agent', 'send_message', 'followup_task')
LOCATIONS = ('classic', 'lite', 'discovered')


def payload_for(location):
    tools = native_tools(*HANDOFFS)
    tools.append({**deepcopy(tools[0]), 'name': 'unrelated'})
    if location == 'classic':
        return {'tools': tools, 'input': []}
    if location == 'lite':
        return {'input': [{'type': 'additional_tools', 'role': 'developer',
                          'id': 'at_synthetic', 'tools': tools}]}
    return {'tools': [{'type': 'tool_search', 'parameters': {'type': 'object'}}],
            'input': [{'type': 'tool_search_call', 'call_id': 'search_fixture',
                       'execution': 'client', 'arguments': {'query': 'collaboration'}},
                      {'type': 'tool_search_output', 'call_id': 'search_fixture',
                       'execution': 'client', 'tools': tools}]}


def prepare(provider, payload, model='openai/gpt-6.1-sol', credentials=KEY):
    return provider.prepare(model, '/responses', payload, json.dumps(payload).encode(), {}, credentials)


def declarations(body):
    tools = list(body.get('tools', []))
    for item in body.get('input', []):
        tools.extend(item.get('tools', []))
    return list(tool_entries(tools))


class ExternalHandoffSchemaTests(unittest.TestCase):
    def setUp(self):
        self.external = ExternalResponsesProvider(provider_defs.OPENROUTER)

    def test_all_locations_offer_readable_messages_unless_the_install_is_subscription_only(self):
        for location in LOCATIONS:
            for model in ('openai/gpt-6.1-sol', 'deepseek/deepseek-v4.1-flash'):
                with self.subTest(location=location, model=model):
                    payload = payload_for(location)
                    original = deepcopy(payload)
                    prepared = prepare(self.external, payload, model)
                    self.assertEqual(payload, original)
                    body = json.loads(prepared.body)
                    for name in HANDOFFS:
                        wire = next(key[1] for key, entry in prepared.tool_names.items()
                            if isinstance(entry, dict) and entry['namespace'] == 'collaboration'
                            and entry['name'] == name)
                        schema = next(tool for tool in body['tools'] if tool['name'] == wire)
                        message = schema['parameters']['properties']['message']
                        self.assertIs(message['encrypted'], False)
                        self.assertIn('Do not encrypt', message['description'])
                    for tool, namespace in declarations(body):
                        if namespace == 'collaboration':
                            self.assertIs(tool['parameters']['properties']['message']['encrypted'], False)
                        if namespace == 'unrelated' or tool['name'].startswith('unrelated__'):
                            self.assertIs(tool['parameters']['properties']['message']['encrypted'], True)
                    # A keyed native route hides the canonical handoffs behind readable aliases.
                    for credentials, namespace in ((KEY, 'collaboration_plaintext'), (NO_KEY, 'collaboration')):
                        native = prepare(SubscriptionProvider(), payload, 'gpt-6-astra', credentials)
                        handoff = [(ns, tool) for tool, ns in declarations(json.loads(native.body))
                                   if ns in ('collaboration', 'collaboration_plaintext')]
                        self.assertEqual(sorted(tool['name'] for _, tool in handoff), sorted(HANDOFFS))
                        for ns, tool in handoff:
                            self.assertEqual(ns, namespace)
                            self.assertIs(tool['parameters']['properties']['message']['encrypted'],
                                          credentials is NO_KEY)
                    self.assertEqual(payload, original)

    def test_each_advertised_call_restores_plaintext_and_refuses_explicit_encryption(self):
        for location in LOCATIONS:
            prepared = prepare(self.external, payload_for(location))
            for name in HANDOFFS:
                wire = next(key[1] for key, entry in prepared.tool_names.items()
                    if isinstance(entry, dict) and entry['namespace'] == 'collaboration'
                    and entry['name'] == name)
                call = {'type': 'function_call', 'name': wire, 'call_id': 'synthetic-call',
                        'arguments': json.dumps({'message': 'SYNTH_READABLE_TASK\nKeep this scope.'})}
                for stream in (False, True):
                    with self.subTest(location=location, name=name, stream=stream):
                        value = {'item': call, 'type': 'response.output_item.done'} if stream else {'output': [call]}
                        raw = json.dumps(value).encode()
                        source = Response(b'data: ' + raw + b'\n\n' if stream else raw,
                                          'text/event-stream' if stream else 'application/json')
                        result = b''.join(self.external.adapt(source, prepared.tool_names))
                        decoded = json.loads(result[6:] if stream else result)
                        restored = decoded['item'] if stream else decoded['output'][0]
                        self.assertEqual(restored, {**call, 'namespace': 'collaboration',
                            'name': name, 'encrypted_function_args': []})
                with self.subTest(location=location, name=name, encrypted=True):
                    source = Response(json.dumps({'output': [
                        {**call, 'encrypted_function_args': ['message']}]}).encode())
                    with self.assertRaises(errors.ResponseRejected):
                        b''.join(self.external.adapt(source, prepared.tool_names))

    def test_changed_lite_prefix_is_deterministic_and_tracks_schema_changes(self):
        payload = payload_for('lite')
        first = json.loads(prepare(self.external, payload).body)['input'][0]
        retry = json.loads(prepare(self.external, payload).body)['input'][0]
        native = json.loads(prepare(SubscriptionProvider(), payload, 'gpt-6-astra').body)['input'][0]
        stock = json.loads(prepare(SubscriptionProvider(), payload, 'gpt-6-astra', NO_KEY).body)['input'][0]
        self.assertEqual(first, retry)
        self.assertEqual(native, json.loads(prepare(SubscriptionProvider(), payload, 'gpt-6-astra').body)['input'][0])
        self.assertEqual(len({first['id'], native['id'], stock['id'], payload['input'][0]['id']}), 4)
        changed = deepcopy(payload)
        changed['input'][0]['tools'][0]['tools'][0]['parameters']['properties']['message']['maxLength'] = 500
        self.assertNotEqual(first['id'], json.loads(prepare(self.external, changed).body)['input'][0]['id'])

    def test_effective_authority_keeps_the_captured_request_metadata(self):
        payload = payload_for('discovered')
        payload['stream'] = True
        payload['input'].extend([
            {'type': 'function_call', 'namespace': 'collaboration', 'call_id': 'synthetic-previous',
             'name': 'spawn_agent', 'arguments': json.dumps({'task_name': 'previous_child',
                 'model': 'openai/gpt-6.1-sol', 'message': 'SYNTH_PREVIOUS'})},
            {'type': 'function_call_output', 'call_id': 'synthetic-previous', 'output': 'spawned'}])
        context = request_context.resolve('openai/gpt-6.1-sol', request_context.capture())
        prepared = self.external.prepare(context.slug, '/responses', payload,
            json.dumps(payload).encode(), {}, KEY, context=context)
        authority = prepared.tool_names.handoffs
        self.assertEqual(authority, set(HANDOFFS))
        self.assertEqual(authority.location, 'discovered')
        self.assertIs(authority.catalogue, context.catalogue)
        self.assertEqual(authority.spawn_models, {'previous_child': 'openai/gpt-6.1-sol'})
        self.assertTrue(authority.stream)

    def test_paged_out_handoffs_cannot_grant_a_plaintext_response_signal(self):
        payload = payload_for('lite')
        payload['input'][0]['tools'].extend([
            {'type': 'tool_search', 'parameters': {'type': 'object'}},
            *[{'type': 'function', 'name': f'unused_{index}', 'parameters': {'type': 'object'}}
              for index in range(130)]])
        prepared = prepare(self.external, payload, 'z-ai/glm-5.3-flash')
        self.assertFalse(prepared.tool_names.handoffs)
        call = {'type': 'function_call', 'namespace': 'collaboration', 'name': 'spawn_agent',
                'call_id': 'synthetic-unadvertised', 'arguments': '{"message":"SYNTH"}'}
        source = Response(json.dumps({'output': [call]}).encode())
        restored = json.loads(b''.join(self.external.adapt(source, prepared.tool_names)))['output'][0]
        self.assertEqual(restored, call)


if __name__ == '__main__':
    unittest.main()
