"""Work sign-in preserves identity and keeps credentials out of UI commands."""
import json
import subprocess
import unittest
from unittest import mock

from ai_router import key_dialog, key_prompt, provider_defs, work_account

KEY = 'sk-or-v1-' + 'synthetic-key-for-offline-testing-only'


def issued():
    return {'data': {'key': KEY, 'keyHash': 'synthetic-hash',
                    'companyId': 'example',
                    'workspaceId': '00000000-0000-0000-0000-000000000001',
                    'monthlyLimitUsd': 50, 'limitReset': 'monthly'}}


class ProvisionTests(unittest.TestCase):
    def test_signed_in_person_is_only_issuance_input(self):
        post = mock.Mock(return_value=issued())
        authorize = mock.Mock(return_value={'access_token': 'synthetic-access',
                                            'refresh_token': 'synthetic-refresh'})
        config = work_account.configuration()
        self.assertTrue(config['scope'].endswith('/Router.Provision'))
        self.assertEqual(work_account.provision(authorize=authorize, post=post), KEY)
        self.assertEqual(authorize.call_args.args[0],
                         {**config, 'scope': config['scope'] + ' openid profile'})
        self.assertEqual(config['tenant_id'], 'organizations')
        url, body, headers = post.call_args.args
        self.assertEqual(url, config['provision_url'])
        self.assertEqual(json.loads(body), {'confirm': True})
        self.assertEqual(headers['Authorization'], 'Bearer synthetic-access')
        self.assertNotIn('synthetic-refresh', str(post.call_args))

    def test_sign_in_rejects_personal_account_and_arbitrary_authorities(self):
        config = work_account.configuration()
        for authority in ('common', 'consumers', 'example.invalid/collect'):
            with self.subTest(authority), mock.patch('pathlib.Path.read_text',
                    return_value=json.dumps({**config, 'tenant_id': authority})):
                with self.assertRaises(work_account.SignInFailed):
                    work_account.configuration()

    def test_wrong_budget_and_invalid_credential_responses_are_refused(self):
        for field, value in (('monthlyLimitUsd', 100), ('limitReset', 'daily'),
                             ('workspaceId', 'wrong'), ('companyId', ''),
                             ('keyHash', ''), ('key', KEY + '\n')):
            with self.subTest(field):
                response = issued()
                response['data'][field] = value
                with self.assertRaises(work_account.SignInFailed) as raised:
                    work_account.provision(authorize=lambda _: {'access_token': 'synthetic'},
                                           post=lambda *_: response)
                self.assertNotIn(KEY, str(raised.exception))

    def test_redirects_cannot_relay_access_token_or_provider_key(self):
        oauth = work_account._load('download_oauth')
        request = mock.Mock()
        with self.assertRaises(oauth.SignInRequired):
            oauth._NoRedirects().redirect_request(request, None, 307, '', {},
                                                  'https://example.invalid/collect')

    def test_upstream_errors_do_not_reach_dialogs(self):
        with self.assertRaises(work_account.SignInFailed) as raised:
            work_account.provision(authorize=mock.Mock(side_effect=OSError(KEY)))
        self.assertNotIn(KEY, str(raised.exception))

    def test_provisioning_hold_and_outage_have_actionable_fixed_messages(self):
        oauth = work_account._load('download_oauth')
        for status, expected in ((409, 'IT check'), (429, 'busy'), (503, 'unavailable')):
            with self.subTest(status), mock.patch.object(work_account, '_load', return_value=oauth):
                post = mock.Mock(side_effect=oauth.SignInRequired('download_unavailable', status))
                with self.assertRaises(work_account.SignInFailed) as raised:
                    work_account.provision(authorize=lambda _: {'access_token': 'synthetic'}, post=post)
                self.assertIn(expected, str(raised.exception))


class SetupTests(unittest.TestCase):
    def collect(self, platform, responses, issue=None, clients='both'):
        calls = []
        def run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, responses.pop(0), '')
        fields = work_account.collect('/dialog', platform, clients, run,
                                       issue=issue or (lambda: KEY))
        return fields, calls

    def test_staff_flow_on_each_platform_uses_no_key_input_or_key_arguments(self):
        for platform in ('darwin', 'win32', 'linux'):
            with self.subTest(platform):
                fields, calls = self.collect(platform, ['Sign in with my work account',
                    'No subscription', 'I have one', 'Coding help'])
                self.assertEqual(fields, {'key': KEY, 'mode': 'none',
                                          'claude_mode': 'subscription', 'profile': 'dev'})
                commands = str(calls)
                self.assertNotIn(KEY, commands)
                self.assertNotIn('add-password', commands)
                self.assertNotIn('hidden answer', commands)
                self.assertIn('Cancel', commands)
                self.assertIn('router-icon.png', commands)

    def test_manual_choice_preserves_existing_key_setup(self):
        fields, _ = self.collect('darwin', ['Use my own key'])
        self.assertIs(fields, work_account.MANUAL)

    def test_cancel_does_not_issue_a_key(self):
        for platform, code in (('darwin', 0), ('win32', 2), ('linux', 1)):
            issue = mock.Mock()
            run = lambda *a, **k: subprocess.CompletedProcess([], code, '', '')
            self.assertIs(work_account.collect('/dialog', platform, 'codex', run, issue),
                          work_account.CANCELLED)
            issue.assert_not_called()

    def test_failed_dialog_does_not_issue_a_key(self):
        issue = mock.Mock()
        run = lambda *a, **k: subprocess.CompletedProcess([], 3, '', 'synthetic failure')
        with self.assertRaises(OSError):
            work_account.collect('/dialog', 'linux', 'codex', run, issue)
        issue.assert_not_called()

    def test_headless_linux_preserves_the_existing_browser_fallback(self):
        run = mock.Mock(return_value=subprocess.CompletedProcess([], 1, '',
            'Gtk-WARNING: cannot open display'))
        fallback = mock.Mock(return_value=True)
        with mock.patch.object(work_account, 'provision') as issue:
            result = key_prompt.run_window('http://127.0.0.1:1/t/setup/n',
                tool_path='/dialog', platform_name='linux', run=run,
                opener=fallback, work=True)
        self.assertEqual(result, 3)
        fallback.assert_called_once_with('http://127.0.0.1:1/t/setup/n')
        issue.assert_not_called()

    def test_denied_sign_in_does_not_ask_assistant_questions(self):
        run = mock.Mock(return_value=subprocess.CompletedProcess([], 0,
            'Sign in with my work account', ''))
        issue = mock.Mock(side_effect=work_account.SignInFailed('Contact IT.'))
        with self.assertRaises(work_account.SignInFailed):
            work_account.collect('/dialog', 'darwin', 'both', run, issue)
        self.assertEqual(run.call_count, 1)

    def test_managed_local_failure_does_not_repeat_browser_sign_in(self):
        with mock.patch.object(work_account, 'collect', return_value={'key': KEY}) as issue, \
             mock.patch.object(key_dialog, 'message') as message, \
             mock.patch.object(key_prompt, 'submit', return_value=(503, {'ok': False})):
            self.assertEqual(key_prompt.run_window('http://127.0.0.1:1/t/setup/n',
                tool_path='/dialog', platform_name='linux', work=True), 1)
        issue.assert_called_once()
        self.assertNotIn('Your work key is ready', message.call_args.args[1])

    def test_work_key_confirmation_follows_success_and_names_installed_clients(self):
        for clients, expected in (('codex', 'Restart Codex'),
                                  ('claude', 'Restart Claude Code'),
                                  ('both', 'Quit and reopen Codex, and restart Claude Code'),
                                  ('none', 'Continue installation')):
            with self.subTest(clients), \
                 mock.patch.object(work_account, 'collect', return_value={'key': KEY}), \
                 mock.patch.object(key_dialog, 'message') as message, \
                 mock.patch.object(key_prompt, 'submit', return_value=(200, {'ok': True})):
                self.assertEqual(key_prompt.run_window('http://127.0.0.1:1/t/setup/n',
                    tool_path='/dialog', platform_name='linux', work=True, clients=clients), 0)
            text = message.call_args.args[1]
            self.assertIn('Your work key is ready.', text)
            self.assertIn(expected, text)
            if clients == 'claude':
                self.assertNotIn('Codex', text)
            if clients == 'none':
                self.assertNotIn('Restart', text)
            self.assertNotIn('Credit left', text)

    def test_managed_key_uses_the_existing_setup_submission(self):
        fields = {'key': KEY, 'mode': 'none', 'profile': 'general'}
        with mock.patch.object(work_account, 'collect', return_value=fields), \
             mock.patch.object(key_dialog, 'message'), \
             mock.patch.object(key_dialog, 'collect') as manual, \
             mock.patch.object(key_prompt, 'submit', return_value=(200, {'ok': True})) as submit:
            result = key_prompt.run_window('http://127.0.0.1:1/t/setup/n',
                tool_path='/dialog', platform_name='linux', work=True)
        self.assertEqual(result, 0)
        submit.assert_called_once_with('http://127.0.0.1:1/t/setup/n', fields, opener=None)
        manual.assert_not_called()

    def test_other_providers_keep_their_existing_key_dialog(self):
        other = next(d.id for d in provider_defs.external_defs() if d.id != 'openrouter')
        with mock.patch.object(work_account, 'collect') as managed, \
             mock.patch.object(key_dialog, 'collect', return_value=None):
            self.assertEqual(key_prompt.run_window('http://127.0.0.1:1/t/setup/n',
                tool_path='/dialog', platform_name='linux', work=True, provider_id=other), 2)
        managed.assert_not_called()

    def test_work_key_never_goes_to_a_host_hidden_in_a_loopback_url(self):
        for url in ('http://127.0.0.1:80@example.invalid/t/setup/n',
                    'http://127.0.0.1:1/t/setup/n?redirect=elsewhere',
                    'https://example.invalid/t/setup/n',
                    'http://127.0.0.1:0/t/setup/n'):
            with self.subTest(url), mock.patch.object(work_account, 'collect') as issue:
                self.assertEqual(key_prompt.run_window(url, tool_path='/dialog', work=True), 1)
                issue.assert_not_called()


if __name__ == '__main__':
    unittest.main()
