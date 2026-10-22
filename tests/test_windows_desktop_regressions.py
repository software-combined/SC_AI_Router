"""Store layouts retain the verified app; Windows dialogs never create consoles."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_codex_desktop_switch import switcher
from tests.test_codex_config_proof import proof, _load

dialog = _load('windows_client_dialog_test', 'packaging/client_dialog.py')
native = _load('windows_native_dialog_test', 'packaging/native_dialog.py')
notice = _load('windows_notice_console_test', 'packaging/notice.py')
NO_WINDOW = 0x08000000


class WindowsDesktopTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.app = self.root / 'StorePackage'
        self.exe = self.app / 'app' / 'ChatGPT.exe'
        self.cli = self.exe.parent / 'resources' / 'codex.exe'
        self.cli.parent.mkdir(parents=True)
        self.cli.touch()
        self.exe.touch()

    def test_store_cli_precedes_package_root_and_override_still_wins(self):
        legacy = self.app / 'resources' / 'codex.exe'
        legacy.parent.mkdir()
        legacy.touch()
        self.assertEqual(proof.codex_bin({}, self.app, app_exe=self.exe), str(self.cli))
        self.assertEqual(proof.codex_bin({'CODEX_BIN': '/chosen'}, self.app,
                                       app_exe=self.exe), '/chosen')
        self.assertEqual(proof.codex_bin({}, self.app), str(legacy))

    def test_switch_and_pending_recovery_prove_the_same_verified_app(self):
        home, config = self.root / 'router', self.root / 'config.toml'
        home.mkdir()
        state = {'port': 4321, 'token': 'fixture', 'openai_mode': 'subscription'}
        (home / 'mixed-router-state.json').write_text(json.dumps(state))
        block = switcher._blocks.build(home, state, 'subscription', False, 'default')
        switcher._blocks._codex.write_receipt(home, config, block, None, 'subscription', '')
        config.write_text(block)
        identity = {'root': str(self.app), 'exe': str(self.exe), 'user': 'fixture',
                    'app': 'Codex!App'}
        ops = mock.Mock()
        ops.app_identity.return_value = identity
        ops.confirm.return_value = True
        ops.request_stop.return_value = True
        ops.open_app.return_value = SimpleNamespace(returncode=0)
        with mock.patch.object(switcher.sys, 'platform', 'win32'), \
                mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(switcher._proof, 'prove', return_value=True) as prove:
            switcher.switch(home, platform_ops=ops, ready=lambda _: True)
            prove.assert_called_once_with(str(self.app), app_exe=str(self.exe))
            self.assertEqual(ops.app_identity.call_count, 1)
            self.assertEqual(ops.request_stop.call_args.kwargs['identity'], identity)
            self.assertEqual(ops.open_app.call_args.kwargs['identity'], identity)
            entry = switcher._receipts.codex_attachment(home)
            (home / switcher.MARKER).write_text(json.dumps({'to': 'switched', 'entry': entry}))
            prove.reset_mock()
            ops.confirm.return_value = False
            switcher.switch(home, platform_ops=ops, ready=lambda _: True)
            prove.assert_called_once_with(str(self.app), app_exe=str(self.exe))

    def test_windows_shared_runner_chooser_progress_and_notice_hide_console(self):
        run = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout='{}', stderr=''))
        platform = switcher._platform
        platform._json_command('{}', run)
        self.assertEqual(run.call_args.kwargs.get('creationflags'), NO_WINDOW)
        platform.show_message('Ready', 'win32', run=run)
        self.assertEqual(run.call_args.kwargs.get('creationflags'), NO_WINDOW)
        run.return_value.stdout = 'ChatGPT'
        dialog.ask('win32', 'powershell', run)
        self.assertTrue(all(call.kwargs.get('creationflags') == NO_WINDOW
                            for call in run.call_args_list[-2:]))
        with mock.patch.object(native.sys, 'platform', 'win32'), \
                mock.patch.object(native.dialog, 'tool', return_value='powershell'), \
                mock.patch.object(native.subprocess, 'Popen') as popen:
            native.choose('Choose', (('chatgpt', 'ChatGPT'),), run)
            self.assertEqual(run.call_args.kwargs.get('creationflags'), NO_WINDOW)
            with native.Progress():
                self.assertEqual(popen.call_args.kwargs.get('creationflags'), NO_WINDOW)
        with mock.patch.object(notice.sys, 'platform', 'win32'), \
                mock.patch.object(notice.subprocess, 'run', run), \
                mock.patch.object(notice.subprocess, 'Popen') as popen:
            notice._pid_alive(42)
            self.assertEqual(run.call_args.kwargs.get('creationflags'), NO_WINDOW)
            notice._spawn(['powershell'])
            self.assertTrue(popen.call_args.kwargs['creationflags'] & NO_WINDOW)

    def test_store_update_during_confirmation_refuses_before_settings_change(self):
        home, config = self.root / 'router', self.root / 'config.toml'
        home.mkdir()
        state = {'port': 4321, 'token': 'fixture', 'openai_mode': 'subscription'}
        (home / 'mixed-router-state.json').write_text(json.dumps(state))
        block = switcher._blocks.build(home, state, 'subscription', False, 'default')
        switcher._blocks._codex.write_receipt(home, config, block, None, 'subscription', '')
        config.write_text(block)
        identity = dict(root=str(self.app), exe=str(self.exe), user='fixture', app='Codex!App')
        changed = dict(identity, root=str(self.root / 'UpdatedPackage'), exe='updated.exe')
        ops = switcher._platform
        with mock.patch.object(switcher.sys, 'platform', 'win32'), \
                mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(ops, 'app_identity', side_effect=[identity, changed]), \
                mock.patch.object(ops, 'confirm', return_value=True), \
                mock.patch.object(ops, '_snapshot', return_value={}), \
                mock.patch.object(ops, 'open_app') as reopen, \
                mock.patch.object(switcher._proof, 'prove', return_value=True):
            before = config.read_bytes(), (home / 'activation.json').read_bytes()
            with self.assertRaises(switcher.SwitchError):
                switcher.switch(home, platform_ops=ops, ready=lambda _: True)
            self.assertEqual((config.read_bytes(), (home / 'activation.json').read_bytes()), before)
            reopen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
