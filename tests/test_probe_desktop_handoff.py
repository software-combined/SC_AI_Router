"""The desktop profile keeps Codex's own setup, stays within its caps and records no content."""
import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import logging
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import time
import tomllib
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from ai_router.transport import Prepared
from ai_router import provider_defs
from tests._platform import unix_only
from tools import probe_agent_handoffs as handoffs
from tools.probe_desktop_handoff import (CHILD, NATIVE_INPUT, PARENT, ROOT, CaseBudget, DesktopProbe, LegacyProbe,
                                         installed_rows)
from tools.probe_handoff_matrix import MatrixProbe, RouterRows
from tools.probe_review_handoffs import MAX_CALLS, MAX_INPUT, MAX_OUTPUT

PLANTED = 'PLANTED private text 7f3a'
LIVE_CONFIG = '''openai_base_url = "http://127.0.0.1:9/synthetic"
model = "gpt-6.1-sol"
model_reasoning_effort = "max"
notify = ["synthetic-notify"]
[features]
memories = true
[features.context_management]
experimental_mode = true
[mcp_servers.synthetic]
command = "synthetic-mcp"
[apps.synthetic]
enabled = true
[hooks]
synthetic = "synthetic"
[projects."/synthetic/project"]
trust_level = "trusted"
[marketplaces.scg-agent-plugins]
source_type = "local"
source = "/synthetic/marketplace"
[marketplaces.other-market]
source_type = "git"
source = "https://example.invalid/market"
[plugins."scg-review@scg-agent-plugins"]
enabled = true
[plugins."github@openai-curated"]
enabled = true
'''
ROWS = [{'slug': PARENT, 'use_responses_lite': True}, {'slug': CHILD, 'use_responses_lite': False},
        {'slug': 'z-ai/glm-5.3-flash', 'use_responses_lite': False}]


def offline(probe_type, live=True):
    probe = probe_type(False, MAX_CALLS, True)
    probe.live, probe.version, probe.auth_headers, probe.parent_thread_id = live, '0.0.0', {}, 'synthetic-parent'
    probe.upstream, probe.deadline = 'http://127.0.0.1:9/synthetic/backend-api/codex/responses', time.monotonic() + 30
    return probe


class DesktopProfileTests(unittest.TestCase):
    def setUp(self):
        names = patch.multiple(handoffs, PARENT=PARENT, CHILD=CHILD)
        names.start()
        self.addCleanup(names.stop)

    def launch(self, probe_type, home):
        """Run run() up to the first turn with a stand-in client; return what it was given."""
        seen, copies, real_run = {}, [], subprocess.run

        class Client:
            def __init__(self, command, cwd, env, **unused):
                codex_home = Path(env['CODEX_HOME'])
                config = codex_home / 'config.toml'
                seen.update(command=command, cwd=cwd, home=str(codex_home),
                    config=tomllib.loads(config.read_text()) if config.exists() else None,
                    auth_mode=(codex_home / 'auth.json').stat().st_mode & 0o777,
                    catalog=[row['slug'] for row in json.loads((codex_home / 'catalog.json').read_text())['models']],
                    skill=(codex_home / 'skills/demo/SKILL.md').is_file() and not (codex_home / 'skills').is_symlink(),
                    escape=os.path.lexists(codex_home / 'plugins/cache/escape'))
                self.replies = queue.Queue()

            def send(self, message):
                if message.get('method') == 'turn/start':
                    seen['turn'] = message['params']
                    raise InterruptedError('synthetic stop before any inference')
                seen.setdefault('rpc', {})[message.get('method')] = message.get('params')
                if 'id' in message:
                    self.replies.put({'id': message['id'], 'result': {'thread': {'id': 'synthetic-parent'}}})

            def next_event(self, deadline=None):
                return self.replies.get(timeout=2)

            def close(self):
                pass

        def run(command, *args, **kwargs):
            if command[0] != 'cp':
                return SimpleNamespace(stdout='codex-cli 0.0.0')
            copies.append(command)
            shutil.copytree(command[2], command[3], symlinks=True)  # Portable stand-in for an APFS clone.
            return SimpleNamespace(returncode=0)
        args = SimpleNamespace(live=True, max_live_calls=MAX_CALLS, live_children=True, lifecycle=False,
                               installed=True, native_only=False, codex='synthetic-codex', wire_mode='lite')
        with patch.object(Path, 'home', return_value=home), patch.object(handoffs, 'AppServer', Client), \
                patch.object(handoffs.subprocess, 'run', run), patch.object(DesktopProbe, 'fetch_catalogue', return_value=ROWS), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(handoffs.run(args, probe_type=lambda *unused: offline(probe_type)), 1)
        self.assertIs(subprocess.run, real_run)
        return seen, copies

    def test_native_desktop_probe_refuses_before_copying_or_launching(self):
        args = SimpleNamespace(live=True)
        with patch.object(handoffs, 'AppServer') as client, \
                patch.object(handoffs.subprocess, 'run') as launch:
            with self.assertRaisesRegex(SystemExit, 'retired'):
                handoffs.run(args, probe_type=DesktopProbe)
            client.assert_not_called()
            launch.assert_not_called()

    def test_prompts_name_no_tool_namespace_or_fork_option(self):
        text = ' '.join(DesktopProbe(False, MAX_CALLS, True).live_prompts)
        for word in ('spawn_agent', 'send_message', 'followup_task', 'wait_agent', 'collaboration', 'fork_turns', 'namespace'):
            self.assertNotIn(word, text)
        self.assertIn(f'on {CHILD}, reasoning effort high', text)

    def test_caps_refuse_before_any_send(self):
        send, conn = Mock(return_value='sent'), SimpleNamespace(timeout=120, sock=None)

        def prepared(provider, payload):
            return Prepared('synthetic.invalid', '/responses', {}, json.dumps(payload).encode(), {}, provider.id)
        native = prepared(provider_defs.OPENAI, {'input': 'x' * 300 * 1024})  # A real desktop parent's size.
        external = prepared(provider_defs.OPENROUTER, {'max_output_tokens': MAX_OUTPUT})
        budget = CaseBudget(send)
        for _ in range(MAX_CALLS // 2):
            budget(conn, native, {})
            budget(conn, external, {})
        with self.assertRaisesRegex(ValueError, 'call budget'):
            budget(conn, external, {})
        self.assertEqual((send.call_count, budget.exhausted), (MAX_CALLS, 'call'))
        for body, reason in ((prepared(provider_defs.OPENAI, {'input': 'x' * NATIVE_INPUT}), 'input'),
                             (prepared(provider_defs.OPENROUTER, {'max_output_tokens': MAX_OUTPUT, 'input': 'x' * MAX_INPUT}), 'input'),
                             (prepared(provider_defs.OPENROUTER, {}), 'output'),
                             (prepared(provider_defs.OPENROUTER, {'max_output_tokens': MAX_OUTPUT * 2}), 'output')):
            with self.subTest(reason=reason):
                fresh = CaseBudget(send)
                with self.assertRaisesRegex(ValueError, reason + ' budget'):
                    fresh(conn, body, {})
                self.assertEqual(fresh.exhausted, reason)
        self.assertEqual(send.call_count, MAX_CALLS)
        # Reserve both possible native sends before forwarding, then reconcile the daemon ledger.
        probe = offline(DesktopProbe)
        probe.installed, probe.budget = True, CaseBudget(Mock())
        rows = [{'event': 'request_started', 'request_id': 'synthetic'},
                {'event': 'attempt_ledger', 'request_id': 'synthetic', 'sends': 2}]
        with patch.object(handoffs.Probe, 'forward', return_value=b'') as forwarded, \
                patch('tools.probe_desktop_handoff.installed_rows', return_value=rows):
            with self.assertRaisesRegex(ValueError, 'output budget'):
                probe.forward({'model': CHILD, 'input': []}, {}, role='child')
            for _ in range(MAX_CALLS // 2):
                probe.forward({'model': PARENT, 'input': []}, {}, role='parent')
            with self.assertRaisesRegex(ValueError, 'call budget'):
                probe.forward({'model': PARENT, 'input': []}, {}, role='parent')
        self.assertEqual((forwarded.call_count, probe.budget.calls), (MAX_CALLS // 2, MAX_CALLS))

    def test_records_keep_shapes_but_never_request_or_response_text(self):
        probe = offline(LegacyProbe)
        probe.scope_ready = True
        rows = RouterRows(probe)
        spawn = {'type': 'function_call', 'namespace': 'collaboration', 'name': 'spawn_agent', 'call_id': 'call_1',
                 'encrypted_function_args': [], 'arguments': json.dumps({'task_name': 'legacy_native', 'model': PARENT,
                     'reasoning_effort': 'low', 'fork_turns': 'none', 'message': PLANTED})}
        failed = json.dumps({'type': 'response.failed', 'response': {'error': {'code': 'HANDOFF_REQUIRES_PLAINTEXT', 'message': PLANTED}}})
        tools = [{'type': 'namespace', 'name': 'collaboration', 'tools': []}, {'type': 'function', 'name': 'shell', 'description': PLANTED}]
        body = {'model': PARENT, 'reasoning': {'effort': 'high'}, 'tools': tools, 'input': [
            {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': PLANTED}]},
            {'type': 'function_call_output', 'call_id': 'call_0', 'output': PLANTED},
            {'type': 'agent_message', 'content': [{'type': 'input_text', 'text': PLANTED}]}]}
        error = __import__('urllib.error').error.HTTPError('http://127.0.0.1:9/synthetic', 400, PLANTED, {}, io.BytesIO(
            json.dumps({'error': {'code': 'UPSTREAM_INVALID_REQUEST', 'message': PLANTED}}).encode()))
        child = {'thread-id': 'synthetic-child', 'x-codex-parent-thread-id': 'synthetic-parent',
                 'x-codex-turn-metadata': json.dumps({'agent_name': '/root/legacy_native'})}
        parent = {'thread-id': 'synthetic-parent', 'x-codex-turn-metadata': json.dumps({'agent_name': '/root'})}
        reply = handoffs.sse([spawn, handoffs.message(PLANTED, '1')], '1') + b'data: ' + failed.encode() + b'\n\n'
        with patch.object(handoffs.Probe, 'forward', side_effect=[reply, error]) as sent:
            probe.respond(body, parent, 1)
            with self.assertRaises(Exception):
                probe.respond({**body, 'reasoning': {'effort': 'low'}}, child, 2)
        self.assertEqual(sent.call_args_list[0].args[0]['tools'], tools)  # Tools reach the router unfiltered.
        for row in ({'event': 'upstream_rejected', 'code': 'UPSTREAM_INVALID_REQUEST', 'tool': PLANTED, 'message': PLANTED},
                    {'event': 'handoff_observed', 'phase': 'done', 'message_shape': 'readable', 'detail': PLANTED,
                     'upstream': {'namespace': 'plaintext', 'marker': PLANTED, 'arguments': 'object'}}):
            rows.emit(logging.makeLogRecord({'msg': json.dumps(row)}))
        record = probe.record('legacy-native', 'in-process', 1, CaseBudget(Mock()), 1.0, 2)
        self.assertNotIn('PLANTED', json.dumps(record) + json.dumps(probe.facts))
        self.assertEqual(record['client_calls'][0]['message_shape'], 'readable')
        self.assertEqual(record['router_upstream_namespaces'], {'turn1': {'plaintext': 1}})
        self.assertEqual((record['outcome'], record['refusals']), ('refused', ['HANDOFF_REQUIRES_PLAINTEXT', 'UPSTREAM_INVALID_REQUEST']))

    def test_installed_rows_follow_only_this_case_requests(self):
        start = datetime(2026, 10, 1, 1, tzinfo=timezone.utc)

        def row(minute, **fields):
            return json.dumps({'ts': (start + timedelta(minutes=minute)).isoformat(timespec='milliseconds'), **fields})
        with tempfile.TemporaryDirectory() as temp:
            logs = Path(temp)
            (logs / 'router.jsonl').write_text('\n'.join((
                row(1, event='request_started', request_id='a' * 32, model=PARENT, request_bytes=1234),
                row(1, event='attempt_ledger', request_id='a' * 32, sends=2),
                row(1, event='handoff_observed', request_id='a' * 32, phase='done', message_shape='readable', note=PLANTED,
                    upstream={'namespace': 'plaintext', 'marker': 'empty', 'arguments': 'object'}),
                row(2, event='request_started', request_id='b' * 32, model=PARENT, request_bytes=999),
                row(2, event='attempt_ledger', request_id='b' * 32, sends=5),
                row(9, event='request_started', request_id='c' * 32, model=PARENT, request_bytes=1234),
                row(9, event='attempt_ledger', request_id='c' * 32, sends=7), 'not json')))
            found = installed_rows(start, start + timedelta(minutes=5),
                                   [{'turn': 2, 'role': 'parent', 'model': PARENT, 'bytes': 1234}], logs)
        self.assertEqual([(row['turn'], row['event']) for row in found],
                         [(2, 'request_started'), (2, 'attempt_ledger'), (2, 'handoff_observed')])
        self.assertEqual(found[1]['sends'], 2)
        self.assertEqual(found[2]['upstream']['namespace'], 'plaintext')
        self.assertNotIn('PLANTED', json.dumps(found))

    def test_desktop_pass_ignores_the_upstream_namespace_but_not_the_client_call(self):
        probe = offline(DesktopProbe)
        readable = {'namespace': 'canonical', 'marker': 'empty', 'message_shape': 'readable'}
        probe.child_agents = {('synthetic-child', '/root/matrix_child')}
        probe.router_rows = [{'turn': 1, 'event': 'handoff_observed', 'upstream': {'namespace': 'plaintext'}}]
        probe.facts.update(child_receipts=list(probe.markers), served=[{'role': 'child', 'model': CHILD, 'effort': 'high'}],
            client_calls=[{'turn': 1, 'tool': 'spawn_agent', **readable}, {'turn': 2, 'tool': 'followup_task', **readable}])
        self.assertTrue(probe.verify())
        probe.facts['client_calls'][1]['namespace'] = 'other'
        self.assertFalse(probe.verify())


if __name__ == '__main__':
    unittest.main()
