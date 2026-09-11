"""Plan 063 Step 1: characterize client-owned changes and restoration.

Pins pre-existing file preservation, owner-chosen model/effort retention,
edited-block rejection, legacy receipt restore, restore-failure ordering,
and the disable return-code/output relation. Assertions examine
files/service outcomes, not private helper identities.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests._platform import unix_only
from tests.install_fixtures import _ok_run, _patch_attrs, install_mod
from tests.test_install_config import _install


@unix_only
class ClientActivationTests(unittest.TestCase):
    def test_pre_existing_config_content_survives_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            fakehome = Path(tmp) / 'fakehome'
            config = fakehome / '.codex' / 'config.toml'
            config.parent.mkdir(parents=True)
            config.write_text('owner_setting = 1\n')
            config_path, _, _, _ = _install(self, tmp, home, '1.0.0')
            self.assertEqual(config_path, config)
            self.assertIn('owner_setting = 1', config.read_text())
            self.assertIn('# BEGIN local mixed model picker', config.read_text())

    def test_owner_picker_selection_survives_reinstall(self):
        # Picker lines ride inside the receipt-owned block; simulate a prior
        # install whose receipt already carried the owner's choice.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            config, _, _, _ = _install(self, tmp, home, '1.0.0')
            receipt_path = home / 'activation.json'
            receipt = json.loads(receipt_path.read_text())
            owned = receipt['clients']['codex']['inserted_block'].replace(
                '# END local mixed model picker\n',
                'model = "z-ai/glm-5.3"\nmodel_reasoning_effort = "high"\n'
                '# END local mixed model picker\n')
            config.write_text(config.read_text().replace(
                receipt['clients']['codex']['inserted_block'], owned))
            receipt['clients']['codex']['inserted_block'] = owned
            receipt_path.write_text(json.dumps(receipt))
            config2, _, _, _ = _install(self, tmp, home, '1.0.1')
            self.assertEqual(config2, config)
            body = config.read_text()
            self.assertIn('model = "z-ai/glm-5.3"', body)
            self.assertIn('model_reasoning_effort = "high"', body)

    def test_edited_block_refuses_second_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            config, _, _, _ = _install(self, tmp, home, '1.0.0')
            config.write_text(config.read_text().replace(
                'openai_base_url', 'openai_base_url_edited'))
            from tests.install_fixtures import _craft_bundle, _static_fetch
            blob, latest = _craft_bundle('1.0.1')
            _patch_attrs(self, run=lambda cmd, **kw: _ok_run(cmd, **kw),
                         self_test=lambda *args: None,
                         wait_version=lambda *args, **kwargs: True)
            from tests.test_install_config import _fake_write_catalogue
            _patch_attrs(self, write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *args, **kwargs: True)
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            with mock.patch.dict(os.environ, {'HOME': str(Path(tmp) / 'fakehome'),
                                              'OPENROUTER_API_KEY': 'k'}):
                with self.assertRaisesRegex(SystemExit, 'edited by hand'):
                    install_mod.do_install(args, _fetch=_static_fetch(latest, blob))

    def test_legacy_receipt_restores_exact_owned_block(self):
        # Legacy receipt shape (config path + block, no client field) drives
        # the real disable.py in a subprocess against a temporary profile.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            config, _, _, _ = _install(self, tmp, home, '1.0.0')
            receipt = json.loads((home / 'activation.json').read_text())
            block = receipt['clients']['codex']['inserted_block']
            (home / 'activation.json').write_text(json.dumps(
                {'config_path': str(config), 'inserted_block': block}))
            disable = (Path(__file__).resolve().parents[1] / 'tools' / 'disable.py')
            env = dict(os.environ, ROUTER_HOME=str(home), ROUTER_RESTORE_ONLY='1')
            result = subprocess.run(
                [sys.executable, str(disable)], capture_output=True, text=True,
                env=env, cwd=str(disable.parent))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('OpenAI direct routing restored', result.stdout)
            self.assertNotIn(block, config.read_text())

    def test_restore_failure_stops_before_service_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            _install(self, tmp, home, '1.0.0')
            _patch_attrs(self, run=lambda cmd, **kw: SimpleNamespace(
                returncode=1, stdout='boom\n', stderr=''))
            args = install_mod.build_parser().parse_args(['--home', str(home)])
            with mock.patch.dict(os.environ, {'HOME': str(Path(tmp) / 'fakehome')}):
                with self.assertRaisesRegex(SystemExit, 'configuration restore failed'):
                    install_mod.do_uninstall(args)

    def test_success_text_alone_cannot_pass_a_failing_remover(self):
        # The verdict follows the machine result: a nonzero exit with the
        # legacy success text still stops service removal.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            _install(self, tmp, home, '1.0.0')
            _patch_attrs(self, run=lambda cmd, **kw: SimpleNamespace(
                returncode=1, stdout='OpenAI direct routing restored.\n', stderr=''))
            args = install_mod.build_parser().parse_args(['--home', str(home)])
            with mock.patch.dict(os.environ, {'HOME': str(Path(tmp) / 'fakehome')}):
                with self.assertRaisesRegex(SystemExit, 'configuration restore failed'):
                    install_mod.do_uninstall(args)

    def test_disable_reports_machine_result_not_substring(self):
        # Covered directly by test_success_text_alone_cannot_pass_a_failing_remover;
        # kept as a named pointer to the verdict contract.
        self.assertTrue(callable(install_mod.do_uninstall))


class ReceiptVersionTests(unittest.TestCase):
    # Plan 049: versioned receipts carry a clients map; legacy flat
    # receipts import as the codex attachment with restore info intact.
    def _mod(self):
        import importlib.util as _ilu
        root = Path(__file__).resolve().parents[1]
        spec = _ilu.spec_from_file_location(
            'router_codex_config', root / 'packaging' / 'codex_config.py')
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # Same injection as install.py: receipt writes go through the
        # shared atomic writer, so the direct spec-load needs it too.
        aspec = _ilu.spec_from_file_location(
            'router_atomic_write', root / 'packaging' / 'atomic_write.py')
        amod = _ilu.module_from_spec(aspec)
        aspec.loader.exec_module(amod)
        mod._atomic_write = amod
        return mod

    def test_parse_snapshot_falls_back_to_empty_for_non_objects(self):
        # Plan 095: the shared parser replaces both per-adapter decoders; pin
        # the {} fallback the re-attach paths rely on.
        config = self._mod()
        for text in ('{', '[1]', '"s"', 'null', '42', 'true'):
            with self.subTest(text=text):
                self.assertEqual(config.parse_snapshot(text), {})
        self.assertEqual(config.parse_snapshot('{"a": 1}'), {'a': 1})

    def test_legacy_flat_receipt_imports_as_codex(self):
        mod = self._mod()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            (home / 'activation.json').write_text(json.dumps(
                {'config_path': '/home/u/.codex/config.toml',
                 'inserted_block': '# BEGIN local mixed model picker\n# END\n'}))
            doc = mod.read_receipt(home)
            self.assertEqual(doc['version'], mod.RECEIPT_VERSION)
            self.assertEqual(doc['clients']['codex']['config_path'],
                             '/home/u/.codex/config.toml')
            # Read imports without rewriting: the flat file is untouched.
            raw = json.loads((home / 'activation.json').read_text())
            self.assertNotIn('version', raw)

    def test_second_client_write_preserves_first(self):
        mod = self._mod()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            mod.write_receipt(home, '/c/config.toml', 'block-codex', None, 'subscription', '')
            mod.write_receipt(home, '/c/settings.json', 'block-claude', None, 'subscription',
                              '', client='claude')
            doc = mod.read_receipt(home)
            self.assertEqual(set(doc['clients']), {'codex', 'claude'})
            self.assertTrue(mod.drop_client(home, 'claude'))
            doc = mod.read_receipt(home)
            self.assertEqual(set(doc['clients']), {'codex'})
            self.assertFalse(mod.drop_client(home, 'claude'))

if __name__ == '__main__':
    unittest.main()


@unix_only
class ServiceOnlyTests(unittest.TestCase):
    def _install_service_only(self, test, tmp, home, version, *extra):
        from tests.install_fixtures import _craft_bundle, _static_fetch
        from tests.test_install_config import _fake_write_catalogue
        blob, latest = _craft_bundle(version)
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if len(cmd) > 1 and Path(cmd[1]).name == 'disable.py':
                # Real remover against the temporary profile: the single
                # restore path, not a re-implementation in the test.
                env = dict(kwargs.get('env') or {})
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, env=env,
                    cwd=str(Path(cmd[1]).parent))
                return SimpleNamespace(returncode=proc.returncode,
                                       stdout=proc.stdout, stderr=proc.stderr)
            return _ok_run(cmd, **kwargs)

        _patch_attrs(test, run=fake_run,
                     self_test=lambda *args: None,
                     write_catalogue=_fake_write_catalogue,
                     wait_version=lambda *args, **kwargs: True)
        args = install_mod.build_parser().parse_args(
            ['--feed', 'file:///latest.json', '--home', str(home),
             '--client', 'none', *extra])
        env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'k'}
        with mock.patch.dict(os.environ, env):
            with contextlib.redirect_stdout(io.StringIO()):
                rc = install_mod.do_install(args, _fetch=_static_fetch(latest, blob))
        return rc, calls, env

    def test_service_only_leaves_client_files_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            fakehome = Path(tmp) / 'fakehome'
            rc, _, _ = self._install_service_only(self, tmp, home, '1.0.0')
            self.assertEqual(rc, 0)
            self.assertFalse((fakehome / '.codex' / 'config.toml').exists())
            self.assertFalse((home / 'activation.json').exists())
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.assertEqual(state.get('client'), 'none')

    def test_service_only_update_preserves_choice_and_touches_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            self._install_service_only(self, tmp, home, '1.0.0')
            rc, _, _ = self._install_service_only(self, tmp, home, '1.0.1')
            self.assertEqual(rc, 0)
            fakehome = Path(tmp) / 'fakehome'
            self.assertFalse((fakehome / '.codex' / 'config.toml').exists())
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.assertEqual(state.get('client'), 'none')
            self.assertEqual(install_mod.current_version(home), '1.0.1')

    def test_service_only_uninstall_needs_no_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            self._install_service_only(self, tmp, home, '1.0.0')
            _patch_attrs(self, run=lambda cmd, **kw: _ok_run(cmd, **kw))
            args = install_mod.build_parser().parse_args(['--home', str(home)])
            with mock.patch.dict(os.environ, {'HOME': str(Path(tmp) / 'fakehome')}):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(install_mod.do_uninstall(args), 0)

    def test_receiptless_uninstall_with_managed_block_fails_closed(self):
        # A missing receipt with the managed block still present means manual
        # interference: uninstall must refuse rather than orphan the client.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            self._install_service_only(self, tmp, home, '1.0.0')
            config = Path(tmp) / 'fakehome' / '.codex' / 'config.toml'
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text('# BEGIN local mixed model picker\n# END local mixed model picker\n')
            _patch_attrs(self, run=lambda cmd, **kw: _ok_run(cmd, **kw))
            args = install_mod.build_parser().parse_args(['--home', str(home)])
            with mock.patch.dict(os.environ, {'HOME': str(Path(tmp) / 'fakehome')}):
                with self.assertRaisesRegex(SystemExit, 'without a receipt'):
                    install_mod.do_uninstall(args)

    def test_managed_block_without_receipt_or_release_fails_closed(self):
        # The marker check sits before the release gate: even with no
        # installed release, a managed block without a receipt refuses.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            config = Path(tmp) / 'fakehome' / '.codex' / 'config.toml'
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text('# BEGIN local mixed model picker\n# END local mixed model picker\n')
            _patch_attrs(self, run=lambda cmd, **kw: _ok_run(cmd, **kw))
            args = install_mod.build_parser().parse_args(['--home', str(home)])
            with mock.patch.dict(os.environ, {'HOME': str(Path(tmp) / 'fakehome')}):
                with self.assertRaisesRegex(SystemExit, 'without a receipt'):
                    install_mod.do_uninstall(args)

    def test_legacy_state_means_codex(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            config, _, _, _ = _install(self, tmp, home, '1.0.0')
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.assertNotIn('client', state)
            self.assertIn('# BEGIN local mixed model picker', config.read_text())

    def test_codex_to_none_restores_owned_block_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            config, _, _, _ = _install(self, tmp, home, '1.0.0')
            receipt = json.loads((home / 'activation.json').read_text())
            block = receipt['clients']['codex']['inserted_block']
            rc, _, _ = self._install_service_only(self, tmp, home, '1.0.1')
            self.assertEqual(rc, 0)
            self.assertNotIn(block, config.read_text())
            self.assertFalse((home / 'activation.json').exists())
            # Guidance detaches with the block: no orphaned router rules.
            for name in ('AGENTS.md', 'AGENTS.override.md'):
                agents = Path(tmp) / 'fakehome' / '.codex' / name
                if agents.exists():
                    self.assertNotIn('codex-model-router', agents.read_text())

    def test_codex_reinstall_never_silently_detaches_claude(self):
        # Plan 049: setup attaches selected clients and never silently
        # detaches an already attached one. A codex reinstall keeps the
        # Claude settings and claim untouched.
        # A sibling client attachment survives the codex detach: only the
        # codex entry is forgotten and the receipt file remains.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            config, _, _, _ = _install(self, tmp, home, '1.0.0')
            receipt = json.loads((home / 'activation.json').read_text())
            block = receipt['clients']['codex']['inserted_block']
            claude_settings = Path(tmp) / 'claude-settings.json'
            claude_settings.write_text(json.dumps({'env': {}}))
            install_mod.attach_claude(home, json.loads(
                (home / 'mixed-router-state.json').read_text()),
                settings_path=claude_settings)
            config2, _, _, _ = _install(self, tmp, home, '1.0.1')
            self.assertEqual(config2, config)
            kept = json.loads((home / 'activation.json').read_text())
            self.assertEqual(set(kept['clients']), {'codex', 'claude'})
            claude_doc = json.loads(claude_settings.read_text())
            self.assertIn('ANTHROPIC_BASE_URL', claude_doc.get('env', {}))

    def test_service_only_detaches_all_attachments(self):
        # Explicit service-only drops every attachment and restores owned
        # settings, leaving a never-attached-shaped home.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            config, _, _, _ = _install(self, tmp, home, '1.0.0')
            receipt = json.loads((home / 'activation.json').read_text())
            block = receipt['clients']['codex']['inserted_block']
            claude_settings = Path(tmp) / 'claude-settings.json'
            claude_settings.write_text(json.dumps({'env': {}}))
            install_mod.attach_claude(home, json.loads(
                (home / 'mixed-router-state.json').read_text()),
                settings_path=claude_settings)
            rc, _, _ = self._install_service_only(self, tmp, home, '1.0.1')
            self.assertEqual(rc, 0)
            self.assertNotIn(block, config.read_text())
            self.assertFalse((home / 'activation.json').exists())
            claude_doc = json.loads(claude_settings.read_text())
            self.assertNotIn('ANTHROPIC_BASE_URL', claude_doc.get('env', {}))

    def test_codex_to_none_refuses_edited_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            config, _, _, _ = _install(self, tmp, home, '1.0.0')
            config.write_text(config.read_text().replace(
                'openai_base_url', 'openai_base_url_edited'))
            with self.assertRaisesRegex(SystemExit, 'refusing the client change'):
                self._install_service_only(self, tmp, home, '1.0.1')

    def test_unsupported_client_fails_before_mutation(self):
        # argparse choices reject unknown clients at parse time, before any
        # home, bundle, or service work.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            with self.assertRaises(SystemExit):
                install_mod.build_parser().parse_args(
                    ['--feed', 'file:///latest.json', '--home', str(home),
                     '--client', 'claude'])
            self.assertFalse(home.exists())


@unix_only
class SubscriptionModeTests(unittest.TestCase):
    def test_all_four_mode_combinations(self):
        from tests.fakes import FakeUpstream, install_fake
        from tests.harness import (
            auth_file as _auth_file,
            post as _post,
            start_server as _start_server,
            test_state as _test_state,
        )
        from tests.test_claude_ingress import _messages
        cases = [
            # (openai_mode, anthropic_mode, want_status, want_host)
            ('subscription', None, 200, 'api.anthropic.com'),
            ('subscription', 'subscription', 200, 'api.anthropic.com'),
            ('subscription', 'none', 400, None),
            ('none', None, 400, None),
            ('none', 'subscription', 200, 'api.anthropic.com'),
            ('none', 'none', 400, None),
        ]
        for openai_mode, anthropic_mode, want_status, want_host in cases:
            with self.subTest(openai_mode=openai_mode, anthropic_mode=anthropic_mode):
                recorded = install_fake(
                    self, lambda: FakeUpstream(
                        200, b'{"id":"msg_1","type":"message","content":[]}', []))
                state = _test_state(_auth_file(self))
                state['openai_mode'] = openai_mode
                if anthropic_mode is not None:
                    state['anthropic_mode'] = anthropic_mode
                server = _start_server(state)
                self.addCleanup(server.shutdown)
                response = _post(
                    server.server_port, '/test-token/v1/messages',
                    _messages('claude-opus-4-6'),
                    {'Authorization': 'Bearer subscription-secret',
                     'anthropic-version': '2023-06-01'})
                self.assertEqual(response.status, want_status)
                response.read()
                if want_host is None:
                    self.assertEqual(recorded, [])
                else:
                    self.assertEqual(recorded[0][0], want_host)
                    self.assertNotIn('test-key', json.dumps(recorded[0][4]))

    def test_anthropic_enabled_with_openai_disabled(self):
        from tests.fakes import FakeUpstream, install_fake
        from tests.harness import (
            auth_file as _auth_file,
            post as _post,
            start_server as _start_server,
            test_state as _test_state,
        )
        from tests.test_claude_ingress import _messages
        recorded = install_fake(
            self, lambda: FakeUpstream(
                200, b'{"id":"msg_1","type":"message","content":[]}', []))
        state = _test_state(_auth_file(self))
        state['openai_mode'] = 'none'
        state['anthropic_mode'] = 'subscription'
        server = _start_server(state)
        self.addCleanup(server.shutdown)
        response = _post(server.server_port, '/test-token/v1/messages',
                         _messages('claude-opus-4-6'),
                         {'Authorization': 'Bearer subscription-secret',
                          'anthropic-version': '2023-06-01'})
        self.assertEqual(response.status, 200)
        host, _, _, _, headers = recorded[0]
        self.assertEqual(host, 'api.anthropic.com')
        self.assertNotIn('test-key', json.dumps(headers))

    def test_invalid_anthropic_mode_fails_closed(self):
        from ai_router.runtime import load_state
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            path.write_text(json.dumps({'port': 1, 'token': 'x',
                                        'openai_models': [],
                                        'anthropic_mode': 'sometimes'}))
            with self.assertRaisesRegex(SystemExit, 'anthropic_mode'):
                load_state(path)


if __name__ == '__main__':
    unittest.main()
