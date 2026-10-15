"""Windows key ACL contracts with synthetic structured API responses."""
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


def _load_service():
    spec = importlib.util.spec_from_file_location(
        'router_service_for_windows_acl', ROOT / 'packaging' / 'service.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


winacl = _load_winacl()
backend = _load_backend()
service = _load_service()


def _ok(cmd_responses):
    def fake_run(cmd, **kwargs):
        for prefix, result in cmd_responses:
            if cmd[:len(prefix)] == prefix:
                return result
        raise AssertionError('unexpected command: %r' % (cmd,))
    return fake_run


def _ok_acl(user='CORP\\cyril'):
    return SimpleNamespace(returncode=0, stdout=user + '\n', stderr='')


SID = 'S-1-5-21-1-2-3-1001'


def _rule(sid=SID, kind=0, mask=2032127, flags=0):
    return {'sid': sid, 'type': kind, 'mask': mask, 'flags': flags}


def _acl(rules=None, **extra):
    return dict(user=SID, owner=SID, dacl=True,
                rules=[_rule()] if rules is None else rules, **extra)


def _structured(doc, calls=None):
    def run(cmd, **kwargs):
        if calls is not None:
            calls.append((list(cmd), kwargs))
        if cmd[0] == 'whoami':
            return _ok_acl()  # Legacy scheduler identity is outside this slice.
        if cmd[0] == 'icacls' and '/grant:r' in cmd:
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        return SimpleNamespace(returncode=0, stdout=json.dumps(doc), stderr='')
    return run


class WinAclCheckTests(unittest.TestCase):
    def setUp(self):
        winacl.reset()  # verdicts are cached per file across calls

    def test_the_verdict_is_cached_for_a_short_interval(self):
        calls = []
        run = _structured(_acl(), calls)
        winacl.check('C:\\keys\\openrouter.key', run=run, _now=100.0)
        winacl.check('C:\\keys\\openrouter.key', run=run, _now=100.0 + 5)
        self.assertEqual(len(calls), 1, 'one structured query, then cached')
        winacl.check('C:\\keys\\openrouter.key', run=run,
                     _now=100.0 + winacl.VERDICT_TTL_S + 1)
        self.assertEqual(len(calls), 2, 'the cache expires and re-checks')

    def test_a_cached_refusal_is_raised_without_respawning(self):
        calls = []
        run = _structured(_acl([_rule('S-1-1-0')]), calls)
        with self.assertRaisesRegex(SystemExit, 'readable by'):
            winacl.check('C:\\keys\\openrouter.key', run=run, _now=200.0)
        with self.assertRaisesRegex(SystemExit, 'readable by'):
            winacl.check('C:\\keys\\openrouter.key', run=run, _now=200.0 + 1)
        self.assertEqual(len(calls), 1, 'the refusal is cached too')

    def test_sids_allow_equivalent_english_and_french_system_rules(self):
        for label, owner in (('NT AUTHORITY\\SYSTEM', SID), ('AUTORITE NT\\Système', SID),
                             ('SYSTEM', 'S-1-5-18'), ('Administrateurs', 'S-1-5-32-544')):
            rules = [_rule(), dict(_rule('S-1-5-18'), name=label),
                     _rule('S-1-5-32-544'), _rule('S-1-3-4'), _rule('S-1-1-0', kind=1)]
            winacl.check('C:\\keys\\openrouter.key', run=_structured(dict(_acl(rules), owner=owner)))

    def test_broad_or_foreign_grants_and_foreign_owner_are_refused(self):
        for sid in ('S-1-1-0', 'S-1-5-11', 'S-1-5-32-545', 'S-1-5-21-4-5-6-1001'):
            with self.subTest(sid=sid), self.assertRaisesRegex(SystemExit, 'readable by'):
                winacl.check('key', run=_structured(_acl([_rule(), _rule(sid)])))
        doc = _acl([_rule('S-1-3-4')])
        doc['owner'] = 'S-1-5-21-4-5-6-1001'
        with self.assertRaisesRegex(SystemExit, 'owner'):
            winacl.check('key', run=_structured(doc))

    def test_malformed_null_and_unknown_rules_fail_closed(self):
        invalid = [None, {}, dict(_acl(), dacl=False), dict(_acl(), rules=[]),
                   dict(_acl(), owner='CORP\\cyril'), dict(_acl(), user=''),
                   dict(_acl(), rules=[_rule(kind=9)]), dict(_acl(), rules=[_rule(mask='F')]),
                   dict(_acl(), rules=[_rule(flags=64)]), dict(_acl(), rules=[_rule(mask=True)]),
                   dict(_acl(), rules=[_rule(mask=512)]), dict(_acl(), user=SID.replace('-1-', '-01-', 1))]
        for doc in invalid:
            with self.subTest(doc=doc), self.assertRaisesRegex(SystemExit, 'cannot verify'):
                winacl.check('key', run=_structured(doc))

    def test_empty_or_failed_query_is_refused(self):
        for rc in (0, 1):
            run = lambda *a, **kw: SimpleNamespace(returncode=rc, stdout='', stderr='')
            with self.subTest(rc=rc), self.assertRaisesRegex(SystemExit, 'cannot verify'):
                winacl.check('key', run=run)

    def test_unreadable_or_timed_out_query_is_refused(self):
        for error in (OSError('unavailable'), winacl.subprocess.TimeoutExpired('powershell', 15)):
            with self.subTest(error=error), self.assertRaisesRegex(SystemExit, 'cannot verify'):
                winacl.check('key', run=mock.Mock(side_effect=error))

    def test_path_is_json_data_and_default_runner_is_windowless(self):
        path = "C:\\keys\\é [$value]'; (test) &.key"
        with mock.patch.object(winacl.subprocess, 'run', return_value=_structured(_acl())(['powershell'])) as run:
            winacl.check(path)
        command, options = run.call_args.args[0], run.call_args.kwargs
        self.assertNotIn(path, ' '.join(command))
        self.assertEqual(json.loads(options['input']), {'path': path})
        self.assertEqual(options['creationflags'], getattr(winacl.subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertGreater(options['timeout'], 0)


class WinProtectTests(unittest.TestCase):
    def test_protect_restricts_parent_first_then_verifies(self):
        order = []
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'sub' / 'openrouter.key'

            backend.protect_file(target, run=_structured(_acl(), order))
            grants = [c for c, _ in order if c[:1] == ['icacls'] and '/grant:r' in c]
            self.assertEqual(len(grants), 2)
            # Parent restricted before the file grant: never widen-then-narrow.
            self.assertIn('sub', grants[0][1])
            self.assertTrue(target.exists())

    def test_grants_use_the_current_sid_without_username_fallback(self):
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'openrouter.key'

            with mock.patch.dict(os.environ, {'USERNAME': 'testuser'}):
                backend.protect_file(target, run=_structured(_acl(), seen))
            grants = [c for c, _ in seen if '/grant:r' in c]
            self.assertEqual(len(grants), 2)
            # Parent: inheritable owner-only grant, so files the router
            # writes beside the key later are born owner-only. File: plain.
            self.assertEqual(grants[0][grants[0].index('/grant:r') + 1],
                             '*' + SID + ':(OI)(CI)F')
            self.assertEqual(grants[1][grants[1].index('/grant:r') + 1],
                             '*' + SID + ':F')
            refused = []
            with mock.patch.dict(os.environ, {'USERNAME': 'testuser'}), \
                    self.assertRaisesRegex(SystemExit, 'cannot verify'):
                backend.protect_file(target, run=_structured({'user': ''}, refused))
            self.assertFalse(any(command[0] == 'icacls' for command, _ in refused))

    def test_protect_rechecks_a_cached_pass_after_granting(self):
        doc = _acl()
        run = _structured(doc)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'key'
            backend._winacl.check(target, run=run)
            doc['rules'].append(_rule('S-1-1-0'))
            with self.assertRaisesRegex(SystemExit, 'readable by'):
                backend.protect_file(target, run=run)

    def test_protect_failure_leaves_no_silent_exposure(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'openrouter.key'
            run = _ok([(['icacls'], SimpleNamespace(returncode=1, stdout='', stderr='denied')),
                       (['powershell'], _structured(_acl())(['powershell'])),
                       (['whoami'], _ok_acl())])
            with self.assertRaisesRegex(SystemExit, 'cannot restrict|cannot protect'):
                backend.protect_file(target, run=run)


class WinBackendShapeTests(unittest.TestCase):
    # Lifecycle shape (install/restart/stop/uninstall task control) moved to
    # tests/test_windows_backend.py with the Stage 3 implementation; only
    # the failure-path pins that have no counterpart there stay here.
    def test_uninstall_failure_names_the_surviving_task(self):
        from tests.test_windows_backend import _fake_run
        with self.assertRaisesRegex(SystemExit, 'CodexMixedModelRouterUpdate'):
            backend.Backend(service, _fake_run(fail=(backend.UPDATE_TASK,))).uninstall('/home/x')

    def test_failed_state_protection_keeps_a_pre_existing_token(self):
        # Gap 0 (PR 55 review): a failed state-file ACL check unlinks only
        # a file this run minted, never a pre-existing live token.
        from tests.install_fixtures import _craft_bundle, _static_fetch, install_mod
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
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'k', 'ROUTER_NO_KEY_WINDOW': '1'}
            with mock.patch.dict(os.environ, env), mock.patch.object(
                    install_mod, 'platform_backend', return_value=FailingBackend()):
                with self.assertRaisesRegex(SystemExit, 'cannot protect state'):
                    install_mod.do_install(args, _fetch=_static_fetch(latest, blob))
            self.assertEqual(json.loads(live.read_text())['token'], 'live')

    def test_failed_protection_removes_the_placeholder(self):
        # A failed protect_secret must not leave an unprotected placeholder
        # that the next run's exists-early-return would trust.
        from tests.install_fixtures import install_mod
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
            backend.protect_file(tmp, run=_structured(_acl(), seen))
        grants = [c for c, _ in seen if '/grant:r' in c]
        self.assertEqual([(c[1], c[c.index('/grant:r') + 1]) for c in grants],
                         [(tmp, '*' + SID + ':(OI)(CI)F')])
        self.assertEqual(len(seen), 3)  # SID query, grant, structured verification

    def test_install_hardens_the_home_before_minting_the_state_file(self):
        # Protect the home before creating the token, then verify it before service startup.
        from tests.install_fixtures import _craft_bundle, _ok_run, _patch_attrs, install_mod
        from tests.fakes import signed_static_fetch
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
            fetch, _, public = signed_static_fetch(latest, blob)
            _patch_attrs(self, run=_ok_run, wait_version=lambda s, v: {'version': v},
                         self_test=lambda *a: None, write_catalogue=lambda *a: None)
            args = install_mod.build_parser().parse_args(
                ['--home', str(home), '--client', 'none'])
            with mock.patch.object(install_mod, 'platform_backend', return_value=StubBackend()), \
                    mock.patch.object(install_mod._updater, '_FEED_VERIFY_KEY', public), \
                    mock.patch.object(install_mod, 'find_python', return_value=sys.executable), \
                    mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': 'env-key-for-test', 'ROUTER_NO_KEY_WINDOW': '1'}):
                self.assertEqual(install_mod.do_install(args, _fetch=fetch), 0)
        self.assertEqual(events, [('protect', 'home', False),
                                  ('protect', 'mixed-router-state.json', None),
                                  ('install',)])


if __name__ == '__main__':
    unittest.main()
