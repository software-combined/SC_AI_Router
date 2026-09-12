"""First-run key window reachability (Plan 149).

A fresh install opens the native key window whenever the installed service
has no service-visible key; environment variables never count as service
configuration, and update runs mint the boot nonce without ever opening a
dialog. No network, no real install.
"""
import contextlib
import io
import json
import os
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._platform import unix_only
from tests.install_fixtures import (
    _craft_bundle,
    _ok_run,
    _patch_attrs,
    _static_fetch,
    install_mod,
)
from tests.test_install_config import _fake_write_catalogue


@unix_only
class InstallKeyWindowTests(unittest.TestCase):
    def test_fresh_install_without_key_arms_the_window_and_proceeds(self):
        # The native key window is the first-run flow: with no key anywhere
        # the install mints the nonce, passes health and spawns the popup
        # instead of stopping with the paste-and-re-run instruction.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            blob, latest = _craft_bundle('1.0.0')
            spawned = []

            class FakePopen:
                def __init__(self, cmd, **kwargs):
                    spawned.append(cmd)

            _patch_attrs(self, run=lambda cmd, **kwargs: _ok_run(cmd, **kwargs),
                         self_test=lambda *args: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *args, **kwargs: True)
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'PATH': '/usr/bin:/bin'}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(install_mod.subprocess, 'Popen', FakePopen):
                self.assertEqual(
                    install_mod.do_install(args, _fetch=_static_fetch(latest, blob)), 0)
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.assertIn('setup', state)
            self.assertEqual(len(spawned), 1)
            self.assertEqual(spawned[0][1:3], ['-m', 'ai_router.key_prompt'])
            self.assertIn(f"/setup/{state['setup']['nonce']}", spawned[0][3])

    def test_env_only_key_arms_the_window_and_names_the_var(self):
        # A shell-exported key never reaches the installed service, whose
        # environment carries only ROUTER_HOME: the install prints one
        # non-secret notice, mints the nonce and spawns the popup while the
        # service environment still carries only ROUTER_HOME.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            blob, latest = _craft_bundle('1.0.0')
            spawned = []

            class FakePopen:
                def __init__(self, cmd, **kwargs):
                    spawned.append(cmd)

            _patch_attrs(self, run=lambda cmd, **kwargs: _ok_run(cmd, **kwargs),
                         self_test=lambda *args: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *args, **kwargs: True)
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'PATH': '/usr/bin:/bin',
                   'OPENROUTER_API_KEY': 'test-key'}
            out = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(install_mod.subprocess, 'Popen', FakePopen), \
                    mock.patch.object(install_mod.sys, 'stdout', out):
                self.assertEqual(
                    install_mod.do_install(args, _fetch=_static_fetch(latest, blob)), 0)
            self.assertIn('OPENROUTER_API_KEY', out.getvalue())
            self.assertNotIn('test-key', out.getvalue())
            plist = (Path(env['HOME']) / 'Library' / 'LaunchAgents' /
                     (install_mod.LABEL + '.plist'))
            self.assertEqual(
                plistlib.loads(plist.read_bytes())['EnvironmentVariables'],
                {'ROUTER_HOME': str(home)})
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.assertIn('setup', state)
            self.assertEqual(len(spawned), 1)

    def test_present_key_file_arms_nothing(self):
        # A configured key file needs no window: no nonce, no popup.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir(parents=True)
            key_file = home / 'openrouter.key'
            key_file.write_text('sk-file\n')
            os.chmod(key_file, 0o600)
            blob, latest = _craft_bundle('1.0.0')
            spawned = []

            class FakePopen:
                def __init__(self, cmd, **kwargs):
                    spawned.append(cmd)

            _patch_attrs(self, run=lambda cmd, **kwargs: _ok_run(cmd, **kwargs),
                         self_test=lambda *args: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *args, **kwargs: True)
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'PATH': '/usr/bin:/bin'}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(install_mod.subprocess, 'Popen', FakePopen):
                self.assertEqual(
                    install_mod.do_install(args, _fetch=_static_fetch(latest, blob)), 0)
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.assertNotIn('setup', state)
            self.assertEqual(spawned, [])

    def test_widened_key_file_refuses_before_install(self):
        # A non-blank key file that fails the owner-only check refuses with
        # the file and the required permission; it never arms a window.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir(parents=True)
            key_file = home / 'openrouter.key'
            key_file.write_text('sk-wide\n')
            os.chmod(key_file, 0o644)
            blob, latest = _craft_bundle('1.0.0')
            _patch_attrs(self, run=lambda cmd, **kwargs: _ok_run(cmd, **kwargs),
                         self_test=lambda *args: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *args, **kwargs: True)
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'PATH': '/usr/bin:/bin'}
            with mock.patch.dict(os.environ, env, clear=True):
                with self.assertRaisesRegex(SystemExit, 'openrouter.key'):
                    install_mod.do_install(args, _fetch=_static_fetch(latest, blob))
            # A shell-exported key is never treated as installed-service
            # configuration, so it cannot excuse a widened file either.
            env = dict(env, OPENROUTER_API_KEY='sk-env')
            with mock.patch.dict(os.environ, env, clear=True):
                with self.assertRaisesRegex(SystemExit, 'openrouter.key'):
                    install_mod.do_install(args, _fetch=_static_fetch(latest, blob))
            self.assertFalse((home / 'current').exists())

    def test_setup_rearms_on_an_up_to_date_home(self):
        # The documented "no window appeared" recovery must work after a
        # successful install: --setup reinstalls the current release so the
        # service restarts with a fresh nonce and the window opens. A plain
        # re-run stays "up to date" and mints nothing new.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            blob, latest = _craft_bundle('1.0.0')
            _patch_attrs(self, run=lambda cmd, **kwargs: _ok_run(cmd, **kwargs),
                         self_test=lambda *args: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *args, **kwargs: True)
            base = ['--feed', 'file:///latest.json', '--home', str(home)]
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'PATH': '/usr/bin:/bin'}
            spawned = []

            class FakePopen:
                def __init__(self, cmd, **kwargs):
                    spawned.append(cmd)

            def state():
                return json.loads((home / 'mixed-router-state.json').read_text())

            with mock.patch.dict(os.environ, dict(env, ROUTER_NO_KEY_WINDOW='1'),
                                 clear=True), \
                    mock.patch.object(install_mod.subprocess, 'Popen', FakePopen):
                self.assertEqual(install_mod.do_install(
                    install_mod.build_parser().parse_args(base),
                    _fetch=_static_fetch(latest, blob)), 0)
                first = state()['setup']['nonce']
                sentinel = home / 'releases' / '1.0.0' / 'sentinel.txt'
                sentinel.write_text('keep\n')
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(install_mod.do_install(
                        install_mod.build_parser().parse_args(base),
                        _fetch=_static_fetch(latest, blob)), 0)
                self.assertIn('up to date', out.getvalue())
                self.assertEqual(state()['setup']['nonce'], first)
                self.assertEqual(spawned, [])
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(install_mod.subprocess, 'Popen', FakePopen):
                self.assertEqual(install_mod.do_install(
                    install_mod.build_parser().parse_args(base + ['--setup']),
                    _fetch=_static_fetch(latest, blob)), 0)
            self.assertNotEqual(state()['setup']['nonce'], first)
            self.assertEqual(len(spawned), 1)
            self.assertEqual(spawned[0][1:3], ['-m', 'ai_router.key_prompt'])
            # The repair restarts the service; it never re-extracts the live
            # release, so anything inside it survives.
            self.assertEqual(sentinel.read_text(), 'keep\n')

    def test_repair_restart_failure_leaves_the_release_intact(self):
        # A failed repair reload must not touch the installed release or the
        # current pointer, and must report failure instead of a fake success.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            blob, latest = _craft_bundle('1.0.0')
            _patch_attrs(self, run=lambda cmd, **kwargs: _ok_run(cmd, **kwargs),
                         self_test=lambda *args: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *args, **kwargs: True)
            base = ['--feed', 'file:///latest.json', '--home', str(home)]
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'PATH': '/usr/bin:/bin',
                   'ROUTER_NO_KEY_WINDOW': '1'}
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(install_mod.do_install(
                    install_mod.build_parser().parse_args(base),
                    _fetch=_static_fetch(latest, blob)), 0)
            sentinel = home / 'releases' / '1.0.0' / 'sentinel.txt'
            sentinel.write_text('keep\n')
            real = install_mod.platform_backend()

            class FailingBackend:
                def __getattr__(self, name):
                    return getattr(real, name)

                def install(self, *args, **kwargs):
                    raise SystemExit('task registration refused')

            _patch_attrs(self, platform_backend=lambda: FailingBackend())
            out = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=True), \
                    contextlib.redirect_stdout(out):
                self.assertEqual(install_mod.do_install(
                    install_mod.build_parser().parse_args(base + ['--setup']),
                    _fetch=_static_fetch(latest, blob)), 1)
            self.assertIn('service restart failed', out.getvalue())
            self.assertEqual(sentinel.read_text(), 'keep\n')
            self.assertEqual((home / 'current').read_text().strip(), '1.0.0')

    def test_setup_repairs_when_the_feed_lags_the_install(self):
        # Channel rollback: the feed can be older than the installed release.
        # --setup must still repair (restart + fresh nonce) and never
        # downgrade to the feed's version.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            blob, latest = _craft_bundle('1.0.1')
            _patch_attrs(self, run=lambda cmd, **kwargs: _ok_run(cmd, **kwargs),
                         self_test=lambda *args: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *args, **kwargs: True)
            base = ['--feed', 'file:///latest.json', '--home', str(home)]
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'PATH': '/usr/bin:/bin'}
            with mock.patch.dict(os.environ, dict(env, ROUTER_NO_KEY_WINDOW='1'),
                                 clear=True):
                self.assertEqual(install_mod.do_install(
                    install_mod.build_parser().parse_args(base),
                    _fetch=_static_fetch(latest, blob)), 0)
            first = json.loads(
                (home / 'mixed-router-state.json').read_text())['setup']['nonce']
            sentinel = home / 'releases' / '1.0.1' / 'sentinel.txt'
            sentinel.write_text('keep\n')
            old_blob, old_latest = _craft_bundle('1.0.0')
            spawned = []

            class FakePopen:
                def __init__(self, cmd, **kwargs):
                    spawned.append(cmd)

            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(install_mod.subprocess, 'Popen', FakePopen):
                self.assertEqual(install_mod.do_install(
                    install_mod.build_parser().parse_args(base + ['--setup']),
                    _fetch=_static_fetch(old_latest, old_blob)), 0)
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.assertEqual((home / 'current').read_text().strip(), '1.0.1')
            self.assertEqual(sentinel.read_text(), 'keep\n')
            self.assertNotEqual(state['setup']['nonce'], first)
            self.assertEqual(len(spawned), 1)

    def test_key_window_opt_out_mints_the_nonce_without_a_dialog(self):
        # ROUTER_NO_KEY_WINDOW=1 suppresses only the dialog: the nonce is
        # still minted so a keyless service can boot.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            blob, latest = _craft_bundle('1.0.0')
            spawned = []

            class FakePopen:
                def __init__(self, cmd, **kwargs):
                    spawned.append(cmd)

            _patch_attrs(self, run=lambda cmd, **kwargs: _ok_run(cmd, **kwargs),
                         self_test=lambda *args: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *args, **kwargs: True)
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'PATH': '/usr/bin:/bin',
                   'ROUTER_NO_KEY_WINDOW': '1'}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(install_mod.subprocess, 'Popen', FakePopen):
                self.assertEqual(
                    install_mod.do_install(args, _fetch=_static_fetch(latest, blob)), 0)
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.assertIn('setup', state)
            self.assertEqual(spawned, [])

    def test_popup_spawn_failure_prints_no_url_off_a_tty(self):
        # The setup URL carries the per-install path token: when the popup
        # cannot spawn and stdout is not a TTY, only a token-free line is
        # printed.
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

            def no_dialog(*args, **kwargs):
                raise OSError('no dialog tool')

            out = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(install_mod.subprocess, 'Popen', no_dialog), \
                    contextlib.redirect_stdout(out):
                self.assertEqual(
                    install_mod.do_install(args, _fetch=_static_fetch(latest, blob)), 0)
            self.assertNotIn('/setup/', out.getvalue())
            self.assertIn('could not open the key window', out.getvalue())


@unix_only
class UpdateKeyWindowTests(unittest.TestCase):
    def test_update_child_carries_the_key_window_opt_out(self):
        # Scheduled and manual update runs never pop the first-run key
        # window: the installer child inherits ROUTER_NO_KEY_WINDOW=1.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir(parents=True)
            (home / 'mixed-router-state.json').write_text(
                json.dumps({'port': 1, 'token': 'x'}))
            blob, latest = _craft_bundle('9.9.9')
            seen = {}

            def fake_run(cmd, **kwargs):
                seen['env'] = dict(kwargs.get('env') or {})
                seen['cmd'] = list(cmd)
                return _ok_run(cmd, **kwargs)

            _patch_attrs(self, run=fake_run)
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            with contextlib.redirect_stdout(io.StringIO()):
                install_mod.do_update(
                    args, _fetch=lambda url: blob,
                    _read_feed=lambda feed, etag: (
                        200, json.dumps(latest).encode(), None),
                    _sleep=lambda s: None)
            child = [c for c in [seen.get('cmd', [])] if '--home' in c]
            self.assertTrue(child, 'the check must reach the child installer')
            self.assertEqual(seen['env'].get('ROUTER_NO_KEY_WINDOW'), '1')

    def test_update_on_a_keyless_home_mints_the_nonce_without_a_dialog(self):
        # An update that lands on a home with no service-visible key
        # installs, mints the setup nonce and opens no dialog; the next
        # request opens the window through the request path.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir(parents=True)
            (home / 'mixed-router-state.json').write_text(
                json.dumps({'port': 1, 'token': 'x'}))
            blob, latest = _craft_bundle('9.9.9')
            _patch_attrs(self, run=lambda cmd, **kwargs: _ok_run(cmd, **kwargs),
                         self_test=lambda *a: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *a, **k: {'status': 'ok'})
            # Run the extracted child installer in-process with the opt-out
            # the updater sets, as the spawned child would inherit it.
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'PATH': '/usr/bin:/bin',
                   'ROUTER_NO_KEY_WINDOW': '1'}
            spawned = []
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(install_mod.subprocess, 'Popen',
                                      lambda *a, **k: spawned.append(a)), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    install_mod.do_install(args, _fetch=_static_fetch(latest, blob)), 0)
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.assertIn('setup', state)
            self.assertEqual(spawned, [])


if __name__ == '__main__':
    unittest.main()
