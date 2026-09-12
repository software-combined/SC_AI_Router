"""Rejected handoffs must execute validation, not masquerade as tool results."""
from copy import deepcopy
import io
import json
import unittest

from ai_router import agent_handoffs as handoffs
from ai_router.providers import SubscriptionProvider
from tests.test_agent_handoff_providers import Response
from tests.test_agent_handoffs import alias_call, encrypted_call, native_tools, spawn_history
from tests.test_lite_handoffs import lite


class HandoffRecoveryTests(unittest.TestCase):
    def test_all_three_rejections_keep_executable_identity_and_discard_opaque_arguments(self):
        for name in sorted(handoffs.HANDOFF_TOOLS):
            for encryption in ({}, {'encrypted_function_args': ['message']}):
                with self.subTest(name=name, encryption=encryption):
                    arguments = {'task_name': 'sensitive-task', 'target': '/root/sensitive-task',
                        'model': 'deepseek/deepseek-v4.1-flash', 'message': 'OPAQUE-SECRET' * 1000}
                    call = encrypted_call(name=name, arguments=json.dumps(arguments), **encryption)
                    original = deepcopy(call)
                    names = handoffs.AliasTools({name}, spawn_models={
                        'sensitive-task': 'deepseek/deepseek-v4.1-flash'})
                    rejected = handoffs.steer_plaintext(call, names)
                    self.assertEqual(call, original)
                    for field in ('type', 'namespace', 'name', 'id', 'call_id'):
                        self.assertEqual(rejected[field], call[field])
                    # Native handlers require an object. This scalar gives a real
                    # validation error before spawning or messaging any child.
                    diagnostic = json.loads(rejected['arguments'])
                    self.assertIsInstance(diagnostic, str)
                    self.assertLess(len(diagnostic), 250)
                    self.assertIn('collaboration_plaintext.' + name, diagnostic)
                    self.assertNotIn('OPAQUE-SECRET', diagnostic)
                    self.assertNotIn('sensitive-task', diagnostic)
                    self.assertEqual(rejected['encrypted_function_args'], [])
                    self.assertNotIn('output', rejected)
                    self.assertIs(handoffs.steer_plaintext(rejected, names), rejected)

    def test_rejected_spawn_replay_does_not_create_a_phantom_external_child(self):
        call = encrypted_call(name='spawn_agent', arguments=json.dumps({
            'task_name': 'plain', 'model': 'deepseek/deepseek-v4.1-flash', 'message': 'OPAQUE'}))
        rejected = handoffs.steer_plaintext(call, handoffs.AliasTools({'spawn_agent'}))
        self.assertEqual(handoffs.spawn_models([rejected]), {})
        retry = {**call, 'encrypted_function_args': [], 'arguments': json.dumps({
            'task_name': 'plain', 'model': 'deepseek/deepseek-v4.1-flash', 'message': 'READABLE'})}
        self.assertEqual(handoffs.spawn_models([rejected, retry]), {
            'plain': 'deepseek/deepseek-v4.1-flash'})

    def test_partial_sse_and_completed_json_preserve_valid_calls_beside_rejection(self):
        native = encrypted_call(arguments='{"target":"native","message":"NATIVE-OPAQUE"}')
        rejected = encrypted_call(name='send_message', arguments=(
            '{"target":"plain","message":"EXTERNAL-OPAQUE"}'), id='fc_bad', call_id='call_bad')
        valid = alias_call(id='fc_good', call_id='call_good')
        response = {'id': 'resp_test', 'status': 'completed', 'output': [native, rejected, valid]}
        for wire_mode in ('classic', 'lite'):
            for streaming in (False, True):
                with self.subTest(wire_mode=wire_mode, streaming=streaming):
                    payload = lite() if wire_mode == 'lite' else {
                        'model': 'gpt-6-astra', 'tools': native_tools('send_message'), 'input': []}
                    payload['stream'] = streaming
                    payload['input'].append(spawn_history('plain', 'deepseek/deepseek-v4.1-flash'))
                    provider = SubscriptionProvider()
                    prepared = provider.prepare('gpt-6-astra', '/responses', payload, b'', {}, None)
                    if streaming:
                        events = [
                            {'type': 'response.output_item.added', 'output_index': 1,
                             'item': {**rejected, 'arguments': ''}},
                            {'type': 'response.function_call_arguments.delta', 'item_id': 'fc_bad',
                             'output_index': 1, 'delta': rejected['arguments']},
                            {'type': 'response.output_item.done', 'output_index': 1, 'item': rejected},
                            {'type': 'response.completed', 'response': response}]
                        wire = b''.join(b'data: ' + json.dumps(e).encode() + b'\n\n' for e in events)
                        # Fragment transport reads, independent of SSE item boundaries.
                        class Fragments(io.BytesIO):
                            def read(self, n=-1):
                                return super().read(min(n, 3) if n >= 0 else 3)
                        source = Fragments(wire)
                        source.getheader = lambda name, default='': 'text/event-stream'
                        source.status = 200
                        output = b''.join(provider.adapt(source, prepared.tool_names))
                        decoded = [json.loads(frame[6:]) for frame in output.split(b'\n\n') if frame]
                        items = decoded[-1]['response']['output']
                        self.assertEqual(decoded[-2]['item'], items[1])
                    else:
                        source = Response(json.dumps(response).encode())
                        items = json.loads(b''.join(provider.adapt(source, prepared.tool_names)))['output']
                    self.assertEqual(items[0], native)
                    self.assertEqual(items[2], {**valid, 'namespace': 'collaboration',
                                               'encrypted_function_args': []})
                    self.assertEqual(items[1]['type'], 'function_call')
                    self.assertIsInstance(json.loads(items[1]['arguments']), str)
                    self.assertEqual(items[1]['call_id'], rejected['call_id'])
                    self.assertNotIn('EXTERNAL-OPAQUE', items[1]['arguments'])


if __name__ == '__main__':
    unittest.main()
