"""Installer configuration: catalogue default, none-mode layout, and update persistence.

Brief defects 1-3: the static catalogue is the default (the router serves no
/models), the none-mode block keeps root keys out of the provider table with
a provisioned key name, and mode/feed/home survive updates.
"""
import contextlib
import hashlib
import io
import json
import os
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fakes import LAUNCHD, launchd_in_sync
from tests._platform import unix_only
from tests.test_install import (
    _craft_bundle,
    _ok_run,
    _patch_attrs,
    _static_fetch,
    _tarball,
    install_mod,
)


def _fake_write_catalogue(home, release_dir, python):
    from ai_router.catalogue import merge, read_roster
    path = home / 'mixed-models.json'
    base = json.loads(path.read_text()) if path.exists() else {'models': []}
    path.write_text(json.dumps(merge(base, read_roster(path)), indent=2) + '\n')


def _install(test, tmp, home, version, *extra_args, feed='file:///latest.json',
             in_sync=False):
    blob, latest = _craft_bundle(version)
    latest = dict(latest, version=version)
    fake_fetch = _static_fetch(latest, blob)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return _ok_run(cmd, **kwargs)

    _patch_attrs(test, run=fake_run, self_test=lambda *args: None,
                 write_catalogue=_fake_write_catalogue,
                 wait_version=lambda *args, **kwargs: True)
    if in_sync:
        # After _patch_attrs, which resets the launchd domain.
        launchd_in_sync(home, install_mod.LABEL, install_mod.UPDATE_LABEL)
    argv = ['--home', str(home), *extra_args]
    if feed is not None:
        argv = ['--feed', feed, *argv]
    args = install_mod.build_parser().parse_args(argv)
    env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'test-key'}
    with mock.patch.dict(os.environ, env):
        test.assertEqual(
            install_mod.do_install(args, _fetch=fake_fetch, _run=fake_run), 0)
    config = Path(env['HOME']) / '.codex' / 'config.toml'
    return config, calls, args, env


@unix_only
class InstallConfigTests(unittest.TestCase):
    def test_default_install_writes_subscription_block_with_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            config, _, _, _ = _install(self, tmp, home, '1.0.0')
            block = config.read_text()
            self.assertIn('openai_base_url = ', block)
            self.assertIn(f'model_catalog_json = "{home}/mixed-models.json"', block)
            self.assertNotIn('model_provider', block)
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.assertEqual(state.get('openai_mode'), 'subscription')

    def test_none_mode_block_keeps_root_keys_out_of_provider_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            config, _, _, _ = _install(self, tmp, home, '1.0.0', '--openai-mode', 'none')
            block = config.read_text()
            provider_at = block.index('model_provider = "scg_router"')
            catalog_at = block.index('model_catalog_json = ')
            table_at = block.index('[model_providers.scg_router]')
            self.assertLess(provider_at, table_at)
            self.assertLess(catalog_at, table_at)
            self.assertNotIn('env_key', block)
            self.assertNotIn('ROUTER_OPENROUTER_KEY_', block)
            self.assertNotIn('openai_base_url', block)
            approvals_at = block.index('approvals_reviewer = "user"')
            self.assertLess(approvals_at, table_at)
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.assertIn(f"/{state['token']}/backend-api/codex", block)
            self.assertEqual(state.get('openai_mode'), 'none')
            receipt = json.loads((home / 'activation.json').read_text())
            self.assertEqual(receipt['clients']['codex'].get('openai_mode'), 'none')

    def test_mode_survives_update_without_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            _install(self, tmp, home, '1.0.0', '--openai-mode', 'none')
            config, _, _, _ = _install(self, tmp, home, '1.0.1')
            block = config.read_text()
            self.assertNotIn('env_key', block)
            self.assertNotIn('openai_base_url', block)
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.assertEqual(state.get('openai_mode'), 'none')

    def test_update_preserves_picker_model_selection(self):
        # Owner model lines live inside the managed block; an update must
        # carry them forward, not reset the picker (0.6.7.21 dropped them).
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            config, _, _, _ = _install(self, tmp, home, '1.0.0')
            picked = ('# BEGIN local mixed model picker\n'
                      f'model_catalog_json = "{home}/mixed-models.json"\n'
                      'model = "meta/muse-spark-1.3"\n'
                      'model_reasoning_effort = "xhigh"\n'
                      '# END local mixed model picker\n')
            full = config.read_text()
            start = full.index('# BEGIN local mixed model picker')
            end = full.index('# END local mixed model picker') + len('# END local mixed model picker\n')
            config.write_text(full[:start] + picked + full[end:])
            receipt_path = home / 'activation.json'
            receipt = json.loads(receipt_path.read_text())
            receipt['clients']['codex']['inserted_block'] = picked
            receipt_path.write_text(json.dumps(receipt) + '\n')
            config, _, _, _ = _install(self, tmp, home, '1.0.1')
            block = config.read_text()
            self.assertIn('model = "meta/muse-spark-1.3"', block)
            self.assertIn('model_reasoning_effort = "xhigh"', block)

    def test_explicit_flag_flips_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            _install(self, tmp, home, '1.0.0')
            config, _, _, _ = _install(self, tmp, home, '1.0.1', '--openai-mode', 'none')
            self.assertIn('model_provider = "scg_router"', config.read_text())
            config, _, _, _ = _install(
                self, tmp, home, '1.0.2', '--openai-mode', 'subscription')
            block = config.read_text()
            self.assertIn('openai_base_url = ', block)
            self.assertNotIn('model_provider', block)
            self.assertNotIn('approvals_reviewer', block)

    def test_update_plist_carries_home_without_feed_pin(self):
        # --feed is one-shot: it selects this run's source but must not pin
        # future scheduled updates (pin froze prod on a local file in 0.6.2.4).
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            _install(self, tmp, home, '1.0.0', feed='file:///pinned.json')
            agents = Path(tmp) / 'fakehome' / 'Library' / 'LaunchAgents'
            content = agents / (install_mod.UPDATE_LABEL + '.plist')
            doc = plistlib.loads(content.read_bytes())
            argv = doc['ProgramArguments']
            # The stable launcher supplies --check-update/--home itself, so the
            # plist carries no argv to go stale. --feed must never be pinned:
            # a pin froze prod on a local file in 0.6.2.4.
            self.assertEqual(argv, ['/opt/homebrew/bin/python3.14',
                                    str(home / 'update_launch.py')])
            self.assertNotIn('--feed', argv)
            self.assertFalse((home / 'feed').exists())

    def test_update_plist_omits_feed_for_channel_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            _install(self, tmp, home, '1.0.0', feed=None)
            agents = Path(tmp) / 'fakehome' / 'Library' / 'LaunchAgents'
            doc = plistlib.loads(
                (agents / (install_mod.UPDATE_LABEL + '.plist')).read_bytes())
            self.assertNotIn('--feed', doc['ProgramArguments'])
            self.assertFalse((home / 'feed').exists())

    def test_update_plist_never_names_a_release_path(self):
        # launchd runs its in-memory copy of a loaded plist, so a versioned
        # install.py path outlives the release it names: prune that release and
        # the updater keeps firing a deleted installer every 15 minutes.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            _install(self, tmp, home, '1.0.0', feed=None)
            agents = Path(tmp) / 'fakehome' / 'Library' / 'LaunchAgents'
            doc = plistlib.loads(
                (agents / (install_mod.UPDATE_LABEL + '.plist')).read_bytes())
            argv = doc['ProgramArguments']
            self.assertEqual(argv[1], str(home / 'update_launch.py'))
            self.assertNotIn('releases', ' '.join(argv))
            self.assertTrue((home / 'update_launch.py').is_file(),
                            'the launcher the plist names must be installed')

    def test_fresh_install_bootstraps_missing_updater_after_main(self):
        # Fresh home, updater never loaded: restart_service bootstraps main,
        # then bootstraps the updater only because `launchctl print` misses.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            blob, latest = _craft_bundle('1.0.0')
            fake_fetch = _static_fetch(latest, blob)
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(list(cmd))
                return _ok_run(cmd, **kwargs)

            _patch_attrs(self, run=fake_run, self_test=lambda *args: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *args, **kwargs: True)
            # Fresh machine: launchd knows neither label until we bootstrap.
            LAUNCHD.reset(unloaded={install_mod.LABEL, install_mod.UPDATE_LABEL})
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'test-key'}
            with mock.patch.dict(os.environ, env):
                self.assertEqual(
                    install_mod.do_install(args, _fetch=fake_fetch, _run=fake_run), 0)
            agents = Path(tmp) / 'fakehome' / 'Library' / 'LaunchAgents'
            main = str(agents / (install_mod.LABEL + '.plist'))
            update = str(agents / (install_mod.UPDATE_LABEL + '.plist'))
            boots = [cmd for cmd in calls if cmd[:2] == ['launchctl', 'bootstrap']]
            targets = [cmd[-1] for cmd in boots]
            self.assertIn(main, targets)
            self.assertIn(update, targets)
            self.assertLess(targets.index(main), targets.index(update))

    def test_fresh_install_leaves_loaded_updater_alone(self):
        # Same fresh install but the updater already loaded: no updater
        # bootout/bootstrap churn, only the main service bootstrap.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            _, calls, _, _ = _install(self, tmp, home, '1.0.0', in_sync=True)
            agents = Path(tmp) / 'fakehome' / 'Library' / 'LaunchAgents'
            main = str(agents / (install_mod.LABEL + '.plist'))
            update = str(agents / (install_mod.UPDATE_LABEL + '.plist'))
            self.assertFalse(any(cmd[:2] == ['launchctl', 'bootout']
                                 and cmd[-1].endswith('.update') for cmd in calls),
                             'loaded updater must not be booted out')
            boots = [cmd for cmd in calls if cmd[:2] == ['launchctl', 'bootstrap']]
            targets = [cmd[-1] for cmd in boots]
            self.assertIn(main, targets)
            self.assertNotIn(update, targets)

    def test_setup_mode_installs_without_key_and_opens_window(self):
        import time as _time
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            blob, latest = _craft_bundle('1.0.0')
            opened = []

            class FakeBrowser:
                def open(self, url):
                    opened.append(url)
                    return True

            _patch_attrs(self, run=lambda cmd, **kwargs: _ok_run(cmd, **kwargs),
                         self_test=lambda *args: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *args, **kwargs: True,
                         webbrowser=FakeBrowser())
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home), '--setup'])
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'PATH': '/usr/bin:/bin'}
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(
                    install_mod.do_install(args, _fetch=_static_fetch(latest, blob)), 0)
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.assertIn('setup', state)
            self.assertGreater(state['setup']['expires'], int(_time.time()))
            self.assertEqual(len(opened), 1)
            self.assertIn(f"/setup/{state['setup']['nonce']}", opened[0])
            config = Path(env['HOME']) / '.codex' / 'config.toml'
            self.assertIn('# BEGIN local mixed model picker', config.read_text())

    def test_setup_mode_with_key_still_opens_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            blob, latest = _craft_bundle('1.0.0')
            opened = []

            class FakeBrowser:
                def open(self, url):
                    opened.append(url)
                    return True

            _patch_attrs(self, run=lambda cmd, **kwargs: _ok_run(cmd, **kwargs),
                         self_test=lambda *args: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *args, **kwargs: True,
                         webbrowser=FakeBrowser())
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home), '--setup'])
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'PATH': '/usr/bin:/bin',
                   'OPENROUTER_API_KEY': 'test-key'}
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(
                    install_mod.do_install(args, _fetch=_static_fetch(latest, blob)), 0)
            self.assertEqual(len(opened), 1)

    def test_no_setup_without_key_still_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            blob, latest = _craft_bundle('1.0.0')
            _patch_attrs(self, run=lambda cmd, **kwargs: _ok_run(cmd, **kwargs),
                         self_test=lambda *args: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *args, **kwargs: True)
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'PATH': '/usr/bin:/bin'}
            with mock.patch.dict(os.environ, env, clear=True):
                with self.assertRaises(SystemExit) as ctx:
                    install_mod.do_install(args, _fetch=_static_fetch(latest, blob))
            self.assertEqual(ctx.exception.code, 3)

    def test_channel_feed_prefers_pinned_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'channel').write_text('beta\n')
            (home / 'feed').write_text('file:///pinned.json\n')
            self.assertEqual(install_mod.channel_feed(home),
                             'file:///pinned.json')

    def test_check_update_reinvoke_does_not_pin_channel_feed(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            (home / 'mixed-router-state.json').write_text(
                json.dumps({'port': 1, 'token': 'x'}) + '\n')
            rel = home / 'releases' / '1.0.0'
            (rel / 'packaging').mkdir(parents=True)
            (rel / 'packaging' / 'VERSION').write_text('1.0.0\n')
            os.symlink(str(rel), home / 'current')
            manifest = {'version': '1.0.1', 'files': {}}
            manifest['files']['packaging/install.py'] = \
                hashlib.sha256(b'# updater re-invoke target').hexdigest()
            manifest['files']['packaging/VERSION'] = \
                hashlib.sha256(b'1.0.1\n').hexdigest()
            blob = _tarball(files=[
                ('MANIFEST.json', json.dumps(manifest)),
                ('packaging/install.py', '# updater re-invoke target'),
                ('packaging/VERSION', '1.0.1\n')])
            latest = {'version': '1.0.1', 'url': 'file:///bundle.tar.gz',
                      'sha256': None, 'min_python': '3.14'}
            seen = []

            def fake_run(cmd, **kwargs):
                seen.append(list(cmd))
                return _ok_run(cmd, **kwargs)

            _patch_attrs(self, run=fake_run)
            args = install_mod.build_parser().parse_args(['--home', str(home)])
            buf = io.StringIO()
            with mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': 'k'}):
                with contextlib.redirect_stdout(buf):
                    rc = install_mod.do_check_update(
                        args, _fetch=_static_fetch(latest, blob),
                        _read_feed=lambda feed, etag: (
                            200, json.dumps(latest).encode(), None),
                        _sleep=lambda s: None)
            self.assertEqual(rc, 0)
            invoked = [cmd for cmd in seen if cmd[-2:] == ['--home', str(home)]]
            self.assertTrue(invoked, 'updater must re-invoke with the custom home')
            for cmd in invoked:
                self.assertNotIn('--feed', cmd)
            self.assertFalse((home / 'feed').exists())


if __name__ == '__main__':
    unittest.main()
