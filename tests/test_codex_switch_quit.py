"""Quitting an app for a switch, and the Switch Codex run log.

Crash reporters (`crashpad_handler`) write only crash reports and can outlive
an app update by days, so they never keep a switch waiting. An app that did
not close is reopened before Switch Codex refuses, and every run appends one
line to logs/codex-switch.log that names only basenames, never paths.
"""
import json
import os
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests._platform import unix_only
from tests.test_claude_desktop_platform import PlatformHarness, platform
from tests.test_codex_desktop_switch import FakeApp, switcher

blocks = switcher._blocks
APP = '/Applications/ChatGPT.app'
HELPERS = APP + '/Contents/Frameworks/Codex Framework.framework/Versions/%s/Helpers/'
DID_NOT_CLOSE = ('The ChatGPT app (Codex) did not close. Quit it from the ChatGPT menu, close '
                 'any Codex sessions in Terminal, then open Switch Codex again.')


def row(pid, parent, exe, born='Wed Sep 30 12:22:59 2026'):
    return dict(pid=pid, parent=parent, user='501', born=born, exe=exe)


class CrashReporterTests(unittest.TestCase):
    identity = dict(root=APP, exe=APP + '/Contents/MacOS/ChatGPT', user='501', app='Codex!App')

    def stop(self, name, snapshots):
        harness = PlatformHarness(name, self.identity, snapshots)
        with mock.patch.object(platform, 'app_identity', return_value=self.identity), \
                mock.patch.object(platform.time, 'monotonic', return_value=0):
            # With no time left, the first check after the quit decides.
            return platform.request_stop(name, run=harness, timeout=0)

    def test_crash_reporters_never_hold_the_quit_but_the_app_still_does(self):
        main = row(10, 1, self.identity['exe'])
        # Left running by the previous app version, then the current app's own.
        stale = row(20, 1, HELPERS % '153.0.8010.53' + 'browser_crashpad_handler',
                    born='Thu Sep 24 08:24:00 2026')
        own = row(21, 10, HELPERS % '154.0.8037.57' + 'browser_crashpad_handler')
        running = [main, stale, own]
        self.assertIs(self.stop('darwin', [running, [stale, dict(own, parent=1)]]), True)
        self.assertIs(self.stop('darwin', [running, running]), False)
        windows = row(22, 1, APP + '/Chrome_Crashpad_Handler.exe')  # case folds on Windows
        self.assertIs(self.stop('win32', [[main, windows], [windows]]), True)


@unix_only
class SwitchCodexQuitTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.home, config, self.app = root / 'router', root / 'config.toml', root / 'ChatGPT.app'
        self.home.mkdir()
        cli = self.app / switcher._proof.BUNDLED[0]
        cli.parent.mkdir(parents=True)
        cli.touch()
        for patcher in (mock.patch.object(switcher.sys, 'platform', 'darwin'),
                        mock.patch.dict(os.environ)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop('CODEX_BIN', None)
        state = {'port': 4321, 'token': 'tok', 'openai_mode': 'subscription'}
        (self.home / 'mixed-router-state.json').write_text(json.dumps(state))
        block = blocks.build(self.home, state, 'subscription', False, 'default')
        blocks._codex.write_receipt(self.home, config, block, None, 'subscription', '')
        config.write_text(block)
        self.log = self.home / 'logs' / 'codex-switch.log'

    def switch(self, app, run=None):
        return switcher.switch(self.home, run=run or mock.Mock(), platform_ops=app,
                               prove=lambda root: True, ready=lambda home: True)

    def lines(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_an_app_that_did_not_close_is_reopened_refused_and_logged(self):
        app = FakeApp(self.app, stops=False)
        still = [str(self.app / 'Contents/MacOS/ChatGPT'), '/usr/libexec/logd',
                 str(self.app / 'Contents/Frameworks/Helpers/browser_crashpad_handler')]
        run = mock.Mock(return_value=SimpleNamespace(stdout='\n'.join(still) + '\n', returncode=0))
        with self.assertRaisesRegex(switcher.SwitchError, '^%s$' % re.escape(DID_NOT_CLOSE)):
            self.switch(app, run)
        self.assertEqual([call[0] for call in app.calls], ['confirm', 'stop', 'open'])
        run.assert_called_once_with(['/bin/ps', '-axo', 'comm='], capture_output=True,
                                    text=True, timeout=5)
        [line] = self.lines()
        self.assertEqual((line['to'], line['result'], line['open']),
                         ('switched', DID_NOT_CLOSE, ['ChatGPT', 'browser_crashpad_handler']))

    def test_each_run_logs_its_target_and_result_and_a_failed_log_changes_nothing(self):
        self.assertIsNone(self.switch(FakeApp(self.app, confirm=False)))
        self.assertEqual(self.switch(FakeApp(self.app)), 'switched')
        cancelled, done = self.lines()
        self.assertEqual((cancelled['to'], cancelled['result']), ('switched', 'cancelled'))
        self.assertEqual((done['to'], done['result']), ('switched', 'done'))
        self.assertNotIn('open', done)
        self.assertIsNotNone(datetime.fromisoformat(done['at']).utcoffset())
        self.log.unlink()
        self.log.mkdir()  # the line cannot be written, and the switch still goes ahead
        self.assertEqual(self.switch(FakeApp(self.app)), 'switched_back')


if __name__ == '__main__':
    unittest.main()
