"""Plan 057 Stage 2: Windows key ACL hardening, proven offline.

Write-side protect_file restricts parent-first then verifies; read-side
winacl.check refuses widened ACLs mirroring the POSIX gate. Fake icacls
and whoami only; no Windows machine, no real ACL, no secrets.
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _load_winacl():
    spec = importlib.util.spec_from_file_location(
        'router_winacl_under_test', ROOT / 'ai_router' / 'winacl.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_backend():
    spec = importlib.util.spec_from_file_location(
        'router_windows_backend_under_test',
        ROOT / 'packaging' / 'platforms' / 'windows.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


winacl = _load_winacl()
backend = _load_backend()


def _ok(cmd_responses):
    def fake_run(cmd, **kwargs):
        for prefix, result in cmd_responses:
            if cmd[:len(prefix)] == prefix:
                return result
        raise AssertionError('unexpected command: %r' % (cmd,))
    return fake_run


def _ok_acl(user='CORP\\cyril'):
    return SimpleNamespace(returncode=0, stdout=user + '\n', stderr='')


OWNER_ONLY = ('C:\\keys\\openrouter.key\n'
              '   CORP\\cyril:(F)\n'
              'Successfully processed 1 files; Failed processing 0 files\n')
WIDENED = ('C:\\keys\\openrouter.key\n'
           '   BUILTIN\\Users:(R)\n'
           '   CORP\\cyril:(F)\n'
           'Successfully processed 1 files; Failed processing 0 files\n')


class WinAclCheckTests(unittest.TestCase):
    def test_owner_only_acl_passes(self):
        run = _ok([(['icacls'], SimpleNamespace(returncode=0, stdout=OWNER_ONLY, stderr='')),
                   (['whoami'], _ok_acl())])
        winacl.check('C:\\keys\\openrouter.key', run=run)

    def test_widened_acl_is_refused(self):
        run = _ok([(['icacls'], SimpleNamespace(returncode=0, stdout=WIDENED, stderr='')),
                   (['whoami'], _ok_acl())])
        with self.assertRaisesRegex(SystemExit, 'readable by'):
            winacl.check('C:\\keys\\openrouter.key', run=run)

    def test_same_line_ace_granting_non_owner_is_refused(self):
        # Real icacls prints the first ACE on the filename line itself; a
        # path-prefix skip would discard it and pass vacuously.
        same_line = ('C:\\keys\\openrouter.key BUILTIN\\Users:(R)\n'
                     '   CORP\\cyril:(F)\n'
                     'Successfully processed 1 files; Failed processing 0 files\n')
        run = _ok([(['icacls'], SimpleNamespace(returncode=0, stdout=same_line, stderr='')),
                   (['whoami'], _ok_acl())])
        with self.assertRaisesRegex(SystemExit, 'readable by'):
            winacl.check('C:\\keys\\openrouter.key', run=run)

    def test_same_name_cross_domain_ace_is_refused(self):
        # A bare-name suffix rule would accept OTHERDOMAIN\\cyril for a
        # CORP\\cyril owner; only the full whoami identity passes.
        cross = ('C:\\keys\\openrouter.key\n'
                 '   OTHERDOMAIN\\cyril:(F)\n'
                 '   CORP\\cyril:(F)\n'
                 'Successfully processed 1 files; Failed processing 0 files\n')
        run = _ok([(['icacls'], SimpleNamespace(returncode=0, stdout=cross, stderr='')),
                   (['whoami'], _ok_acl())])
        with self.assertRaisesRegex(SystemExit, 'readable by'):
            winacl.check('C:\\keys\\openrouter.key', run=run)

    def test_os_aces_pass_but_broad_groups_are_refused(self):
        # Default profiles/temp dirs inherit OS ACEs; like root with POSIX
        # 0600, SYSTEM/Administrators can read everything already, and OWNER
        # RIGHTS (S-1-3-4) grants only the object's current owner, so none
        # of them is exposure. Broad pseudo-groups still refuse.
        owned = ('C:\\keys\\openrouter.key NT AUTHORITY\\SYSTEM:(F)\n'
                 '   BUILTIN\\Administrators:(F)\n'
                 '   OWNER RIGHTS:(F)\n'
                 '   CORP\\cyril:(F)\n'
                 'Successfully processed 1 files; Failed processing 0 files\n')
        run = _ok([(['icacls'], SimpleNamespace(returncode=0, stdout=owned, stderr='')),
                   (['whoami'], _ok_acl())])
        winacl.check('C:\\keys\\openrouter.key', run=run)
        wide = ('C:\\keys\\openrouter.key\n'
                '   NT AUTHORITY\\Authenticated Users:(R)\n'
                '   CORP\\cyril:(F)\n'
                'Successfully processed 1 files; Failed processing 0 files\n')
        run = _ok([(['icacls'], SimpleNamespace(returncode=0, stdout=wide, stderr='')),
                   (['whoami'], _ok_acl())])
        with self.assertRaisesRegex(SystemExit, 'readable by'):
            winacl.check('C:\\keys\\openrouter.key', run=run)

    def test_icacls_failure_is_refused(self):
        run = _ok([(['icacls'], SimpleNamespace(returncode=1, stdout='', stderr='Access denied'))])
        with self.assertRaisesRegex(SystemExit, 'cannot verify'):
            winacl.check('C:\\keys\\openrouter.key', run=run)


class WinProtectTests(unittest.TestCase):
    def test_protect_restricts_parent_first_then_verifies(self):
        order = []
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'sub' / 'openrouter.key'

            def fake_run(cmd, **kwargs):
                order.append(list(cmd))
                if cmd[:1] == ['icacls'] and len(cmd) > 2 and cmd[2].startswith('/inheritance'):
                    return SimpleNamespace(returncode=0, stdout='', stderr='')
                if cmd[:1] == ['icacls']:
                    queried = cmd[1]
                    return SimpleNamespace(
                        returncode=0,
                        stdout='%s\n   CORP\\cyril:(F)\n'
                               'Successfully processed 1 files; Failed processing 0 files\n'
                               % queried,
                        stderr='')
                if cmd[:1] == ['whoami']:
                    return _ok_acl()
                raise AssertionError('unexpected command: %r' % (cmd,))

            backend.protect_file(target, run=fake_run)
            grants = [c for c in order if c[:1] == ['icacls'] and '/grant:r' in c]
            self.assertEqual(len(grants), 2)
            # Parent restricted before the file grant: never widen-then-narrow.
            self.assertIn('sub', grants[0][1])
            self.assertTrue(target.exists())

    def test_grants_name_the_resolved_user_never_a_literal(self):
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'openrouter.key'

            def fake_run(cmd, **kwargs):
                seen.append(list(cmd))
                if cmd[:1] == ['icacls'] and '/grant:r' in cmd:
                    return SimpleNamespace(returncode=0, stdout='', stderr='')
                if cmd[:1] == ['icacls']:
                    return SimpleNamespace(
                        returncode=0,
                        stdout='%s\n   testuser:(F)\nSuccessfully processed 1 files\n' % cmd[1],
                        stderr='')
                if cmd[:1] == ['whoami']:
                    return SimpleNamespace(returncode=0, stdout='testuser\n', stderr='')
                raise AssertionError('unexpected command: %r' % (cmd,))

            with mock.patch.dict(os.environ, {'USERNAME': 'testuser'}):
                backend.protect_file(target, run=fake_run)
            grants = [c for c in seen if '/grant:r' in c]
            self.assertEqual(len(grants), 2)
            # Parent: inheritable owner-only grant, so files the router
            # writes beside the key later are born owner-only. File: plain.
            self.assertEqual(grants[0][grants[0].index('/grant:r') + 1],
                             'testuser:(OI)(CI)F')
            self.assertEqual(grants[1][grants[1].index('/grant:r') + 1],
                             'testuser:F')

    def test_protect_failure_leaves_no_silent_exposure(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'openrouter.key'
            run = _ok([(['icacls'], SimpleNamespace(returncode=1, stdout='', stderr='denied')),
                       (['whoami'], _ok_acl())])
            with self.assertRaisesRegex(SystemExit, 'cannot restrict|cannot protect'):
                backend.protect_file(target, run=run)


class WinBackendShapeTests(unittest.TestCase):
    # Lifecycle shape (install/restart/stop/uninstall task control) moved to
    # tests/test_windows_backend.py with the Stage 3 implementation; only
    # the failure-path pins that have no counterpart there stay here.
    def test_uninstall_failure_names_the_surviving_task(self):
        def fake_run(cmd, **kwargs):
            if 'CodexMixedModelRouterUpdate' in cmd:
                return SimpleNamespace(returncode=1, stdout='', stderr='not found')
            return SimpleNamespace(returncode=0, stdout='', stderr='')

        with self.assertRaisesRegex(SystemExit, 'CodexMixedModelRouterUpdate'):
            backend.Backend(None, fake_run).uninstall('/home/x')

    def test_failed_state_protection_keeps_a_pre_existing_token(self):
        # Gap 0 (PR 55 review): a failed state-file ACL check unlinks only
        # a file this run minted, never a pre-existing live token.
        from tests.test_install import _craft_bundle, _static_fetch, install_mod
        from tests.test_install_lifecycle import _patch_attrs, _recording
        from tests.test_install_config import _fake_write_catalogue
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            blob, latest = _craft_bundle('1.0.0')

            class FailingBackend:
                def protect_secret(self, path):
                    if Path(path).name == 'mixed-router-state.json':
                        raise SystemExit('cannot protect state')
                def check(self, home):
                    pass

            _patch_attrs(self, run=_recording([]),
                         self_test=lambda *a: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *a, **k: True)
            home.mkdir(parents=True)
            live = home / 'mixed-router-state.json'
            live.write_text('{"port": 1, "token": "live"}')
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'k'}
            with mock.patch.dict(os.environ, env), mock.patch.object(
                    install_mod, 'platform_backend', return_value=FailingBackend()):
                with self.assertRaisesRegex(SystemExit, 'cannot protect state'):
                    install_mod.do_install(args, _fetch=_static_fetch(latest, blob))
            self.assertEqual(json.loads(live.read_text())['token'], 'live')

    def test_failed_protection_removes_the_placeholder(self):
        # A failed protect_secret must not leave an unprotected placeholder
        # that the next run's exists-early-return would trust.
        from tests.test_install import install_mod
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            calls = []

            class StubBackend:
                def protect_secret(self, path):
                    calls.append(path)
                    raise SystemExit('cannot protect')

            with mock.patch.object(install_mod, 'platform_backend',
                                    return_value=StubBackend()):
                with self.assertRaisesRegex(SystemExit, 'cannot protect'):
                    install_mod.ensure_credentials(home, {})
            self.assertFalse((home / 'openrouter.key').exists())
            self.assertEqual(len(calls), 1)

    def test_protecting_the_home_hardens_it_in_place(self):
        # Given the router home itself: one inheritable owner-only grant on
        # the directory, verified, nothing created inside it.
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            def fake_run(cmd, **kwargs):
                seen.append(list(cmd))
                if cmd[:1] == ['icacls'] and '/grant:r' in cmd:
                    return SimpleNamespace(returncode=0, stdout='', stderr='')
                if cmd[:1] == ['icacls']:
                    return SimpleNamespace(
                        returncode=0,
                        stdout='%s CORP\\cyril:(OI)(CI)(F)\nSuccessfully processed 1 files\n' % cmd[1],
                        stderr='')
                return _ok_acl()
            backend.protect_file(tmp, run=fake_run)
        grants = [c for c in seen if '/grant:r' in c]
        self.assertEqual([(c[1], c[c.index('/grant:r') + 1]) for c in grants],
                         [(tmp, 'CORP\\cyril:(OI)(CI)F')])
        self.assertEqual(len(seen), 4)  # whoami, grant, verify (icacls + whoami)

    def test_install_hardens_the_home_before_minting_the_state_file(self):
        # The state file carries the loopback token: it must be born inside
        # an already-restricted home, then verified, before the backend runs.
        from tests.test_install import _craft_bundle, _ok_run, _patch_attrs, install_mod
        blob, latest = _craft_bundle('1.0.0')
        events = []

        class StubBackend:
            def protect_secret(self, path):
                events.append(('protect', Path(path).name,
                               (Path(path) / 'mixed-router-state.json').exists()
                               if Path(path).is_dir() else None))

            def check(self, home):
                pass

            def install(self, *args):
                events.append(('install',))

            def start_updates(self, home):
                pass

            def pinned_release(self, home):
                return None

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            fetch = lambda url: blob if url.endswith('.tar.gz') else json.dumps(latest).encode()  # noqa: E731
            _patch_attrs(self, run=_ok_run, wait_version=lambda s, v: {'version': v},
                         self_test=lambda *a: None, write_catalogue=lambda *a: None)
            args = install_mod.build_parser().parse_args(
                ['--home', str(home), '--client', 'none'])
            with mock.patch.object(install_mod, 'platform_backend', return_value=StubBackend()), \
                    mock.patch.object(install_mod, 'find_python', return_value=sys.executable), \
                    mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': 'env-key-for-test'}):
                self.assertEqual(install_mod.do_install(args, _fetch=fetch), 0)
        self.assertEqual(events, [('protect', 'home', False),
                                  ('protect', 'mixed-router-state.json', None),
                                  ('install',)])



if __name__ == '__main__':
    unittest.main()
