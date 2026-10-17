"""Offline checks for the parent-switch probe (Plan 185 step 2): the client is
never started, and the probe's upstream is its scripted fake or a local
stand-in for the installed router. No network and no billed call."""
import io
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest import mock

from tools import probe_parent_switch as probe_mod
from tools.probe_agent_handoffs import message, sse

MARKER = probe_mod.MARKER
GLM, LUNA, DEEPSEEK = 'z-ai/glm-5.3-flash', 'gpt-6-luna', 'deepseek/deepseek-v4.1-flash-1017'
CHILD_HEADERS = {'x-codex-parent-thread-id': 'synthetic-parent'}
ENCRYPTED = {'type': 'encrypted_content', 'encrypted_content': 'SYNTH_CIPHER'}


def user(text):
    return {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': text}]}


def agent(blocks, author='/root/plain', recipient='/root'):
    return {'type': 'agent_message', 'author': author, 'recipient': recipient, 'content': blocks}


def said(text):
    return {'type': 'input_text', 'text': text}


ASSIGNMENT = agent([said('Reply exactly ' + MARKER), ENCRYPTED], author='/root', recipient='/root/plain')


def fake_router(test, failure=None):
    """A stand-in for the installed router that counts what reaches it.

    `failure`: None, 'http' (a 400), 'stream' (an HTTP 200 ending in the
    router's late-failure `response.failed`) or 'truncated' (an HTTP 200 cut
    short of `response.completed`). A complete reply reports 2 tokens."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            seen.append((body['model'], self.headers.get('Authorization')))
            reply = sse([message(MARKER + ' CONFIDENTIAL_REPLY_WORDS', '1')], '1')
            reply = reply.replace(b'"status": "completed"',
                                  b'"status": "completed", "model": "served-' + body['model'].encode() + b'"')
            status = 400 if failure == 'http' else 200
            if failure == 'http':
                reply = b'{"error":{"message":"refused"}}'
            elif failure == 'stream':
                reply = b'data: ' + json.dumps({'type': 'response.failed', 'response': {
                    'status': 'failed', 'error': {'code': 'server_error'}}}).encode() + b'\n\n'
            elif failure == 'truncated':
                reply = b''.join(frame + b'\n\n' for frame in reply.split(b'\n\n')
                                 if frame and b'response.completed' not in frame)
            self.send_response(status)
            self.send_header('Content-Length', str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    test.addCleanup(server.server_close)
    test.addCleanup(server.shutdown)
    return server, seen, f'http://127.0.0.1:{server.server_port}/tok-SYNTH-7731/backend-api/codex/responses'


def probe_server(test, probe):
    server = probe_mod.serve(probe)
    test.addCleanup(server.server_close)
    test.addCleanup(server.shutdown)
    return server


def send(server, body, headers=None):
    """POST `body`, or GET when it is None; returns the HTTP status."""
    request = urllib.request.Request(
        f'http://127.0.0.1:{server.server_port}/v1/responses',
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type': 'application/json', **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
            return response.status
    except urllib.error.HTTPError as exc:
        exc.close()
        return exc.code


def items_of(raw):
    return [json.loads(line[6:])['item'] for line in raw.decode().splitlines()
            if line.startswith('data: ') and '"response.output_item.done"' in line]


class OfflineFakeTests(unittest.TestCase):
    def test_the_fake_scripts_c3_and_the_switched_parent_recalls_the_reply(self):
        probe = probe_mod.SwitchProbe(False, 0, DEEPSEEK)
        calls = items_of(probe.respond({'model': GLM, 'input': [user('spawn')]}, {}))
        self.assertEqual([(c['namespace'], c['name']) for c in calls],
                         [('collaboration', 'spawn_agent'), ('collaboration', 'wait_agent')])
        self.assertEqual(json.loads(calls[0]['arguments'])['model'], DEEPSEEK)
        probe.respond({'model': DEEPSEEK, 'input': [ASSIGNMENT]}, CHILD_HEADERS)
        delivered = [user('spawn'), agent([said(MARKER)])]
        probe.respond({'model': GLM, 'input': delivered}, {})
        answer = probe.respond({'model': LUNA, 'input': [*delivered, user(probe_mod.RECALL)]}, {})
        self.assertIn(MARKER, probe_mod.reply_facts(answer)[1])
        probe.switched.append([LUNA, True])
        record = probe_mod.summary('C3', (GLM, LUNA), probe)
        self.assertEqual(record['identities'], [[GLM, None], [DEEPSEEK, None], [GLM, None], [LUNA, None]])
        self.assertEqual((record['calls'], record['child_reply'], record['result']), (4, 'readable', 'pass'))
        self.assertEqual((probe.live_calls, probe.upstream), (0, None))

    def test_a_reply_that_never_reached_the_parent_fails(self):
        probe = probe_mod.SwitchProbe(False, 0, DEEPSEEK)
        probe.respond({'model': GLM, 'input': [user('spawn')]}, {})
        probe.respond({'model': DEEPSEEK, 'input': [ASSIGNMENT]}, CHILD_HEADERS)
        answer = probe.respond({'model': LUNA, 'input': [user(probe_mod.RECALL)]}, {})
        self.assertNotIn(MARKER, probe_mod.reply_facts(answer)[1])
        probe.switched.append([LUNA, False])
        record = probe_mod.summary('C3', (GLM, LUNA), probe)
        self.assertEqual((record['child_reply'], record['result']), ('missing', 'fail'))

    def test_c5_needs_an_encrypted_child_reply_in_the_switched_request(self):
        for blocks, expected in (([said(MARKER), ENCRYPTED], ('encrypted', 'pass')),
                                 ([said(MARKER)], ('readable', 'shape not produced'))):
            with self.subTest(expected=expected):
                probe = probe_mod.SwitchProbe(False, 0, LUNA)
                probe.respond({'model': DEEPSEEK, 'input': [user('spawn')]}, {})
                probe.respond({'model': LUNA, 'input': [ASSIGNMENT]}, CHILD_HEADERS)
                probe.compacted = True
                probe.respond({'model': LUNA, 'input': [agent(blocks), user(probe_mod.RECALL)]}, {})
                probe.switched.append([LUNA, False])  # Compaction may drop the marker.
                record = probe_mod.summary('C5', (DEEPSEEK, LUNA), probe)
                self.assertEqual((record['child_reply'], record['result']), expected)


class LiveForwardingTests(unittest.TestCase):
    def test_a_websocket_attempt_gets_the_routers_426(self):
        server = probe_server(self, probe_mod.SwitchProbe(False, 0, DEEPSEEK))
        self.assertEqual(send(server, None, {'Upgrade': 'websocket'}), 426)  # A 404 fails the turn.
        self.assertEqual(send(server, None), 404)

    def test_forwarding_stops_hard_at_the_cap(self):
        router, seen, url = fake_router(self)
        probe = probe_mod.SwitchProbe(True, 2, DEEPSEEK, upstream=url, token_limit=100)
        server = probe_server(self, probe)
        statuses = [send(server, {'model': GLM, 'input': [user('x')]}) for _ in range(4)]
        self.assertEqual(statuses, [200, 200, 409, 409])
        self.assertEqual((len(seen), probe.live_calls), (2, 2))
        self.assertEqual([e['reason'] for e in probe.errors],
                         ['live call limit reached', probe_mod.STOPPED])
        self.assertEqual(probe.identities, [[GLM, 'served-' + GLM]] * 2)

    def test_forwarding_stops_once_the_token_budget_is_spent(self):
        router, seen, url = fake_router(self)
        probe = probe_mod.SwitchProbe(True, 5, DEEPSEEK, upstream=url, token_limit=3)
        server = probe_server(self, probe)
        statuses = [send(server, {'model': GLM, 'input': [user('x')]}) for _ in range(3)]
        # The second call crosses the budget and still completes: one call over.
        self.assertEqual(statuses, [200, 200, 409])
        self.assertEqual((len(seen), probe.live_calls, probe.tokens), (2, 2, 4))
        self.assertEqual(probe.errors, [{'reason': probe_mod.BUDGET, 'status': None}])
        record = probe_mod.summary('C3', (GLM, LUNA), probe)
        self.assertEqual((record['tokens'], record['max_live_tokens']), (4, 3))
        # Like the call cap, a zero budget lets nothing through.
        closed = probe_mod.SwitchProbe(True, 5, DEEPSEEK, upstream=url)
        self.assertEqual(send(probe_server(self, closed), {'model': GLM, 'input': []}), 409)
        self.assertEqual(len(seen), 2)

    def test_a_failed_call_is_never_retried(self):
        for failure, first, error in (('http', 409, {'reason': 'HTTPError', 'status': 400}),
                                      ('stream', 200, {'reason': 'upstream stream failed', 'status': 200}),
                                      ('truncated', 200, {'reason': 'upstream stream failed', 'status': 200})):
            with self.subTest(failure=failure):
                router, seen, url = fake_router(self, failure)
                probe = probe_mod.SwitchProbe(True, 5, DEEPSEEK, upstream=url, token_limit=100)
                server = probe_server(self, probe)
                statuses = [send(server, {'model': LUNA, 'input': []}) for _ in range(3)]
                self.assertEqual(statuses, [first, 409, 409])
                self.assertEqual((len(seen), probe.live_calls), (1, 1))
                self.assertEqual(probe.errors[0], error)
                self.assertEqual({e['reason'] for e in probe.errors[1:]}, {probe_mod.STOPPED})

    def test_the_record_carries_no_content_ports_or_credentials(self):
        router, seen, url = fake_router(self)
        probe = probe_mod.SwitchProbe(True, 4, DEEPSEEK, upstream=url, token_limit=100)
        server = probe_server(self, probe)
        bearer = {'Authorization': 'Bearer SYNTH_BEARER_VALUE'}
        send(server, {'model': GLM, 'input': [user('PROMPT_SECRET_TEXT')]}, bearer)
        send(server, {'model': DEEPSEEK, 'input': [ASSIGNMENT]}, {**CHILD_HEADERS, **bearer})
        probe.switched.append([LUNA, True])
        record = json.dumps(probe_mod.summary('C3', (GLM, LUNA), probe))
        # The client's own sign-in still reaches the router untouched.
        self.assertEqual(seen[0], (GLM, 'Bearer SYNTH_BEARER_VALUE'))
        for leaked in ('PROMPT_SECRET_TEXT', 'SYNTH_BEARER_VALUE', 'CONFIDENTIAL_REPLY_WORDS',
                       'SYNTH_CIPHER', 'tok-SYNTH-7731', str(router.server_port), str(server.server_port)):
            self.assertNotIn(leaked, record)
        self.assertEqual(set(json.loads(record)), {
            'cell', 'live', 'parents', 'child', 'effort', 'calls', 'max_live_calls', 'tokens',
            'max_live_tokens', 'identities', 'markers', 'child_reply', 'compacted', 'errors', 'result'})


class LiveLaunchTests(unittest.TestCase):
    """Live wiring with the client and the sandbox check stubbed out."""

    def launch(self, sandbox_status):
        seen = {'ended': []}
        end = seen['ended'].append

        def app(command, **unused):
            seen['command'], seen['profile'] = command, Path(command[2]).read_text()
            return SimpleNamespace(rpc=mock.Mock(side_effect=RuntimeError('stop here')),
                                   close=lambda: end('close'), process=SimpleNamespace(
                                       stdin=SimpleNamespace(close=lambda: end('input')),
                                       wait=lambda timeout: end('wait')))
        with tempfile.TemporaryDirectory() as home:
            rows = [{'slug': slug} for slug in (GLM, LUNA, DEEPSEEK)]
            Path(home, 'mixed-models.json').write_text(json.dumps({'models': rows}))
            probe = probe_mod.SwitchProbe(True, 4, DEEPSEEK, upstream='http://127.0.0.1:9/x', token_limit=100)
            ran = SimpleNamespace(returncode=sandbox_status)
            with mock.patch.object(probe_mod, 'INSTALLED', Path(home)), \
                    mock.patch.object(probe_mod, 'AppServer', app), \
                    mock.patch.object(probe_mod.subprocess, 'run', return_value=ran), \
                    self.assertRaises(RuntimeError) as caught:
                probe_mod.drive(SimpleNamespace(live=True, codex='codex'), probe, (GLM, LUNA), False)
        return str(caught.exception), seen

    def test_the_client_runs_sandboxed_with_writers_off_and_ends_by_its_input(self):
        reason, seen = self.launch(0)
        command = seen['command']
        self.assertEqual((reason, command[:2], command[3]), ('stop here', [probe_mod.SANDBOX, '-f'], 'codex'))
        port = re.search(r'127\.0\.0\.1:(\d+)/v1', ' '.join(command)).group(1)
        self.assertIn(f'(allow network-outbound (remote ip "localhost:{port}"))', seen['profile'])
        self.assertIn('(deny network-outbound)', seen['profile'])
        for name in ('shell_snapshot', 'hooks', 'in_app_local_automation', 'in_app_updates', 'remote_plugin'):
            self.assertIn(f'features.{name}=false', command)
        self.assertIn('notify=[]', command)
        self.assertEqual(seen['ended'], ['input', 'wait', 'close'])

    def test_live_mode_refuses_to_start_without_the_sandbox(self):
        reason, seen = self.launch(71)
        self.assertEqual((reason, 'command' in seen), ('network sandbox unavailable', False))


class DriverTests(unittest.TestCase):
    def test_a_turn_waits_for_the_parent_thread_not_the_child(self):
        def App(events):
            return SimpleNamespace(rpc=lambda *unused: None, next_event=lambda deadline: events.pop(0))

        done = {'method': 'turn/completed', 'params': {'threadId': 'child', 'turn': {'status': 'completed'}}}
        said_by = lambda thread, text: {'method': 'item/completed', 'params': {
            'threadId': thread, 'item': {'type': 'agentMessage', 'text': text}}}
        app = App([said_by('child', 'child text'), done, said_by('parent', MARKER),
                   dict(done, params={'threadId': 'parent', 'turn': {'status': 'completed'}})])
        self.assertEqual(probe_mod.step(app, 'parent', 'turn/start', {}, False), MARKER)
        failed = App([dict(done, params={'threadId': 'parent', 'turn': {'status': 'failed'}})])
        with self.assertRaisesRegex(RuntimeError, 'parent turn failed'):
            probe_mod.step(failed, 'parent', 'turn/start', {}, False)

    def test_bad_arguments_stop_before_anything_starts(self):
        with mock.patch.object(probe_mod, 'SwitchProbe', side_effect=AssertionError('built')):
            capped = ['--cell', 'C3', '--live', '--max-live-calls', '4']
            for argv in (['--cell', 'C3', '--live'], ['--cell', 'C3', '--live', '--max-live-calls', '25'],
                         capped, capped + ['--max-live-tokens', str(probe_mod.MAX_LIVE_TOKENS + 1)],
                         ['--cell', 'C5', '--parents', GLM]):
                with self.subTest(argv=argv), redirect_stderr(io.StringIO()), \
                        self.assertRaises(SystemExit) as caught:
                    probe_mod.main(argv)
                self.assertEqual(caught.exception.code, 2)

    def test_main_prints_one_record_and_names_only_known_failures(self):
        def failing_drive(args, probe, parents, compact):
            probe.respond({'model': parents[0], 'input': [user('spawn')]}, {})
            raise RuntimeError('detail with PROMPT_SECRET_TEXT')

        with mock.patch.object(probe_mod, 'drive', failing_drive), \
                redirect_stdout(io.StringIO()) as out:
            code = probe_mod.main(['--cell', 'C3'])
        record = json.loads(out.getvalue())
        self.assertEqual((code, record['live'], record['calls']), (1, False, 1))
        self.assertEqual((record['result'], record['errors']), ('fail', [{'reason': 'RuntimeError'}]))


if __name__ == '__main__':
    unittest.main()
