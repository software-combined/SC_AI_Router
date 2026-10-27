"""Switch dialogs use the verified compiled helper and an explicit safe result."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_native_setup import module, resources, ROOT


class WindowsDialogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve() / 'home'
        self.source = resources(self.home / 'setup/fixture', version='1.3.26')
        self.helper = self.source / 'control/scg-router-menu.exe'
        self.helper.parent.mkdir()
        self.helper.write_bytes(b'MZ helper fixture')
        self.icon = self.source / 'router/packaging/assets/router-icon.png'
        self.icon.parent.mkdir(parents=True)
        self.icon.write_bytes((ROOT / 'packaging/assets/router-icon.png').read_bytes())
        metadata = json.loads((self.source / 'installer.json').read_text())
        metadata.update(target='windows/x86_64', menu_sha256=hashlib.sha256(self.helper.read_bytes()).hexdigest())
        (self.source / 'installer.json').write_text(json.dumps(metadata))
        (self.home / 'setup-current').write_text('fixture')
        self.dialog = module('windows_dialog')

    def test_confirm_and_cancel_are_native_quiet_and_preserve_unicode(self):
        for code, marker, want in ((0, 'accept', True), (1, 'cancel', False)):
            run = mock.Mock(return_value=SimpleNamespace(returncode=code,
                stdout='SCG_ROUTER_DIALOG_RESULT=' + marker + '\n'))
            self.assertIs(self.dialog.show('Switch Codex — café?', self.home, True, run), want)
            self.assertEqual(run.call_args.args[0], [str(self.helper), '--dialog', str(self.icon)])
            self.assertEqual(run.call_args.kwargs['creationflags'], 0x08000000)
            self.assertEqual(run.call_args.kwargs['encoding'], 'utf-8')
            request = json.loads(run.call_args.kwargs['input'])
            self.assertEqual(request['labels'], ['Continue', 'Cancel'])
            self.assertEqual(request['text'], 'Switch Codex — café?')

    def test_old_or_failed_helpers_never_imply_consent(self):
        for code, stdout in ((0, ''), (2, ''), (0, 'SCG_ROUTER_DIALOG_RESULT=cancel'),
                             (1, 'SCG_ROUTER_DIALOG_RESULT=accept')):
            run = mock.Mock(return_value=SimpleNamespace(returncode=code, stdout=stdout))
            with self.assertRaises(OSError):
                self.dialog.show('Switch Codex?', self.home, True, run)

    def test_damaged_helper_is_refused_before_execution(self):
        self.helper.write_bytes(b'damaged helper')
        run = mock.Mock()
        with self.assertRaises(ValueError):
            self.dialog.show('Switch Codex?', self.home, True, run)
        run.assert_not_called()

    def test_waiting_window_uses_the_same_verified_native_helper(self):
        child = mock.Mock()
        with mock.patch.object(self.dialog.subprocess, 'Popen', return_value=child) as popen:
            self.assertIs(self.dialog.progress(self.home, 'Waiting for SCG Router', 'Cancel'), child)
        self.assertEqual(popen.call_args.args[0], [str(self.helper), '--progress', str(self.icon)])
        self.assertEqual(popen.call_args.kwargs['creationflags'], 0x08000000)
        self.assertEqual(json.loads(child.stdin.write.call_args.args[0])['labels'], ['Cancel'])

    def test_pre_dialog_helpers_use_the_styled_quiet_fallback_for_wait_and_cancel(self):
        for name in ('installer.json', 'payload/latest.json'):
            path = self.source / name
            doc = json.loads(path.read_text())
            doc['version'] = '1.3.16.207'
            path.write_text(json.dumps(doc))
        (self.source / 'router/packaging/VERSION').write_text('1.3.16.207')
        for code, marker, expected in ((0, 'accept', True), (1, 'cancel', False)):
            run = mock.Mock(return_value=SimpleNamespace(returncode=code,
                stdout='SCG_ROUTER_DIALOG_RESULT=' + marker))
            self.assertIs(self.dialog.show('Switch Codex?', self.home, True, run), expected)
            self.assertEqual(run.call_args.args[0][0], 'powershell')
            self.assertEqual(run.call_args.kwargs['creationflags'], 0x08000000)
            script = run.call_args.args[0][-1]
            for required in ("$f.Text='SCG Router'", "$b.Text='Continue'", "$b.DialogResult='OK'",
                             "$c.Text='Cancel'", "$c.DialogResult='Cancel'"):
                self.assertIn(required, script)
        with mock.patch.object(self.dialog.subprocess, 'Popen') as popen:
            self.dialog.progress(self.home, 'Waiting for SCG Router', 'Cancel')
        self.assertEqual(popen.call_args.args[0][0], 'powershell')
        self.assertEqual(popen.call_args.kwargs['creationflags'], 0x08000000)


if __name__ == '__main__':
    unittest.main()
