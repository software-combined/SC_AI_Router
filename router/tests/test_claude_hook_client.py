"""Opt-in real Windows client callback check; --init-only makes no model call."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from tests.claude_profile_sync_fixtures import load_helper
from tools.claude_probe_env import environment


@unittest.skipUnless(os.name == 'nt' and os.environ.get('SCG_TEST_CLAUDE_CLIENT') == '1',
                     'opt-in native Windows client check')
class CallbackClientTests(unittest.TestCase):
    def test_generated_callback_runs_with_spaces_unicode_and_shell_metacharacters(self):
        with tempfile.TemporaryDirectory(prefix="router ü's $name ` ") as temporary:
            work = Path(temporary)
            home = work / 'router'
            home.mkdir()
            launcher = home / 'claude_profile_launch.py'
            launcher.write_text(
                'import json,sys\nfrom pathlib import Path\n'
                'event=json.load(sys.stdin)\n'
                'Path(__file__).with_name("result.json").write_text(json.dumps({\n'
                ' "args":sys.argv[1:],"event":event.get("hook_event_name")}))\n', encoding='utf-8')
            env = environment(work, 'http://127.0.0.1:9/', 'synthetic-hook-check', 'low')
            load_helper('claude_profile_hook').install(home, sys.executable, env)
            result = subprocess.run([os.environ['CLAUDE_BIN'], '--init-only'],
                                    cwd=work, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            output = home / 'result.json'
            deadline = time.monotonic() + 10
            while not output.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(output.is_file(), 'Claude did not run the generated callback')
            self.assertEqual(json.loads(output.read_text()), {
                'args': ['--home', str(home), '--action', 'capture'], 'event': 'SessionStart'})
