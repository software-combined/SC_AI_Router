"""Acceptance-harness verification for the Claude Code probe.

The probe drives the installed `claude` binary; CLAUDE_BIN swaps in this
scripted fake so the harness legs themselves are proven offline. The rule
under test is what counts as a finished row: a model that reads the file and
narrates the answer has done the job, while an empty or refused turn must
still fail. No network, no billing, no client install.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._platform import unix_only

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / 'tools' / 'probe_claude_code.py'
MODEL = 'fake/model'

FAKE_BIN = '''#!/usr/bin/env python3
import json, os
mode = os.environ.get('FAKE_CLAUDE_MODE', 'exact')
marker = open('probe.txt').read().strip()
if mode == 'prose':
    out = {'is_error': False, 'num_turns': 2,
           'result': 'The contents of probe.txt are:\\n' + marker}
elif mode == 'empty':
    out = {'is_error': False, 'num_turns': 2, 'result': ''}
elif mode == 'refused':
    out = {'is_error': True, 'subtype': 'error_during_execution', 'num_turns': 1,
           'result': 'API Error: 409 refused this request'}
elif mode == 'gateway':
    # Claude Code lets its process environment outrank the --settings file, and
    # a parent session may export its own address: only the child env counts.
    if os.environ.get('ANTHROPIC_BASE_URL') == os.environ['FAKE_EXPECT_BASE_URL']:
        out = {'is_error': False, 'num_turns': 2, 'result': marker}
    else:
        out = {'is_error': True, 'subtype': 'success', 'num_turns': 1,
               'result': 'There is an issue with the selected model.'}
else:
    out = {'is_error': False, 'num_turns': 2, 'result': marker}
print(json.dumps(out))
'''


@unix_only
class ClaudeCodeProbeTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix='scg-probe-test.'))
        self.addCleanup(shutil.rmtree, self.home, True)
        (self.home / 'mixed-router-state.json').write_text(json.dumps(
            {'port': 1, 'token': 'test-token'}))
        self.binary = self.home / 'fake-claude'
        self.binary.write_text(FAKE_BIN)
        os.chmod(self.binary, 0o755)

    def _run(self, mode, *extra):
        env = dict(os.environ, CLAUDE_BIN=str(self.binary), FAKE_CLAUDE_MODE=mode,
                   FAKE_EXPECT_BASE_URL='http://127.0.0.1:1/test-token/')
        env.pop('ANTHROPIC_BASE_URL', None)  # a developer's own gateway must not pass for it
        return subprocess.run(
            [sys.executable, str(PROBE), '--home', str(self.home),
             '--models', MODEL, '--json', *extra],
            cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120)

    def _row(self, mode):
        done = self._run(mode)
        report = json.loads(done.stdout)
        self.assertEqual(report['rows'], 1, done.stdout + done.stderr)
        return done, report['results'][0]

    def test_exact_echo_passes(self):
        done, row = self._row('exact')
        self.assertTrue(row['pass'], row)
        self.assertEqual(done.returncode, 0)

    def test_a_narrated_answer_still_passes(self):
        # google/gemini-3.1-pro-preview wraps the marker in prose on some
        # turns; an exact-echo rule reported that working row as a failure.
        done, row = self._row('prose')
        self.assertTrue(row['pass'], row)
        self.assertEqual(done.returncode, 0)

    def test_an_empty_answer_fails(self):
        # The shape google/gemini-3.8-flash produced before the repair.
        done, row = self._row('empty')
        self.assertFalse(row['pass'], row)
        self.assertEqual(done.returncode, 1)

    def test_a_refused_turn_fails_and_names_the_subtype(self):
        done, row = self._row('refused')
        self.assertFalse(row['pass'], row)
        self.assertEqual(row['error'], 'error_during_execution')
        self.assertEqual(done.returncode, 1)

    def test_the_router_address_reaches_the_client_process_environment(self):
        # On 29 Sep 2026 a probe started from a Claude Code session inherited
        # ANTHROPIC_BASE_URL=https://api.anthropic.com, which outranks the
        # --settings file, so every leg went to Anthropic on the user's login.
        done, row = self._row('gateway')
        self.assertTrue(row['pass'], row)
        self.assertEqual(done.returncode, 0)

    def test_the_report_never_carries_the_loopback_url(self):
        done, _ = self._row('exact')
        self.assertNotIn('test-token', done.stdout)
        self.assertNotIn('127.0.0.1', done.stdout)

    def test_the_deferred_leg_runs_with_the_installed_client_settings(self):
        # The fake echoes probe.txt, so the marker proves the harness reached
        # the same acceptance rule with the deferred leg's own prompt, tool
        # list and env; the record names the leg it ran.
        done = self._run('exact', '--deferred')
        report = json.loads(done.stdout)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual([row['leg'] for row in report['results']],
                         ['read', 'deferred'])
        self.assertTrue(all(row['pass'] for row in report['results']))
