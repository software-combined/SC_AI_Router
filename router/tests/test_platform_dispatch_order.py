"""Plan 056 Stage 1: characterisation of service-call order per platform.

These tests pin today's observable behavior of do_install / do_uninstall on
launchd and systemd at the level of which service calls happen in which
order. A refactor that reorders or drops a call must fail here. They do not
assert new behavior.
"""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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


def _ordered(calls):
    """Short readable signature per recorded command."""
    sigs = []
    for cmd in calls:
        if cmd[:1] == ['launchctl']:
            sigs.append('launchctl:' + cmd[1])
        elif cmd[:2] == ['systemctl', '--user']:
            sigs.append('systemctl:' + cmd[2])
        elif cmd[:1] == ['brew']:
            sigs.append('brew')
    return sigs


def _run_install_ordered(test, tmp, home, version, platform):
    blob, latest = _craft_bundle(version)
    calls = []
    previous = install_mod.PLATFORM
    install_mod.PLATFORM = platform
    test.addCleanup(setattr, install_mod, 'PLATFORM', previous)

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return _ok_run(cmd, **kwargs)

    _patch_attrs(test, run=fake_run, self_test=lambda *args: None,
                 write_catalogue=_fake_write_catalogue,
                 wait_version=lambda *args, **kwargs: {'status': 'ok'})
    args = install_mod.build_parser().parse_args(
        ['--feed', 'file:///latest.json', '--home', str(home)])
    env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'k',
           'ROUTER_NO_KEY_WINDOW': '1'}
    with mock.patch.dict(os.environ, env):
        with contextlib.redirect_stdout(io.StringIO()):
            rc = install_mod.do_install(args, _fetch=_static_fetch(latest, blob),
                                        _run=fake_run)
    test.assertEqual(rc, 0)
    return calls


@unix_only
class DispatchOrderTests(unittest.TestCase):
    def test_launchd_fresh_install_bootstraps_router_before_updater(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            calls = _run_install_ordered(self, tmp, home, '1.0.0', 'darwin')
            boots = [c[-1].rsplit('/', 1)[-1].replace('.plist', '')
                     for c in calls if c[:2] == ['launchctl', 'bootstrap']]
            self.assertIn(install_mod.LABEL, boots)
            self.assertIn(install_mod.UPDATE_LABEL, boots)
            self.assertLess(boots.index(install_mod.LABEL),
                            boots.index(install_mod.UPDATE_LABEL),
                            'router bootstrap must precede updater bootstrap')

    def test_launchd_uninstall_restores_config_then_boots_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            _run_install_ordered(self, tmp, home, '1.0.0', 'darwin')
            calls = []
            previous = install_mod.PLATFORM
            install_mod.PLATFORM = 'darwin'
            self.addCleanup(setattr, install_mod, 'PLATFORM', previous)

            def fake_run(cmd, **kwargs):
                calls.append(list(cmd))
                if cmd[-1: ] == ['disable.py'] or (len(cmd) > 1 and Path(cmd[1]).name == 'disable.py'):
                    return SimpleNamespace(
                        returncode=0,
                        stdout='OpenAI direct routing restored. Restart Codex.\n',
                        stderr='')
                return _ok_run(cmd, **kwargs)

            _patch_attrs(self, run=fake_run)
            args = install_mod.build_parser().parse_args(['--home', str(home)])
            with mock.patch.dict(os.environ, {'HOME': str(Path(tmp) / 'fakehome')}):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(install_mod.do_uninstall(args), 0)
            kinds = ['restore' if (len(c) > 1 and Path(c[1]).name == 'disable.py') else
                     ('bootout:' + c[2].rsplit('/', 1)[-1] if c[:2] == ['launchctl', 'bootout'] else None)
                     for c in calls]
            kinds = [k for k in kinds if k]
            self.assertIn('restore', kinds)
            self.assertLess(kinds.index('restore'), kinds.index('bootout:' + install_mod.LABEL))

    def test_systemd_install_writes_units_then_reloads_and_restarts(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            env_home = Path(tmp) / 'xdg'
            calls = []
            previous = install_mod.PLATFORM
            install_mod.PLATFORM = 'linux'
            self.addCleanup(setattr, install_mod, 'PLATFORM', previous)

            def fake_run(cmd, **kwargs):
                calls.append(list(cmd))
                return _ok_run(cmd, **kwargs)

            # systemd writes real unit files under XDG_CONFIG_HOME; isolate it.
            blob, latest = _craft_bundle('1.0.0')
            _patch_attrs(self, run=fake_run, self_test=lambda *args: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *args, **kwargs: {'status': 'ok'})
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            env = {'HOME': str(Path(tmp) / 'fakehome'),
                   'XDG_CONFIG_HOME': str(env_home),
                   'OPENROUTER_API_KEY': 'k', 'ROUTER_NO_KEY_WINDOW': '1'}
            with mock.patch.dict(os.environ, env):
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = install_mod.do_install(args, _fetch=_static_fetch(latest, blob),
                                                _run=fake_run)
            self.assertEqual(rc, 0)
            sigs = _ordered(calls)
            self.assertIn('systemctl:daemon-reload', sigs)
            self.assertIn('systemctl:enable', sigs)
            self.assertIn('systemctl:restart', sigs)
            self.assertLess(sigs.index('systemctl:daemon-reload'), sigs.index('systemctl:restart'))
            self.assertLess(sigs.index('systemctl:enable'), sigs.index('systemctl:restart'))


if __name__ == '__main__':
    unittest.main()
