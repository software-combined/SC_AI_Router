"""The real menu entry records subprocess outcomes without copied installer output."""
import json
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_native_setup import module


class MenuInstallationEvidenceTests(unittest.TestCase):
    def run_menu(self, home, run):
        control = module('desktop_control')
        original = control.load
        dialog = SimpleNamespace(confirm=lambda _: True)
        controller = SimpleNamespace(installer=lambda _: home / 'install.py')
        with mock.patch.object(control, 'load', side_effect=lambda name:
                dialog if name == 'native_dialog' else controller if name == 'native_controller'
                else original(name)):
            return control.execute(home, home, 'updates.install', run=run)

    def events(self, home):
        text = (home / 'logs/update.log').read_text()
        self.assertNotIn('PRIVATE', text)
        self.assertNotIn(str(home), text)
        return [json.loads(line) for line in text.splitlines()]

    def test_menu_update_records_start_and_successful_child_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            result = SimpleNamespace(returncode=0, stdout='PRIVATE captured settings', stderr='PRIVATE')
            self.assertEqual(self.run_menu(home, mock.Mock(return_value=result))['outcome'], 'done')
            rows = self.events(home)
            self.assertEqual([row['event'] for row in rows], ['started', 'exited'])
            self.assertTrue(all(row['origin'] == 'menu' and row['task'] == 'update' for row in rows))
            self.assertEqual(rows[-1]['status'], 0)
            self.assertTrue(all(set(row) <= {'at', 'event', 'origin', 'task', 'status', 'error'} for row in rows))

    def test_menu_launch_failure_is_recorded_before_a_target_can_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            with self.assertRaises(OSError):
                self.run_menu(home, mock.Mock(side_effect=OSError('PRIVATE path')))
            rows = self.events(home)
            self.assertEqual([row['event'] for row in rows], ['started', 'failed'])
            self.assertEqual((rows[-1]['status'], rows[-1]['error']), (1, 'launch_failed'))

    def test_deferred_menu_update_is_not_reported_as_installed(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            result = SimpleNamespace(returncode=0, stdout='deferred: another operation\n', stderr='')
            with self.assertRaisesRegex(RuntimeError, 'busy'):
                self.run_menu(home, mock.Mock(return_value=result))
            self.assertEqual(self.events(home)[-1]['event'], 'deferred')

    def test_actual_busy_update_lock_reaches_the_menu_as_deferred(self):
        updater = module('updater')
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            args = SimpleNamespace(home=str(home), express_only=False)
            def child(*_, **__):
                output = io.StringIO()
                with mock.patch.object(updater._svc, 'install_lock', return_value=contextlib.nullcontext(False)), \
                        contextlib.redirect_stdout(output):
                    code = updater.do_update(args, _sleep=lambda _: None)
                return SimpleNamespace(returncode=code, stdout=output.getvalue(), stderr='')
            with self.assertRaisesRegex(RuntimeError, 'busy'):
                self.run_menu(home, child)
            self.assertEqual(self.events(home)[-1]['event'], 'deferred')

    def test_nonzero_installer_exit_retains_its_numeric_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            result = SimpleNamespace(returncode=7, stdout='PRIVATE', stderr='PRIVATE')
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                self.run_menu(home, mock.Mock(return_value=result))
            self.assertEqual(self.events(home)[-1]['status'], 7)
