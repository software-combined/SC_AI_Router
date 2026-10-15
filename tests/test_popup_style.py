"""One style for every dialog the router shows (AGENTS.md section 4a).

The update notice and the first-run key window are produced by different
modules on different Python versions, so this test is the single place that
pins their shared title, icon and vocabulary.
"""
import importlib.util
import unittest
from pathlib import Path

from ai_router import key_dialog

_ROOT = Path(__file__).resolve().parents[1]

# Internals a non-technical operator should never read in a dialog.
JARGON = ('nonce', 'loopback', 'catalogue', 'owner-only', '127.0.0.1',
          'token', 'endpoint', 'process', 'daemon')


def _notice():
    spec = importlib.util.spec_from_file_location(
        'router_notice', _ROOT / 'packaging' / 'notice.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dialog():
    """The client chooser, which is not importable as part of a package."""
    spec = importlib.util.spec_from_file_location(
        'router_client_dialog', _ROOT / 'packaging' / 'client_dialog.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _offer():
    """The Switch Codex offer, with its dialog tool found on every platform."""
    spec = importlib.util.spec_from_file_location(
        'router_codex_switch_offer', _ROOT / 'packaging' / 'codex_switch_offer.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.which = lambda _tool: '/usr/bin/osascript'
    return module


def _popup_text():
    """Every user-visible string the dialog producers can show."""
    notice = _notice()
    dialog = _dialog()
    offer = _offer()
    text = [notice._message('0.6.25'),
            notice._message('0.6.25', names=['Z.ai: GLM 5.3 Flash', '+2 more']),
            dialog.ASSISTANT_QUESTION, dialog.SURFACE_QUESTION,
            dialog.NO_TOOL_NOTE, dialog.NO_ANSWER_NOTE]
    text += list(dialog.CONFIRM.values())
    text += [' '.join(offer.command(kind, '/icon.png')) for kind in offer.MESSAGES]
    text += [label for _key, label in dialog.ASSISTANTS]
    text += [label for _key, label in dialog.SURFACES]
    for platform_name, tool_path in (('darwin', '/usr/bin/osascript'),
                                     ('linux', '/usr/bin/zenity'),
                                     ('win32', 'C:/powershell.exe')):
        text.append(' '.join(key_dialog.argv(tool_path, platform_name)))
        text.append(' '.join(key_dialog.message_argv(tool_path, 'message',
                                                     platform_name)))
        text.append(' '.join(dialog.argv(tool_path, platform_name,
                                         dialog.ASSISTANT_QUESTION,
                                         dialog.ASSISTANTS)))
        text.append(' '.join(dialog.argv(tool_path, platform_name,
                                         dialog.SURFACE_QUESTION, dialog.SURFACES)))
    return ' '.join(text).lower()


class PopupStyleTests(unittest.TestCase):
    def test_shared_title(self):
        self.assertEqual(key_dialog.TITLE, _notice().TITLE, 'SCG Router')

    def test_shared_icon_asset(self):
        self.assertEqual(key_dialog.ICON, _notice().ICON)
        self.assertEqual(key_dialog.ICON,
                         _ROOT / 'packaging' / 'assets' / 'router-icon.png')
        self.assertTrue(key_dialog.ICON.is_file())

    def test_every_platform_carries_the_icon(self):
        for platform_name, tool_path in (('darwin', '/usr/bin/osascript'),
                                         ('linux', '/usr/bin/zenity'),
                                         ('win32', 'C:/powershell.exe')):
            with self.subTest(platform_name):
                blob = ' '.join(key_dialog.argv(tool_path, platform_name))
                self.assertIn(key_dialog.ICON.name, blob)
        self.assertIn('POSIX file', _notice()._darwin_script('0.6.25', '/icon.png'))

    def test_no_jargon_in_user_visible_text(self):
        text = _popup_text()
        for word in JARGON:
            with self.subTest(word):
                self.assertNotIn(word, text)

    def test_bedrock_dialog_names_its_own_key(self):
        for platform_name, tool_path in (('darwin', '/usr/bin/osascript'),
                                         ('linux', '/usr/bin/zenity'),
                                         ('win32', 'C:/powershell.exe')):
            with self.subTest(platform_name):
                blob = ' '.join(key_dialog.argv(
                    tool_path, platform_name, provider_id='bedrock'))
                self.assertIn('aws bedrock key', blob.lower())
                self.assertIn(key_dialog.TITLE, blob)
                self.assertIn('saved as you paste it', blob.lower())

    def test_plain_language_prompts(self):
        text = _popup_text()
        self.assertIn('openrouter key', text)
        self.assertIn('chatgpt subscription', text)
        self.assertIn('codex', text)
        self.assertTrue('reopen codex' in text or 'restart codex' in text,
                        'the dialog tells the operator what to do next')

    def test_the_safe_action_is_always_offered(self):
        macos = key_dialog.argv('/usr/bin/osascript', 'darwin')[-1]
        self.assertIn('"Cancel"', macos)
        self.assertIn("'Cancel'", key_dialog.argv('C:/powershell.exe', 'win32')[-1])

    def test_windows_dialog_lays_every_control_out(self):
        # WinForms gives a control added straight to a form the Location
        # (0, 0), so with no layout container every control stacks in the
        # corner: the key box and both buttons are covered and unusable.
        # Found live on Windows, 2026-09-16.
        script = key_dialog.argv('C:/powershell.exe', 'win32')[-1]
        self.assertEqual(script.count('$f.Controls.Add('), 1,
                         'only the layout panel belongs to the form itself')
        for control in ('$p.Controls.Add($pic)', '$p.Controls.Add($t)',
                        '$p.Controls.Add($k)', '$p.Controls.Add($r)',
                        '$r.Controls.Add($b)', '$r.Controls.Add($c)'):
            with self.subTest(control):
                self.assertIn(control, script)

    def test_windows_combo_uses_the_enum_name(self):
        # DropDownStyle = 3 is not a member of ComboBoxStyle: PowerShell
        # throws a non-terminating error and leaves an editable combo, whose
        # free text collect() then refuses.
        script = key_dialog.argv('C:/powershell.exe', 'win32')[-1]
        self.assertIn("DropDownStyle = 'DropDownList'", script)
        self.assertNotIn('DropDownStyle = 3', script)

    def test_the_chooser_shares_the_title_and_icon(self):
        dialog = _dialog()
        self.assertEqual(dialog.TITLE, key_dialog.TITLE, 'SCG Router')
        self.assertEqual(dialog.ICON, key_dialog.ICON)
        self.assertTrue(dialog.ICON.is_file())

    def test_every_platform_chooser_question_carries_the_icon(self):
        dialog = _dialog()
        for platform_name, tool_path in (('darwin', '/usr/bin/osascript'),
                                         ('linux', '/usr/bin/zenity'),
                                         ('win32', 'C:/powershell.exe')):
            for question, items in ((dialog.ASSISTANT_QUESTION, dialog.ASSISTANTS),
                                    (dialog.SURFACE_QUESTION, dialog.SURFACES)):
                with self.subTest(platform=platform_name, question=question):
                    blob = ' '.join(dialog.argv(tool_path, platform_name,
                                                question, items))
                    self.assertIn(dialog.ICON.name, blob)
                    self.assertIn(dialog.TITLE, blob)

    def test_the_chooser_uses_selection_controls_and_two_actions(self):
        dialog = _dialog()
        for question, items in ((dialog.ASSISTANT_QUESTION, dialog.ASSISTANTS),
                                (dialog.SURFACE_QUESTION, dialog.SURFACES)):
            with self.subTest(question=question):
                macos = dialog.argv('/usr/bin/osascript', 'darwin',
                                    question, items)[-1]
                self.assertIn('NSPopUpButton', macos)
                self.assertEqual(macos.count('addButtonWithTitle('), 2)
                self.assertIn('addButtonWithTitle("Continue")', macos)
                self.assertIn('addButtonWithTitle("Cancel")', macos)
                windows = dialog.argv('C:/powershell.exe', 'win32',
                                      question, items)[-1]
                self.assertIn('System.Windows.Forms.ListBox', windows)
                self.assertEqual(windows.count('System.Windows.Forms.Button'), 2)
                self.assertIn("'Continue'", windows)
                self.assertIn("'Cancel'", windows)
                self.assertIn('$f.CancelButton = $c', windows)
                linux = dialog.argv('/usr/bin/zenity', 'linux', question, items)
                self.assertIn('--radiolist', linux)
                self.assertIn('--ok-label=Continue', linux)
                self.assertIn('--cancel-label=Cancel', linux)

    def test_the_codex_offer_shares_the_style(self):
        offer = _offer()
        for kind in offer.MESSAGES:
            with self.subTest(kind=kind):
                script = offer.command(kind, '/home/router-icon.png')[-1]
                self.assertIn('with title "SCG Router"', script)
                self.assertIn('with icon (POSIX file "/home/router-icon.png")', script)
                self.assertIn('buttons {"Later", "Open Switch Codex"}', script)
                self.assertIn('cancel button "Later"', script)
                message = offer.MESSAGES[kind].lower()
                for words in ('the chatgpt app (codex)', 'chatgpt subscription',
                              'openrouter models'):
                    self.assertIn(words, message)

    def test_windows_chooser_lays_every_control_out(self):
        dialog = _dialog()
        script = dialog.argv('C:/powershell.exe', 'win32', dialog.SURFACE_QUESTION,
                             dialog.SURFACES)[-1]
        self.assertEqual(script.count('$f.Controls.Add('), 1,
                         'only the layout panel belongs to the form itself')
        for control in ('$p.Controls.Add($l)', '$p.Controls.Add($b)',
                        '$p.Controls.Add($r)', '$r.Controls.Add($ok)',
                        '$r.Controls.Add($c)'):
            with self.subTest(control):
                self.assertIn(control, script)


if __name__ == '__main__':
    unittest.main()
