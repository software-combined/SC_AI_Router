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


def _popup_text():
    """Every user-visible string both dialog producers can show."""
    notice = _notice()
    text = [notice._message('0.6.25')]
    for platform_name, tool_path in (('darwin', '/usr/bin/osascript'),
                                     ('linux', '/usr/bin/zenity'),
                                     ('win32', 'C:/powershell.exe')):
        text.append(' '.join(key_dialog.argv(tool_path, platform_name)))
        text.append(' '.join(key_dialog.message_argv(tool_path, 'message',
                                                     platform_name)))
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


if __name__ == '__main__':
    unittest.main()
