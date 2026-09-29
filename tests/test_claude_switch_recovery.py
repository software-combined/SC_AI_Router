"""A gateway user can always reach the subscription, and a refused switch reopens Claude."""
import itertools
import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from tests import claude_profile_sync_fixtures as fixtures
from tests import test_claude_profile_launch as launch
from tests.test_claude_desktop_config import desktop_config

A1, O1 = '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc'
A3, O3 = '87654321-4321-4567-8123-123456789abc', 'fedcbaab-4321-4567-8123-123456789abc'
CODE = 'claude-code-sessions'
REAL_INITIALIZED = fixtures.load_helper('claude_desktop_switch')._initialized
switcher = launch.switcher
EXE = '/apps/Claude.app/Contents/MacOS/Claude'
RUNNING = '10 1 501 Mon Sep 28 10:00:00 2026 S ' + EXE  # ps: pid, parent, user, start, state, path.


class Platform(launch.FakePlatform):
    def __init__(self, events, opens=True, stopped=True):
        super().__init__(events, stopped=stopped)
        self.opens, self.messages = opens, []

    def open_app(self, _platform, run=None):
        self.events.append('open')
        if not self.opens:
            raise OSError('Claude did not open')

    def show_message(self, message, _platform, run=None):
        self.messages.append(message)


class QuitRequest(Platform):
    """The real macOS quit wait, after the given answer to the quit request."""
    def __init__(self, events, answer, probes):
        super().__init__(events)
        self.answer, self.probes = answer, iter(probes)

    def request_stop(self, _platform, run=None):
        self.events.append('stop')
        desktop = switcher._platform

        def fake_run(argv, **kwargs):
            if argv[0] == '/bin/ps':
                return SimpleNamespace(returncode=0, stdout=next(self.probes), stderr='')
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer
        identity = dict(root='/apps/Claude.app', exe=EXE, user='501')
        with mock.patch.object(desktop, 'app_identity', return_value=identity), \
                mock.patch.object(desktop.time, 'sleep'), \
                mock.patch.object(desktop.time, 'monotonic', side_effect=itertools.count()):
            return desktop.request_stop('darwin', run=fake_run, timeout=3)  # Two checks after the quit.


def report(**counts):
    return dict({'copied': 0, 'replaced': 0, 'unchanged': 0, 'unshared': 0,
                 'pending': 0, 'failed': 0, 'errors': []}, **counts)


class SwitchRecoveryTests(unittest.TestCase):
    setUp = launch.ProfileLaunchTests.setUp  # An attached gateway profile, selected (3p).

    def switch(self, platform, sync):
        return switcher.switch(self.home, policy_check=lambda: False, sync=sync,
                               platform_ops=platform)

    def mode(self):
        return json.loads(self.config.read_text())['deploymentMode']

    def use_real_setup_check(self):
        """Only a subscription Code task can record the binding; none exists yet."""
        self.initialized.side_effect = REAL_INITIALIZED
        fixtures.profile(desktop_config.profile_root(self.env), 'Claude', A1, O1)
        (self.profile / 'config.json').write_text(json.dumps({'lastKnownAccountUuid': A3}))
        fixtures.third_party_identity(self.profile, A3, O3)

    def test_gateway_user_with_saved_tasks_reaches_the_subscription_for_setup(self):
        self.use_real_setup_check()
        fixtures.record(self.profile, CODE, A3, O3, 'gateway-task')
        platform, sync = Platform(self.events), mock.Mock()
        self.assertEqual(self.switch(platform, sync), '1p')
        sync.assert_not_called()
        self.assertEqual((self.mode(), self.events), ('1p', ['confirm', 'stop', 'open']))
        self.assertIn('setup only', platform.messages[0])

    def test_subscription_user_is_asked_for_a_code_task_before_claude_quits(self):
        self.use_real_setup_check()
        self.config.write_text(json.dumps({'deploymentMode': '1p'}))
        root = desktop_config.profile_root(self.env) / 'Claude'
        fixtures.record(root, CODE, A1, O1, 'old-subscription-task')
        with self.assertRaisesRegex(switcher.SwitchError,
                                    r'^Open a Code task in Claude, then try again\.$'):
            self.switch(Platform(self.events), mock.Mock())
        self.assertEqual((self.mode(), self.events), ('1p', []))

    def test_claude_that_did_not_close_in_time_is_reopened_unchanged(self):
        for opens, suffix in ((True, ''), (False, ' Open Claude to continue.')):
            with self.subTest(opens=opens):
                self.events.clear()
                sync = mock.Mock()
                with self.assertRaises(switcher.SwitchError) as refused:
                    self.switch(Platform(self.events, opens=opens, stopped=False), sync)
                self.assertEqual(str(refused.exception), 'Claude did not close in time. '
                                 'Finish your work and try again.' + suffix)
                self.assertEqual((self.mode(), self.events), ('3p', ['confirm', 'stop', 'open']))
                sync.assert_not_called()

    def test_quit_request_that_times_out_leaves_the_outcome_to_the_wait(self):
        held = subprocess.TimeoutExpired('osascript', 3)  # Claude holds its quit behind a prompt.
        self.assertEqual(self.switch(QuitRequest(self.events, held, [RUNNING, '']), lambda *_args: report()), '1p')
        # Still running at the deadline, or a quit request that fails at once: reopened unchanged.
        for answer, probes in ((held, [RUNNING] * 3), (SimpleNamespace(returncode=1), [RUNNING])):
            with self.assertRaisesRegex(switcher.SwitchError, r'^Claude did not close in time\.'):
                self.switch(QuitRequest(self.events, answer, probes), lambda *_args: report())
        self.assertEqual((self.mode(), self.events), ('1p', ['confirm', 'stop', 'open'] * 3))

    def test_refusal_after_quit_reopens_claude_unchanged(self):
        platform = Platform(self.events)
        with self.assertRaisesRegex(switcher.SwitchError, r'^Claude tasks were not fully shared\. Try again\.$'):
            self.switch(platform, lambda *_args: report(failed=1))
        self.assertEqual((self.mode(), self.events), ('3p', ['confirm', 'stop', 'open']))

    def test_refusal_after_quit_says_to_open_claude_when_it_cannot_reopen(self):
        with self.assertRaisesRegex(switcher.SwitchError, 'not fully shared.*Open Claude to continue'):
            self.switch(Platform(self.events, opens=False), lambda *_args: report(failed=1))
        self.assertEqual((self.mode(), self.events), ('3p', ['confirm', 'stop', 'open']))

    def test_unexpected_error_after_quit_reopens_claude_with_a_plain_message(self):
        platform = Platform(self.events)
        platform.is_running = mock.Mock(side_effect=RuntimeError('private profile detail'))
        with self.assertRaisesRegex(switcher.SwitchError, r'^Claude tasks were not fully shared\. Try again\.$'):
            self.switch(platform, lambda *_args: report())
        self.assertEqual((self.mode(), self.events), ('3p', ['confirm', 'stop', 'open']))

    def test_failed_reopen_keeps_a_message_that_already_says_open_claude(self):
        def select_subscription(*_args):  # The selection changes while tasks are shared.
            self.config.write_text(json.dumps({'deploymentMode': '1p'}))
            return report()
        with self.assertRaisesRegex(switcher.SwitchError,
                                    r'^Claude settings changed\. Open Claude and try again\.$'):
            self.switch(Platform(self.events, opens=False), select_subscription)
        self.assertEqual(self.events, ['confirm', 'stop', 'open'])

    def test_unshared_tasks_are_counted_after_a_successful_switch(self):
        for count, message in ((1, '1 saved task could not be shared and stayed where it was.'),
                               (2, '2 saved tasks could not be shared and stayed where they were.')):
            with self.subTest(count=count):
                platform = Platform(self.events)
                self.assertIsNotNone(self.switch(platform, lambda *_args: report(unshared=count)))
                self.assertEqual(platform.messages, [message])
