"""Offline chooser regressions: selections reach the intended attachments."""
import importlib.util
import io
import subprocess
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    'router_client_dialog', _ROOT / 'packaging' / 'client_dialog.py')
dialog = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dialog)


def _args():
    return SimpleNamespace(dry_run=False, clients=None, client=None,
                           desktop=False, choose_clients=True)


def _result(stdout='', returncode=0):
    return SimpleNamespace(stdout=stdout, returncode=returncode)


class ClientDialogTests(unittest.TestCase):
    def test_nine_choices_set_the_actual_attachment_flags(self):
        expected = {
            ('ChatGPT', 'Desktop app'): ('codex', False),
            ('ChatGPT', 'Terminal'): ('codex', False),
            ('ChatGPT', 'Both'): ('codex', False),
            ('Claude', 'Desktop app'): ('none', True),
            ('Claude', 'Terminal'): ('claude', False),
            ('Claude', 'Both'): ('claude', True),
            ('Both', 'Desktop app'): ('codex', True),
            ('Both', 'Terminal'): ('both', False),
            ('Both', 'Both'): ('both', True),
        }
        self.assertEqual(dialog.ASSISTANTS, (('chatgpt', 'ChatGPT'),
                                            ('claude', 'Claude'), ('both', 'Both')))
        with patch.dict(dialog.os.environ, {}, clear=True):
            for platform in ('darwin', 'win32', 'linux'):
                for labels, flags in expected.items():
                    with self.subTest(platform=platform, labels=labels):
                        args = _args()
                        run = Mock(side_effect=[_result(label + '\n') for label in labels])
                        with redirect_stdout(io.StringIO()) as output:
                            chosen = dialog.maybe_ask(args, _ROOT, platform,
                                                      '/dialog', run)
                        self.assertTrue(chosen)
                        self.assertEqual((args.clients, args.desktop), flags)
                        self.assertEqual(run.call_count, 2)
                        self.assertTrue(output.getvalue().strip())

    def test_cancel_at_either_question_marks_no_new_attachment(self):
        for platform, cancel_code in (('darwin', 0), ('win32', 2), ('linux', 1)):
            for stage in (0, 1):
                with self.subTest(platform=platform, stage=stage):
                    args = _args()
                    run = Mock(side_effect=[_result('Both')] * stage +
                               [_result(returncode=cancel_code)])
                    with patch.dict(dialog.os.environ, {}, clear=True):
                        with redirect_stdout(io.StringIO()):
                            self.assertFalse(dialog.maybe_ask(
                                args, _ROOT, platform, '/dialog', run))
                    self.assertEqual((args.clients, args.desktop), ('none', False))
                    self.assertTrue(args.client_choice_cancelled)
                    self.assertEqual(run.call_count, stage + 1)

    def test_unusable_answer_or_failure_leaves_flags_unchanged(self):
        # A failed command must never accept even a valid-looking answer.
        for platform in ('darwin', 'win32', 'linux'):
            for stage in (0, 1):
                for result in (_result(returncode=3), _result('Cancel'),
                               _result('ChatGPT\nClaude'), _result('Both', 1),
                               OSError('unavailable'),
                               subprocess.TimeoutExpired('/dialog', 300)):
                    with self.subTest(platform=platform, stage=stage, result=result):
                        args = _args()
                        run = Mock(side_effect=[_result('Both')] * stage + [result])
                        with patch.dict(dialog.os.environ, {}, clear=True):
                            with redirect_stdout(io.StringIO()):
                                self.assertFalse(dialog.maybe_ask(
                                    args, _ROOT, platform, '/dialog', run))
                        self.assertEqual((args.clients, args.desktop), (None, False))
                        self.assertFalse(getattr(args, 'client_choice_cancelled', False))
                        self.assertEqual(run.call_count, stage + 1)
                        self.assertEqual(run.call_args.kwargs['timeout'], dialog.TIMEOUT_S)

    def test_macos_accepts_only_continue(self):
        command = dialog.argv('/usr/bin/osascript', 'darwin',
                              dialog.ASSISTANT_QUESTION, dialog.ASSISTANTS)
        self.assertEqual(command[:4], ['/usr/bin/osascript', '-l', 'JavaScript', '-e'])
        self.assertIn('alert.runModal !== $.NSAlertFirstButtonReturn', command[-1])
        self.assertIn('return ""', command[-1])
        self.assertIn('ObjC.unwrap(picker.titleOfSelectedItem)', command[-1])

    def test_windows_close_and_escape_require_explicit_continue(self):
        script = dialog.argv('powershell', 'win32', dialog.ASSISTANT_QUESTION,
                             dialog.ASSISTANTS)[-1]
        self.assertIn("$ok.DialogResult = 'OK'", script)
        self.assertIn("$c.DialogResult = 'Cancel'", script)
        self.assertIn('$f.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK', script)

    def test_linux_offers_both_with_a_single_default(self):
        command = dialog.argv('zenity', 'linux', dialog.ASSISTANT_QUESTION,
                              dialog.ASSISTANTS)
        self.assertEqual(command[-6:], ['TRUE', 'ChatGPT', 'FALSE', 'Claude',
                                        'FALSE', 'Both'])


if __name__ == '__main__':
    unittest.main()
