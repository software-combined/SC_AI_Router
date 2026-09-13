"""Offline coverage for the shared app-server probe harness (Plan 133).

The three paid probes drive a real Codex app-server over stdio. This module
pins the shared `AppServer` transport and the three environment-scrub
policies against a scripted fake binary so a wire or teardown change is
caught without a live run. No network, no billing, no desktop app.
"""
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from tests._platform import unix_only
from tools.appserver_probe import (AGENT_HANDOFFS, AMBIENT, CONTEXT_BUDGET,
                                   AppServer, scrub_env)

ROOT = Path(__file__).resolve().parents[1]

FAKE_APPSERVER = '''import json
import sys
mode = sys.argv[1] if len(sys.argv) > 1 else 'echo'
if mode == 'noisy':
    sys.stderr.write('diagnostic line one\\ndiagnostic line two\\n')
    sys.stderr.flush()
for line in sys.stdin:
    try:
        message = json.loads(line)
    except ValueError:
        continue
    ident, method = message.get('id'), message.get('method')
    if mode == 'silent' or (method is None and ident is not None):
        continue
    if method in (None, 'initialized'):
        continue
    if method == 'boom':
        sys.stdout.write('not json\\n')
        sys.stdout.flush()
    if mode == 'turn' and method == 'turn/start':
        params = message['params']
        sys.stdout.write(json.dumps({'id': ident, 'result': {'params': params}}) + '\\n')
        sys.stdout.write(json.dumps({'method': 'item/completed', 'params': {
            'item': {'type': 'agentMessage', 'text': 'PROBE_MARKER'}}}) + '\\n')
        sys.stdout.write(json.dumps({'method': 'turn/completed', 'params': {
            'turn': {'status': 'completed'}}}) + '\\n')
        sys.stdout.flush()
        continue
    if mode == 'exit':
        break
    sys.stdout.write(json.dumps({'id': ident, 'result': {'echo': method}}) + '\\n')
    sys.stdout.flush()
'''


@unix_only
class AppServerTests(unittest.TestCase):
    """Offline coverage for the shared harness (plan 133).

    A tiny fake app-server stands in for the desktop binary: spawn, one
    RPC round trip, stderr drain, clean close and the timeout path, plus
    the three scrub modes. No network, no billing, no desktop app.
    """
    def _fake_server(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        path = Path(tmp) / 'fake-appserver.py'
        path.write_text(FAKE_APPSERVER)
        return str(path)

    def _spawn(self, mode='echo', **kwargs):
        kwargs.setdefault('stderr', subprocess.PIPE)
        server = AppServer([sys.executable, self._fake_server(), mode],
                           cwd=None, env=dict(os.environ), **kwargs)
        self.addCleanup(server.close)
        return server

    def test_rpc_round_trip(self):
        server = self._spawn()
        self.assertEqual(server.rpc('ping', {}), {'echo': 'ping'})
        self.assertEqual(server.rpc('ping', {}), {'echo': 'ping'})

    def test_send_and_next_event(self):
        server = self._spawn()
        server.send({'id': 7, 'method': 'hello', 'params': {}})
        event = server.next_event(deadline=time.monotonic() + 10)
        self.assertEqual(event, {'id': 7, 'result': {'echo': 'hello'}})

    def test_malformed_stdout_lines_are_ignored(self):
        server = self._spawn()
        self.assertEqual(server.rpc('boom', {}), {'echo': 'boom'})

    def test_strict_lines_fail_on_a_malformed_line(self):
        # The context-budget client treats a corrupt line as fatal; the
        # other probes keep the lenient default.
        server = self._spawn('echo', strict_lines=True)
        with self.assertRaises(RuntimeError):
            server.rpc('boom', {})

    def test_turn_sends_the_caller_payload_and_applies_the_marker(self):
        calls = []
        server = self._spawn('turn', on_event=calls.append)
        answer, turn = server.turn('thread-1', 'hello', timeout=5,
                                   marker='PROBE_MARKER',
                                   payload={'model': 'fake-model', 'effort': 'low'})
        self.assertEqual(turn['status'], 'completed')
        self.assertEqual(answer, 'PROBE_MARKER')
        # The payload= hook is plan 145's contract: prove it reaches the wire.
        # The fake echoes the received turn/start params in its reply.
        reply = [e for e in calls if e.get('id') == 1][0]
        echoed = reply['result']['params']
        self.assertEqual(echoed['model'], 'fake-model')
        self.assertEqual(echoed['effort'], 'low')
        self.assertEqual(echoed['threadId'], 'thread-1')

    def test_kill_group_close_terminates_the_child(self):
        # The context-budget probe spawns in its own session and closes the
        # whole group; patch killpg so plain terminate() cannot pass this.
        from tools import appserver_probe as probe_mod
        calls = []
        real = probe_mod.os.killpg
        self.addCleanup(setattr, probe_mod.os, 'killpg', real)
        probe_mod.os.killpg = lambda pid, sig: (calls.append((pid, sig)),
                                                 real(pid, sig))[1]
        server = self._spawn(kill_group=True, start_new_session=True)
        process = server.process
        server.close()
        self.assertIsNone(server.process)
        self.assertTrue(calls and calls[0][0] == process.pid)
        self.assertIsNotNone(process.poll())

    def test_stderr_drain_does_not_block_rpc(self):
        server = self._spawn('noisy')
        self.assertEqual(server.rpc('ping', {}), {'echo': 'ping'})

    def test_stderr_file_object_receives_child_output(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        log = open(str(Path(tmp) / 'child.log'), 'w+')
        server = AppServer([sys.executable, self._fake_server(), 'noisy'],
                           cwd=tmp, env=dict(os.environ), stderr=log)
        self.addCleanup(server.close)
        self.assertEqual(server.rpc('ping', {}), {'echo': 'ping'})
        log.seek(0)
        self.assertIn('diagnostic line one', log.read())

    def test_on_event_hook_sees_every_event(self):
        seen = []
        server = self._spawn(on_event=seen.append)
        server.rpc('ping', {})
        self.assertEqual(seen, [{'id': 1, 'result': {'echo': 'ping'}}])

    def test_timeout_path_raises_empty(self):
        server = self._spawn('silent')
        with self.assertRaises(queue.Empty):
            server.rpc('ping', {}, timeout=0.2)

    def test_eof_raises_runtime_error_with_detail(self):
        server = self._spawn('exit')
        server.send({'id': 1, 'method': 'quit', 'params': {}})
        with self.assertRaisesRegex(RuntimeError, 'App server exited'):
            server.next_event(deadline=time.monotonic() + 10)
        detailed = self._spawn('exit', eof_detail=lambda: 'bye')
        detailed.send({'id': 1, 'method': 'quit', 'params': {}})
        with self.assertRaisesRegex(RuntimeError, 'App server exited: bye'):
            detailed.next_event(deadline=time.monotonic() + 10)

    def test_close_is_idempotent(self):
        server = self._spawn()
        server.rpc('ping', {})
        server.close()
        server.close()

    def test_close_does_not_block_on_a_descendant_holding_stdout(self):
        # A grandchild that inherits stdout keeps the pipe open after the
        # direct child exits; close() must still return promptly instead of
        # blocking on the reader thread's stream lock.
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        script = Path(tmp) / 'orphan.py'
        script.write_text(
            "import subprocess, sys, time\n"
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
            "time.sleep(30)\n")
        server = AppServer([sys.executable, str(script)], cwd=tmp,
                           env=dict(os.environ), stderr=subprocess.PIPE)
        time.sleep(0.5)
        started = time.monotonic()
        server.close()
        self.assertLess(time.monotonic() - started, 5.0)

    def test_scrub_ambient_passes_through(self):
        env = {'OPENAI_API_KEY': 'x', 'CODEX_HOME': 'y', 'PLAIN': 'z'}
        self.assertEqual(scrub_env(env, AMBIENT), env)
        self.assertIsNot(scrub_env(env, AMBIENT), env)

    def test_scrub_context_budget_strips_then_injects_in_order(self):
        env = {'OPENAI_API_KEY': 'live', 'CODEX_SOMETHING': 'live',
               'CHATGPT_X': 'live', 'PLAIN': 'kept'}
        inject = {'CODEX_HOME': 'home', 'OPENAI_API_KEY': 'synthetic-test-key',
                  'OPENAI_BASE_URL': 'url'}
        self.assertEqual(scrub_env(env, CONTEXT_BUDGET, inject=inject),
                         {'PLAIN': 'kept', **inject})
        self.assertNotIn('OPENAI_API_KEY', scrub_env(env, CONTEXT_BUDGET))

    def test_scrub_agent_handoffs_strips_secrets_then_sets_home(self):
        env = {'OPENAI_API_KEY': 'x', 'GITHUB_TOKEN': 'x', 'MY_SECRET': 'x',
               'BASIC_AUTH': 'x', 'PLAIN': 'kept', 'CODEX_HOME': 'old'}
        # CODEX_HOME contains none of the strip words, so it survives the
        # scrub and is then overwritten by the injection, as today.
        cleaned = scrub_env(env, AGENT_HANDOFFS, inject={'CODEX_HOME': 'tmp'})
        self.assertEqual(cleaned, {'PLAIN': 'kept', 'CODEX_HOME': 'tmp'})

    def test_scrub_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            scrub_env({}, 'nope')


if __name__ == '__main__':
    unittest.main()
