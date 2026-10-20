"""Run the complete Claude profile transition on the native runner's filesystem."""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests import claude_profile_sync_fixtures as fixtures
from tests.test_native_setup import module


class DesktopProfileTransitionTests(fixtures.SyncFixture):
    def setUp(self):
        super().setUp()
        self.owner = module('claude_desktop_switch')
        self.owner._receipts._atomic_write = module('atomic_write')
        state = dict(port=1, token='synthetic', openai_models=[], claude_mode='subscription')
        (self.home / 'mixed-router-state.json').write_text(json.dumps(state))
        entry = self.owner._desktop.applied_entry_path(self.third)
        values = json.loads(entry.read_bytes())
        for key in self.owner._desktop.OWNED_KEYS:
            values.pop(key, None)
        entry.write_text(json.dumps(values))
        self.owner._desktop.attach(self.home, state, self.owner._receipts, data_dir_override=self.third)
        self.config = self.third / 'claude_desktop_config.json'
        self.config.write_text('{"deploymentMode":"3p","keep":"setting"}')
        self.platform = SimpleNamespace(confirm=mock.Mock(return_value=True),
            request_stop=mock.Mock(return_value=True), is_running=mock.Mock(return_value=False),
            open_app=mock.Mock(return_value=SimpleNamespace(returncode=0)), show_message=mock.Mock())
        self.enterContext(mock.patch.object(self.owner, '_sync_context',
            return_value=(fixtures.sync, self.env, (self.first, self.third))))

    def transition(self, target):
        return self.owner.switch(self.home, target=target, platform_ops=self.platform,
            policy_check=lambda: False, sync=lambda home, mode, third, env: self.sync(mode))

    def test_both_profile_directions_preserve_saved_tasks_and_account_binding(self):
        before_receipt = (self.home / 'activation.json').read_bytes()
        configs = {root: (root / 'config.json').read_bytes() for root in (self.first, self.third)}
        store = 'claude-code-sessions'
        for root, title in ((self.first, 'subscription task'), (self.third, 'gateway task')):
            doc = json.loads((root / 'config.json').read_bytes())
            fixtures.record(root, store, doc['lastKnownAccountUuid'], doc['lastKnownOrganizationUuid'],
                'saved-' + root.name, title=title, cli='session-' + root.name,
                bundle_files={'outputs/keep.txt': title}, transcript=title)
        for target in ('1p', '3p'):
            self.assertEqual(self.transition(target), target)
            self.assertEqual(json.loads(self.config.read_bytes()), {'deploymentMode': target, 'keep': 'setting'})
            for root in (self.first, self.third):
                records = fixtures.sync._records.group_records(root / store)
                self.assertEqual(set(records), {'saved-Claude', 'saved-Claude-3p'})
                for name, paths in records.items():
                    self.assertEqual((paths[0].with_suffix('') / 'outputs/keep.txt').read_text(),
                        'subscription task' if name == 'saved-Claude' else 'gateway task')
                self.assertEqual((root / 'config.json').read_bytes(), configs[root])
            self.assertEqual((self.home / 'activation.json').read_bytes(), before_receipt)
        self.assertTrue((self.home / '.claude-profile-control-accounts.json').is_file())
        self.assertEqual(self.platform.request_stop.call_count, 2)
        self.assertEqual(self.platform.open_app.call_count, 2)

    def test_first_attachment_keeps_subscription_until_openrouter_runs_the_switch(self):
        # Reproduced 20/10/2026: connecting Claude while it ran on the subscription
        # selected OpenRouter in its settings. The menu then ticked OpenRouter, and
        # choosing it skipped the restart and task sharing.
        state = json.loads((self.home / 'mixed-router-state.json').read_text())
        self.owner._desktop.detach(self.home, self.owner._receipts)
        self.config.write_text('{"keep":"setting"}')
        self.owner._desktop.attach(self.home, state, self.owner._receipts, data_dir_override=self.third)
        self.assertEqual(json.loads(self.config.read_bytes()), {'keep': 'setting'})
        control = module('desktop_control')
        installer = mock.Mock()
        installer._diag._status_document.return_value = dict(clients={'claude-desktop': {}})
        owners = dict(install=installer, claude_desktop_switch=self.owner, update_status=module('update_status'),
                      desktop_startup=SimpleNamespace(enabled=lambda home: False))
        with mock.patch.object(control, 'load', side_effect=owners.__getitem__):
            self.assertEqual(control.snapshot(self.home)['clients'][0]['selected'], 'subscription')
        doc = json.loads((self.first / 'config.json').read_bytes())
        fixtures.record(self.first, 'claude-code-sessions', doc['lastKnownAccountUuid'],
                        doc['lastKnownOrganizationUuid'], 'saved-first', title='subscription task',
                        cli='session-first', transcript='subscription task')
        self.assertEqual(self.transition('3p'), '3p')
        self.platform.confirm.assert_called_once()
        self.platform.open_app.assert_called_once()
        self.assertEqual(json.loads(self.config.read_bytes()), {'keep': 'setting', 'deploymentMode': '3p'})
        self.assertIn('saved-first', fixtures.sync._records.group_records(self.third / 'claude-code-sessions'))

    def test_cancel_and_failed_shutdown_leave_mode_and_saved_work_unchanged(self):
        before = fixtures.fingerprint(self.third)
        self.platform.confirm.return_value = False
        self.assertIsNone(self.transition('1p'))
        self.assertEqual(fixtures.fingerprint(self.third), before)
        self.platform.request_stop.assert_not_called()
        self.platform.confirm.return_value = True
        self.platform.request_stop.return_value = False
        with self.assertRaisesRegex(self.owner.SwitchError, 'did not close'):
            self.transition('1p')
        self.assertEqual(fixtures.fingerprint(self.third), before)

    def test_managed_connection_refuses_before_sharing_or_shutdown(self):
        before = fixtures.fingerprint(self.third)
        with self.assertRaisesRegex(self.owner.SwitchError, 'organization manages'):
            self.owner.switch(self.home, target='1p', platform_ops=self.platform, policy_check=lambda: True)
        self.platform.request_stop.assert_not_called()
        self.assertEqual(fixtures.fingerprint(self.third), before)

    def test_changed_signed_in_account_cannot_rebind_saved_tasks(self):
        self.assertEqual(self.sync()['pending'], 0)
        binding = self.home / '.claude-profile-control-accounts.json'
        before_binding = binding.read_bytes()
        first_config = json.loads((self.first / 'config.json').read_bytes())
        first_config['lastKnownAccountUuid'] = '11111111-2222-4333-8444-555555555555'
        (self.first / 'config.json').write_text(json.dumps(first_config))
        fixtures.namespace(self.first, 'claude-code-sessions', first_config['lastKnownAccountUuid'],
                           first_config['lastKnownOrganizationUuid'])
        before = fixtures.fingerprint(self.third)
        with self.assertRaisesRegex(self.owner.SwitchError, 'different account'):
            self.transition('1p')
        self.assertEqual(fixtures.fingerprint(self.third), before)
        self.assertEqual(binding.read_bytes(), before_binding)


class NativeProfileRecoveryTests(fixtures.PairFixture):
    def test_interrupted_bundle_publication_recovers_exact_saved_work(self):
        before = (self.record.read_bytes(), (self.bundle / 'outputs/old.txt').read_bytes())
        manifest = self.manifest()
        original = self.publish.update_pair_manifest
        def interrupted(path, phase):
            result = original(path, phase)
            if phase == 'bundle-published':
                raise SystemExit('simulated interrupted switch')
            return result
        with mock.patch.object(self.publish, 'update_pair_manifest', side_effect=interrupted):
            with self.assertRaises(SystemExit):
                self.transaction.publish_pair(manifest, self.text)
        self.assertEqual(self.transaction.recover_store(self.store), 1)
        self.assertEqual((self.record.read_bytes(), (self.bundle / 'outputs/old.txt').read_bytes()), before)
        self.assertFalse(manifest.exists())


class SetupHandOffTests(unittest.TestCase):
    def test_setup_reaches_openrouter_only_through_switch_claude(self):
        setup, refused = module('native_setup'), type('SwitchError', (Exception,), {})
        facts = dict(serving=True, update={}, onboarding=dict(ready=False, clients={'claude-desktop': dict(
            plugins_available=True, fresh_session_confirmed=False, reply_seen=False)}))
        for outcome, message in ((None, 'stays on your Claude subscription'),
                                 (refused('Open a Code task in Claude, then try again.'), 'Open a Code task'),
                                 ('3p', None)):
            with self.subTest(outcome=outcome):
                owner, dialog = mock.Mock(SwitchError=refused), mock.Mock()
                owner.switch.side_effect = [outcome]
                dialog.confirm.return_value = False
                with mock.patch.object(setup, 'status', return_value=facts), \
                        mock.patch.object(setup, '_missing_assistant', return_value=False), \
                        mock.patch.object(setup, 'load', return_value=owner):
                    setup._check(Path('/resources'), Path('/home'), dialog)
                owner.switch.assert_called_once_with(Path('/home'), target='3p')
                if message:
                    self.assertIn(message, dialog.message.call_args.args[0])
                    dialog.confirm.assert_not_called()
                else:
                    dialog.message.assert_not_called()
                    prompt = dialog.confirm.call_args.args[0]
                    self.assertIn('Choose Code and start a new task', prompt)
                    self.assertNotIn('Quit and reopen', prompt)
