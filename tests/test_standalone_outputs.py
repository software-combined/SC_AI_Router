"""Standalone app-injected tool outputs become matched tool pairs."""
import json
import unittest
from ai_router import tool_aliases
from ai_router.errors import PreparationError
from ai_router.standalone_outputs import (
    DELIVERED_APP_MESSAGE, DELIVERED_MESSAGE, DELIVERED_NAMES,
    OPAQUE_REPLY_NOTE, materialize_outputs)

ENVELOPE = ('<codex_delegation>\n'
            '  <source_thread_id>01a08e3a-0e63-7382-9cf7-bc034d96c726</source_thread_id>\n'
            '  <input>READ-ONLY forensic sub-audit</input>\n'
            '</codex_delegation>')


def delegation(**extra):
    item = {'type': 'function_call_output', 'name': 'create_thread',
            'namespace': 'codex_app', 'output': ENVELOPE}
    item.update(extra)
    return item


def inbound_mixed(**extra):
    item = {'type': 'agent_message', 'author': '/root/router_adversarial',
            'recipient': '/root',
            'content': [{'type': 'input_text', 'text': 'visible result'},
                        {'type': 'encrypted_content', 'encrypted_content': 'CIPHERTEXT'}]}
    item.update(extra)
    return item


def pair_text(out):
    return out[1]['output']


def _prepare_names(namespace, *names):
    from tests.tool_stages import prepare_tools
    tools = [{'type': 'function', 'name': name, 'description': name,
              'parameters': {'type': 'object'}} for name in names]
    payload = {'model': 'z-ai/glm-5.3',
               'tools': [{'type': 'namespace', 'name': namespace, 'tools': tools}],
               'input': []}
    payload, names = prepare_tools(payload)
    return names, payload


def _inert_candidates(name):
    names, _ = _prepare_names('probe', 'echo')
    return tool_aliases.candidates(names, name)


class MaterializeTests(unittest.TestCase):
    def test_delegation_converts_to_call_plus_output_pair(self):
        item = delegation()
        out = materialize_outputs([item])
        self.assertEqual(len(out), 2)
        call, result = out
        self.assertEqual(call['type'], 'function_call')
        self.assertEqual(result['type'], 'function_call_output')
        self.assertEqual(call['call_id'], result['call_id'])
        self.assertEqual(call['name'], 'create_thread')
        self.assertEqual(call['arguments'], '{}')
        self.assertEqual(pair_text(out), ENVELOPE)
        self.assertNotIn('namespace', call)
        self.assertNotIn('namespace', result)

    def test_missing_name_defaults_to_delivered_app_message(self):
        item = delegation()
        del item['name']
        out = materialize_outputs([item])
        self.assertEqual(out[0]['name'], 'delivered_app_message')
        self.assertEqual(pair_text(out), ENVELOPE)

    def test_delivered_names_are_declared_inert(self):
        self.assertEqual(DELIVERED_MESSAGE, 'delivered_message')
        self.assertEqual(DELIVERED_APP_MESSAGE, 'delivered_app_message')
        self.assertEqual(DELIVERED_NAMES,
                         frozenset(('delivered_message', 'delivered_app_message')))
        self.assertEqual(_inert_candidates(DELIVERED_MESSAGE), [])
        self.assertEqual(_inert_candidates(DELIVERED_APP_MESSAGE), [])

    def test_order_preserved_with_neighbours(self):
        before = {'type': 'message', 'role': 'user', 'content': 'hi'}
        after = {'type': 'message', 'role': 'user', 'content': 'bye'}
        out = materialize_outputs([before, delegation(), after])
        self.assertEqual([out[0], out[3]], [before, after])
        self.assertEqual(out[1]['type'], 'function_call')
        self.assertEqual(out[2]['type'], 'function_call_output')
        self.assertIn('READ-ONLY forensic sub-audit', out[2]['output'])

    def test_two_standalones_both_convert(self):
        first = delegation(output='first marker')
        second = delegation(name='send_message_to_thread', output='second marker')
        out = materialize_outputs([first, second])
        self.assertEqual(len(out), 4)
        self.assertEqual(out[0]['call_id'], out[1]['call_id'])
        self.assertEqual(out[2]['call_id'], out[3]['call_id'])
        self.assertNotEqual(out[1]['call_id'], out[3]['call_id'])
        self.assertIn('first marker', out[1]['output'])
        self.assertIn('second marker', out[3]['output'])
        self.assertEqual(out[2]['name'], 'send_message_to_thread')

    def test_call_id_derives_from_item_id_with_index_fallback(self):
        item = delegation(id='it_719')
        out = materialize_outputs([item])
        self.assertEqual(out[0]['call_id'], 'call_it_719')
        self.assertEqual(out[1]['call_id'], 'call_it_719')
        plain = delegation()
        plain.pop('id', None)
        out = materialize_outputs(['x', 'y', plain])
        self.assertEqual(out[2]['call_id'], 'call_standalone_2')
        self.assertEqual(out[3]['call_id'], 'call_standalone_2')

    def test_matched_pair_and_messages_untouched(self):
        call = {'type': 'function_call', 'name': 'e', 'call_id': 'c1',
                'arguments': '{"v": 1}'}
        result = {'type': 'function_call_output', 'call_id': 'c1', 'output': 'ok'}
        message = {'type': 'message', 'role': 'user', 'content': 'hi'}
        items = [call, result, message]
        self.assertIs(materialize_outputs(items), items)
        self.assertEqual(materialize_outputs([message]), [message])

    def test_same_object_fast_path_when_nothing_converts(self):
        message = {'type': 'message', 'role': 'user', 'content': 'hi'}
        items = [message]
        self.assertIs(materialize_outputs(items), items)
        self.assertEqual(materialize_outputs('do the task'), 'do the task')

    def test_second_pass_is_idempotent(self):
        once = materialize_outputs([delegation()])
        twice = materialize_outputs(once)
        self.assertIs(twice, once)
        self.assertEqual(len(twice), 2)
        self.assertEqual(twice[0]['call_id'], twice[1]['call_id'])

    def test_inbound_mixed_reply_becomes_incomplete_delivered_message(self):
        out = materialize_outputs([inbound_mixed(id='agent_reply')])
        self.assertEqual([item['type'] for item in out],
                         ['function_call', 'function_call_output'])
        self.assertEqual(out[0]['name'], DELIVERED_MESSAGE)
        self.assertEqual(out[0]['call_id'], 'call_agent_reply')
        self.assertIn('/root/router_adversarial to /root', pair_text(out))
        self.assertIn('visible result', pair_text(out))
        self.assertIn(OPAQUE_REPLY_NOTE, pair_text(out))
        self.assertNotIn('CIPHERTEXT', json.dumps(out))
        self.assertNotIn('encrypted_content', json.dumps(out))
        self.assertIs(materialize_outputs(out), out)

    def test_text_fields_and_content_blocks_read_verbatim(self):
        for field in ('result', 'content', 'text', 'data'):
            with self.subTest(field=field):
                out = materialize_outputs([delegation(**{field: 'verbatim 719', 'output': ''})])
                self.assertEqual(out[1]['output'], 'verbatim 719')
        blocks = [{'type': 'text', 'text': 'block one'},
                  {'type': 'input_text', 'text': 'block two'}]
        out = materialize_outputs([delegation(content=blocks, output='')])
        self.assertIn('block one', out[1]['output'])
        self.assertIn('block two', out[1]['output'])

    def test_unsupported_shape_raises_without_item_text(self):
        # No readable field at all: empty strings and missing keys only.
        item = {'type': 'function_call_output', 'name': 'create_thread',
                'output': '', 'text': ''}
        empty = {'type': 'function_call_output', 'name': 'create_thread'}
        with self.assertRaises(PreparationError) as caught:
            materialize_outputs([item])
        self.assertIn('resend as plain text', str(caught.exception))
        self.assertNotIn('create_thread', str(caught.exception))
        with self.assertRaises(PreparationError):
            materialize_outputs([empty])


if __name__ == '__main__':
    unittest.main()
