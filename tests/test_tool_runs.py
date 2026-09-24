"""The shared pairing model reads call and output ids in item order (Plan 183)."""
import unittest

from ai_router.tool_runs import open_calls, pairs


def call(call_id, kind='function_call'):
    return {'type': kind, 'call_id': call_id, 'name': 'exec', 'arguments': '{}'}


def output(call_id, kind='function_call_output'):
    return {'type': kind, 'call_id': call_id, 'output': 'ok'}


class ToolRunsTests(unittest.TestCase):
    def test_a_parallel_group_pairs_each_call_with_its_later_output(self):
        items = [call('a'), call('s', 'tool_search_call'), {'type': 'reasoning'},
                 output('a'), output('s', 'tool_search_output')]
        self.assertEqual(pairs(items), {'a': (0, 3), 's': (1, 4)})
        self.assertEqual(open_calls(items), {})

    def test_an_output_before_its_call_answers_nothing(self):
        items = [output('early'), call('early'), call('b'),
                 {'type': 'message', 'role': 'user', 'content': 'next'}]
        self.assertEqual(pairs(items), {})
        self.assertEqual(open_calls(items), {'early': 1, 'b': 2})

    def test_a_repeated_id_keeps_its_first_open_and_first_answered_call(self):
        items = [call('a'), call('a'), output('a'), call('a'), output('a'), call('a')]
        self.assertEqual(pairs(items), {'a': (0, 2)})
        self.assertEqual(open_calls(items), {'a': 5})

    def test_only_string_ids_on_tool_items_take_part(self):
        items = [call(7), output(7), 'text', {'type': 'message', 'call_id': 'm'},
                 output('m')]
        self.assertEqual((pairs(items), open_calls(items)), ({}, {}))
        self.assertEqual((pairs('not a list'), open_calls(None)), ({}, {}))


if __name__ == '__main__':
    unittest.main()
