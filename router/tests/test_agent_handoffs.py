"""Readable handoffs keep the native execution contract on one tool surface."""
from copy import deepcopy
import unittest
from types import SimpleNamespace

from ai_router import agent_handoffs as handoffs, errors, history_items

# Native readability follows the install: whether its external key resolves.
KEY = SimpleNamespace(key_for=lambda _=None: 'synthetic-key', key_missing=lambda _: None)
NO_KEY = SimpleNamespace(key_missing=lambda _: LookupError('no external key'))
CIPHERTEXT = 'gAAAAA' + 'Synthetic_Ciphertext-0123456789' * 3 + '=='


def native_tools(*names):
    return [{'type': 'namespace', 'name': 'collaboration', 'tools': [
        {'type': 'function', 'name': name, 'description': 'Native operation.',
         'parameters': {'type': 'object', 'properties': {
             'message': {'type': 'string', 'encrypted': True},
             'target': {'type': 'string'}}, 'required': ['message', 'target'],
             'additionalProperties': False}, 'strict': True} for name in names]}]


def handoff_call(**changes):
    return {'type': 'function_call', 'namespace': 'collaboration',
            'name': 'send_message', 'arguments': '{"message":"synthetic","count":8.0}',
            'id': 'fc_synthetic', 'call_id': 'call_synthetic', **changes}


class ReadableContractTests(unittest.TestCase):
    def test_handoffs_move_readable_into_the_plaintext_namespace(self):
        original = native_tools('send_message', 'followup_task', 'spawn_agent', 'wait_agent')
        payload = {'tools': original}
        before = deepcopy(payload)
        prepared, names = handoffs.native_handoffs(payload, True)
        self.assertEqual(payload, before)
        self.assertEqual(names, handoffs.HANDOFF_TOOLS)
        canonical, alias = prepared['tools']
        # The backend requires canonical handoffs to stay encrypted, so none remain.
        self.assertEqual(canonical, {**original[0], 'tools': [original[0]['tools'][3]]})
        self.assertEqual((alias['name'], alias['description']),
                         ('collaboration_plaintext', handoffs.PLAINTEXT_DESCRIPTION))
        for new, old in zip(alias['tools'], original[0]['tools']):
            expected = deepcopy(old)
            expected['parameters']['properties']['message'].update(
                encrypted=False, description=handoffs.READABLE_MESSAGE)
            expected['description'] = new['description']
            self.assertEqual(new, expected)

    def test_the_plaintext_namespace_follows_its_own_and_an_emptied_one_is_dropped(self):
        stub = {'type': 'function', 'name': 'send_message', 'description': 'Deferred.'}
        tools = [{'type': 'function', 'name': 'exec_command'},
                 {'type': 'namespace', 'name': 'collaboration',
                  'tools': [*native_tools('spawn_agent')[0]['tools'], stub]},
                 {'type': 'namespace', 'name': 'multi_agent_v1',
                  'tools': [{'type': 'function', 'name': 'spawn_agent'}]}]
        payload, names = handoffs.native_handoffs({'tools': tools}, True)
        self.assertEqual([tool['name'] for tool in payload['tools']],
                         ['exec_command', 'collaboration_plaintext', 'multi_agent_v1'])
        spawn, moved = payload['tools'][1]['tools']
        self.assertEqual(moved, stub)  # A stub without a message schema moves as it is.
        self.assertTrue(spawn['description'].endswith(handoffs.SPAWN_HINT))
        self.assertEqual(names, {'spawn_agent'})
        self.assertIs(handoffs.native_handoffs(payload, True)[0], payload)

    def test_only_the_declared_handoffs_become_readable(self):
        _, names = handoffs.native_handoffs({'tools': native_tools('spawn_agent', 'wait_agent')}, True)
        self.assertEqual(names, {'spawn_agent'})
        self.assertFalse(handoffs.native_handoffs({'tools': native_tools('wait_agent')}, True)[1])

    def test_an_install_without_an_external_key_keeps_the_stock_contract(self):
        payload = {'tools': native_tools('spawn_agent', 'send_message')}
        prepared, names = handoffs.native_handoffs(payload, False)
        self.assertFalse(names)
        spawn, send = prepared['tools'][0]['tools']
        self.assertIs(send, payload['tools'][0]['tools'][1])
        self.assertEqual(spawn, {**payload['tools'][0]['tools'][0],
                                 'description': 'Native operation.\n' + handoffs.LANE_HINT})

    def test_one_encrypted_declaration_withholds_the_marker(self):
        listed = native_tools('spawn_agent', 'send_message')
        stub = listed[0]['tools'][0]['parameters']['properties']
        stub['message'] = {'type': ['string', 'null'], 'encrypted': True}
        payload = {'tools': native_tools('spawn_agent', 'send_message'),
                   'input': [{'type': 'tool_search_output', 'call_id': 's1', 'tools': listed}]}
        self.assertEqual(handoffs.native_handoffs(payload, True)[1], {'send_message'})

    def test_marking_adds_only_the_plaintext_marker(self):
        original = handoff_call()
        marked = handoffs.mark_readable(original, {'send_message'})
        self.assertEqual(marked, {**original, 'encrypted_function_args': []})
        self.assertNotIn('encrypted_function_args', original)
        for item in (handoff_call(encrypted_function_args=[]), handoff_call(name='wait_agent'),
                     handoff_call(namespace='other'), handoff_call(type='custom_tool_call'), 'text'):
            self.assertIs(handoffs.mark_readable(item, {'send_message'}), item)
        self.assertIs(handoffs.mark_readable(original, set()), original)

    def test_alias_calls_return_to_their_canonical_name_with_the_marker(self):
        for changes in ({}, {'encrypted_function_args': []}, {'arguments': '{"message":{"text":"x"}}'}):
            alias = handoff_call(namespace='collaboration_plaintext', **changes)
            with self.subTest(changes=changes):
                self.assertEqual(handoffs.mark_readable(alias, {'send_message'}),
                                 {**alias, 'namespace': 'collaboration', 'encrypted_function_args': []})
        unknown = handoff_call(namespace='collaboration_plaintext', name='close_agent')
        self.assertIs(handoffs.mark_readable(unknown, {'send_message'}), unknown)

    def test_messages_are_classified_without_reading_past_the_fingerprint(self):
        for arguments, shape in (('', 'absent'), ('{"target":"plain"}', 'absent'), ('{broken', 'absent'),
                                 ('{"message":"Read parser.py"}', 'readable'),
                                 ('{"message":"gAAAAshort"}', 'readable'),
                                 ({'message': CIPHERTEXT}, 'ciphertext'),
                                 ('{"message":{"text":"x"}}', 'other')):
            with self.subTest(arguments=arguments):
                self.assertEqual(handoffs.message_shape(handoff_call(arguments=arguments)), shape)

    def test_ciphertext_stays_unmarked_so_the_guard_decides(self):
        opaque = handoff_call(name='spawn_agent', arguments='{"model":"%s","message":"%s"}')
        names = handoffs.ReadableHandoffs({'spawn_agent'})
        external = {**opaque, 'arguments': opaque['arguments'] % ('openai/gpt-6.1-sol', CIPHERTEXT)}
        native = {**opaque, 'arguments': opaque['arguments'] % ('gpt-6-sol', CIPHERTEXT)}
        for item in (external, native):
            self.assertIs(handoffs.mark_readable(item, names), item)
        with self.assertRaises(errors.ResponseRejected) as caught:
            handoffs.validate_handoff(external, names)
        self.assertNotIn(CIPHERTEXT, str(caught.exception))
        self.assertIsNone(handoffs.validate_handoff(native, names))

    def test_an_upstream_encryption_marker_or_alias_ciphertext_is_refused_without_content(self):
        alias = handoff_call(namespace='collaboration_plaintext')
        cases = [*(handoff_call(encrypted_function_args=marker) for marker in (['message'], None, 'message')),
                 {**alias, 'encrypted_function_args': ['message']},
                 {**alias, 'arguments': '{"message":"%s"}' % CIPHERTEXT}]
        for item in cases:
            with self.subTest(item=item), self.assertRaises(errors.ResponseRejected) as caught:
                handoffs.mark_readable(item, {'send_message'})
            self.assertEqual(caught.exception.detail, 'HANDOFF_READABLE_ENCRYPTED')
            self.assertNotIn('synthetic', str(caught.exception))
            self.assertNotIn('collaboration_plaintext', str(caught.exception))


class PlaintextMessageTests(unittest.TestCase):
    def test_peer_text_boundaries_and_sender_recipient_survive(self):
        item = {'type': 'agent_message', 'author': '/root', 'recipient': '/root/worker',
                'content': [{'type': 'input_text', 'text': 'Assignment\n'},
                            {'type': 'input_text', 'text': 'Read only; do not edit.'}]}
        before = deepcopy(item)
        message = history_items.plaintext_agent_message(item)
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
                history_items.plaintext_agent_message({**base, 'content': content})


def encrypted_call(**changes):
    base = {'type': 'function_call', 'namespace': 'collaboration',
            'name': 'followup_task', 'arguments': '{"target":"plain","message":"synthetic"}',
            'id': 'fc_synthetic', 'call_id': 'call_synthetic'}
    base.update(changes)
    return base


def spawn_history(task, model, **fields):
    return {'type': 'function_call', 'namespace': 'collaboration',
            'name': 'spawn_agent',
            'arguments': '{"task_name":"%s","model":"%s"}' % (task, model),
            'id': 'fc_hist', 'call_id': 'call_hist', **fields}


class HandoffPolicyTests(unittest.TestCase):
    def test_spawn_history_maps_every_spawned_child_to_its_model(self):
        items = [spawn_history('plain', 'meta/muse-spark-1.3-contributor',
                               encrypted_function_args=[]),
                 spawn_history('native', 'gpt-6-sol'),
                 {'type': 'message', 'role': 'user', 'content': 'synthetic'}]
        self.assertEqual(handoffs.spawn_models(items),
                         {'plain': 'meta/muse-spark-1.3-contributor',
                          'native': 'gpt-6-sol'})
        self.assertEqual(handoffs.spawn_models('not-a-list'), {})
        bad = [spawn_history('bad', 'm', arguments='{broken')]
        self.assertEqual(handoffs.spawn_models(bad), {})

    def test_encrypted_followup_to_plaintext_child_is_rejected(self):
        names = handoffs.ReadableHandoffs(
            spawn_models={'plain': 'meta/muse-spark-1.3-contributor'})
        original = encrypted_call()
        before = deepcopy(original)
        with self.assertRaises(errors.ResponseRejected) as caught:
            handoffs.validate_handoff(original, names)
        self.assertEqual(original, before)
        self.assertEqual((caught.exception.status, caught.exception.code), (400, 'invalid_prompt'))
        self.assertEqual(caught.exception.detail, 'HANDOFF_REQUIRES_PLAINTEXT')
        self.assertIn("subagent's model cannot read an encrypted message", str(caught.exception))
        self.assertNotIn('collaboration_plaintext', str(caught.exception))
        self.assertNotIn('synthetic', str(caught.exception))

    def test_native_followups_and_unknown_targets_pass_through(self):
        names = handoffs.ReadableHandoffs(
            spawn_models={'plain': 'meta/muse-spark-1.3-contributor'})
        native_spawn = encrypted_call(name='spawn_agent',
            arguments='{"task_name":"n","model":"gpt-6-sol"}')
        self.assertIsNone(handoffs.validate_handoff(native_spawn, names))
        strange = encrypted_call(arguments='{"target":"other","message":"synthetic"}')
        self.assertIsNone(handoffs.validate_handoff(strange, names))
        marked = encrypted_call(encrypted_function_args=[])
        self.assertIsNone(handoffs.validate_handoff(marked, names))

    def test_openrouter_gpt_is_external_despite_sharing_the_native_vendor(self):
        names = handoffs.ReadableHandoffs()
        openrouter = encrypted_call(name='spawn_agent',
            arguments='{"task_name":"x","model":"openai/gpt-6.1-sol"}')
        with self.assertRaisesRegex(errors.ResponseRejected, 'ChatGPT subscription model.*OpenRouter key'):
            handoffs.validate_handoff(openrouter, names)
        self.assertIsNone(handoffs.validate_handoff({**openrouter, 'encrypted_function_args': []}, names))
        for marker in (None, ['message']):
            with self.assertRaises(errors.ResponseRejected):
                handoffs.validate_handoff({**openrouter, 'encrypted_function_args': marker}, names)

    def test_path_targets_resolve_by_unique_suffix(self):
        names = handoffs.ReadableHandoffs(
            spawn_models={'synth_agent': 'meta/muse-spark-1.3-contributor'})
        rooted = encrypted_call(arguments='{"target":"/root/synth_agent","message":"x"}')
        with self.assertRaises(errors.ResponseRejected) as caught:
            handoffs.validate_handoff(rooted, names)
        self.assertEqual(caught.exception.detail, 'HANDOFF_REQUIRES_PLAINTEXT')
        self.assertNotIn('/root/synth_agent', str(caught.exception))
        ambiguous = handoffs.ReadableHandoffs(
            spawn_models={'a/synth_agent': 'meta/muse-spark-1.3-contributor',
                          'b/synth_agent': 'gpt-6-sol'})
        # Unknown or ambiguous targets keep the downstream containment backstop.
        vaguer = encrypted_call(arguments='{"target":"/root/synth_agent","message":"x"}')
        self.assertIsNone(handoffs.validate_handoff(vaguer, ambiguous))


class LaneHintTests(unittest.TestCase):
    def _tools(self, *names, namespace='collaboration'):
        return [{'type': 'namespace', 'name': namespace, 'tools': [
            {'type': 'function', 'name': name, 'description': name + ' tool.'}
            for name in names]}]

    def test_spawn_and_close_gain_the_suffix_once(self):
        original = {'tools': self._tools('spawn_agent', 'close_agent', 'wait_agent')}
        before = deepcopy(original)
        payload = handoffs.hint_full_lanes(original)
        self.assertEqual(original, before)
        spawn, close, wait = payload['tools'][0]['tools']
        self.assertTrue(spawn['description'].endswith(handoffs.LANE_HINT))
        self.assertTrue(close['description'].endswith(handoffs.LANE_HINT))
        self.assertEqual(spawn['description'].count(handoffs.LANE_HINT), 1)
        self.assertNotIn(handoffs.SPAWN_HINT, spawn['description'])
        self.assertIs(wait, original['tools'][0]['tools'][2])
        self.assertIs(handoffs.hint_full_lanes(payload), payload)

    def test_readable_spawn_gets_one_note_and_v1_only_the_lane_hint(self):
        original = {'tools': [*self._tools('spawn_agent', 'wait_agent'),
                              *self._tools('spawn_agent', 'close_agent', namespace='multi_agent_v1')]}
        payload = handoffs.hint_full_lanes(original, plaintext=True)
        (spawn, wait), v1 = payload['tools'][0]['tools'], payload['tools'][1]['tools']
        self.assertEqual(spawn['description'],
                         'spawn_agent tool.\n' + handoffs.LANE_HINT + '\n' + handoffs.SPAWN_HINT)
        self.assertIs(wait, original['tools'][0]['tools'][1])
        for tool in v1:
            self.assertEqual(tool['description'], tool['name'] + ' tool.\n' + handoffs.LANE_HINT)
        self.assertIs(handoffs.hint_full_lanes(payload, plaintext=True), payload)

    def test_search_output_and_lite_prefix_are_hinted(self):
        payload = {
            'input': [
                {'type': 'additional_tools', 'role': 'developer', 'id': 'at_old',
                 'tools': self._tools('spawn_agent', 'wait_agent')},
                {'type': 'tool_search_output', 'call_id': 's1',
                 'tools': self._tools('close_agent', namespace='multi_agent_v1')},
            ]}
        before = deepcopy(payload)
        payload = handoffs.hint_full_lanes(payload)
        self.assertNotEqual(payload, before)
        prefix = payload['input'][0]
        self.assertNotEqual(prefix['id'], 'at_old')
        self.assertTrue(prefix['id'].startswith('at_'))
        self.assertIn(handoffs.LANE_HINT, prefix['tools'][0]['tools'][0]['description'])
        self.assertNotIn(handoffs.LANE_HINT, prefix['tools'][0]['tools'][1]['description'])
        self.assertIn(handoffs.LANE_HINT,
                      payload['input'][1]['tools'][0]['tools'][0]['description'])
        self.assertIs(handoffs.hint_full_lanes(payload), payload)
        self.assertEqual(handoffs.hint_full_lanes(before), payload)


if __name__ == '__main__':
    unittest.main()
