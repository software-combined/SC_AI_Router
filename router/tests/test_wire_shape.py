"""One tool-pairing rule set, and the refusal fingerprint that carries it.

`wire_shape.pair_problems` backs both the provider-refusal log line and the
test fake's check on every external body, so each rule gets a failing and a
passing shape here. The fingerprint is held to names and counts: synthetic
canary text never appears in it, and no paid request is made.
"""
import json
import unittest
from unittest import mock

from ai_router import wire_shape
from tests.fakes import FakeUpstream, install_fake
from tests.harness import auth_file, post, start_server, test_state

CANARY = 'SYNTH-CANARY-W-5d1e'
MESSAGE = {'type': 'message', 'role': 'user', 'content': 'next'}
REASONING = {'type': 'reasoning', 'summary': []}


def _call(call_id='c1', kind='function_call', **extra):
    return {'type': kind, 'call_id': call_id, **extra}


def _output(call_id='c1', kind='function_call_output', **extra):
    return {'type': kind, 'call_id': call_id, **extra}


class PairProblemTests(unittest.TestCase):
    def test_each_rule_flags_its_shape_and_passes_the_paired_one(self):
        cases = {
            'duplicate_call_id': ([_call(), _output(), _call(), _output()],
                                  [_call(), _output(), _call('c2'), _output('c2')]),
            'orphan_output': ([_output()], [_call(), _output()]),
            'family_mismatch': ([_call(kind='custom_tool_call'), _output()],
                                [_call(kind='custom_tool_call'),
                                 _output(kind='custom_tool_call_output')]),
            'namespace_both': ([_call(namespace='ns'), _output(namespace='ns')],
                               [_call(namespace='ns'), _output()]),
            'interrupted_run': ([_call(), MESSAGE, _output()],
                                [_call(), _output(), MESSAGE]),
            'orphan_call': ([MESSAGE, _call()], [MESSAGE, _call(), _output()]),
        }
        for rule, (broken, paired) in cases.items():
            with self.subTest(rule=rule):
                self.assertEqual(wire_shape.pair_problems(broken), {rule: 1})
                self.assertEqual(wire_shape.pair_problems(paired), {})
        # Counted per interrupting item and per call still open at the end.
        self.assertEqual(
            wire_shape.pair_problems([_call('a'), _call('b'), MESSAGE, MESSAGE]),
            {'interrupted_run': 2, 'orphan_call': 2})

    def test_a_parallel_group_with_reasoning_inside_is_clean(self):
        pairs = [('function_call', 'function_call_output'),
                 ('custom_tool_call', 'custom_tool_call_output'),
                 ('apply_patch_call', 'apply_patch_call_output'),
                 ('computer_call', 'computer_call_output'),
                 ('tool_search_call', 'tool_search_output')]
        calls = [_call(str(index), kind) for index, (kind, _) in enumerate(pairs)]
        outputs = [_output(str(index), kind) for index, (_, kind) in enumerate(pairs)]
        self.assertEqual(wire_shape.pair_problems(
            [MESSAGE, REASONING, *calls, REASONING, *outputs, MESSAGE]), {})

    def test_items_without_a_string_call_id_take_no_part(self):
        # Codex's app-injected standalone outputs carry no call_id at all.
        standalone = {'type': 'function_call_output', 'output': 'delegated'}
        self.assertEqual(wire_shape.pair_problems([standalone, _call(7), 'stray']), {})


class FingerprintTests(unittest.TestCase):
    def test_reasoning_shapes_take_the_most_telling_part(self):
        text = [{'type': 'summary_text', 'text': 's'}]
        items = [{'type': 'reasoning', 'encrypted_content': 'b', 'summary': text},
                 {'type': 'reasoning', 'content': [{'type': 'reasoning_text', 'text': 'c'}],
                  'summary': text},
                 {'type': 'reasoning', 'summary': text},
                 {'type': 'reasoning', 'summary': [], 'encrypted_content': None},
                 {'type': 'reasoning'}]
        shape = wire_shape.fingerprint(json.dumps({'input': items}))
        self.assertEqual(shape['reasoning_shapes'],
                         {'blob': 1, 'content': 1, 'summary': 1, 'bare': 2})
        # Empty buckets are left out, and so is the key without reasoning.
        self.assertEqual(wire_shape.fingerprint(
            json.dumps({'input': items[:1]}))['reasoning_shapes'], {'blob': 1})
        self.assertNotIn('reasoning_shapes',
                         wire_shape.fingerprint(json.dumps({'input': [MESSAGE]})))

    def test_top_level_keys_are_bounded_names_sorted_and_capped(self):
        payload = {'model': 'm', 'input': [], 'k.v-1': 1, 'y' * 40: 1,
                   'z' * 41: 1, 'two words': 1, 'line\n': 1, '': 1}
        self.assertEqual(wire_shape.fingerprint(json.dumps(payload))['top_level_keys'],
                         ['input', 'k.v-1', 'model', 'y' * 40])
        many = {'input': [], **{'f%02d' % index: index for index in range(40)}}
        self.assertEqual(wire_shape.fingerprint(json.dumps(many))['top_level_keys'],
                         ['f%02d' % index for index in range(32)])

    def test_no_content_reaches_the_fingerprint(self):
        body = json.dumps({
            'model': 'm', f'{CANARY} note': CANARY,
            'input': [
                {'type': 'message', 'role': 'user',
                 'content': [{'type': 'input_text', 'text': CANARY}]},
                {'type': 'reasoning', 'encrypted_content': CANARY,
                 'summary': [{'type': 'summary_text', 'text': CANARY}]},
                _call(CANARY, name=CANARY, namespace=CANARY, arguments=CANARY),
                _output(CANARY, namespace=CANARY, output=CANARY),
                _output(CANARY + '-2', 'custom_tool_call_output', output=CANARY)],
            'tools': [{'type': 'function', 'name': CANARY, 'description': CANARY}]})
        shape = wire_shape.fingerprint(body.encode())
        self.assertEqual(shape['pair_problems'], {'namespace_both': 1, 'orphan_output': 1})
        self.assertNotIn(CANARY, json.dumps(shape))

    def test_only_a_json_object_with_an_input_list_has_a_shape(self):
        messages = {'messages': [{'role': 'user', 'content': 'hi'}],
                    'tools': [{'name': 'exec'}]}
        for body in (b'not json', b'\x28\xb5\x2f\xfd\x00', None,
                     bytearray(b'{"input": []}'), json.dumps(['input']),
                     json.dumps({'input': 'a string, not a list'}).encode(),
                     json.dumps(messages).encode()):
            with self.subTest(body=body):
                self.assertEqual(wire_shape.fingerprint(body), {})


class RefusalLogTests(unittest.TestCase):
    def test_an_external_refusal_logs_the_shape_and_no_content(self):
        refusal = json.dumps({'error': {'message': 'Provider returned error'}}).encode()
        install_fake(self, lambda: FakeUpstream(
            400, refusal, [('Content-Type', 'application/json')]))
        server = start_server(test_state(auth_file(self)))
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        payload = {
            'model': 'deepseek/deepseek-v4.1-flash-1017',
            'input': [
                {'type': 'message', 'role': 'user',
                 'content': [{'type': 'input_text', 'text': CANARY}]},
                {'type': 'reasoning', 'summary': [{'type': 'summary_text', 'text': CANARY}]},
                _call(name='exec', arguments=json.dumps({'cmd': CANARY})),
                _output(output=CANARY)],
            'tools': [{'type': 'function', 'name': 'exec', 'description': CANARY,
                       'parameters': {'type': 'object'}}]}
        with mock.patch('ai_router.router.log_event') as log:
            response = post(server.server_port, '/test-token/responses', payload)
            response.read()
        self.assertEqual(response.status, 400)
        rejected = [call.kwargs for call in log.call_args_list
                    if call.args == ('upstream_rejected',)]
        self.assertEqual(len(rejected), 1)
        # Router-set `max_output_tokens` shows the shape is of the prepared body.
        self.assertLessEqual({'input', 'max_output_tokens', 'model', 'tools'},
                             set(rejected[0]['top_level_keys']))
        self.assertEqual(rejected[0]['reasoning_shapes'], {'summary': 1})
        self.assertEqual(rejected[0]['item_kinds']['function_call_output'], 1)
        self.assertNotIn('pair_problems', rejected[0])
        self.assertNotIn(CANARY, json.dumps(rejected))


if __name__ == '__main__':
    unittest.main()
