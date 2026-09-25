"""Handoff adapters run at both provider boundaries and preserve credentials."""
from copy import deepcopy
import io
import json
import unittest
from unittest.mock import Mock

from ai_router import agent_handoffs, compaction, providers, upstream
from tests.test_agent_handoffs import alias_call, native_tools
from ai_router.tool_adapter import tool_entries


def _external_responses():
    """OpenRouter Codes adapter; Plan 141 makes adapters per-provider."""
    from ai_router import provider_defs as _defs
    return providers.ExternalResponsesProvider(_defs.OPENROUTER)


class Response(io.BytesIO):
    status = 200

    def __init__(self, body, content_type='application/json', encoding='identity'):
        super().__init__(body)
        self.headers = {'Content-Type': content_type, 'Content-Encoding': encoding}

    def getheader(self, name, default=''):
        return self.headers.get(name, default)


def plaintext(text='SYNTH_ASSIGNMENT'):
    return {'type': 'agent_message', 'author': '/root', 'recipient': '/root/child',
            'content': [{'type': 'input_text', 'text': text}]}


class ProviderTests(unittest.TestCase):
    def prepare(self, provider, tools=None, items=None):
        credentials = Mock()
        credentials.key_for.return_value = 'synthetic-router-key'
        payload = {'model': 'meta/muse-spark-1.3-contributor',
                   'tools': tools or [], 'input': items or []}
        original = deepcopy(payload)
        prepared = provider.prepare(payload['model'], '/responses', payload,
            b'synthetic-compressed-body', {'Authorization': 'Bearer synthetic-subscription',
            'Content-Encoding': 'zstd', 'Accept-Encoding': 'gzip', 'Content-Length': '25'},
            credentials)
        return prepared, credentials, original

    def test_codex_prepare_hints_spawn_and_close(self):
        tools = native_tools('spawn_agent', 'wait_agent')
        tools[0]['tools'].append(
            {'type': 'function', 'name': 'close_agent', 'description': 'Close it.',
             'parameters': {'type': 'object', 'properties': {
                 'target': {'type': 'string'}}, 'required': ['target'],
                 'additionalProperties': False}, 'strict': True})
        for provider in (providers.SubscriptionProvider(), _external_responses()):
            with self.subTest(provider=provider.name):
                prepared, _, original = self.prepare(provider, deepcopy(tools))
                body = json.loads(prepared.body)
                hinted, skipped = [], []
                for tool, _ in tool_entries(body['tools']):
                    name, desc = tool.get('name', ''), tool.get('description', '')
                    base = name.rsplit('__', 1)[-1]
                    if base == 'wait_agent':
                        skipped.append(desc)
                    elif base in agent_handoffs.LANE_HINT_NAMES:
                        hinted.append(desc)
                self.assertTrue(hinted)
                self.assertTrue(all(agent_handoffs.LANE_HINT in desc for desc in hinted))
                self.assertTrue(all(agent_handoffs.LANE_HINT not in desc for desc in skipped))
                self.assertNotIn(agent_handoffs.LANE_HINT,
                                 original['tools'][0]['tools'][0]['description'])

    def test_native_reserialized_headers_and_encrypted_tools(self):
        prepared, credentials, original = self.prepare(providers.SubscriptionProvider(),
                                                       native_tools('spawn_agent'))
        body = json.loads(prepared.body)
        native = body['tools'][0]
        self.assertEqual(native['name'], 'collaboration')
        self.assertEqual(native['tools'][0]['name'], 'spawn_agent')
        self.assertIn(agent_handoffs.LANE_HINT, native['tools'][0]['description'])
        self.assertEqual(prepared.headers['Authorization'], 'Bearer synthetic-subscription')
        self.assertEqual(prepared.headers['Accept-Encoding'], 'identity')
        self.assertFalse(any(k.lower() in ('content-length', 'content-encoding')
                             for k in prepared.headers))
        credentials.key_for.assert_not_called()

    def test_native_without_collaboration_preserves_body_and_encoding(self):
        prepared, credentials, _ = self.prepare(providers.SubscriptionProvider())
        self.assertEqual(prepared.body, b'synthetic-compressed-body')
        self.assertEqual(prepared.headers['Content-Encoding'], 'zstd')
        credentials.key_for.assert_not_called()

    def test_plaintext_conversion_order_summary_and_openrouter_credentials(self):
        before = {'type': 'message', 'role': 'user', 'content': 'SYNTH_BEFORE'}
        after = {'type': 'message', 'role': 'assistant', 'content': 'SYNTH_AFTER'}
        prepared, credentials, _ = self.prepare(_external_responses(),
            items=[before, plaintext('SYNTH_ASSIGNMENT\nDo not edit.'), after])
        items = json.loads(prepared.body)['input']
        self.assertEqual(items[0], before)
        self.assertEqual(items[3], after)
        self.assertEqual(items[1]['type'], 'function_call')
        self.assertEqual(items[2]['type'], 'function_call_output')
        self.assertEqual(items[1]['call_id'], items[2]['call_id'])
        self.assertEqual(items[2]['output'],
            'Agent message from /root to /root/child:\nSYNTH_ASSIGNMENT\nDo not edit.')
        summary = compaction.transcript_for_summary([plaintext('SYNTH_SCOPE')])
        for value in ('/root', '/root/child', 'SYNTH_SCOPE'):
            self.assertIn(value, summary)
        self.assertEqual(prepared.headers, {'Authorization': 'Bearer synthetic-router-key',
            'Content-Type': 'application/json', 'Accept-Encoding': 'identity',
            'X-OpenRouter-Metadata': 'enabled'})
        self.assertEqual(prepared.host, 'openrouter.ai')
        credentials.key_for.assert_called_once_with('openrouter')

    def test_opaque_initial_followup_and_compact_fail_before_key_lookup(self):
        opaque = plaintext()
        opaque['content'].append({'type': 'encrypted_content', 'encrypted_content': 'SYNTH_OPAQUE'})
        for path in ('/responses', '/responses/compact'):
            for items in ([opaque], [plaintext(), opaque]):
                credentials = Mock()
                with self.subTest(path=path), self.assertRaises(providers.PreparationError):
                    _external_responses().prepare('z-ai/glm-5.3', path,
                        {'input': items}, b'', {}, credentials)
                credentials.key_for.assert_not_called()

    def test_openrouter_json_and_sse_aliases_restore_native_call_ids(self):
        provider = _external_responses()
        prepared, _, _ = self.prepare(provider, native_tools('send_message'))
        wire = next(name for (_, name), info in prepared.tool_names.items()
                    if info['namespace'] == 'collaboration_plaintext')
        call = alias_call(namespace=None, name=wire)
        response = {'model': 'synthetic-served', 'output': [call]}
        for streaming in (False, True):
            event = {'type': 'response.completed', 'response': response}
            raw = (b'data: ' + json.dumps(event).encode() + b'\n\n' if streaming
                   else json.dumps(response).encode())
            source = Response(raw, 'text/event-stream' if streaming else 'application/json')
            result = b''.join(provider.adapt(source, prepared.tool_names))
            decoded = json.loads(result[6:] if streaming else result)
            item = (decoded['response'] if streaming else decoded)['output'][0]
            self.assertEqual(item['namespace'], 'collaboration')
            self.assertEqual(item['name'], 'send_message')
            self.assertEqual(item['encrypted_function_args'], [])
            self.assertEqual(item['call_id'], call['call_id'])
            self.assertEqual(item['id'], call['id'])

    def test_peer_reply_ends_in_matched_result_without_assistant_prefill(self):
        original = [plaintext('SYNTH_FIRST'), plaintext('SYNTH_LAST')]
        prepared, _, before = self.prepare(_external_responses(), items=original)
        items = json.loads(prepared.body)['input']
        self.assertEqual([i['type'] for i in items],
                         ['function_call', 'function_call_output'] * 2)
        self.assertEqual(len({i['call_id'] for i in items}), 2)
        for call, output in zip(items[::2], items[1::2]):
            self.assertEqual(call['call_id'], output['call_id'])
            self.assertEqual(call['arguments'], '{}')
            self.assertNotIn('namespace', call)
            self.assertNotIn('namespace', output)
        self.assertTrue(items[-1]['output'].endswith('SYNTH_LAST'))
        self.assertEqual(original, before['input'])

    def test_external_native_handoffs_execute_as_plaintext_in_json_and_stream(self):
        provider = _external_responses()
        history = [{'type': 'function_call', 'namespace': 'collaboration',
                    'name': 'spawn_agent', 'call_id': 'call_spawn',
                    'arguments': json.dumps({'task_name': 'child',
                        'model': 'deepseek/deepseek-v4.1-flash'})},
                   {'type': 'function_call_output', 'call_id': 'call_spawn',
                    'output': 'synthetic spawned'}]
        for name in ('spawn_agent', 'followup_task', 'send_message'):
            prepared, _, _ = self.prepare(provider, native_tools(name), deepcopy(history))
            wire = next(w for (_, w), info in prepared.tool_names.items()
                        if info['namespace'] == 'collaboration')
            args = {'task_name': 'child', 'model': 'deepseek/deepseek-v4.1-flash',
                    'target': '/root/child', 'message': 'SYNTH_SECRET_BRIEF'}
            for native in (False, True):
                call = {'type': 'function_call', 'name': name if native else wire,
                        'call_id': 'call_next', 'arguments': json.dumps(args)}
                if native:
                    call['namespace'] = 'collaboration'
                for stream in (False, True):
                    response = {'output': [call]}
                    raw = (b'data: ' + json.dumps({'type': 'response.output_item.done',
                           'item': call}).encode() + b'\n\n' if stream
                           else json.dumps(response).encode())
                    source = Response(raw, 'text/event-stream' if stream else 'application/json')
                    result = b''.join(provider.adapt(source, prepared.tool_names))
                    decoded = json.loads(result[6:] if stream else result)
                    item = decoded['item'] if stream else decoded['output'][0]
                    self.assertEqual(item['type'], 'function_call')
                    self.assertEqual(item['call_id'], 'call_next')
                    self.assertEqual(item['namespace'], 'collaboration')
                    self.assertEqual(item['name'], name)
                    self.assertEqual(item['encrypted_function_args'], [])
                    self.assertEqual(json.loads(item['arguments']), args)

    def test_external_plaintext_signal_requires_advertisement_and_readable_fields(self):
        call = {'type': 'function_call', 'namespace': 'collaboration',
                'name': 'send_message', 'arguments': '{"message":"SYNTH"}'}
        self.assertIs(agent_handoffs.external_plaintext_call(call, set()), call)
        opaque = {**call, 'encrypted_function_args': ['message']}
        with self.assertRaisesRegex(ValueError, 'encrypted external'):
            agent_handoffs.external_plaintext_call(opaque, {'send_message'})
        self.assertNotIn('encrypted_function_args', call)

    def test_adapted_responses_reject_unsupported_encoding(self):
        for provider in (providers.SubscriptionProvider(), _external_responses()):
            prepared, _, _ = self.prepare(provider, native_tools('send_message'))
            for encoding in ('gzip', 'zstd', 'br'):
                with self.subTest(provider=provider.name, encoding=encoding):
                    with self.assertRaisesRegex(ValueError, 'encoding'):
                        upstream.validate_response(Response(b'', encoding=encoding), prepared)


class NativeStreamTests(unittest.TestCase):
    def test_missing_content_type_uses_the_requested_streaming_contract(self):
        payload = {'stream': True, 'tools': native_tools('send_message')}
        _, names = agent_handoffs.add_plaintext_tools(payload)
        event = {'type': 'response.output_item.done', 'item': alias_call()}
        source = Response(b'data: ' + json.dumps(event).encode() + b'\n\n', '')
        result = b''.join(agent_handoffs.adapt_response(source, names))
        self.assertEqual(json.loads(result[6:])['item']['encrypted_function_args'], [])

    def test_json_alias_restoration_keeps_native_calls_exact(self):
        native = alias_call(namespace='collaboration', encrypted_function_args=['message'])
        response = {'model': 'synthetic-served', 'output': [native, alias_call()]}
        notes = {}
        result = json.loads(b''.join(providers.SubscriptionProvider().adapt(
            Response(json.dumps(response).encode()), {'send_message'}, notes)))
        self.assertEqual(result['output'][0], native)
        self.assertEqual(result['output'][1]['encrypted_function_args'], [])
        self.assertEqual(notes['served_model'], 'synthetic-served')

    def test_fragmented_native_stream_keeps_frames_and_alias_arguments(self):
        native = b'data: {"type":"response.output_item.done","item":{"type":"function_call","namespace":"collaboration","name":"send_message","arguments":"{\\"count\\":8.0}"}}\r\n\r\n'
        event = {'type': 'response.output_item.done', 'item': alias_call()}
        alias = b'id: synthetic\n: comment\ndata: ' + json.dumps(event).encode() + b'\n\n'
        class Fragmented(io.RawIOBase):
            def __init__(self, raw):
                self.raw = io.BytesIO(raw)
            def readable(self):
                return True
            def readinto(self, buffer):
                chunk = self.raw.read(min(len(buffer), 3))
                buffer[:len(chunk)] = chunk
                return len(chunk)
        source = io.BufferedReader(Fragmented(native + alias + b'data: [DONE]\n\n'))
        source.getheader = lambda name, default='': 'text/event-stream' if name == 'Content-Type' else default
        result = b''.join(agent_handoffs.adapt_response(source, {'send_message'}))
        self.assertTrue(result.startswith(native))
        self.assertIn(b'id: synthetic\n: comment\n', result)
        self.assertIn(b'data: [DONE]\n\n', result)
        mapped = json.loads(result[len(native):].split(b'data: ', 1)[1].split(b'\n\n')[0])
        self.assertEqual(mapped['item']['arguments'], alias_call()['arguments'])
        self.assertEqual(mapped['item']['encrypted_function_args'], [])
        source.close()

    def test_truncated_event_and_encrypted_alias_fail(self):
        for raw in (b'data: {', b'data: ' + json.dumps({'type': 'response.output_item.done',
                        'item': alias_call(encrypted_function_args=['message'])}).encode() + b'\n\n'):
            with self.assertRaises(ValueError):
                list(agent_handoffs.adapt_response(Response(raw, 'text/event-stream'), {'send_message'}))


class SteerWiringTests(unittest.TestCase):
    def test_subscription_steers_doomed_wake_followup(self):
        spawn = {'type': 'function_call', 'namespace': 'collaboration',
                 'name': 'spawn_agent', 'id': 'fc_hist', 'call_id': 'call_hist',
                 'arguments': json.dumps({'task_name': 'plain',
                     'model': 'meta/muse-spark-1.3-contributor'}),
                 'encrypted_function_args': []}
        credentials = Mock()
        payload = {'model': 'gpt-6-luna', 'tools': native_tools('followup_task'),
                   'input': [spawn]}
        prepared = providers.SubscriptionProvider().prepare(
            payload['model'], '/responses', payload, b'', {}, credentials)
        self.assertEqual(prepared.tool_names.spawn_models,
                         {'plain': 'meta/muse-spark-1.3-contributor'})
        wake = {'type': 'function_call', 'namespace': 'collaboration',
                'name': 'followup_task', 'id': 'fc_wake', 'call_id': 'call_wake',
                'arguments': json.dumps({'target': 'plain', 'message': 'SYNTH_WAKE'})}
        event = {'type': 'response.output_item.done', 'item': wake}
        raw = b'data: ' + json.dumps(event).encode() + b'\n\n'
        result = b''.join(providers.SubscriptionProvider().adapt(
            Response(raw, 'text/event-stream'), prepared.tool_names))
        item = json.loads(result[6:])['item']
        self.assertEqual(item['type'], 'function_call')
        self.assertEqual(item['call_id'], 'call_wake')
        self.assertIsInstance(json.loads(item['arguments']), str)
        self.assertIn('collaboration_plaintext.followup_task', item['arguments'])
        self.assertNotIn('SYNTH_WAKE', item['arguments'])
        credentials.key_for.assert_not_called()

    def test_subscription_leaves_native_followup_alone(self):
        credentials = Mock()
        payload = {'model': 'gpt-6-luna', 'tools': native_tools('followup_task'),
                   'input': []}
        prepared = providers.SubscriptionProvider().prepare(
            payload['model'], '/responses', payload, b'', {}, credentials)
        call = {'type': 'function_call', 'namespace': 'collaboration',
                'name': 'followup_task', 'id': 'fc_n', 'call_id': 'call_n',
                'arguments': json.dumps({'target': 'native', 'message': 'SYNTH_OPAQUE'})}
        event = {'type': 'response.output_item.done', 'item': call}
        raw = b'data: ' + json.dumps(event).encode() + b'\n\n'
        result = b''.join(providers.SubscriptionProvider().adapt(
            Response(raw, 'text/event-stream'), prepared.tool_names))
        self.assertEqual(json.loads(result[6:])['item'], call)


if __name__ == '__main__':
    unittest.main()
