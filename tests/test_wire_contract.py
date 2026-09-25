"""The learnt wire contract: a broken and a clean shape for every rule.

`wire_shape.violations` checks a prepared Responses payload against the rules
that bind its dialect, at the level and target Plan 181's table gives, and
the refusal fingerprint carries the same facts. Results stay names and
counts: canary text in content, arguments, outputs and tool descriptions
never reaches one. No request leaves the process.
"""
import inspect
import json
import re
import unittest
from compression import zstd
from unittest import mock

from ai_router import compaction, provider_defs, rejected_repair, wire_shape

SUBSCRIPTION = provider_defs.DIALECT_OPENAI
EXTERNAL = provider_defs.DIALECT_OPENROUTER
COMPATIBLE = provider_defs.DIALECT_OPENAI_COMPATIBLE
TARGETS = {'both': (SUBSCRIPTION, EXTERNAL, COMPATIBLE),
           'external': (EXTERNAL, COMPATIBLE), 'subscription': (SUBSCRIPTION,)}
EMPTY = {'violations': {}, 'warnings': {}, 'unknown_top_level': []}
CANARY = 'SYNTH-CANARY-181-7c3a'
USER = {'type': 'message', 'role': 'user', 'content': 'next'}


def _call(call_id='c1', kind='function_call', **extra):
    return {'type': kind, 'call_id': call_id, **extra}


def _output(call_id='c1', kind='function_call_output', **extra):
    return {'type': kind, 'call_id': call_id, **extra}


def _reasoning(**extra):
    return {'type': 'reasoning', 'id': 'rs_1', 'summary': [], **extra}


def _body(*items, model='z-ai/glm-5.3', **fields):
    return {'model': model, 'input': list(items), **fields}


CUSTOM = _call(kind='custom_tool_call')
ROUTER_BLOB = {'type': 'compaction', 'encrypted_content': compaction.PREFIX + 'c3VtbWFyeQ=='}
NATIVE_BLOB = {'type': 'compaction', 'encrypted_content': 'gAAAA-native'}
# rule: (target, level, a payload breaking it once, the nearest clean payload)
CASES = {
    'pair.family_mismatch': ('both', 'violations', _body(CUSTOM, _output()),
                             _body(CUSTOM, _output(kind='custom_tool_call_output'))),
    'pair.orphan_output': ('both', 'violations', _body(_output()), _body(_call(), _output())),
    'pair.orphan_call': ('both', 'warnings', _body(USER, _call()),
                         _body(USER, _call(), _output())),
    'pair.duplicate_call_id': ('both', 'warnings', _body(_call(), _output(), _call(), _output()),
                               _body(_call(), _output(), _call('c2'), _output('c2'))),
    'run.interrupted': ('external', 'violations', _body(_call(), USER, _output()),
                        _body(_call(), _output(), USER)),
    'pair.namespace_both': ('external', 'violations',
                            _body(_call(namespace='ns'), _output(namespace='ns')),
                            _body(_call(namespace='ns'), _output())),
    'output.standalone': ('external', 'violations',
                          _body({'type': 'function_call_output', 'output': 'delegated'}),
                          _body(_call(), _output())),
    'item.agent_message': ('external', 'violations',
                           _body({'type': 'agent_message', 'content': []}), _body(USER)),
    # DeepSeek alone took a compaction item as sent.
    'item.unverified_type': ('external', 'warnings', _body(NATIVE_BLOB),
                             _body(NATIVE_BLOB, model='deepseek/deepseek-v4.1-flash')),
    'top_level.forbidden': ('external', 'violations',
                            _body(USER, access_programs={'cyber': True}), _body(USER)),
    'top_level.unknown': ('both', 'warnings', _body(USER, conversation='x'),
                          _body(USER, prompt_cache_key='k')),
    'blob.router_owned': ('subscription', 'violations', _body(ROUTER_BLOB), _body(NATIVE_BLOB)),
    'reasoning.plaintext_content': (
        'subscription', 'violations',
        _body(_reasoning(content=[{'type': 'reasoning_text', 'text': 't'}])),
        _body(_reasoning(encrypted_content='opaque'))),
    'reasoning.id_only': ('subscription', 'warnings', _body(_reasoning()),
                          _body(_reasoning(encrypted_content='opaque'))),
}


class RuleTests(unittest.TestCase):
    def test_every_pairing_rule_maps_to_a_contract_rule(self):
        # A pairing rule added without a mapping would raise inside the
        # refusal log line instead of naming the rule.
        emitted = set(re.findall(r"problems\['([a-z_]+)'\]",
                                 inspect.getsource(wire_shape.pair_problems)))
        self.assertEqual(emitted, set(wire_shape._PAIR_RULES))
        self.assertLessEqual(set(wire_shape._PAIR_RULES.values()), set(wire_shape.CONTRACT))

    def test_every_rule_has_a_case(self):
        self.assertEqual(set(CASES), set(wire_shape.CONTRACT))

    def test_each_rule_fires_once_at_its_level_for_its_targets_only(self):
        for rule, (target, level, broken, clean) in CASES.items():
            for dialect in TARGETS['both']:
                with self.subTest(rule=rule, dialect=dialect):
                    found = wire_shape.violations(dialect, broken)
                    if dialect in TARGETS[target]:
                        self.assertEqual(found[level].get(rule), 1)
                    else:
                        self.assertNotIn(rule, found['violations'] | found['warnings'])
                    clean_found = wire_shape.violations(dialect, clean)
                    self.assertNotIn(rule, clean_found['violations'] | clean_found['warnings'])

    def test_realistic_clean_bodies_break_nothing(self):
        external = _body(
            {'role': 'user', 'content': 'a typeless item with a role is a message'},
            {'type': 'message', 'role': 'developer', 'content': [{'type': 'input_text',
                                                                  'text': '<model_switch>'}]},
            _reasoning(summary=[{'type': 'summary_text', 'text': 's'}]),
            _call('a'), _call('b'), _reasoning(), _output('a'), _output('b'), USER,
            tools=[], instructions='i', max_output_tokens=8, provider={}, stream=True)
        self.assertEqual(wire_shape.violations(EXTERNAL, external), EMPTY)
        subscription = _body(
            USER, _reasoning(encrypted_content='opaque'), NATIVE_BLOB, _call(), _output(),
            model='gpt-6-astra', service_tier='priority', access_programs={}, store=False,
            include=[], client_metadata={}, text={}, reasoning={}, tool_choice='auto',
            parallel_tool_calls=True, prompt_cache_key='k')
        self.assertEqual(wire_shape.violations(SUBSCRIPTION, subscription), EMPTY)

    def test_a_dialect_no_rule_binds_and_a_non_object_find_nothing(self):
        broken = _body(_output(), ROUTER_BLOB, access_programs={}, conversation='x')
        for dialect in (provider_defs.DIALECT_ANTHROPIC, None):
            with self.subTest(dialect=dialect):
                self.assertEqual(wire_shape.violations(dialect, broken), EMPTY)
        for payload in (None, [], 'text'):
            with self.subTest(payload=payload):
                self.assertEqual(wire_shape.violations(EXTERNAL, payload), EMPTY)

    def test_unknown_field_names_are_capped_and_name_shaped(self):
        odd = {'bad name': 1, 'z' * 41: 1, 'line\n': 1, '': 1}
        payload = _body(USER, **{f'u{index:02d}': index for index in range(10)}, **odd)
        found = wire_shape.violations(SUBSCRIPTION, payload)
        self.assertEqual(found['warnings'], {'top_level.unknown': 14})
        self.assertEqual(found['unknown_top_level'], [f'u{index:02d}' for index in range(8)])

    def test_no_content_reaches_a_result(self):
        text = [{'type': 'input_text', 'text': CANARY}]
        payload = {
            'model': CANARY, 'instructions': CANARY, f'{CANARY} note': CANARY,
            'input': [
                {'type': 'message', 'role': 'developer', 'content': text},
                # Like a field name, a type is kept only when name-shaped.
                {'type': f'{CANARY} text', 'content': text},
                _reasoning(content=[{'type': 'reasoning_text', 'text': CANARY}],
                           summary=[{'type': 'summary_text', 'text': CANARY}]),
                {'type': 'compaction', 'encrypted_content': compaction.PREFIX + CANARY},
                _call(CANARY, name=CANARY, namespace=CANARY, arguments=CANARY),
                {'type': 'agent_message', 'content': text},
                _output(CANARY, namespace=CANARY, output=CANARY),
                {'type': 'function_call_output', 'output': CANARY}],
            'tools': [{'type': 'function', 'name': CANARY, 'description': CANARY}]}
        body = json.dumps(payload).encode()
        for dialect in TARGETS['both']:
            with self.subTest(dialect=dialect):
                found = wire_shape.violations(dialect, payload)
                self.assertTrue(found['violations'])
                shape = wire_shape.fingerprint(body, dialect)
                self.assertIn('contract_violations', shape)
                self.assertNotIn(CANARY, json.dumps([found, shape]))


class DecodeTests(unittest.TestCase):
    def test_limits_mirror_their_owners(self):
        self.assertEqual(wire_shape.DECODE_LIMIT, rejected_repair.ZSTD_DECODE_LIMIT)
        self.assertEqual(wire_shape._ROUTER_BLOB, compaction.PREFIX)

    def test_identity_and_zstd_bodies_decode_to_the_object(self):
        raw = json.dumps({'input': []}).encode()
        for body in (raw, raw.decode(), zstd.compress(raw)):
            with self.subTest(body=body):
                self.assertEqual(wire_shape.decode_wire(body), {'input': []})

    def test_anything_else_is_none(self):
        truncated = zstd.compress(b'{"input": []}')[:-3]
        for body in (b'not json', truncated, zstd.compress(b'[1]'), b'[1]', b'\xff{',
                     bytearray(b'{"input": []}'), None, {'input': []}):
            with self.subTest(body=body):
                self.assertIsNone(wire_shape.decode_wire(body))

    def test_zstd_stops_at_the_decode_limit(self):
        raw = b'{"input": []}'
        with mock.patch.object(wire_shape, 'DECODE_LIMIT', len(raw)):
            self.assertEqual(wire_shape.decode_wire(zstd.compress(raw)), {'input': []})
        with mock.patch.object(wire_shape, 'DECODE_LIMIT', len(raw) - 1):
            self.assertIsNone(wire_shape.decode_wire(zstd.compress(raw)))


class FingerprintContractTests(unittest.TestCase):
    MARKER = {'type': 'message', 'role': 'developer',
              'content': [{'type': 'input_text', 'text': '<model_switch> hop'}]}

    def test_contract_facts_join_without_repeating_the_pair_counts(self):
        payload = _body(self.MARKER, CUSTOM, _output(),
                        {'type': 'function_call_output', 'output': 'delegated'},
                        access_programs={})
        body = json.dumps(payload).encode()
        shape = wire_shape.fingerprint(body, EXTERNAL)
        self.assertEqual(shape['pair_problems'], {'family_mismatch': 1})
        self.assertEqual(shape['contract_violations'],
                         {'output.standalone': 1, 'top_level.forbidden': 1})
        self.assertEqual(shape['contract_warnings'], {'item.unverified_type': 1})
        self.assertIs(shape['switch_marker'], True)
        # The compressed body carries the same facts; no dialect, no contract.
        self.assertEqual(wire_shape.fingerprint(zstd.compress(body), EXTERNAL), shape)
        bare = wire_shape.fingerprint(body)
        self.assertEqual({key for key in shape if key not in bare},
                         {'contract_violations', 'contract_warnings'})

    def test_switch_marker_needs_a_developer_or_system_block_opening_on_it(self):
        def marked(role, blocks):
            item = {'type': 'message', 'role': role,
                    'content': [{'type': 'input_text', 'text': text} for text in blocks]}
            return 'switch_marker' in wire_shape.fingerprint(json.dumps(_body(item)))
        self.assertTrue(marked('developer', ['<model_switch> hop']))
        self.assertTrue(marked('system', ['context', '  <model_switch>']))
        self.assertFalse(marked('user', ['<model_switch> hop']))
        self.assertFalse(marked('developer', ['switched: <model_switch>']))


if __name__ == '__main__':
    unittest.main()
