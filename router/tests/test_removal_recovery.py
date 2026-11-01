"""Disposable mixed-client removal proves all-preflight and retry after failures."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from tests._platform import unix_only
from tests.install_fixtures import install_mod_factory
from tests.test_native_setup import module


class RemovalRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.install = install_mod_factory()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home = self.root / 'router'
        self.home.mkdir()
        (self.home / 'releases/1.2.6.174/packaging').mkdir(parents=True)
        (self.home / 'releases/1.2.6.174/packaging/VERSION').write_text('1.2.6.174')
        (self.home / 'current').write_text('1.2.6.174')
        self.config, self.settings = self.root / 'config.toml', self.root / 'settings.json'
        self.owner = self.install._codex_config
        self.state = {'port': 1234, 'token': 'synthetic-test', 'claude_mode': 'subscription'}
        (self.home / 'mixed-router-state.json').write_text(json.dumps(self.state))
        self.config.write_text('person_setting = true\n' + self.owner.build_block(self.home, self.state, 'subscription'))
        self.owner.write_client_receipt(self.home, 'codex', dict(config_path=str(self.config),
            inserted_block=self.owner.build_block(self.home, self.state, 'subscription')))
        self.settings.write_text('{ "tools" : {"disabled":true}, "env": {} }\n')
        self.install._claude_config.attach(self.home, self.state, self.owner,
                                          settings_path_override=self.settings)
        self.backend = mock.Mock()
        self.args = self.install.build_parser().parse_args(['--home', str(self.home), '--python', sys.executable])
        for patcher in (mock.patch.object(self.install, 'platform_backend', return_value=self.backend),
                mock.patch.object(self.install, 'find_python', return_value=sys.executable),
                mock.patch.dict(os.environ, HOME=str(self.root / 'user'))):
            patcher.start()
            self.addCleanup(patcher.stop)
        load = self.install._delivery._load
        patcher = mock.patch.object(self.install._delivery, '_load', side_effect=lambda name:
            mock.Mock() if name in ('native_shortcuts', 'claude_profile_hook') else load(name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def remove(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.install.do_uninstall(self.args)

    def test_later_connection_conflict_prevents_every_detach(self):
        doc = self.owner.read_receipt(self.home)
        doc['clients'] = {name: doc['clients'][name] for name in ('claude', 'codex')}
        (self.home / 'activation.json').write_text(json.dumps(doc))
        self.config.write_text(self.config.read_text().replace('openai_base_url', 'changed_base_url'))
        before = self.settings.read_bytes()
        with self.assertRaisesRegex(SystemExit, 'No assistants were detached'):
            self.remove()
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertEqual(set(self.owner.read_receipt(self.home)['clients']), {'codex', 'claude'})
        self.backend.uninstall.assert_not_called()

    def test_switched_codex_refuses_before_detaching_an_earlier_claude(self):
        module('codex_switch_config').switch(self.home, 'switched')
        doc = self.owner.read_receipt(self.home)
        doc['clients'] = {name: doc['clients'][name] for name in ('claude', 'codex')}
        (self.home / 'activation.json').write_text(json.dumps(doc))
        before = self.settings.read_bytes()
        restore = mock.Mock()
        with self.assertRaisesRegex(SystemExit, 'switched to OpenRouter only'):
            module('client_removal').remove_all(self.home, self.owner, restore)
        restore.assert_not_called()
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertEqual(set(self.owner.read_receipt(self.home)['clients']), {'claude', 'codex'})

    def test_partial_io_failure_keeps_remaining_router_and_retry_finishes(self):
        removal = module('client_removal')
        load = self.install._delivery._load
        real = removal._atomic.replace_text
        def fail_cli(path, *args, **kwargs):
            if path == self.settings.resolve():
                raise OSError('synthetic write failure')
            return real(path, *args, **kwargs)
        with mock.patch.object(self.install._delivery, '_load', side_effect=lambda name:
                removal if name == 'client_removal' else load(name)), \
                mock.patch.object(removal._atomic, 'replace_text', side_effect=fail_cli), \
                self.assertRaisesRegex(SystemExit, 'Removed: Codex. Remaining: Claude Code'):
            self.remove()
        self.backend.uninstall.assert_not_called()
        self.assertEqual(set(self.owner.read_receipt(self.home)['clients']), {'claude'})
        self.assertNotIn('openai_base_url', self.config.read_text())
        self.assertEqual(self.remove(), 0)
        self.backend.uninstall.assert_called_once()
        self.assertFalse((self.home / 'activation.json').exists())
        self.assertEqual(json.loads(self.settings.read_text())['tools'], {'disabled': True})

    def test_interrupted_receipt_removal_can_retry_a_restored_codex(self):
        doc = self.owner.read_receipt(self.home)
        doc['clients']['codex']['reviewer'] = {'removed': ['model_provider = "previous-provider"']}
        (self.home / 'activation.json').write_text(json.dumps(doc))
        drop = self.owner.drop_client
        def interrupted(home, client, **kwargs):
            if client == 'codex':
                raise OSError('receipt write interrupted')
            return drop(home, client, **kwargs)
        with mock.patch.object(self.owner, 'drop_client', side_effect=interrupted), \
                self.assertRaisesRegex(SystemExit, 'left running'):
            self.remove()
        self.assertNotIn('openai_base_url', self.config.read_text())
        self.backend.uninstall.assert_not_called()
        self.assertEqual(self.remove(), 0)
        self.assertTrue(json.loads(self.settings.read_text())['tools']['disabled'])

    def test_completed_codex_restore_accepts_unrelated_provider_but_not_missing_prior_route(self):
        entry = self.owner.read_receipt(self.home)['clients']['codex']
        entry['reviewer'] = {'removed': ['model_provider = "previous-provider"']}
        self.config.write_text(self.config.read_text() + '\n[model_providers.person]\nname = "Keep"\n')
        _, restored = self.owner.removal_plan(self.config, entry)
        self.config.write_text(restored, newline='')
        self.assertEqual(self.owner.removal_plan(self.config, entry), (restored, restored))
        changed = restored.replace('model_provider = "previous-provider"', '# removed previous route')
        self.config.write_text(changed, newline='')
        with self.assertRaises(SystemExit):
            self.owner.removal_plan(self.config, entry)
        self.assertEqual(self.config.read_bytes(), changed.encode())

    def test_legacy_claude_receipt_restores_only_proven_keys_and_migrates_new_key_evidence(self):
        cli = self.install._claude_config
        legacy_keys = (cli.BASE_URL_KEY, cli.DISCOVERY_KEY, cli.FIRST_PARTY_KEY)
        for repair in (False, True):
            with self.subTest(repair=repair):
                previous = dict.fromkeys(legacy_keys)
                env = cli.desired_env(self.home, self.state)
                env[cli.FIRST_PARTY_KEY] = '1'
                env[cli.TOOL_SEARCH_KEY] = 'true' if repair else 'false'
                self.settings.write_text(json.dumps({'env': env, 'keep': True}))
                entry = dict(config_path=str(self.settings), inserted_block=json.dumps(previous))
                self.owner.write_client_receipt(self.home, 'claude', entry)
                if repair:
                    cli.attach(self.home, self.state, self.owner, settings_path_override=self.settings)
                else:
                    (self.home / 'mixed-router-state.json').write_text(json.dumps(self.state))
                cli.detach(self.home, self.owner)
                after = json.loads(self.settings.read_text())
                self.assertEqual(after, {'env': {cli.TOOL_SEARCH_KEY: 'true' if repair else 'false'}, 'keep': True})

    def test_damaged_receipts_refuse_before_any_change(self):
        path = self.home / 'activation.json'
        for value in ('{broken', '{}', '{"version":2,"clients":{},"clients":{}}'):
            with self.subTest(value=value):
                path.write_text(value)
                before = (self.config.read_bytes(), self.settings.read_bytes())
                with self.assertRaisesRegex(SystemExit, 'receipt'):
                    self.remove()
                self.assertEqual((self.config.read_bytes(), self.settings.read_bytes()), before)
        self.backend.uninstall.assert_not_called()

    def test_interrupted_desktop_restore_keeps_claim_and_retries_remaining_file(self):
        from tests.test_claude_desktop_config import _profile
        profile = _profile(self.root)
        self.install._desktop_config.attach(self.home, self.state, self.owner, data_dir_override=profile)
        config = profile / 'claude_desktop_config.json'
        config.write_text('{"deploymentMode":"3p"}')  # Switch Claude selected OpenRouter.
        removal, load = module('client_removal'), self.install._delivery._load
        real = removal._atomic.replace_text
        def fail_mode(path, *args, **kwargs):
            if path == config.resolve():
                raise OSError('synthetic later write failure')
            return real(path, *args, **kwargs)
        with mock.patch.object(self.install._delivery, '_load', side_effect=lambda name:
                removal if name == 'client_removal' else load(name)), \
                mock.patch.object(removal._atomic, 'replace_text', side_effect=fail_mode), \
                self.assertRaisesRegex(SystemExit, 'Remaining: Claude desktop'):
            self.remove()
        self.assertEqual(set(self.owner.read_receipt(self.home)['clients']), {'claude-desktop'})
        self.backend.uninstall.assert_not_called()
        self.assertEqual(self.remove(), 0)
        self.assertEqual(json.loads(config.read_text()), {})

    def test_changed_json_after_preflight_is_preserved(self):
        removal = module('client_removal')
        entry = self.owner.read_receipt(self.home)['clients']['claude']
        plan = removal.json_plan(self.home, 'claude', entry)
        changed = self.settings.read_text().replace('"disabled": true', '"disabled": false')
        self.settings.write_text(changed)
        with self.assertRaises(removal._atomic.ConcurrentChange):
            removal.apply(plan)
        self.assertEqual(self.settings.read_text(), changed)

    def test_real_callback_cleanup_preserves_user_formatting_after_mixed_removal(self):
        hook = module('claude_profile_hook')
        hook.install(self.home, sys.executable, {'CLAUDE_CONFIG_DIR': str(self.settings.parent)})
        recorded = json.loads((self.home / hook.RECEIPT).read_text())
        env = json.loads(self.settings.read_text())['env']
        before = ('{\r\n "tools" : {"disabled":true}, "env": ' + json.dumps(env)
                  + ', "hooks": {"SessionStart": [' + json.dumps(recorded['entry'])
                  + ', { "keep" : [1,  2] }]}\r\n}\r\n')
        self.settings.write_bytes(before.encode())
        load = self.install._delivery._load
        with mock.patch.object(self.install._delivery, '_load', side_effect=lambda name:
                hook if name == 'claude_profile_hook' else load(name)):
            self.assertEqual(self.remove(), 0)
        self.assertEqual(self.settings.read_bytes(),
            b'{\r\n "tools" : {"disabled":true}, "env": {}, "hooks": {"SessionStart": [{ "keep" : [1,  2] }]}\r\n}\r\n')
        self.assertFalse((self.home / hook.RECEIPT).exists())

    @unix_only
    def test_service_only_checks_later_claude_conflict_before_detaching_codex(self):
        from tests.test_client_activation import ServiceOnlyTests
        from tests.test_install_config import _install
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            config, _, _, _ = _install(self, tmp, home, '1.0.0')
            settings = Path(tmp) / 'claude-settings.json'
            settings.write_text('{"env":{}}')
            self.install.attach_claude(home, json.loads(
                (home / 'mixed-router-state.json').read_text()), settings_path=settings)
            doc = json.loads(settings.read_text())
            doc['env']['ANTHROPIC_BASE_URL'] = 'https://person.example'
            settings.write_text(json.dumps(doc))
            before = config.read_bytes()
            with self.assertRaisesRegex(SystemExit, 'No assistants were detached'):
                ServiceOnlyTests._install_service_only(self, self, tmp, home, '1.0.1')
            self.assertEqual(config.read_bytes(), before)
            self.assertEqual(set(self.owner.read_receipt(home)['clients']), {'codex', 'claude'})
