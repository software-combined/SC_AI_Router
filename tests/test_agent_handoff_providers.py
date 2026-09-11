"""Handoff adapters run at both provider boundaries and preserve credentials."""
from copy import deepcopy
import io
import json
import unittest
from unittest.mock import Mock

from ai_router import agent_handoffs, compaction, providers, upstream
from tests.test_agent_handoffs import alias_call, native_tools


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

    def test_native_reserialized_headers_and_encrypted_tools(self):
        prepared, credentials, original = self.prepare(providers.SubscriptionProvider(),
                                                       native_tools('spawn_agent'))
        body = json.loads(prepared.body)
        self.assertEqual(body['tools'][0], original['tools'][0])
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
        self.assertEqual(items[2], after)
        self.assertEqual(items[1], agent_handoffs.plaintext_agent_message(
            plaintext('SYNTH_ASSIGNMENT\nDo not edit.')))
        summary = compaction.transcript_for_summary([plaintext('SYNTH_SCOPE')])
        for value in ('/root', '/root/child', 'SYNTH_SCOPE'):
            self.assertIn(value, summary)
        self.assertEqual(prepared.headers, {'Authorization': 'Bearer synthetic-router-key',
            'Content-Type': 'application/json', 'Accept-Encoding': 'identity'})
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
        names = agent_handoffs.add_plaintext_tools(payload)
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
        payload = {'model': 'gpt-5.6-luna', 'tools': native_tools('followup_task'),
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
        self.assertEqual(item['type'], 'function_call_output')
        self.assertEqual(item['call_id'], 'call_wake')
        self.assertIn('collaboration_plaintext.followup_task', item['output'])
        self.assertNotIn('SYNTH_WAKE', item['output'])
        credentials.key_for.assert_not_called()

    def test_subscription_leaves_native_followup_alone(self):
        credentials = Mock()
        payload = {'model': 'gpt-5.6-luna', 'tools': native_tools('followup_task'),
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
