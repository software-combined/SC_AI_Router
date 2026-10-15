"""Client choices survive updates; explicit additions change the serving policy."""
import contextlib
import io
import itertools
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import urllib.request
from unittest import mock

from tests.install_fixtures import _craft_bundle, _ok_run, _static_fetch, install_mod
from tests import test_update_channel
from tests.test_client_choice import _full_install, _home, _install


class ClientRetentionTests(unittest.TestCase):
    def setUp(self):
        self.backend = mock.Mock()
        self.backend.pinned_release.return_value = None
        self.enterContext(mock.patch.object(install_mod, 'platform_backend',
                                           return_value=self.backend))

    def scheduled_update(self, tmp, home):
        fixture = test_update_channel.UpdateBackoffTests()
        self.addCleanup(fixture.doCleanups)
        blob, latest = _craft_bundle('1.0.1')
        def run(cmd, **kwargs):
            if len(cmd) > 1 and cmd[1].endswith('install.py'):
                self.assertNotIn('--clients', cmd)
                args = install_mod.build_parser().parse_args(cmd[2:])
                rc = install_mod.do_install(args, _fetch=_static_fetch(latest, blob))
                return SimpleNamespace(returncode=rc, stdout='', stderr='')
            return _ok_run(cmd, **kwargs)
        with mock.patch.dict(os.environ, {'HOME': str(Path(tmp) / 'fakehome'),
                             'USERPROFILE': str(Path(tmp) / 'fakehome'),
                             'CLAUDE_CONFIG_DIR': str(Path(tmp) / 'claude'),
                             'ROUTER_NO_KEY_WINDOW': '1', 'OPENROUTER_API_KEY': 'test-key'}), \
                mock.patch.object(install_mod._claude_config, 'release_listing',
                                  return_value={'data': [{'id': 'synthetic-update'}]}):
            rc, out = fixture._check(home, blob, latest, [], run=run)
            self.assertIn('agent skills:', out)
            return rc

    def test_claude_only_scheduled_update_preserves_absent_or_unmanaged_codex(self):
        for before, mode in itertools.product((None, b'owner_setting = 1\n'), ('subscription', 'none')):
            with self.subTest(before=before, mode=mode), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp) / 'router'
                config = Path(tmp) / 'fakehome/.codex/config.toml'
                if before is not None:
                    config.parent.mkdir(parents=True)
                    config.write_bytes(before)
                _, _, fake_home, _ = _full_install(self, tmp, home, '1.0.0', ['--clients', 'claude'])
                _install(tmp, home, ['--clients', 'none', '--anthropic-mode', mode])
                self.assertEqual(self.scheduled_update(tmp, home), 0)
                self.assertEqual(install_mod.ensure_state(home)['anthropic_mode'], mode)
                self.assertEqual(install_mod.current_version(home), '1.0.1')
                self.assertEqual(config.read_bytes() if config.exists() else None, before)
                self.assertEqual(set(install_mod._codex_config.read_receipt(home)['clients']),
                                 {'claude'})
                entry = install_mod._codex_config.read_receipt(home)['clients']['claude']
                self.assertEqual(entry['listing']['models'][0]['id'], 'synthetic-update')
                self.assertFalse((fake_home / '.codex/AGENTS.md').exists())
                self.assertFalse((fake_home / '.codex/AGENTS.override.md').exists())

    def test_receipts_override_last_selection_and_keep_desktop_delivery(self):
        for selection, expected in ((['--clients', 'both', '--desktop'], {'codex', 'claude', 'claude-desktop'}),
                                    (['--clients', 'none', '--desktop'], {'claude-desktop'})):
            with self.subTest(selection=selection), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp) / 'router'
                _full_install(self, tmp, home, '1.0.0', selection)
                _install(tmp, home, ['--clients', 'none', '--anthropic-mode', 'none'])
                state = install_mod.ensure_state(home)
                state['clients'] = 'claude'  # Last selection is not the attachment union.
                install_mod._write_state(home, state)
                _, out, _, _ = _full_install(self, tmp, home, '1.0.1', [])
                self.assertIn('agent skills:', out)
                self.assertEqual(set(install_mod._codex_config.read_receipt(home)['clients']),
                                 expected)
                state = install_mod.ensure_state(home)
                self.assertEqual(state['anthropic_mode'], 'none')
                self.assertEqual(state['clients'], 'both' if 'codex' in expected else 'none')
                self.assertEqual(set(install_mod._delivery.clients(home, state)),
                                 {'codex', 'claude'} if 'codex' in expected else {'claude'})
                if 'claude-desktop' in expected:
                    entry = install_mod._desktop_config.applied_entry_path(Path(tmp) / 'Claude-3p')
                    self.assertEqual(json.loads(entry.read_text())['inferenceProvider'], 'gateway')

    def test_service_only_accepts_each_explicit_addition(self):
        cases = ((['--clients', 'claude'], {'claude'}),
                 (['--clients', 'codex'], {'codex'}),
                 (['--clients', 'both'], {'codex', 'claude'}),
                 (['--desktop'], {'claude-desktop'}),
                 (['--client', 'codex', '--clients', 'claude'], {'claude'}))
        for argv, expected in cases:
            with self.subTest(argv=argv), tempfile.TemporaryDirectory() as tmp:
                home = _home(tmp)
                state = install_mod.ensure_state(home)
                state.update(client='none', clients='none')
                install_mod._write_state(home, state)
                self.assertEqual(_install(tmp, home, argv)[0], 0)
                self.assertEqual(set(install_mod._codex_config.read_receipt(home)['clients']),
                                 expected)
                self.assertEqual(install_mod.ensure_state(home)['client'], 'codex')

    def test_explicit_conflicts_refuse_before_creating_state(self):
        for argv in (['--client', 'none', '--clients', 'claude'],
                     ['--client', 'none', '--desktop'],
                     ['--claude-mode', 'subscription', '--anthropic-mode', 'none']):
            with self.subTest(argv=argv), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp) / 'router'
                with self.assertRaisesRegex(SystemExit, 'conflict'):
                    _full_install(self, tmp, home, '1.0.0', argv)
                self.assertFalse(home.exists())

    def test_saved_selection_and_deliberate_modes_survive_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            state = install_mod.ensure_state(home)
            state.update(clients='claude', openai_mode='none', anthropic_mode='none')
            args = install_mod.build_parser().parse_args([])
            _, clients, claude_mode, mode = install_mod._resolve_clients_and_modes(args, home, state)
            self.assertEqual((clients, claude_mode, mode), ('claude', 'none', 'none'))
            state.pop('anthropic_mode')
            state.update(clients='codex', claude_mode='subscription')
            install_mod._resolve_clients_and_modes(args, home, state)
            self.assertNotIn('anthropic_mode', state)  # Old default is not a Claude choice.

    def test_corrupt_receipt_allows_only_current_service_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'router'
            _, _, user, _ = _full_install(self, tmp, home, '1.0.0', ['--clients', 'both'])
            paths = (home / 'activation.json', user / '.codex/config.toml',
                     Path(tmp) / 'claude/settings.json')
            paths[0].write_text('{broken json')
            before = [path.read_bytes() for path in paths]
            self.assertEqual(_full_install(self, tmp, home, '1.0.0', ['--setup'])[0], 0)
            self.assertEqual([path.read_bytes() for path in paths], before)
            for version, args in (('1.0.0', ['--clients', 'claude']),
                                  ('1.0.0', ['--setup', '--clients', 'claude']),
                                  ('1.0.0', ['--setup', '--openai-mode', 'none']),
                                  ('1.0.1', ['--setup'])):
                with self.subTest(version=version, args=args):
                    state = (home / 'mixed-router-state.json').read_bytes()
                    with self.assertRaisesRegex(SystemExit, 'receipts are unreadable'):
                        _full_install(self, tmp, home, version, args)
                    self.assertEqual([path.read_bytes() for path in paths], before)
                    self.assertEqual((home / 'mixed-router-state.json').read_bytes(), state)
                    self.assertEqual(install_mod.current_version(home), '1.0.0')

    def test_codex_mode_change_preserves_retained_claude_effective_mode(self):
        cases = (('subscription', None, 'none', 'subscription'),
                 ('subscription', 'none', 'none', 'none'),
                 ('none', None, 'subscription', 'none'))
        for prior_openai, prior_claude, selected, expected in cases:
            with self.subTest(prior=prior_claude, selected=selected), \
                    tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp) / 'router'
                _full_install(self, tmp, home, '1.0.0', ['--clients', 'both'])
                state = install_mod.ensure_state(home)
                state.update(openai_mode=prior_openai, claude_mode='subscription')
                if prior_claude is None:
                    state.pop('anthropic_mode')
                else:
                    state['anthropic_mode'] = prior_claude
                install_mod._write_state(home, state)
                _full_install(self, tmp, home, '1.0.1',
                              ['--clients', 'codex', '--openai-mode', selected])
                state = install_mod.ensure_state(home)
                self.assertEqual(state['openai_mode'], selected)
                self.assertEqual(state.get('anthropic_mode', state['openai_mode']), expected)
                self.assertEqual(state['claude_mode'], expected)


class CurrentModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.home = _home(self.tmp)
        state = install_mod.ensure_state(self.home)
        state.update(openai_mode='none', openai_models=[])
        install_mod._write_state(self.home, state)
        self.enterContext(mock.patch.dict(os.environ, {
            'HOME': str(Path(self.tmp) / 'fakehome'),
            'USERPROFILE': str(Path(self.tmp) / 'fakehome'),
            'CLAUDE_CONFIG_DIR': str(Path(self.tmp) / 'claude'), 'ROUTER_NO_KEY_WINDOW': '1'}))
        install_mod._client_choice.attach_codex(self.home, state, 'none', install_mod._codex_config)
        self.codex = Path.home() / '.codex/config.toml'
        self.codex_before = self.codex.read_bytes()
        self.enterContext(mock.patch.object(install_mod, 'find_python', return_value='/test/python'))
        self.enterContext(mock.patch.object(install_mod._claude_config, 'release_listing', return_value=None))
        self.backend = mock.Mock()
        self.enterContext(mock.patch.object(install_mod, 'platform_backend', return_value=self.backend))

    def install(self, *extra, clients='claude'):
        selection = ['--clients', clients] if clients is not None else []
        args = install_mod.build_parser().parse_args([
            '--home', str(self.home), '--feed', 'file:///latest.json', *selection, *extra])
        return install_mod.do_install(args, _fetch=lambda _: b'{"version":"1.0.0"}')

    def assert_reload_admits_native_claude(self, *extra, clients='claude'):
        from ai_router import ingress
        from tests.fakes import FakeUpstream, install_fake
        from tests.harness import get, post, start_server
        from tests.test_claude_ingress import _messages
        self.enterContext(mock.patch.object(ingress, 'VERSION', '1.0.0'))
        self.enterContext(mock.patch.object(urllib.request, '_opener',
                          urllib.request.build_opener(urllib.request.ProxyHandler({}))))
        recorded = install_fake(self, lambda: FakeUpstream(
            200, b'{"id":"msg_1","type":"message","content":[]}', []))
        server = start_server(install_mod.ensure_state(self.home) | {'port': 0})
        servers = [server]
        def close_servers():
            for serving in servers:
                serving.shutdown()
                serving.server_close()
        self.addCleanup(close_servers)
        state = install_mod.ensure_state(self.home)
        state['port'] = server.server_port
        install_mod._write_state(self.home, state)
        def request():
            return post(servers[-1].server_port, '/test-token/v1/messages',
                        _messages('claude-opus-4-6'), {'Authorization': 'Bearer synthetic-subscription',
                                                    'anthropic-version': '2023-06-01'})
        response = request()
        self.assertEqual(response.status, 400)
        response.read()
        def reload(*_args):
            server.shutdown()
            server.server_close()
            servers.append(start_server(install_mod.ensure_state(self.home)))
        self.backend.install.side_effect = reload
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.install(*extra, clients=clients), 0)
        self.backend.install.assert_called_once()
        self.assertIsNone(self.backend.install.call_args.args[-1])
        live = json.loads(get(servers[-1].server_port, '/test-token/health').read())
        self.assertEqual(live['version'], '1.0.0')
        self.assertEqual(servers[-1].state['anthropic_mode'], 'subscription')
        response = request()
        self.assertEqual(response.status, 200)
        response.read()
        self.assertEqual(recorded[0][0], 'api.anthropic.com')
        self.assertEqual(install_mod.ensure_state(self.home)['openai_mode'], 'none')
        self.assertEqual(self.codex.read_bytes(), self.codex_before)

    def test_current_attach_restarts_from_disk_and_admits_native_claude(self):
        self.assert_reload_admits_native_claude()

    def test_none_reloads_changed_policy_but_skips_unchanged_service_work(self):
        receipt = (self.home / 'activation.json').read_bytes()
        self.assert_reload_admits_native_claude('--anthropic-mode', 'subscription', clients='none')
        self.assertEqual((self.home / 'activation.json').read_bytes(), receipt)
        self.backend.install.reset_mock()
        with mock.patch.object(install_mod._svc, 'wait_version') as wait:
            self.assertEqual(self.install(clients='none'), 0)
        self.backend.install.assert_not_called()
        wait.assert_not_called()

    def test_mode_only_service_request_reloads_without_adding_a_client(self):
        (self.home / 'activation.json').unlink()
        state = install_mod.ensure_state(self.home)
        state.update(client='none', clients='none')
        install_mod._write_state(self.home, state)
        self.assert_reload_admits_native_claude('--anthropic-mode', 'subscription', clients=None)
        self.assertFalse((self.home / 'activation.json').exists())

    def test_failed_reload_restores_modes_without_attaching_or_claiming_success(self):
        for clients in ('claude', 'none', None):
            with self.subTest(clients=clients):
                before = install_mod.ensure_state(self.home)
                if clients is None:
                    (self.home / 'activation.json').unlink()
                    before.update(client='none', clients='none')
                    install_mod._write_state(self.home, before)
                out = io.StringIO()
                with mock.patch.object(install_mod._svc, 'wait_version', return_value=None), \
                        contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
                    self.install('--anthropic-mode', 'subscription', clients=clients)
                self.assertEqual(install_mod.ensure_state(self.home), before)
                self.assertEqual(self.codex.read_bytes(), self.codex_before)
                self.assertNotIn('claude', install_mod._codex_config.read_receipt(
                    self.home).get('clients', {}))
                self.assertNotIn('connected', out.getvalue())
                self.assertNotIn('nothing to attach', out.getvalue())

    def test_canonical_none_requires_an_explicit_change(self):
        state = install_mod.ensure_state(self.home)
        state['anthropic_mode'] = 'none'
        install_mod._write_state(self.home, state)
        with self.assertRaisesRegex(SystemExit, 'claude_mode is none'):
            self.install()
        self.assertEqual(install_mod.ensure_state(self.home)['anthropic_mode'], 'none')
        with mock.patch.object(install_mod._svc, 'wait_version', return_value=True):
            self.assertEqual(self.install('--claude-mode', 'subscription'), 0)
        self.assertEqual(install_mod.ensure_state(self.home)['anthropic_mode'], 'subscription')
