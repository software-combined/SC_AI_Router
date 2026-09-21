"""Attaching the selected clients to an already-current install.

A plain re-run used to stop at "up to date" before the client stage, so
--clients claude silently attached nothing until the next release. These
tests pin the same-version attach and its additive desktop-only case.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from tests.install_fixtures import install_mod

# The module the installer actually delegates to, so patching it here is the
# same object the install path reads.
dialog = install_mod._client_choice._dialog


def _home(tmp):
    home = Path(tmp) / 'router'
    (home / 'releases/1.0.0').mkdir(parents=True)
    (home / 'current').write_text('1.0.0')
    (home / 'mixed-router-state.json').write_text(json.dumps(
        {'port': 1, 'token': 'test-token', 'claude_mode': 'subscription'}))
    return home


def _install(tmp, home, argv, extra_env=None):
    """Run a current-install do_install with every client path isolated."""
    args = install_mod.build_parser().parse_args(
        ['--home', str(home), '--feed', 'file:///latest.json', *argv])
    env = {'HOME': str(Path(tmp) / 'fakehome'),
           'CLAUDE_CONFIG_DIR': str(Path(tmp) / 'claude'),
           'CLAUDE_USER_DATA_DIR': str(Path(tmp) / 'Claude-3p'),
           'ROUTER_NO_KEY_WINDOW': '1'}
    env.update(extra_env or {})
    out = io.StringIO()
    with mock.patch.dict(os.environ, env), \
            mock.patch.object(install_mod, 'find_python', return_value='python3.14'), \
            mock.patch.object(install_mod._claude_config, 'release_listing',
                              return_value=None), \
            mock.patch.object(install_mod, 'install_bundle') as bundle, \
            contextlib.redirect_stdout(out):
        code = install_mod.do_install(args, _fetch=lambda _: b'{"version":"1.0.0"}')
    return code, out.getvalue(), bundle, Path(env['HOME']), Path(env['CLAUDE_CONFIG_DIR'])


def _full_install(test, tmp, home, version, argv):
    """Run the newer-version install path with the bundle and service seams faked."""
    from tests.install_fixtures import _craft_bundle, _ok_run, _patch_attrs, _static_fetch
    from tests.test_install_config import _fake_write_catalogue

    blob, latest = _craft_bundle(version)
    fetch = _static_fetch(dict(latest, version=version), blob)

    def fake_run(cmd, **kwargs):
        return _ok_run(cmd, **kwargs)

    _patch_attrs(test, run=fake_run, self_test=lambda *args: None,
                 write_catalogue=_fake_write_catalogue,
                 wait_version=lambda *args, **kwargs: True)
    args = install_mod.build_parser().parse_args(
        ['--feed', 'file:///latest.json', '--home', str(home), *argv])
    env = {'HOME': str(Path(tmp) / 'fakehome'),
           'CLAUDE_CONFIG_DIR': str(Path(tmp) / 'claude'),
           'CLAUDE_USER_DATA_DIR': str(Path(tmp) / 'Claude-3p'),
           'OPENROUTER_API_KEY': 'test-key', 'ROUTER_NO_KEY_WINDOW': '1'}
    out = io.StringIO()
    with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out):
        code = install_mod.do_install(args, _fetch=fetch, _run=fake_run)
    return code, out.getvalue(), Path(env['HOME']), Path(env['CLAUDE_CONFIG_DIR'])


class CurrentInstallAttachTests(unittest.TestCase):
    def test_claude_attach_on_a_current_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            code, out, bundle, fake_home, claude = _install(tmp, home, ['--clients', 'claude'])
            self.assertEqual(code, 0)
            bundle.assert_not_called()
            self.assertEqual((home / 'current').read_text(), '1.0.0')
            env = json.loads((claude / 'settings.json').read_text())['env']
            self.assertIn('ANTHROPIC_BASE_URL', env)
            self.assertEqual(env['CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY'], 'true')
            clients = install_mod._codex_config.read_receipt(home)['clients']
            self.assertIn('claude', clients)
            self.assertNotIn('codex', clients)
            self.assertFalse((fake_home / '.codex' / 'config.toml').exists())
            self.assertIn('Claude Code connected', out)

    def test_both_attaches_codex_and_claude(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            code, out, bundle, fake_home, claude = _install(tmp, home, ['--clients', 'both'])
            self.assertEqual(code, 0)
            bundle.assert_not_called()
            block = (fake_home / '.codex' / 'config.toml').read_text()
            self.assertIn('openai_base_url = ', block)
            clients = install_mod._codex_config.read_receipt(home)['clients']
            self.assertIn('codex', clients)
            self.assertIn('claude', clients)
            self.assertTrue((claude / 'settings.json').exists())
            self.assertIn('Codex, Claude Code connected', out)

    def test_bare_rerun_attaches_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            code, out, bundle, fake_home, claude = _install(tmp, home, [])
            self.assertEqual(code, 0)
            bundle.assert_not_called()
            self.assertIn('up to date 1.0.0', out)
            self.assertFalse((fake_home / '.codex' / 'config.toml').exists())
            self.assertFalse((claude / 'settings.json').exists())
            self.assertFalse((home / 'activation.json').exists())

    def test_desktop_only_attaches_the_profile_and_detaches_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            _install(tmp, home, ['--clients', 'both'])
            config = Path(tmp) / 'fakehome' / '.codex' / 'config.toml'
            before = config.read_text()
            settings = Path(tmp) / 'claude' / 'settings.json'
            before_settings = settings.read_text()
            code, out, _, _, _ = _install(tmp, home, ['--clients', 'none', '--desktop'])
            self.assertEqual(code, 0)
            entry = install_mod._desktop_config.applied_entry_path(Path(tmp) / 'Claude-3p')
            self.assertEqual(json.loads(entry.read_text())['inferenceProvider'], 'gateway')
            self.assertEqual(config.read_text(), before)
            clients = install_mod._codex_config.read_receipt(home)['clients']
            self.assertIn('codex', clients)
            self.assertIn('claude', clients)
            self.assertEqual(settings.read_text(), before_settings)
            self.assertIn('Claude desktop connected', out)

    def test_hand_edited_claude_setting_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            settings = Path(tmp) / 'claude' / 'settings.json'
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps(
                {'env': {'ANTHROPIC_BASE_URL': 'http://elsewhere.example'}}))
            with self.assertRaisesRegex(SystemExit, 'managed outside this installer'):
                _install(tmp, home, ['--clients', 'claude'])
            self.assertEqual(json.loads(settings.read_text())['env'],
                             {'ANTHROPIC_BASE_URL': 'http://elsewhere.example'})

    def test_full_install_desktop_only_keeps_existing_attachments(self):
        # The newer-version path used to drop --desktop and detach every
        # client instead; only this test covers that branch.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'router'
            code, _, fake_home, claude = _full_install(
                self, tmp, home, '1.0.0', ['--clients', 'both'])
            self.assertEqual(code, 0)
            config = fake_home / '.codex' / 'config.toml'
            config_bytes = config.read_bytes()
            settings = claude / 'settings.json'
            settings_bytes = settings.read_bytes()
            code, out, fake_home, claude = _full_install(
                self, tmp, home, '1.0.1', ['--clients', 'none', '--desktop'])
            self.assertEqual(code, 0)
            entry = install_mod._desktop_config.applied_entry_path(Path(tmp) / 'Claude-3p')
            self.assertEqual(json.loads(entry.read_text())['inferenceProvider'], 'gateway')
            self.assertEqual(config.read_bytes(), config_bytes)
            self.assertEqual(settings.read_bytes(), settings_bytes)
            clients = install_mod._codex_config.read_receipt(home)['clients']
            self.assertIn('codex', clients)
            self.assertIn('claude', clients)
            self.assertIn('claude-desktop', clients)
            self.assertIn('Claude desktop connected', out)


if __name__ == '__main__':
    unittest.main()
