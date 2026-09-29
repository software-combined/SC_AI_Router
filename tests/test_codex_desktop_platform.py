"""The shared macOS app helpers serving Switch Codex, with Claude's defaults kept.

Codex is found, quit and reopened by its own bundle id, and a running Claude
blocks only a Claude switch.
"""
import importlib.util
import os
import plistlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'codex_desktop_platform_test', ROOT / 'packaging' / 'claude_desktop_platform.py')
platform = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(platform)
CODEX = platform.App('com.openai.codex', ())


def result(stdout='', returncode=0):
    return SimpleNamespace(stdout=stdout, stderr='', returncode=returncode)


def bundle(root):
    (root / 'Contents/MacOS').mkdir(parents=True)
    (root / 'Contents/MacOS/ChatGPT').touch()
    (root / 'Contents/Info.plist').write_bytes(plistlib.dumps(
        {'CFBundleIdentifier': 'com.openai.codex', 'CFBundleExecutable': 'ChatGPT'}))
    return root


class SharedPlatformTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_codex_is_found_quit_and_reopened_by_its_own_bundle_id(self):
        app = bundle(self.root / 'ChatGPT.app')
        commands = []

        def run(argv, **kwargs):
            commands.append(argv)
            if argv[0] == '/usr/bin/mdfind':
                return result(str(app) if 'com.openai.codex' in argv[1] else '')
            if argv[0] == '/bin/ps':
                rows = [] if any('to quit' in c[-1] for c in commands) else [
                    '10 1 %s Mon Sep 28 10:00:00 2026 %s/Contents/MacOS/ChatGPT'
                    % (os.getuid(), app)]
                return result('\n'.join(rows))
            return result()

        identity = platform.app_identity('darwin', run=run, app=CODEX)
        self.assertEqual(identity['exe'], str(app / 'Contents/MacOS/ChatGPT'))
        self.assertTrue(platform.request_stop('darwin', run=run, app=CODEX))
        self.assertIn(['/usr/bin/osascript', '-e',
                       'tell application id "com.openai.codex" to quit'], commands)
        platform.open_app('darwin', run=run, app=CODEX)
        self.assertEqual(commands[-1], ['/usr/bin/open', str(app)])
        with self.assertRaises(OSError):
            platform.app_identity('darwin', run=run)  # Claude is not installed here

    def test_a_running_claude_blocks_only_a_claude_switch(self):
        identity = {'root': '/Applications/ChatGPT.app', 'user': '501',
                    'exe': '/Applications/ChatGPT.app/Contents/MacOS/ChatGPT'}
        rows = {20: dict(pid=20, parent=1, user='501', born='x',
                         exe='/Applications/Claude.app/Contents/MacOS/Claude')}
        self.assertFalse(platform._writers(rows, identity, {}, 'darwin', CODEX.writers))
        with self.assertRaisesRegex(OSError, 'unverified'):
            platform._writers(rows, identity, {}, 'darwin')
        with self.assertRaises(OSError):
            platform.app_identity('linux', app=CODEX)


if __name__ == '__main__':
    unittest.main()
