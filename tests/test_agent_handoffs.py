"""Plaintext aliases preserve the native execution and encryption contracts."""
from copy import deepcopy
import unittest

from codex_router import agent_handoffs as handoffs


def native_tools(*names):
    return [{'type': 'namespace', 'name': 'collaboration', 'tools': [
        {'type': 'function', 'name': name, 'description': 'Native operation.',
         'parameters': {'type': 'object', 'properties': {
             'message': {'type': 'string', 'encrypted': True},
             'target': {'type': 'string'}}, 'required': ['message', 'target'],
             'additionalProperties': False}, 'strict': True} for name in names]}]


def alias_call(**changes):
    return {'type': 'function_call', 'namespace': 'collaboration_plaintext',
            'name': 'send_message', 'arguments': '{"message":"synthetic","count":8.0}',
            'id': 'fc_synthetic', 'call_id': 'call_synthetic', **changes}


class AliasContractTests(unittest.TestCase):
    def test_aliases_preserve_originals_and_every_parameter_constraint(self):
        original = native_tools('send_message', 'followup_task', 'spawn_agent', 'wait_agent')
        before = deepcopy(original)
        payload = {'tools': original}
        self.assertEqual(handoffs.add_plaintext_tools(payload), handoffs.HANDOFF_TOOLS)
        self.assertEqual(original, before)
        aliases = payload['tools'][-1]
        self.assertEqual(aliases['name'], 'collaboration_plaintext')
        for alias, native in zip(aliases['tools'], original[0]['tools']):
            expected = deepcopy(native)
            expected['parameters']['properties']['message']['encrypted'] = False
            expected['parameters']['properties']['message']['description'] = alias['parameters']['properties']['message']['description']
            expected['description'] = alias['description']
            self.assertEqual(alias, expected)

    def test_no_native_authority_means_no_aliases(self):
        payload = {'tools': [{'type': 'function', 'name': 'send_message'}]}
        before = deepcopy(payload)
        self.assertEqual(handoffs.add_plaintext_tools(payload), set())
        self.assertEqual(payload, before)

    def test_collisions_and_changed_message_contract_are_rejected(self):
        collision = {'tools': [*native_tools('send_message'),
                               {'type': 'namespace', 'name': 'collaboration_plaintext'}]}
        malformed = {'tools': native_tools('send_message')}
        malformed['tools'][0]['tools'][0]['parameters']['properties']['message'] = {'type': 'object'}
        duplicate = {'tools': native_tools('send_message', 'send_message')}
        for payload in (collision, malformed, duplicate):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                handoffs.add_plaintext_tools(payload)

    def test_restore_keeps_exact_arguments_and_native_ids(self):
        original = alias_call()
        result = handoffs.restore_item(original, {'send_message'})
        self.assertEqual(result, {**original, 'namespace': 'collaboration', 'encrypted_function_args': []})
        self.assertEqual(original['namespace'], 'collaboration_plaintext')

    def test_unrelated_and_native_encrypted_calls_are_not_rewritten(self):
        for item in (alias_call(namespace='collaboration', encrypted_function_args=['message']),
                     alias_call(namespace='other_namespace')):
            self.assertIs(handoffs.restore_item(item, {'send_message'}), item)

    def test_opaque_or_unadvertised_alias_is_rejected_without_content(self):
        bad = [alias_call(encrypted_function_args=['message']),
               alias_call(encrypted_function_args=None),
               alias_call(name='spawn_agent'), alias_call(type='custom_tool_call')]
        for item in bad:
            with self.subTest(item=item), self.assertRaises(ValueError) as caught:
                handoffs.restore_item(item, {'send_message'})
            self.assertNotIn('synthetic', str(caught.exception))

    def test_sse_and_json_envelopes_get_consistent_restoration(self):
        for phase in ('added', 'done'):
            event = {'type': 'response.output_item.' + phase, 'output_index': 0, 'item': alias_call()}
            restored = handoffs.restore_event(event, {'send_message'})
            self.assertEqual(restored['item']['namespace'], 'collaboration')
            self.assertEqual(restored['item']['encrypted_function_args'], [])
        response = {'id': 'resp_synthetic', 'output': [alias_call()]}
        event = {'type': 'response.completed', 'response': response}
        self.assertEqual(handoffs.restore_event(event, {'send_message'})['response'],
                         handoffs.restore_response(response, {'send_message'}))

    def test_native_events_keep_identity_and_float_spelling(self):
        item = alias_call(namespace='collaboration', encrypted_function_args=['message'])
        response = {'output': [item]}
        event = {'type': 'response.completed', 'response': response}
        self.assertIs(handoffs.restore_event(event, {'send_message'}), event)
        self.assertIn('8.0', event['response']['output'][0]['arguments'])


class PlaintextMessageTests(unittest.TestCase):
    def test_peer_text_boundaries_and_sender_recipient_survive(self):
        item = {'type': 'agent_message', 'author': '/root', 'recipient': '/root/worker',
                'content': [{'type': 'input_text', 'text': 'Assignment\n'},
                            {'type': 'input_text', 'text': 'Read only; do not edit.'}]}
        before = deepcopy(item)
        message = handoffs.plaintext_agent_message(item)
        self.assertEqual(message['role'], 'assistant')
        self.assertEqual(message['content'][0]['text'], 'Agent message from /root to /root/worker:\n')
        self.assertEqual([b['text'] for b in message['content'][1:]],
                         [b['text'] for b in item['content']])
        self.assertEqual(item, before)

    def test_unknown_or_opaque_blocks_are_not_silently_dropped(self):
        base = {'type': 'agent_message', 'author': '/root', 'recipient': '/root/worker'}
        for content in ([], 'text', [{'type': 'input_text', 'text': 42}],
                        [{'type': 'input_text', 'text': 'label'},
                         {'type': 'encrypted_content', 'encrypted_content': 'synthetic'}],
                        [{'type': 'input_image', 'image_url': 'synthetic'}]):
            with self.subTest(content=content), self.assertRaises(ValueError):
                handoffs.plaintext_agent_message({**base, 'content': content})


if __name__ == '__main__':
    unittest.main()
