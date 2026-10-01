"""Unreadable external handoffs end before an executable tool reaches Codex."""
from copy import deepcopy
import json
import unittest
from unittest import mock

from ai_router import agent_handoffs as handoffs, events, sse
from tests.fakes import FakeUpstream, install_fake
from tests.harness import auth_file, post, start_server, test_state
from tests.test_agent_handoffs import alias_call, encrypted_call, native_tools, spawn_history


def frame(event):
    return sse.frame(json.dumps(event).encode())


class HandoffRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.server = start_server(test_state(auth_file(self)))
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.server.state['openai_models'] = ['gpt-6-luna']

    def turn(self, output, *, stream, lite=False, content_type=None):
        raw = b''.join(frame(e) for e in output) if stream else json.dumps(output).encode()
        content_type = (content_type if content_type is not None else
                        'text/event-stream' if stream else 'application/json')
        sends = install_fake(self, lambda: FakeUpstream(200, raw, [('Content-Type', content_type)]))
        tools = native_tools(*handoffs.HANDOFF_TOOLS)
        history = [spawn_history('plain', 'deepseek/deepseek-v4.1-flash')]
        payload = {'model': 'gpt-6-luna', 'stream': stream, 'input': history}
        if lite:
            payload['input'] = [{'type': 'additional_tools', 'role': 'developer',
                                 'id': 'at_fixture', 'tools': tools}, *history]
        else:
            payload['tools'] = tools
        with mock.patch.object(events, 'log_event') as observed:
            response = post(self.server.server_port, '/test-token/responses', payload,
                            {'Authorization': 'Bearer subscription-fixture'})
            received = response.read()
        self.assertEqual(len(sends), 1)  # Only the parent's already-open native request.
        self.assertEqual(sends[0][4]['Authorization'], 'Bearer subscription-fixture')
        self.assertNotIn('PRIVATE', str(observed.call_args_list))
        return response.status, received

    def test_each_wrong_route_is_one_terminal_rejection_without_executable_arguments(self):
        for name in sorted(handoffs.HANDOFF_TOOLS):
            for stream in (False, True):
                for lite in (False, True):
                    with self.subTest(name=name, stream=stream, lite=lite):
                        call = encrypted_call(name=name, arguments=json.dumps({
                            'task_name': 'plain', 'target': '/root/plain',
                            'model': 'deepseek/deepseek-v4.1-flash', 'message': 'PRIVATE_OPAQUE'}))
                        response = {'status': 'completed', 'output': [call]}
                        source = ([{'type': 'response.output_item.done', 'item': call},
                                   {'type': 'response.completed', 'response': response}]
                                  if stream else response)
                        status, wire = self.turn(source, stream=stream, lite=lite)
                        self.assertEqual(status, 200 if stream else 400)
                        result = json.loads(wire.split(b'data: ', 1)[1] if stream else wire)
                        error = result['response']['error'] if stream else result['error']
                        self.assertEqual(error['code'], 'invalid_prompt')
                        self.assertIn('collaboration_plaintext.' + name, error['message'])
                        self.assertNotIn(b'PRIVATE_OPAQUE', wire)
                        self.assertNotIn(b'function_call', wire)
                        self.assertNotIn(b'function_call_output', wire)
                        if stream:
                            self.assertEqual(result['type'], 'response.failed')
                            self.assertEqual(wire.count(b'data:'), 1)

    def test_partial_stream_preserves_prior_tools_and_stops_before_bad_done(self):
        valid = alias_call(id='fc_good', call_id='call_good')
        bad = encrypted_call(name='spawn_agent', id='fc_bad', call_id='call_bad',
                             arguments=json.dumps({'task_name': 'plain',
                                 'model': 'deepseek/deepseek-v4.1-flash', 'message': 'PRIVATE_OPAQUE'}),
                             encrypted_function_args=['message'])
        original = deepcopy(bad)
        prefix = [{'type': 'response.output_item.done', 'item': valid},
                  {'type': 'response.output_item.added', 'item': {**bad, 'arguments': ''}},
                  {'type': 'response.function_call_arguments.delta', 'item_id': 'fc_bad',
                   'delta': bad['arguments']}]
        source = [*prefix, {'type': 'response.output_item.done', 'item': bad},
                  {'type': 'response.output_item.done', 'item': alias_call(id='fc_later')},
                  {'type': 'response.completed', 'response': {'output': [valid, bad]}}]
        for content_type in ('text/event-stream', ''):
            with self.subTest(content_type=content_type):
                status, wire = self.turn(source, stream=True, content_type=content_type)
                data = [json.loads(d) for _, d in sse.blocks(wire.splitlines(keepends=True)) if d]
                self.assertEqual(status, 200)
                self.assertEqual(data[0]['item'], handoffs.restore_item(valid, {'send_message'}))
                self.assertEqual(data[1:3], prefix[1:])
                self.assertEqual(data[-1]['type'], 'response.failed')
                self.assertEqual(len(data), 4)
                self.assertEqual(bad, original)

    def test_unreadable_or_unadvertised_alias_is_terminal_before_execution(self):
        for call in (alias_call(encrypted_function_args=['message']),
                     alias_call(encrypted_function_args=None), alias_call(name='close_agent')):
            for stream in (False, True):
                with self.subTest(call=call, stream=stream):
                    response = {'output': [call]}
                    source = ([{'type': 'response.output_item.done', 'item': call}]
                              if stream else response)
                    status, wire = self.turn(source, stream=stream)
                    self.assertEqual(status, 200 if stream else 400)
                    decoded = json.loads(wire.split(b'data: ', 1)[1] if stream else wire)
                    error = decoded['response']['error'] if stream else decoded['error']
                    self.assertEqual(error['code'], 'invalid_prompt')
                    self.assertIn('collaboration_plaintext', error['message'])
                    self.assertNotIn(b'function_call', wire)
                    self.assertNotIn(b'synthetic', wire)


if __name__ == '__main__':
    unittest.main()
