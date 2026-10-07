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
import json, os, sys
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
elif mode == 'isolated':
    # The child must get an empty config dir of its own: never the parent's
    # CLAUDE_CONFIG_DIR and never ~/.claude, where the owner's setup lives.
    config = os.environ.get('CLAUDE_CONFIG_DIR') or os.path.expanduser('~/.claude')
    open(os.environ['FAKE_RECORD'], 'w').write(config)
    owners = {os.path.realpath(os.environ['FAKE_OWNER_CONFIG']),
              os.path.realpath(os.path.expanduser('~/.claude'))}
    if os.path.realpath(config) in owners or not os.path.isdir(config) or os.listdir(config):
        out = {'is_error': True, 'subtype': 'success', 'num_turns': 1,
               'result': 'The owner setup reached the probe.'}
    else:
        out = {'is_error': False, 'num_turns': 2, 'result': marker}
elif mode == 'bounded':
    expected = {'CLAUDE_CODE_EFFORT_LEVEL': 'low',
                'CLAUDE_CODE_MAX_RETRIES': '0', 'CLAUDE_CODE_RETRY_WATCHDOG': '0',
                'CLAUDE_CODE_MAX_OUTPUT_TOKENS': '2048', 'CLAUDE_CODE_MAX_TURNS': '3'}
    safe = all(os.environ.get(key) == value for key, value in expected.items())
    safe = safe and not os.environ.get('ANTHROPIC_API_KEY')
    out = {'is_error': not safe, 'num_turns': 2, 'result': marker if safe else ''}
else:
    out = {'is_error': False, 'num_turns': 2, 'result': marker}
if 'stream-json' in sys.argv and mode != 'echo-only':
    for name, identifier in (('ToolSearch', 'search-id'), ('mcp__stubtools__tool_000', 'stub-id')):
        print(json.dumps({'type':'assistant','message':{'model':'fake/model','content':[
            {'type':'tool_use','id':identifier,'name':name,'input':{}}]}}))
        print(json.dumps({'type':'user','message':{'content':[
            {'type':'tool_result','tool_use_id':identifier}]}}))
out['type'] = 'result'
print(json.dumps(out))
if mode == 'failed-exit':
    raise SystemExit(1)
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

    def _run(self, mode, *extra, **overrides):
        env = dict(os.environ, CLAUDE_BIN=str(self.binary), FAKE_CLAUDE_MODE=mode,
                   FAKE_EXPECT_BASE_URL='http://127.0.0.1:1/test-token/')
        env.pop('ANTHROPIC_BASE_URL', None)  # a developer's own gateway must not pass for it
        env.pop('CLAUDE_CONFIG_DIR', None)
        env.update({key: value for key, value in overrides.items() if value is not None})
        return subprocess.run(
            [sys.executable, str(PROBE), '--home', str(self.home),
             '--models', MODEL, '--json', *extra],
            cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120)

    def _row(self, mode, **overrides):
        done = self._run(mode, **overrides)
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

    def test_failed_process_cannot_certify_an_earlier_success_result(self):
        done, row = self._row('failed-exit')
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

    def test_the_client_never_loads_the_owner_config(self):
        # Sonnet 5.5 obeyed the owner's global instructions from ~/.claude and
        # read a skill before the probe's files; that extra call failed the gate.
        owner = self.home / 'owner'
        (owner / '.claude').mkdir(parents=True)
        (owner / '.claude' / 'settings.json').write_text('{}')
        record = self.home / 'seen-config'
        for parent in (str(owner / '.claude'), None):
            with self.subTest(parent_config=parent is not None):
                done, row = self._row('isolated', HOME=str(owner), CLAUDE_CONFIG_DIR=parent,
                                      FAKE_OWNER_CONFIG=str(owner / '.claude'),
                                      FAKE_RECORD=str(record))
                self.assertTrue(row['pass'], row)
                self.assertFalse(Path(record.read_text()).exists())  # removed afterwards

    def test_the_report_never_carries_the_loopback_url(self):
        done, _ = self._row('exact')
        self.assertNotIn('test-token', done.stdout)
        self.assertNotIn('127.0.0.1', done.stdout)

    def test_parent_effort_retries_and_api_key_cannot_override_probe_limits(self):
        done = self._run('bounded', '--effort', 'low',
                        CLAUDE_CODE_EFFORT_LEVEL='max', CLAUDE_CODE_MAX_RETRIES='10',
                        CLAUDE_CODE_RETRY_WATCHDOG='1', CLAUDE_CODE_MAX_TURNS='100',
                        CLAUDE_CODE_MAX_OUTPUT_TOKENS='32000', ANTHROPIC_API_KEY='synthetic-owner')
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(json.loads(done.stdout)['results'][0]['pass'])

    def test_the_deferred_leg_runs_with_the_installed_client_settings(self):
        done = self._run('exact', '--deferred')
        report = json.loads(done.stdout)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual([row['leg'] for row in report['results']],
                         ['read', 'deferred'])
        self.assertTrue(all(row['pass'] for row in report['results']))

    def test_deferred_marker_without_tool_execution_is_rejected(self):
        done = self._run('echo-only', '--deferred')
        report = json.loads(done.stdout)
        self.assertEqual(done.returncode, 1)
        self.assertEqual([row['pass'] for row in report['results']], [True, False])
