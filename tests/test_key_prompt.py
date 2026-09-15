"""Native key window: platform dialogs, the submit flow and its fallbacks."""
import io
import json
import subprocess
import sys
import threading
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from ai_router import key_dialog, key_prompt

KEY = 'sk-or-v1-secret'


def kd_joined(argv):
    return ' '.join(argv)


def _ok(stdout):
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr='')


class ToolTests(unittest.TestCase):
    def test_tool_per_platform(self):
        which = lambda name: '/usr/bin/' + name  # noqa: E731
        self.assertTrue(key_dialog.tool('darwin', which).endswith('osascript'))
        self.assertTrue(key_dialog.tool('linux', which).endswith('zenity'))
        self.assertTrue(key_dialog.tool('win32', which).endswith('powershell'))
        self.assertIsNone(key_dialog.tool('plan9', which))

    def test_linux_needs_zenity(self):
        self.assertIsNone(key_dialog.tool('linux', lambda name: None))


class DialogArgvTests(unittest.TestCase):
    def test_macos_asks_for_key_then_choices(self):
        argv = key_dialog.argv('/usr/bin/osascript', 'darwin')
        script = argv[argv.index('-e') + 1]
        self.assertIn('with hidden answer', script)
        self.assertIn('buttons {"Cancel", "Continue"}', script)
        self.assertIn('buttons {"No subscription", "I have one"}', script)
        self.assertIn('buttons {"Coding help", "Everyday help"}', script)
        self.assertIn('return k & line_break & a0 & line_break & a1', script)
        self.assertIn(key_dialog.ICON.name, script)

    def test_windows_form_masks_the_key(self):
        argv = key_dialog.argv(r'C:\powershell.exe', 'win32')
        script = argv[argv.index('-Command') + 1]
        self.assertIn('UseSystemPasswordChar = $true', script)
        self.assertIn("'I have one', 'No subscription'", script)
        self.assertIn("'Everyday help', 'Coding help'", script)
        self.assertIn(key_dialog.ICON.name, script)
        # Each answer the form writes must be a combo it actually declared.
        for index in range(len(key_dialog.questions('codex'))):
            name = key_dialog.combo_name(index)
            self.assertIn(name + ' = New-Object System.Windows.Forms.ComboBox', script)
            self.assertIn(name + '.SelectedItem', script)

    def test_linux_zenity_form_fields(self):
        argv = key_dialog.argv('/usr/bin/zenity', 'linux')
        self.assertIn('--forms', argv)
        self.assertIn('--add-password=OpenRouter key', argv)
        self.assertIn('--add-combo=' + key_dialog.CODEX_QUESTION, argv)
        self.assertIn('--combo-values=I have one|No subscription', argv)
        self.assertIn('--combo-values=Everyday help|Coding help', argv)
        self.assertIn('--window-icon=' + str(key_dialog.ICON), argv)

    def test_the_key_never_reaches_argv(self):
        for platform_name, tool_path in (('darwin', '/usr/bin/osascript'),
                                         ('linux', '/usr/bin/zenity'),
                                         ('win32', 'C:/powershell.exe')):
            with self.subTest(platform_name):
                self.assertNotIn(KEY, ' '.join(key_dialog.argv(tool_path, platform_name)))


class CollectTests(unittest.TestCase):
    def test_darwin_choices(self):
        run = lambda argv, **kw: _ok(KEY + '\nI have one\nCoding help')  # noqa: E731
        fields = key_dialog.collect('/usr/bin/osascript', 'darwin', run)
        self.assertEqual(fields, {'key': KEY, 'mode': 'subscription',
                                  'profile': 'dev'})

    def test_darwin_blank_key_is_reprompted_not_misparsed(self):
        run = lambda argv, **kw: _ok('')  # noqa: E731
        with self.assertRaises(OSError):
            key_dialog.collect('/usr/bin/osascript', 'darwin', run)

    def test_linux_choices(self):
        run = lambda argv, **kw: _ok(KEY + '\tNo subscription\tEveryday help')  # noqa: E731
        self.assertEqual(key_dialog.collect('/usr/bin/zenity', 'linux', run),
                         {'key': KEY, 'mode': 'none', 'profile': 'general'})

    def test_win32_choices(self):
        run = lambda argv, **kw: _ok(KEY + '\r\nI have one\r\nEveryday help')  # noqa: E731
        self.assertEqual(key_dialog.collect('C:/powershell.exe', 'win32', run),
                         {'key': KEY, 'mode': 'subscription',
                          'profile': 'general'})

    def test_cancelling_each_platform(self):
        darwin = lambda argv, **kw: subprocess.CompletedProcess(  # noqa: E731
            [], 1, stdout='', stderr='execution error: User canceled. (-128)')
        darwin_british = lambda argv, **kw: subprocess.CompletedProcess(  # noqa: E731
            [], 1, stdout='', stderr='execution error: User cancelled. (-128)')
        linux = lambda argv, **kw: subprocess.CompletedProcess(  # noqa: E731
            [], 1, stdout='', stderr='')
        win32 = lambda argv, **kw: subprocess.CompletedProcess(  # noqa: E731
            [], 2, stdout='', stderr='')
        self.assertIsNone(key_dialog.collect('/a', 'darwin', darwin))
        self.assertIsNone(key_dialog.collect('/a', 'darwin', darwin_british))
        self.assertIsNone(key_dialog.collect('/a', 'linux', linux))
        self.assertIsNone(key_dialog.collect('/a', 'win32', win32))

    def test_headless_zenity_is_not_a_cancel(self):
        headless = lambda argv, **kw: subprocess.CompletedProcess(  # noqa: E731
            [], 1, stdout='', stderr='Gtk-WARNING: cannot open display:')
        with self.assertRaises(OSError):
            key_dialog.collect('/usr/bin/zenity', 'linux', headless)

    def test_malformed_output_is_an_error(self):
        run = lambda argv, **kw: _ok('only-one-field')  # noqa: E731
        with self.assertRaises(OSError):
            key_dialog.collect('/usr/bin/osascript', 'darwin', run)

    def test_unknown_choice_is_an_error(self):
        run = lambda argv, **kw: _ok(KEY + '\nMaybe\nEveryday help')  # noqa: E731
        with self.assertRaises(OSError):
            key_dialog.collect('/usr/bin/osascript', 'darwin', run)

    def test_claude_only_asks_about_claude(self):
        asked = key_dialog.questions('claude')
        self.assertEqual([field for field, _q, _a in asked], ['claude_mode'])
        self.assertEqual(asked[0][1], key_dialog.CLAUDE_QUESTION)
        run = lambda argv, **kw: _ok(KEY + '\nNo subscription')  # noqa: E731
        fields = key_dialog.collect('/usr/bin/osascript', 'darwin', run,
                                    which='claude')
        self.assertEqual(fields, {'key': KEY, 'claude_mode': 'none'})

    def test_both_clients_ask_both_subscriptions(self):
        asked = key_dialog.questions('both')
        self.assertEqual([field for field, _q, _a in asked],
                         ['mode', 'claude_mode', 'profile'])
        run = lambda argv, **kw: _ok(KEY + '\tI have one\tNo subscription\tEveryday help')  # noqa: E731
        fields = key_dialog.collect('/usr/bin/zenity', 'linux', run, which='both')
        self.assertEqual(fields, {'key': KEY, 'mode': 'subscription',
                                  'claude_mode': 'none', 'profile': 'general'})

    def test_service_only_asks_for_the_key_alone(self):
        self.assertEqual(key_dialog.questions('none'), [])
        run = lambda argv, **kw: _ok(KEY)  # noqa: E731
        self.assertEqual(key_dialog.collect('/usr/bin/zenity', 'linux', run,
                                            which='none'), {'key': KEY})

    def test_the_client_sets_the_question_text(self):
        self.assertIn('ChatGPT subscription',
                      kd_joined(key_dialog.argv('/usr/bin/zenity', 'linux', 'codex')))
        self.assertNotIn('ChatGPT subscription',
                         kd_joined(key_dialog.argv('/usr/bin/zenity', 'linux', 'claude')))
        self.assertIn('Claude subscription',
                      kd_joined(key_dialog.argv('/usr/bin/zenity', 'linux', 'both')))


class SubmitTests(unittest.TestCase):
    def _response(self, payload, status=200):
        class Resp:
            def __init__(self):
                self.status = status
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False
            def read(self):
                return json.dumps(payload).encode()
        return Resp()

    def test_posts_form_encoded_with_json_accept(self):
        seen = {}

        def opener(request, timeout=None):
            seen['url'] = request.full_url
            seen['body'] = request.data.decode()
            seen['accept'] = request.get_header('Accept')
            return self._response({'ok': True, 'label': 'probe'})

        status, payload = key_prompt.submit(
            'http://127.0.0.1:1/t/setup/n',
            {'key': KEY, 'mode': 'subscription', 'profile': 'general'}, opener)
        self.assertEqual((status, payload['label']), (200, 'probe'))
        self.assertIn('key=sk-or-v1-secret', seen['body'])
        self.assertEqual(seen['accept'], 'application/json')

    def test_http_error_carries_the_json_reason(self):
        def opener(request, timeout=None):
            raise urllib.error.HTTPError(
                request.full_url, 422, 'no', {}, None)

        status, payload = key_prompt.submit('http://127.0.0.1:1/x', {}, opener)
        self.assertEqual(status, 422)
        self.assertIn('setup failed', payload['error'])


class RunWindowTests(unittest.TestCase):
    def test_the_browser_opener_is_never_used_for_the_post(self):
        # The router path passes the browser fallback opener; it must not
        # reach submit(), whose opener is a urllib-style POST seam.
        def browser_only(url, new=0, autoraise=True):
            raise AssertionError('the key POST must not use the browser opener')
        with mock.patch.object(key_dialog, 'collect',
                               return_value={'key': KEY, 'mode': 'none',
                                             'profile': 'general'}), \
                mock.patch.object(key_dialog, 'message'), \
                mock.patch.object(key_prompt, 'submit',
                                  return_value=(200, {'ok': True})) as posted:
            rc = key_prompt.run_window('http://127.0.0.1:1/t/setup/n',
                                       tool_path='/usr/bin/osascript',
                                       platform_name='darwin', opener=browser_only)
        self.assertEqual(rc, 0)
        self.assertIsNone(posted.call_args.kwargs['opener'],
                          'browser opener leaked into the POST')

    def test_no_dialog_tool_falls_back_to_the_page(self):
        opened = []
        rc = key_prompt.run_window('http://127.0.0.1:1/t/setup/n',
                                   platform_name='plan9',
                                   opener=opened.append)
        self.assertEqual(rc, 3)
        self.assertEqual(opened, ['http://127.0.0.1:1/t/setup/n'])

    def test_cancel_changes_nothing(self):
        with mock.patch.object(key_dialog, 'collect', return_value=None):
            rc = key_prompt.run_window('http://127.0.0.1:1/t/setup/n',
                                       tool_path='/usr/bin/osascript',
                                       platform_name='darwin')
        self.assertEqual(rc, 2)

    def test_empty_key_reprompts_then_stores(self):
        replies = [{'key': '', 'mode': 'none', 'profile': 'general'},
                   {'key': KEY, 'mode': 'none', 'profile': 'general'}]
        messages = []
        with mock.patch.object(key_dialog, 'collect', side_effect=replies), \
                mock.patch.object(key_dialog, 'message',
                                  side_effect=lambda *a, **k: messages.append(a[1])), \
                mock.patch.object(key_prompt, 'submit',
                                  return_value=(200, {'ok': True, 'label': 'probe'})):
            rc = key_prompt.run_window('http://127.0.0.1:1/t/setup/n',
                                       tool_path='/usr/bin/osascript',
                                       platform_name='darwin')
        self.assertEqual(rc, 0)
        self.assertIn('Paste an OpenRouter key before saving.', messages)
        self.assertTrue(any('You are connected.' in m for m in messages))

    def test_refused_key_reprompts_and_expired_link_stops(self):
        with mock.patch.object(key_dialog, 'collect',
                               return_value={'key': KEY, 'mode': 'none',
                                             'profile': 'general'}), \
                mock.patch.object(key_dialog, 'message'), \
                mock.patch.object(key_prompt, 'submit',
                                  side_effect=[(422, {'ok': False, 'error': 'bad'}),
                                               (404, {'ok': False, 'error': 'gone'})]):
            rc = key_prompt.run_window('http://127.0.0.1:1/t/setup/n',
                                       tool_path='/usr/bin/osascript',
                                       platform_name='darwin')
        self.assertEqual(rc, 1)

    def test_unreachable_router_is_an_error_not_a_loop(self):
        with mock.patch.object(key_dialog, 'collect',
                               return_value={'key': KEY, 'mode': 'none',
                                             'profile': 'general'}), \
                mock.patch.object(key_dialog, 'message'), \
                mock.patch.object(key_prompt, 'submit', side_effect=OSError('down')):
            rc = key_prompt.run_window('http://127.0.0.1:1/t/setup/n',
                                       tool_path='/usr/bin/osascript',
                                       platform_name='darwin')
        self.assertEqual(rc, 1)

    def test_claude_install_posts_claude_mode_and_says_so(self):
        collected = {'key': KEY, 'claude_mode': 'none'}
        messages, posted = [], {}

        def submit(url, fields, opener=None):
            posted.update(fields)
            return 200, {'ok': True, 'label': 'probe', 'claude_mode': 'none',
                         'starter': 'Starter not installed (setup continued)'}

        with mock.patch.object(key_dialog, 'collect', return_value=collected), \
                mock.patch.object(key_dialog, 'message',
                                  side_effect=lambda *a, **k: messages.append(a[1])), \
                mock.patch.object(key_prompt, 'submit', side_effect=submit):
            rc = key_prompt.run_window('http://127.0.0.1:1/t/setup/n',
                                       tool_path='/usr/bin/osascript',
                                       platform_name='darwin', clients='claude')
        self.assertEqual(rc, 0)
        self.assertEqual(posted, {'key': KEY, 'claude_mode': 'none'})
        self.assertIn('Claude Code: OpenRouter models only', messages[-1])
        self.assertIn('restart claude code', messages[-1].lower())

    def test_cli_parses_the_client_set(self):
        self.assertEqual(key_prompt._parse(['http://127.0.0.1:1/x']),
                         ('http://127.0.0.1:1/x', 'codex'))
        self.assertEqual(
            key_prompt._parse(['http://127.0.0.1:1/x', '--clients', 'both']),
            ('http://127.0.0.1:1/x', 'both'))
        self.assertEqual(key_prompt._parse(['https://example.com/x']),
                         (None, None))

    def test_cli_reads_the_url_from_stdin(self):
        with mock.patch.object(key_prompt.sys, 'stdin',
                               io.StringIO('http://127.0.0.1:1/t/setup/n\n')):
            self.assertEqual(key_prompt._parse(['--stdin', '--clients', 'both']),
                             ('http://127.0.0.1:1/t/setup/n', 'both'))
        with mock.patch.object(key_prompt.sys, 'stdin', io.StringIO('https://example.com/x\n')):
            self.assertEqual(key_prompt._parse(['--stdin']), (None, None))


class OpenWindowTests(unittest.TestCase):
    def test_router_path_starts_a_thread_and_returns(self):
        started = []
        with mock.patch.object(key_prompt, 'run_window',
                               side_effect=lambda *a, **k: started.append(a) or 0):
            self.assertTrue(key_prompt.open_window(
                'http://127.0.0.1:1/t/setup/n', thread=True,
                platform_name='darwin', which=lambda name: '/usr/bin/' + name))
        for thread in threading.enumerate():
            if thread.name == 'Thread':
                thread.join(timeout=5)
        self.assertEqual(len(started), 1)

    def test_installer_path_runs_inline(self):
        with mock.patch.object(key_prompt, 'run_window', return_value=0) as ran:
            self.assertTrue(key_prompt.open_window(
                'http://127.0.0.1:1/t/setup/n', platform_name='darwin',
                which=lambda name: '/usr/bin/' + name))
        ran.assert_called_once()

    def test_no_tool_opens_the_page(self):
        opened = []
        self.assertTrue(key_prompt.open_window(
            'http://127.0.0.1:1/t/setup/n', thread=True, platform_name='plan9',
            opener=opened.append))
        self.assertEqual(opened, ['http://127.0.0.1:1/t/setup/n'])


class CliTests(unittest.TestCase):
    def test_rejects_anything_but_a_loopback_url(self):
        self.assertEqual(key_prompt.main([]), 1)
        self.assertEqual(key_prompt.main(['https://example.com/setup']), 1)

    @unittest.skipUnless(sys.platform == 'darwin', 'compiles AppleScript')
    def test_macos_script_compiles(self):
        argv = key_dialog.argv('/usr/bin/osascript', 'darwin')
        with tempfile.TemporaryDirectory() as tmp:
            out = subprocess.run(
                ['osacompile', '-e', argv[argv.index('-e') + 1],
                 '-o', str(Path(tmp) / 'key.scpt')],
                capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)

    @unittest.skipUnless(sys.platform == 'darwin', 'runs osascript')
    def test_real_osascript_output_parses(self):
        # The real tool ends its return value with a newline; the parser must
        # accept that shape, not just the fakes the other tests feed it.
        script = ('set line_break to ASCII character 10\n'
                  'return "sk-or-v1-live" & line_break & "I have one" & '
                  'line_break & "Everyday help"')
        result = subprocess.run(['osascript', '-e', script],
                                capture_output=True, text=True)
        fields = key_dialog.collect('/usr/bin/osascript', 'darwin',
                                    lambda *a, **k: result)
        self.assertEqual(fields, {'key': 'sk-or-v1-live', 'mode': 'subscription',
                                  'profile': 'general'})

    @unittest.skipUnless(sys.platform == 'darwin', 'runs osascript')
    def test_real_osascript_blank_key_keeps_the_leading_field(self):
        script = ('set line_break to ASCII character 10\n'
                  'return "" & line_break & "No subscription" & '
                  'line_break & "Coding help"')
        result = subprocess.run(['osascript', '-e', script],
                                capture_output=True, text=True)
        fields = key_dialog.collect('/usr/bin/osascript', 'darwin',
                                    lambda *a, **k: result)
        self.assertEqual(fields['key'], '')


if __name__ == '__main__':
    unittest.main()
