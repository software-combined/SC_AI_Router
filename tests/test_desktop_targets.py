"""Explicit destinations cannot reverse a stale menu selection."""
import unittest
import tempfile
from pathlib import Path
from unittest import mock

from tests import test_codex_desktop_switch as codex_tests
from tests import test_claude_desktop_switch as claude_tests

codex, claude = codex_tests.switcher, claude_tests.switcher


class DesktopTargetTests(unittest.TestCase):
    def fixture(self, kind):
        case = kind()
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def test_codex_current_destination_is_a_noop(self):
        case = self.fixture(codex_tests.SwitchFlowTests)
        app = case.fake()
        self.assertEqual(codex.switch(case.home, target='switched_back', platform_ops=app),
                         'switched_back')
        self.assertEqual(app.calls, [])

    def test_codex_explicit_selection_is_idempotent(self):
        case = self.fixture(codex_tests.SwitchFlowTests)
        for target in ('switched', 'switched', 'switched_back', 'switched_back'):
            app = case.fake()
            self.assertEqual(codex.switch(case.home, target=target, platform_ops=app,
                                         prove=case.prove(), ready=lambda _: True), target)
            if not app.calls:
                self.assertEqual(target, codex._blocks.current(case.home))
        self.assertEqual(len(case.proofs), 1)

    def test_claude_current_destination_does_not_quit_or_copy_tasks(self):
        case = self.fixture(claude_tests.SwitchTests)
        self.assertEqual(claude.switch(case.home, target='3p', run=case.run,
                                      policy_check=case.policy), '3p')
        case.run.assert_not_called()
        case.sync.assert_not_called()

    def test_claude_switch_refuses_during_an_installer_operation(self):
        case = self.fixture(claude_tests.SwitchTests)
        with claude._service.install_lock(case.home) as held:
            self.assertTrue(held)
            with self.assertRaisesRegex(claude.SwitchError, 'updating'):
                claude.switch(case.home, target='1p', run=case.run)
        case.run.assert_not_called()

    def test_invalid_targets_never_reach_the_lifecycle(self):
        for owner in (codex, claude):
            with mock.patch.object(owner, '_service') as service:
                with self.assertRaises(ValueError):
                    owner.switch('/unused', target='untrusted')
                service.install_lock.assert_not_called()

    def test_codex_windows_and_linux_use_the_selected_platform_lifecycle(self):
        case = self.fixture(codex_tests.SwitchFlowTests)
        for name in ('win32', 'linux'):
            with mock.patch.object(codex.sys, 'platform', name):
                cli = case.app / 'resources/codex.exe'
                cli.parent.mkdir(exist_ok=True)
                cli.write_bytes(b'MZ fixture')
                version = mock.Mock(return_value=mock.Mock(returncode=0,
                    stdout='codex-cli 0.163.0-alpha.11', stderr=''))
                app = mock.Mock(wraps=case.fake())
                for target in ('switched', 'switched_back'):
                    self.assertEqual(codex.switch(case.home, target=target, platform_ops=app,
                                                 prove=case.prove(), ready=lambda _: True,
                                                 run=version), target)
                    self.assertEqual(app.request_stop.call_args.args[0], name)
                    self.assertEqual(app.open_app.call_args.args[0], name)

    def test_linux_open_uses_the_verified_client_desktop_id(self):
        platform = codex._platform
        with mock.patch.object(platform, 'app_identity', return_value={'desktop_id': 'codex-desktop'}):
            run = mock.Mock(return_value=mock.Mock(returncode=0))
            platform.open_app('linux', run=run, app=codex.CODEX)
        self.assertEqual(run.call_args.args[0], ['gtk-launch', 'codex-desktop'])

    def test_non_mac_bundled_cli_is_bound_to_the_verified_application(self):
        with tempfile.TemporaryDirectory() as root:
            cli = Path(root) / 'resources/codex.exe'
            cli.parent.mkdir()
            cli.write_bytes(b'MZfixture')
            version = mock.Mock(return_value=mock.Mock(returncode=0, stdout='codex-cli 0.163.0'))
            self.assertEqual(codex._proof.codex_bin({}, root, platform_name='win32', run=version), str(cli))
