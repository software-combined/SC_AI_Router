"""A gateway user can always reach the subscription, and a refused switch reopens Claude."""
import json
import unittest
from unittest import mock

from tests import claude_profile_sync_fixtures as fixtures
from tests import test_claude_profile_launch as launch
from tests.test_claude_desktop_config import desktop_config

A1, O1 = '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc'
A3, O3 = '87654321-4321-4567-8123-123456789abc', 'fedcbaab-4321-4567-8123-123456789abc'
CODE = 'claude-code-sessions'
REAL_INITIALIZED = fixtures.load_helper('claude_desktop_switch')._initialized
switcher = launch.switcher


class Platform(launch.FakePlatform):
    def __init__(self, events, opens=True):
        super().__init__(events)
        self.opens, self.messages = opens, []

    def open_app(self, _platform, run=None):
        self.events.append('open')
        if not self.opens:
            raise OSError('Claude did not open')

    def show_message(self, message, _platform, run=None):
        self.messages.append(message)


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
