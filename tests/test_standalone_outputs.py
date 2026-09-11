"""Standalone app-injected tool outputs become readable plaintext."""
import unittest
from ai_router.errors import PreparationError
from ai_router.standalone_outputs import materialize_outputs

ENVELOPE = ('<codex_delegation>\n'
            '  <source_thread_id>01a08e3a-0e63-7382-9cf7-bc034d96c726</source_thread_id>\n'
            '  <input>READ-ONLY forensic sub-audit</input>\n'
            '</codex_delegation>')


def delegation(**extra):
    item = {'type': 'function_call_output', 'name': 'create_thread',
            'namespace': 'codex_app', 'output': ENVELOPE}
    item.update(extra)
    return item


def as_text(converted):
    return converted['content'][0]['text']


class MaterializeTests(unittest.TestCase):
    def test_delegation_converts_to_one_prefixed_assistant_message(self):
        item = delegation()
        out = materialize_outputs([item])
        self.assertEqual(len(out), 1)
        converted = out[0]
        self.assertEqual((converted['type'], converted['role']),
                         ('message', 'assistant'))
        self.assertTrue(as_text(converted).startswith(
            'Delegated task message via create_thread:\n'))
        self.assertTrue(as_text(converted).endswith(ENVELOPE))
        self.assertIn('<source_thread_id>01a08e3a-0e63-7382-9cf7-bc034d96c726</source_thread_id>',
                      as_text(converted))

    def test_missing_name_defaults_to_codex_app(self):
        item = delegation()
        del item['name']
        self.assertTrue(as_text(materialize_outputs([item])[0]).startswith(
            'Delegated task message via codex_app:\n'))

    def test_order_preserved_with_neighbours(self):
        before = {'type': 'message', 'role': 'user', 'content': 'hi'}
        after = {'type': 'message', 'role': 'user', 'content': 'bye'}
        out = materialize_outputs([before, delegation(), after])
        self.assertEqual([out[0], out[2]], [before, after])
        self.assertEqual(out[1]['role'], 'assistant')
        self.assertIn('READ-ONLY forensic sub-audit', as_text(out[1]))

    def test_two_standalones_both_convert(self):
        first = delegation(output='first marker')
        second = delegation(name='send_message_to_thread', output='second marker')
        out = materialize_outputs([first, second])
        self.assertEqual(len(out), 2)
        self.assertIn('first marker', as_text(out[0]))
        self.assertIn('second marker', as_text(out[1]))
        self.assertIn('send_message_to_thread', as_text(out[1]))

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
        self.assertEqual(as_text(twice[0]).count('Delegated task message via'), 1)

    def test_text_fields_and_content_blocks_read_verbatim(self):
        for field in ('result', 'content', 'text', 'data'):
            with self.subTest(field=field):
                out = materialize_outputs([delegation(**{field: 'verbatim 719', 'output': ''})])
                self.assertIn('verbatim 719', as_text(out[0]))
        blocks = [{'type': 'text', 'text': 'block one'},
                  {'type': 'input_text', 'text': 'block two'}]
        out = materialize_outputs([delegation(content=blocks, output='')])
        self.assertIn('block one', as_text(out[0]))
        self.assertIn('block two', as_text(out[0]))

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
