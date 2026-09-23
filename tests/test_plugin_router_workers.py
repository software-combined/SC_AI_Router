"""Router workers skill: linked into the plugin, and its runner keeps the router's contract.

The runner lives in the plugin, not ai_router, so these tests pin the two
places it depends on the router: the listing id it resolves must be the one
`ai_router.claude` advertises, and the per-install token must never reach the
printed result or the saved transcript.
"""
import contextlib
import http.server
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_router import registry
from ai_router.claude import claude_alias

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins/scg-subagents'
SKILL = PLUGIN / 'skills/router-workers'
spec = importlib.util.spec_from_file_location('router_worker', SKILL / 'scripts/router_worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

FAKE_CLAUDE = '''#!%s
import json, os, sys
sys.stdin.read()
model = sys.argv[sys.argv.index('--model') + 1]
settings = sys.argv[sys.argv.index('--settings') + 1]
seen = os.environ['ANTHROPIC_BASE_URL']
print(json.dumps({'type': 'assistant', 'message': {'model': model, 'content': [
    {'type': 'tool_use', 'name': 'Bash'}, {'type': 'text', 'text': seen}]}}))
print(json.dumps({'type': 'result', 'result': 'env said ' + seen + ' settings ' + settings,
                  'num_turns': 2, 'is_error': False,
                  'usage': {'input_tokens': 3, 'output_tokens': 4}}))
'''


class RouterWorkersSkillTest(unittest.TestCase):
    def test_skill_is_linked_inside_the_plugin_and_from_the_entrypoint(self):
        text = (SKILL / 'SKILL.md').read_text()
        head = text.split('---')[1]
        self.assertIn('name: router-workers', head)
        self.assertIn('description:', head)
        self.assertIn('updates.md', text)
        for target in re.findall(r'\]\(([^)]+)\)', text):
            path = target.split('#')[0]
            if path and '://' not in path:
                resolved = (SKILL / path).resolve()
                self.assertTrue(resolved.is_relative_to(PLUGIN), target)
                self.assertTrue(resolved.is_file(), target)
        entry = (PLUGIN / 'skills/optimal-subagents/SKILL.md').read_text()
        self.assertIn('../router-workers/SKILL.md', entry)

    def test_listing_id_is_the_id_the_router_advertises(self):
        rows = [{'id': alias} for alias in map(claude_alias, (m.slug for m in registry.MODELS))
                if alias]
        self.assertTrue(rows)
        for entry in registry.MODELS:
            with self.subTest(slug=entry.slug):
                self.assertEqual(worker.listing_id(entry.slug, rows), claude_alias(entry.slug))
        self.assertIsNone(worker.listing_id('vendor/not-offered', rows))

    def test_summary_reports_every_served_model_and_rejects_failed_runs(self):
        stream = '\n'.join(json.dumps(event) for event in (
            {'type': 'system', 'subtype': 'init'},
            {'type': 'assistant', 'message': {'model': 'z-ai/glm-5.3-flash', 'content': [
                {'type': 'tool_use'}, {'type': 'text'}]}},
            {'type': 'assistant', 'parent_tool_use_id': 'toolu_1', 'message': {
                'model': 'xiaomi/mimo-v2.6-flash', 'content': [{'type': 'tool_use'}]}},
            {'type': 'result', 'result': 'done', 'num_turns': 3, 'is_error': False,
             'usage': {'input_tokens': 10, 'cache_read_input_tokens': 5, 'output_tokens': 7}},
        )) + '\nnot json\n'
        summary = worker.summarise(stream)
        self.assertTrue(summary['finished'])
        self.assertEqual(summary['answer'], 'done')
        self.assertEqual(summary['served'], ['xiaomi/mimo-v2.6-flash', 'z-ai/glm-5.3-flash'])
        self.assertEqual((summary['tool_calls'], summary['tokens']), (2, {'input': 15, 'output': 7}))
        failed = worker.summarise(json.dumps(
            {'type': 'result', 'is_error': True, 'subtype': 'error_during_execution'}))
        self.assertEqual((failed['finished'], failed['error']), (False, 'error_during_execution'))
        self.assertFalse(worker.summarise('')['finished'])

    def test_worker_environment_carries_none_of_the_callers_credentials(self):
        # USERPROFILE keeps Path.home() working on Windows once the rest is cleared.
        caller = {'PATH': os.defpath, 'USERPROFILE': str(Path.home()), 'GH_TOKEN': 'gh',
                  'AWS_SECRET_ACCESS_KEY': 'aws', 'ANTHROPIC_API_KEY': 'key',
                  'CLAUDE_CODE_OAUTH_TOKEN': 'oauth'}
        with patch.dict(os.environ, caller, clear=True):
            env = worker.worker_env('http://127.0.0.1:1/t/', 'claude/scg/x', Path('/s'))
        for name in ('GH_TOKEN', 'AWS_SECRET_ACCESS_KEY', 'ANTHROPIC_API_KEY',
                     'CLAUDE_CODE_OAUTH_TOKEN'):
            self.assertNotIn(name, env)
        self.assertEqual(env['CLAUDE_CONFIG_DIR'], str(Path('/s') / 'config'))
        self.assertEqual(env['ANTHROPIC_DEFAULT_HAIKU_MODEL'], 'claude/scg/x')

    def test_home_folder_is_refused_before_any_worker_starts(self):
        # Every spelling of home that exists here: case variants on macOS and
        # Windows, and the macOS data-volume path. A missing router home makes a
        # wrongly ordered check fail here instead of reaching the real router.
        home = str(Path.home())
        spellings = [path for path in {home, home.swapcase(), '/System/Volumes/Data' + home}
                     if os.path.isdir(path)]
        for spelling in spellings:
            with self.subTest(cwd=spelling):
                with tempfile.TemporaryDirectory() as temporary, \
                        patch.object(worker, 'ROUTER_HOME', Path(temporary) / 'absent'), \
                        contextlib.redirect_stderr(io.StringIO()) as err, \
                        self.assertRaises(SystemExit):
                    worker.main(['--model', 'z-ai/glm-5.3-flash', '--effort', 'max',
                                 '--task', 'brief', '--cwd', spelling])
                self.assertIn('home folder', err.getvalue())

    def test_listing_models_from_the_home_folder_is_not_refused(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(worker, 'ROUTER_HOME', Path(temporary) / 'absent'), \
                contextlib.redirect_stdout(out):
            code = worker.main(['--list', '--cwd', str(Path.home())])
        self.assertEqual(code, 1)
        self.assertIn('router not reachable', out.getvalue())

    def test_brief_and_output_round_trip_as_utf8_on_every_platform(self):
        brief = 'Fix → ❌ \U0001f4dd “quotes” 中文'
        echo = 'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())'
        out, _, timed_out = worker.run_worker(
            [sys.executable, '-c', echo], brief, ROOT, dict(os.environ), 30)
        self.assertEqual((out, timed_out), (brief, False))

    def test_timeout_stops_the_worker_instead_of_waiting(self):
        started = time.monotonic()
        _, _, timed_out = worker.run_worker(
            [sys.executable, '-c', 'import time; time.sleep(30)'], '', ROOT, dict(os.environ), 1)
        self.assertTrue(timed_out)
        self.assertLess(time.monotonic() - started, 15)

    @unittest.skipIf(os.name == 'nt', 'the fake client is a shebang script')
    def test_run_resolves_the_model_and_never_prints_the_router_token(self):
        token = 'tok' + 'e' * 40
        alias = claude_alias('z-ai/glm-5.3-flash')

        class Listing(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({'data': [{'id': alias}]}).encode()
                self.send_response(200 if self.path == '/%s/v1/models' % token else 404)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Listing)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / 'mixed-router-state.json').write_text(
                json.dumps({'port': server.server_address[1], 'token': token}))
            claude = home / 'claude'
            claude.write_text(FAKE_CLAUDE % sys.executable)
            claude.chmod(0o755)
            out = io.StringIO()
            with patch.object(worker, 'ROUTER_HOME', home), \
                    patch.object(worker, 'RUNS', home / 'runs'), \
                    patch.dict(os.environ, {'CLAUDE_CODE_EXECPATH': str(claude)}), \
                    contextlib.redirect_stdout(out):
                code = worker.main(['--model', 'z-ai/glm-5.3-flash', '--effort', 'max',
                                    '--task', 'brief', '--cwd', temporary])
            result = json.loads(out.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(result['ok'])
            self.assertEqual(result['served'], [alias])
            self.assertIn('<router-token>', result['answer'])
            # The caller's own ~/.claude memory is excluded from the worker.
            self.assertIn(Path.home().as_posix() + '/.claude/**', result['answer'])
            self.assertNotIn(token, out.getvalue())
            self.assertNotIn(token, Path(result['transcript']).read_text())


if __name__ == '__main__':
    unittest.main()
