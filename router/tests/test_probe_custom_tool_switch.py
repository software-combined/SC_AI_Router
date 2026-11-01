"""The custom-switch probe caps real sends, including router retries."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from ai_router.transport import Prepared
from tools.probe_agent_handoffs import sse
from tools.probe_context_budget import Reply
from tools.probe_custom_tool_switch import (Budget, EXTERNAL, MAX_CALLS, MAX_INPUT,
    MAX_OUTPUT, TOKEN_STOP, ECHO_PROMPT, probe_input, probe_tools)
from tools import probe_custom_tool_switch as probe


def request(**extra):
    return Prepared('synthetic.invalid', '/responses', {}, json.dumps(
        {'model': EXTERNAL, 'input': [], **extra}).encode(), {}, 'openrouter')


class CustomSwitchBudgetTests(unittest.TestCase):
    def test_ambient_instructions_are_withheld_but_synthetic_history_survives(self):
        task = {'role': 'user', 'content': ECHO_PROMPT}
        call = {'type': 'function_call', 'call_id': 'call_synthetic'}
        result = {'type': 'function_call_output', 'call_id': 'call_synthetic', 'output': 'marker'}
        switch = {'role': 'developer', 'content': '<model_switch> synthetic'}
        ambient = {'role': 'user', 'content': 'PRIVATE-CANARY ambient instructions'}
        self.assertEqual(probe_input([ambient, task, call, result, switch]), [task, call, result, switch])

    def test_probe_exposes_only_echo_and_patch_in_flat_and_lite_declarations(self):
        echo = {'type': 'function', 'name': 'echo_probe'}
        patch = {'type': 'custom', 'name': 'apply_patch'}
        unrelated = {'type': 'function', 'name': 'unrelated'}
        namespace = {'type': 'namespace', 'name': 'functions', 'tools': [patch, unrelated]}
        self.assertEqual(probe_tools([echo, unrelated, namespace]),
                         [echo, {**namespace, 'tools': [patch]}])

    def budget(self):
        send = Mock(side_effect=lambda *_: (Reply(200, sse([], 'synthetic'), 'text/event-stream'), 0))
        return Budget(send), send, SimpleNamespace(timeout=120, sock=None)

    def test_retries_share_the_send_cap_and_output_is_capped(self):
        budget, send, conn = self.budget()
        for _ in range(MAX_CALLS):
            prepared = request(max_output_tokens=65536)
            budget(conn, prepared, {})
            self.assertEqual(json.loads(prepared.body)['max_output_tokens'], MAX_OUTPUT)
        with self.assertRaisesRegex(ValueError, 'send budget'):
            budget(conn, request(), {})
        self.assertEqual(send.call_count, MAX_CALLS)

    def test_oversized_request_deadline_and_usage_stop_never_send(self):
        for reason in ('input', 'time', 'usage', 'stopped'):
            with self.subTest(reason=reason):
                budget, send, conn = self.budget()
                prepared = request()
                if reason == 'input':
                    prepared = request(input=[{'type': 'function_call_output', 'output': 'x' * MAX_INPUT}])
                elif reason == 'time':
                    budget.deadline = 0
                elif reason == 'usage':
                    budget.tokens = TOKEN_STOP
                else:
                    budget.stopped = True
                with self.assertRaisesRegex(ValueError, 'send budget'):
                    budget(conn, prepared, {})
                send.assert_not_called()

    def test_rejection_or_missing_usage_stops_later_sends(self):
        for response in (Reply(400, b'{}', 'application/json'),
                         Reply(200, b'data: {"type":"response.completed","response":{}}\n\n', 'text/event-stream')):
            with self.subTest(status=response.status):
                send = Mock(return_value=(response, 0))
                budget = Budget(send)
                conn = SimpleNamespace(timeout=120, sock=None)
                budget(conn, request(), {})
                with self.assertRaisesRegex(ValueError, 'send budget'):
                    budget(conn, request(), {})
                self.assertEqual(send.call_count, 1)

    def test_buffered_response_preserves_client_continuation_headers(self):
        response = Reply(200, sse([], 'synthetic'), 'text/event-stream')
        response.headers.append(('x-codex-turn-state', 'synthetic-state'))
        budget = Budget(Mock(return_value=(response, 0)))
        buffered, _ = budget(SimpleNamespace(timeout=120, sock=None), request(), {})
        self.assertEqual(buffered.getheader('x-codex-turn-state'), 'synthetic-state')


class LiveIsolationTests(unittest.TestCase):
    def launch(self, sandbox_result):
        seen = {}
        server = Mock(server_port=45123)

        def start(command, **kwargs):
            seen['command'] = command
            seen['profile'] = Path(command[2]).read_text()
            raise RuntimeError('stop before client startup')

        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            state = home / '.codex/mixed-model-router/mixed-router-state.json'
            state.parent.mkdir(parents=True)
            state.write_text('{}')
            with patch.object(Path, 'home', return_value=home), \
                    patch.object(probe, 'Credentials'), \
                    patch('ai_router.router.Router', return_value=server), \
                    patch.object(probe, 'AppServer', side_effect=start) as app, \
                    patch('tools.probe_parent_switch.subprocess.run',
                          return_value=SimpleNamespace(returncode=sandbox_result)), \
                    self.assertRaises(RuntimeError) as caught:
                probe.run('synthetic-codex', live=True)
        server.shutdown.assert_called_once()
        server.server_close.assert_called_once()
        return str(caught.exception), seen, app

    def test_live_client_has_only_the_probe_network_and_background_features_off(self):
        reason, seen, app = self.launch(0)
        self.assertEqual(reason, 'stop before client startup')
        self.assertEqual(seen['command'][:2], ['/usr/bin/sandbox-exec', '-f'])
        self.assertIn('(deny network-outbound)', seen['profile'])
        self.assertIn('(remote ip "localhost:45123")', seen['profile'])
        self.assertIn('notify=[]', seen['command'])
        for feature in ('shell_snapshot', 'hooks', 'in_app_local_automation', 'in_app_updates'):
            self.assertIn('features.' + feature + '=false', seen['command'])
        app.assert_called_once()

    def test_unavailable_sandbox_refuses_before_starting_the_live_client(self):
        reason, seen, app = self.launch(71)
        self.assertEqual(reason, 'network sandbox unavailable')
        self.assertEqual(seen, {})
        app.assert_not_called()


if __name__ == '__main__':
    unittest.main()
