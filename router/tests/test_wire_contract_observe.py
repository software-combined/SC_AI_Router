"""The observe-only contract check on every prepared Responses turn.

`subscription_fallback.prepare` logs one `wire_contract` line of rule names
and counts when a prepared body breaks a learnt rule, and nothing for a clean
turn. The body goes upstream unchanged either way, and a fault in the check
never fails the turn. Fake upstreams only: no request leaves the process.
"""
import http.client
import json
import unittest
from unittest import mock

from ai_router import upstream, wire_shape
from tests.fakes import FakeUpstream, install_fake
from tests.harness import auth_file, post, start_server, test_state

CANARY = 'SYNTH-CANARY-181-obs-4b8e'
EXTERNAL = 'deepseek/deepseek-v4.1-flash-1017'
SUBSCRIPTION = 'gpt-6-astra'


def _turn(model, *items, **fields):
    user = {'type': 'message', 'role': 'user',
            'content': [{'type': 'input_text', 'text': CANARY}]}
    return {'model': model, 'input': [user, *items], **fields}


def _unchecked_upstream(test):
    """A 200 upstream recording bodies without the fake's pairing check.

    `tests.fakes.install_fake` fails a test whose external body breaks
    pairing; this one sends such a body on purpose, to show it is observed
    and sent as prepared.
    """
    sent = []

    class Conn:
        def __init__(self, host, *args, **kwargs):
            pass

        def connect(self):
            pass

        def request(self, method, path, body=None, headers=None):
            sent.append(body)

        def getresponse(self):
            return FakeUpstream(200, b'{"output": []}', [])

        def close(self):
            pass

    upstream.clear_refusals()
    test.addCleanup(upstream.clear_refusals)
    patcher = mock.patch.object(http.client, 'HTTPSConnection', Conn)
    test.addCleanup(patcher.stop)
    patcher.start()
    return sent


class ObserveTests(unittest.TestCase):
    def setUp(self):
        state = test_state(auth_file(self))
        state['openai_models'] = [SUBSCRIPTION]
        self.server = start_server(state)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def _post(self, payload, path='/responses'):
        with mock.patch('ai_router.subscription_fallback.log_event') as log:
            response = post(self.server.server_port, '/test-token' + path, payload)
            response.read()
        events = [call.kwargs for call in log.call_args_list
                  if call.args == ('wire_contract',)]
        return response.status, events

    def test_a_mismatched_external_custom_pair_logs_one_event_and_is_sent(self):
        sent = _unchecked_upstream(self)
        status, events = self._post(_turn(
            EXTERNAL,
            {'type': 'custom_tool_call', 'call_id': 'c1', 'name': 'shell', 'input': CANARY},
            {'type': 'function_call_output', 'call_id': 'c1', 'output': CANARY}))
        self.assertEqual(status, 200)
        self.assertEqual(events, [{'provider': 'openrouter', 'model': EXTERNAL,
                                   'path': '/responses',
                                   'violations': {'pair.family_mismatch': 1},
                                   'warnings': {'item.unverified_type': 1},
                                   'unknown_top_level': []}])
        self.assertNotIn(CANARY, json.dumps(events))
        # Observe only: the pair went upstream exactly as prepared.
        self.assertEqual([item['type'] for item in json.loads(sent[0])['input'][1:]],
                         ['custom_tool_call', 'function_call_output'])

    def test_a_clean_turn_logs_nothing(self):
        install_fake(self, lambda: FakeUpstream(200, b'{"output": []}', []))
        call = {'type': 'function_call', 'call_id': 'c1', 'name': 'exec', 'arguments': '{}'}
        output = {'type': 'function_call_output', 'call_id': 'c1', 'output': CANARY}
        for model in (EXTERNAL, SUBSCRIPTION):
            with self.subTest(model=model):
                self.assertEqual(self._post(_turn(model, call, output)), (200, []))

    def test_a_failing_check_never_fails_the_turn(self):
        # The stub, since install_fake's own pairing check calls the checker.
        _unchecked_upstream(self)
        with mock.patch.object(wire_shape, 'violations', side_effect=RuntimeError(CANARY)):
            status, events = self._post(_turn(EXTERNAL))
        self.assertEqual(status, 200)
        self.assertEqual(events, [{'provider': 'openrouter', 'model': EXTERNAL,
                                   'path': '/responses', 'error_type': 'RuntimeError'}])

    def test_an_external_refusal_line_carries_the_contract_facts(self):
        refusal = json.dumps({'error': {'message': 'Provider returned error'}}).encode()
        install_fake(self, lambda: FakeUpstream(
            400, refusal, [('Content-Type', 'application/json')]))
        # An undeclared custom pair stays custom, which only DeepSeek was measured on.
        pair = ({'type': 'custom_tool_call', 'call_id': 'c1', 'name': 'shell', 'input': CANARY},
                {'type': 'custom_tool_call_output', 'call_id': 'c1', 'output': CANARY})
        with mock.patch('ai_router.router.log_event') as log:
            status, events = self._post(_turn('z-ai/glm-5.3', *pair))
        self.assertEqual(status, 400)
        rejected = [call.kwargs for call in log.call_args_list
                    if call.args == ('upstream_rejected',)]
        self.assertEqual(rejected[0]['contract_warnings'], {'item.unverified_type': 2})
        self.assertEqual(events[0]['warnings'], {'item.unverified_type': 2})
        self.assertNotIn(CANARY, json.dumps([rejected, events]))

    def test_a_passthrough_subscription_body_is_checked_without_a_second_parse(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{"output": []}', []))
        for path in ('/responses', '/responses/compact'):
            with self.subTest(path=path), \
                    mock.patch.object(wire_shape, 'decode_wire',
                                      wraps=wire_shape.decode_wire) as decode:
                status, events = self._post(_turn(SUBSCRIPTION, SYNTH_field=1), path)
                self.assertEqual(status, 200)
                decode.assert_not_called()
                self.assertEqual(events, [{'provider': 'openai', 'model': SUBSCRIPTION,
                                           'path': path, 'violations': {},
                                           'warnings': {'top_level.unknown': 1},
                                           'unknown_top_level': ['SYNTH_field']}])
                self.assertIn(b'SYNTH_field', recorded[-1][3])


if __name__ == '__main__':
    unittest.main()
