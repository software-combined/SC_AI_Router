"""A refresh cannot change the encryption guard for an in-flight handoff.

Readability follows the install's key, so these calls carry backend ciphertext
with no marker: they stay unmarked and the guard decides from the request's
captured catalogue.
"""
import contextlib
import json
import unittest
from unittest import mock

from ai_router import model_refresh, registry, request_context
from tests.fakes import FakeUpstream, install_fake
from tests.harness import auth_file, post, start_server, test_state
from tests.test_agent_handoffs import CIPHERTEXT, native_tools, spawn_history
from tests.test_request_context import _after_resolution, _generation, _poison

CHILD = 'xiaomi/mimo-v2.6-pro'
PARENT = 'gpt-6-luna'


class HandoffRequestContextTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(_generation())
        self.server = start_server(test_state(auth_file(self)))
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.server.state['openai_models'] = [PARENT]

    def turn(self, lite=False, stream=False):
        calls = [{'type': 'function_call', 'namespace': 'collaboration', 'name': name,
                  'id': 'fc_' + name, 'call_id': 'call_' + name,
                  'arguments': json.dumps({'model': CHILD, 'task_name': 'plain',
                                            'target': '/root/plain', 'message': CIPHERTEXT})}
                 for name in ('spawn_agent', 'followup_task', 'send_message')]
        output = {'output': calls, 'status': 'completed'}
        raw = (b'data: ' + json.dumps({'type': 'response.completed', 'response': output}).encode()
               + b'\n\n' if stream else json.dumps(output).encode())
        sends = install_fake(self, lambda: FakeUpstream(200, raw, [
            ('Content-Type', 'text/event-stream' if stream else 'application/json')]))
        tools = native_tools('spawn_agent', 'followup_task', 'send_message')
        history = [spawn_history('plain', CHILD),
                   {'type': 'function_call_output', 'call_id': 'call_hist', 'output': 'spawned'}]
        payload = {'model': PARENT, 'input': history, 'stream': stream}
        if lite:
            payload['input'] = [{'type': 'additional_tools', 'role': 'developer',
                                 'id': 'at_fixture', 'tools': tools}, *history]
        else:
            payload['tools'] = tools
        response = post(self.server.server_port, '/test-token/responses', payload,
                        {'Authorization': 'Bearer subscription-fixture'})
        received = response.read()
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0][4]['Authorization'], 'Bearer subscription-fixture')
        body = json.loads(received.split(b'data: ', 1)[1] if stream else received)
        return body['response'] if stream else body, received, raw, response.status

    def assert_guarded(self, result):
        body, received, _, status = result
        self.assertEqual(body['error']['code'], 'invalid_prompt')
        self.assertIn(status, (200, 400))
        self.assertNotIn(CIPHERTEXT.encode(), received)
        self.assertNotIn('output', body)

    def test_refresh_changes_only_the_next_handoff_request(self):
        for lite in (False, True):
            for stream in (False, True):
                with self.subTest(lite=lite, stream=stream), _generation():
                    without_child = tuple(row for row in registry.MODELS if row.slug != CHILD)
                    with mock.patch.object(request_context, 'capture', wraps=request_context.capture) as capture:
                        with _after_resolution(lambda: model_refresh.apply(without_child)):
                            self.assert_guarded(self.turn(lite, stream))
                        self.assertEqual(capture.call_count, 1)
                        _, received, original, status = self.turn(lite, stream)
                        self.assertEqual(status, 200)
                        self.assertEqual(received, original)
                        self.assertEqual(capture.call_count, 2)

    def test_guard_uses_the_snapshot_when_live_lookups_are_unavailable(self):
        with contextlib.ExitStack() as stack:
            with _after_resolution(lambda: _poison(stack)):
                self.assert_guarded(self.turn())


if __name__ == '__main__':
    unittest.main()
