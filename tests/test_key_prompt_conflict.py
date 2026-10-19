"""A stored-key conflict cannot be fixed by collecting the key repeatedly."""
import unittest
from unittest import mock

from ai_router import key_dialog, key_prompt


class KeyPromptConflictTests(unittest.TestCase):
    def test_windows_close_requires_explicit_save(self):
        script = key_dialog.argv('powershell', 'win32')[-1]
        self.assertLess(script.index("$f.Tag = 'cancel'"), script.index('$f.ShowDialog()'))
        self.assertIn("$b.Add_Click({ $f.Tag = 'save'; $f.Close() })", script)
        self.assertIn("$f.ShowDialog(); if ($f.Tag -ne 'save') { exit 2 }", script)
        with mock.patch.object(key_dialog, 'collect', return_value=None), \
                mock.patch.object(key_prompt, 'submit') as post:
            self.assertEqual(key_prompt.run_window('http://127.0.0.1:1/t/setup/n',
                                                   tool_path='powershell',
                                                   platform_name='win32'), 2)
        post.assert_not_called()

    def test_stored_key_conflict_stops_after_one_prompt(self):
        message = 'a key file already exists; delete it to rotate keys'
        with mock.patch.object(key_dialog, 'collect',
                               side_effect=[{'key': 'synthetic'},
                                            AssertionError('key requested again')]) as collect, \
                mock.patch.object(key_dialog, 'message') as show, \
                mock.patch.object(key_prompt, 'submit',
                                  return_value=(409, {'ok': False, 'error': message})) as post:
            result = key_prompt.run_window('http://127.0.0.1:1/t/setup/n',
                                            tool_path='powershell', platform_name='win32')
        self.assertEqual(result, 1)
        collect.assert_called_once()
        post.assert_called_once()
        self.assertIn('A key is already saved', show.call_args.args[1])
        self.assertIn('Check setup', show.call_args.args[1])
        self.assertNotIn('delete', show.call_args.args[1])
