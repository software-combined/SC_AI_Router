"""Retained dialogs work after the download leaves; failed notices stay pending."""
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ai_router import key_dialog
from tests.test_native_setup import ROOT, module, payload, resources


class DialogDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = self.root / 'home'
        self.home.mkdir()
        self.native_env = dict(os.environ)
        self.enterContext(mock.patch.dict(os.environ, {'HOME': str(self.root),
                          'USERPROFILE': str(self.root), 'PATH': '',
                          'ROUTER_HOME': str(self.root / 'other')}, clear=True))
        self.client = module('client_dialog')

    def retained(self):
        download = resources(self.root / 'download')
        wrapper = download / 'gui/bin/zenity'
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text('#!/bin/sh\nexit 0\n')
        wrapper.chmod(0o755)
        with mock.patch.dict(os.environ, self.native_env, clear=True):
            kept = payload.retained(download, self.home)
        (self.home / 'setup-current').write_text(kept.name + '\n')
        shutil.rmtree(download)
        return kept / 'gui/bin/zenity'

    def test_chooser_and_key_dialog_find_retained_copy_without_download_or_path(self):
        wrapper = self.retained()
        args = SimpleNamespace(dry_run=False, clients=None, client=None,
                               desktop=False, choose_clients=True)
        run = mock.Mock(side_effect=[SimpleNamespace(returncode=0, stdout=value)
                                    for value in ('Claude', 'Terminal')])
        with mock.patch('shutil.which', return_value=None), redirect_stdout(io.StringIO()):
            self.assertTrue(self.client.maybe_ask(args, self.home, 'linux', run=run))
            self.assertEqual(args.clients, 'claude')
            self.assertEqual(run.call_args.args[0][0], str(wrapper.resolve()))
            with mock.patch.dict(os.environ, {'ROUTER_HOME': str(self.home)}):
                self.assertEqual(key_dialog.tool('linux'), str(wrapper.resolve()))

    def test_failed_renewal_presentation_does_not_suppress_a_graphical_retry(self):
        self.retained()
        notice, native = module('download_notice'), module('native_dialog')
        auth = mock.Mock()
        load = notice._load
        def modules(name):
            return native if name == 'native_dialog' else auth if name == 'download_auth' else load(name)
        with mock.patch.object(notice, '_load', side_effect=modules), \
                mock.patch.object(native.sys, 'platform', 'linux'), \
                mock.patch.dict(os.environ, {'DISPLAY': ':9'}), \
                mock.patch('shutil.which', return_value='/system/zenity'), \
                mock.patch.object(native.platform, '_run', return_value=SimpleNamespace(
                    returncode=1, stdout='', stderr='Gtk-WARNING: cannot open display')) as run:
            self.assertFalse(notice.show(self.home, now=100000))
            self.assertFalse((self.home / 'download-notice.json').exists())
            auth.signin.assert_not_called()
            run.return_value = SimpleNamespace(returncode=0, stdout='', stderr='')
            self.assertTrue(notice.show(self.home, now=100001))
            self.assertEqual(json.loads((self.home / 'download-notice.json').read_text()),
                             {'shown': 100001})
            auth.signin.assert_called_once_with(self.home)

    def test_invalid_pointer_or_missing_wrapper_falls_back_to_system_tool(self):
        wrapper = self.retained()
        pointer = self.home / 'setup-current'
        valid = pointer.read_text()
        for value in ('', '../outside', '/outside', valid + '\n', valid + 'more',
                      '1.2.0-deadbeef', valid + valid, ' ' + valid):
            with self.subTest(value=value):
                pointer.write_text(value)
                self.assertEqual(self.client.tool('linux', lambda _: '/system/zenity', self.home),
                                 '/system/zenity')
                self.assertIsNone(self.client.tool('linux', lambda _: None, self.home))
        pointer.write_text(valid)
        if os.name != 'nt':
            wrapper.chmod(0o600)
            self.assertIsNone(self.client.tool('linux', lambda _: None, self.home))
        wrapper.unlink()
        self.assertEqual(self.client.tool('linux', lambda _: '/system/zenity', self.home),
                         '/system/zenity')

    @unittest.skipIf(os.name == 'nt', 'Unprivileged Windows cannot create these file links.')
    def test_pointer_folder_and_wrapper_symlink_escapes_are_rejected(self):
        wrapper = self.retained()
        pointer, folder = self.home / 'setup-current', wrapper.parents[2]
        outside = self.root / 'outside'
        shutil.copytree(folder, outside)
        target = self.root / 'pointer'
        target.write_text(pointer.read_text())
        for link, destination in ((pointer, target), (wrapper, outside / 'gui/bin/zenity'),
                                  (folder, outside), (self.home / 'setup', self.root)):
            with self.subTest(link=link):
                backup = link.with_name(link.name + '.saved')
                link.rename(backup)
                link.symlink_to(destination)
                try:
                    self.assertIsNone(self.client.tool('linux', lambda _: None, self.home))
                finally:
                    link.unlink()
                    backup.rename(link)

    def test_platform_confirmation_distinguishes_cancel_and_presentation_failure(self):
        native = module('native_dialog')
        for name, rows in (
                ('linux', ((0, '', '', True), (1, '', '', False),
                           (1, '', 'cannot open display', None), (2, '', '', None))),
                ('win32', ((0, 'SCG_ROUTER_DIALOG_RESULT=accept', '', True),
                           (1, 'SCG_ROUTER_DIALOG_RESULT=cancel', 'progress output', False),
                           (0, '', '', None), (1, '', '', None),
                           (1, 'SCG_ROUTER_DIALOG_RESULT=accept', '', None),
                           (1, '', 'PowerShell error', None), (2, '', '', None))),
                ('darwin', ((0, 'button returned:Continue', '', True),
                            (1, '', 'execution error: User canceled. (-128)', False),
                            (1, '', 'execution error: unavailable (-600)', None),
                            (0, '', '', None)))):
            for code, stdout, stderr, expected in rows:
                with self.subTest(platform=name, code=code, stderr=stderr), \
                        mock.patch.object(native.sys, 'platform', name), \
                        mock.patch.dict(os.environ, {'DISPLAY': ':9'}), \
                        mock.patch('shutil.which', return_value='/dialog'):
                    run = mock.Mock(return_value=SimpleNamespace(
                        returncode=code, stdout=stdout, stderr=stderr))
                    self.assertIs(native.confirm_result('Question', self.home, run), expected)
                    self.assertEqual(run.call_args.args[0][0], '/dialog')

    def test_missing_display_launch_error_and_timeout_stay_pending_then_cancel_suppresses(self):
        wrapper = self.retained()
        notice, native, auth = module('download_notice'), module('native_dialog'), mock.Mock()
        load = notice._load
        def modules(name):
            return native if name == 'native_dialog' else auth if name == 'download_auth' else load(name)
        with mock.patch.object(notice, '_load', side_effect=modules), \
                mock.patch.object(native.sys, 'platform', 'linux'), \
                mock.patch.object(native.platform, '_run') as run, \
                mock.patch.object(native, 'message') as message:
            self.assertFalse(notice.show(self.home, now=100000))
            run.assert_not_called()
            with mock.patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-0'}):
                for failure in (FileNotFoundError(), subprocess.CalledProcessError(2, 'dialog'),
                                subprocess.TimeoutExpired('dialog', 120)):
                    run.side_effect = failure
                    self.assertFalse(notice.show(self.home, now=100001))
                    self.assertFalse((self.home / 'download-notice.json').exists())
                run.side_effect = None
                run.return_value = SimpleNamespace(returncode=1, stdout='', stderr='')
                self.assertFalse(notice.show(self.home, now=100002))
                argv = run.call_args.args[0]
                self.assertEqual(argv[0], str(wrapper.resolve()))
                self.assertIn('SCG Router', argv)
                self.assertIn(str(native.ICON), argv)
                self.assertEqual(argv[argv.index('--ok-label') + 1], 'Continue')
                self.assertEqual(argv[argv.index('--cancel-label') + 1], 'Cancel')
                before = run.call_count
                self.assertFalse(notice.show(self.home, now=100003))
                self.assertEqual(run.call_count, before)
            auth.signin.assert_not_called()
            message.assert_not_called()
            self.assertEqual(json.loads((self.home / 'download-notice.json').read_text()),
                             {'shown': 100002})

    def test_signin_failure_message_is_best_effort(self):
        notice, native = module('download_notice'), module('native_dialog')
        auth = mock.Mock()
        auth.signin.side_effect = OSError('unavailable')
        load = notice._load
        with mock.patch.object(notice, '_load', side_effect=lambda name:
                native if name == 'native_dialog' else auth if name == 'download_auth' else load(name)), \
                mock.patch.object(native, 'confirm_result', return_value=True), \
                mock.patch.object(native, 'message', side_effect=subprocess.TimeoutExpired('dialog', 120)):
            self.assertFalse(notice.show(self.home, now=100000))
        self.assertTrue((self.home / 'download-notice.json').is_file())

    @unittest.skipIf(os.name == 'nt', 'The retained Linux wrapper uses POSIX shell.')
    def test_only_the_wrapper_child_receives_bundled_gtk_environment(self):
        gui = self.root / 'gui'
        (gui / 'bin').mkdir(parents=True)
        (gui / 'libexec').mkdir()
        wrapper = gui / 'bin/zenity'
        shutil.copyfile(ROOT / 'packaging/native/zenity-wrapper.sh', wrapper)
        executable = gui / 'libexec/zenity'
        executable.write_text('#!/bin/sh\nprintf "%s\\n" "$LD_LIBRARY_PATH" '
                              '"$GI_TYPELIB_PATH" "$GSETTINGS_SCHEMA_DIR"\n')
        executable.chmod(0o755)
        env = module('native_setup').environment(self.root)
        env['PATH'] += ':/usr/bin:/bin'
        names = ('LD_LIBRARY_PATH', 'GI_TYPELIB_PATH', 'GSETTINGS_SCHEMA_DIR')
        self.assertFalse(any(name in env for name in names))
        result = subprocess.run(['/bin/sh', str(wrapper)], env=env, text=True,
                                capture_output=True, timeout=5, check=True)
        self.assertEqual(result.stdout.splitlines(), [str(gui / 'lib'),
                         str(gui / 'lib/girepository-1.0'), str(gui / 'share/glib-2.0/schemas')])
        self.assertFalse(any(name in os.environ for name in names))


if __name__ == '__main__':
    unittest.main()
