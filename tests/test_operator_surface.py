"""Plan 147: doctor, update state, rollback listing and the support bundle.

The read-only verbs never write; the doctor names a Fix line per failing
row and exits 1; --check-update makes no change while the scheduled
--update records recency and a closed-set error code; the support bundle
carries no path, URL, key or free text.
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests._platform import assert_owner_only, requires_posix_perms
from tests.install_fixtures import _craft_bundle, _ok_run, _patch_attrs, install_mod

ROOT = Path(__file__).resolve().parents[1]
FEED = 'file:///latest.json'


class OperatorSurfaceTests(unittest.TestCase):
    def _home(self, version='1.0.0', **state):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        home = tmp / 'home'
        release = home / 'releases' / version / 'packaging'
        release.mkdir(parents=True)
        (release / 'VERSION').write_text(version + '\n')
        (home / 'current').write_text(version + '\n')
        (home / 'update_launch.py').write_text(
            "sys.argv = [installer, '--update', '--home', home]\n")
        doc = {'port': 1, 'token': 'x'}
        doc.update(state)
        (home / 'mixed-router-state.json').write_text(json.dumps(doc))
        return home

    def _args(self, home, *extra):
        return install_mod.build_parser().parse_args(['--home', str(home), *extra])

    def _doctor(self, home):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = install_mod.do_doctor(self._args(home, '--doctor', '--json'))
        return rc, json.loads(buf.getvalue())

    def _attach_claude(self, home, listing=None):
        entry = {'config_path': str(home / 'settings.json'),
                 'inserted_block': '{}', 'claude_mode': 'subscription'}
        if listing is not None:
            entry['listing'] = listing
        install_mod._codex_config.write_client_receipt(home, 'claude', entry)

    def _claude_row(self, home):
        _rc, doc = self._doctor(home)
        return next(row for row in doc['rows'] if row['check'] == 'claude')

    def _bind_listing(self, value):
        operator = install_mod._operator
        self.addCleanup(setattr, operator, 'listing', operator.listing)
        operator.listing = value

    def test_doctor_reports_claude_listing_drift_and_match(self):
        home = self._home()
        self._attach_claude(home, {'served_at': '2026-09-13T00:00:00Z',
                                   'models': [{'id': 'a'}, {'id': 'b'}]})
        self._bind_listing(lambda state: {'data': [{'id': 'b'}, {'id': 'c'}]})
        row = self._claude_row(home)
        self.assertEqual(row['status'], 'WARN')
        self.assertIn('+c', row['detail'])
        self.assertIn('-a', row['detail'])
        self._bind_listing(lambda state: {'data': [{'id': 'a'}, {'id': 'b'}]})
        self.assertEqual(self._claude_row(home)['status'], 'OK')
        self._bind_listing(lambda state: None)
        down = self._claude_row(home)
        self.assertEqual(down['status'], 'WARN')
        self.assertIn('did not answer', down['detail'])

    def test_doctor_reports_absent_and_unsnapshotted_claude(self):
        home = self._home()
        absent = self._claude_row(home)
        self.assertEqual(absent['status'], 'OK')
        self.assertIn('not attached', absent['detail'])
        self._attach_claude(home)
        self._bind_listing(lambda state: {'data': [{'id': 'a'}]})
        unsnapshotted = self._claude_row(home)
        self.assertEqual(unsnapshotted['status'], 'WARN')
        self.assertIn('snapshot', unsnapshotted['detail'])

    def test_doctor_warns_on_an_unreadable_activation_receipt(self):
        home = self._home()
        for shape in ('{broken json', '[]', '{}',
                      '{"version": 3, "clients": {}}',
                      '{"version": 2, "clients": "x"}'):
            with self.subTest(shape=shape):
                (home / 'activation.json').write_text(shape)
                row = self._claude_row(home)
                self.assertEqual(row['status'], 'WARN')
                self.assertIn('unreadable', row['detail'])

    def test_doctor_row_filters_the_live_side_and_caps_the_list(self):
        home = self._home()
        self._attach_claude(home, {'served_at': '2026-09-13T00:00:00Z',
                                   'models': [{'id': 'ok-model'}]})
        self._bind_listing(lambda state: {'data': [
            {'id': 'ok-model'}, {'id': 'evil\n    service  OK  FORGED ROW'}]})
        row = self._claude_row(home)
        self.assertEqual(row['status'], 'OK')
        self.assertNotIn('FORGED', row['detail'])
        self._attach_claude(home, {'served_at': '2026-09-13T00:00:00Z',
                                   'models': [{'id': 'old-%d' % i} for i in range(9)]})
        self._bind_listing(lambda state: {'data': [
            {'id': 'new-%d' % i} for i in range(9)]})
        capped = self._claude_row(home)
        self.assertEqual(capped['status'], 'WARN')
        self.assertEqual(capped['detail'].count('old-'), 5)
        self.assertEqual(capped['detail'].count('new-'), 5)

    def test_doctor_row_never_prints_a_forged_listing_id(self):
        home = self._home()
        self._attach_claude(home, {'served_at': '2026-09-13T00:00:00Z', 'models': [
            {'id': 'ok-model'},
            {'id': 'evil\n    service  OK  FORGED ROW'}]})
        self._bind_listing(lambda state: {'data': [{'id': 'ok-model'}, {'id': 'new-model'}]})
        row = self._claude_row(home)
        self.assertEqual(row['status'], 'WARN')
        self.assertNotIn('\n', row['detail'])
        self.assertNotIn('FORGED', row['detail'])

    def test_doctor_fails_with_a_fix_line_per_failing_row_and_writes_nothing(self):
        home = self._home()
        _patch_attrs(self, health=lambda *a, **k: None)
        before = sorted(p.name for p in home.rglob('*'))
        state_before = (home / 'mixed-router-state.json').read_bytes()
        rc, doc = self._doctor(home)
        self.assertEqual(rc, 1)
        self.assertFalse(doc['ok'])
        failing = [row for row in doc['rows'] if row['status'] == 'FAIL']
        self.assertIn('service', [row['check'] for row in failing])
        for row in failing:
            self.assertTrue(row['fix'], row['check'])
        self.assertEqual(sorted(p.name for p in home.rglob('*')), before)
        self.assertEqual((home / 'mixed-router-state.json').read_bytes(), state_before)

    @requires_posix_perms
    def test_doctor_exits_zero_on_a_healthy_home(self):
        home = self._home()
        key = home / 'openrouter.key'
        key.write_text('sk-or-v1-' + 'a' * 24 + '\n')
        os.chmod(key, 0o600)
        (home / 'mixed-models.json').write_text(
            json.dumps({'models': [{'slug': 'm'}]}))
        _patch_attrs(self,
                     find_python=lambda explicit=None: sys.executable,
                     health=lambda state, timeout=5: {'status': 'ok', 'version': '1.0.0'},
                     run=lambda cmd, **kw: SimpleNamespace(returncode=0, stdout='', stderr=''))
        with mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': str(home / 'config')}):
            unit = (home / 'config' / 'systemd' / 'user' /
                    'codex-mixed-model-router-update.service')
            unit.parent.mkdir(parents=True)
            unit.write_text('ExecStart=%s --update --home %s\n'
                            % (sys.executable, home))
            rc, doc = self._doctor(home)
        self.assertEqual(rc, 0, [r for r in doc['rows'] if r['status'] == 'FAIL'])
        self.assertTrue(doc['ok'])

    def test_scheduler_row_accepts_the_launcher_the_installer_writes(self):
        # The packaged launcher keeps --check-update as its fallback for a
        # rolled-back release; the row must judge the verb it passes.
        home = self._home()
        install_mod.install_launcher(home, ROOT)
        with mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': str(home / 'config')}):
            unit = (home / 'config' / 'systemd' / 'user' /
                    'codex-mixed-model-router-update.service')
            unit.parent.mkdir(parents=True)
            unit.write_text('ExecStart=%s --update --home %s\n'
                            % (sys.executable, home))
            state, _detail = install_mod._operator._scheduler_state(home)
        self.assertEqual(state, 'current')

    def test_doctor_and_status_render_a_corrupt_state_document(self):
        home = self._home()
        (home / 'mixed-router-state.json').write_text('{')
        with mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': str(home / 'config')}):
            unit = (home / 'config' / 'systemd' / 'user' /
                    'codex-mixed-model-router-update.service')
            unit.parent.mkdir(parents=True)
            unit.write_text('ExecStart=%s --update --home %s\n'
                            % (sys.executable, home))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = install_mod.main(['--doctor', '--home', str(home)])
            self.assertIn('doctor:', buf.getvalue())
            self.assertEqual(rc, 1)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                install_mod.main(['--status', '--json', '--home', str(home)])
            doc = json.loads(buf.getvalue())
        self.assertFalse(doc['key_present'])
        self.assertIsNone(doc['update']['last_check_at'])

    def test_free_text_in_state_never_reaches_doctor_or_status(self):
        poison = '/Users/someone/secret.log sk-or-v1-' + 'a' * 24
        home = self._home(last_error=poison)
        _patch_attrs(self, health=lambda *a, **k: None)
        for argv in (['--status'], ['--doctor']):
            with self.subTest(argv=argv):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    action = (install_mod.do_status if argv == ['--status']
                              else install_mod.do_doctor)
                    action(self._args(home, *argv))
                self.assertNotIn('secret.log', buf.getvalue())
                self.assertNotIn('sk-or-v1-', buf.getvalue())

    def test_doctor_flags_a_legacy_scheduled_command(self):
        home = self._home()
        (home / 'update_launch.py').write_text(
            "sys.argv = [installer, '--check-update', '--home', home]\n")
        rc, doc = self._doctor(home)
        row = next(r for r in doc['rows'] if r['check'] == 'scheduler')
        self.assertEqual(row['status'], 'FAIL')
        self.assertIn('installer', row['fix'])
        self.assertEqual(rc, 1)

    def test_doctor_fails_when_the_scheduled_command_is_missing(self):
        home = self._home()
        (home / 'update_launch.py').unlink()
        rc, doc = self._doctor(home)
        row = next(r for r in doc['rows'] if r['check'] == 'scheduler')
        self.assertEqual(row['status'], 'FAIL')
        self.assertEqual(rc, 1)

    def test_status_reports_update_recency_and_parked_versions_without_network(self):
        home = self._home(last_check_at='2026-09-13T02:00:00Z',
                          last_applied_version='1.0.0',
                          last_error='installer_failed',
                          update_failures={'9.9.9': 3})
        _patch_attrs(self, health=lambda *a, **k: None)
        with mock.patch.object(install_mod._svc, 'fetch',
                               side_effect=AssertionError('status must stay offline')):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = install_mod.do_status(self._args(home, '--status', '--json'))
            doc = json.loads(buf.getvalue())
            text = io.StringIO()
            with contextlib.redirect_stdout(text):
                install_mod.do_status(self._args(home, '--status'))
        self.assertEqual(rc, 0)
        self.assertEqual(doc['update']['last_check_at'], '2026-09-13T02:00:00Z')
        self.assertEqual(doc['update']['last_applied_version'], '1.0.0')
        self.assertEqual(doc['update']['last_error'], 'installer_failed')
        self.assertEqual(doc['update']['failures'], {'9.9.9': 3})
        self.assertIn('checked 2026-09-13T02:00:00Z', text.getvalue())
        self.assertIn('parked 9.9.9 x3', text.getvalue())

    def test_check_update_names_the_available_version_and_writes_nothing(self):
        home = self._home()
        (home / 'update-etag').write_text('old-etag\n')
        state_before = (home / 'mixed-router-state.json').read_bytes()
        latest = {'version': '9.9.9', 'url': 'file:///bundle.tar.gz', 'sha256': None}
        args = self._args(home, '--check-update', '--json', '--feed', FEED)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = install_mod.do_check_update(
                args,
                _read_feed=lambda feed, etag: (200, json.dumps(latest).encode(), 'new'),
                _fetch=lambda url: self.fail('a read-only check must not download'))
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(buf.getvalue())['available'], '9.9.9')
        self.assertEqual((home / 'update-etag').read_text(), 'old-etag\n')
        self.assertEqual((home / 'mixed-router-state.json').read_bytes(), state_before)

    def test_check_update_304_writes_nothing(self):
        home = self._home()
        (home / 'update-etag').write_text('etag-A\n')
        args = self._args(home, '--check-update', '--feed', FEED)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = install_mod.do_check_update(
                args, _read_feed=lambda feed, etag: (304, b'', 'etag-B'))
        self.assertEqual(rc, 0)
        self.assertIn('up to date', buf.getvalue())
        self.assertEqual((home / 'update-etag').read_text(), 'etag-A\n')

    def test_update_applies_and_records_the_pass_in_state(self):
        home = self._home(last_error='installer_failed')
        blob, latest = _craft_bundle('9.9.9')

        def fake_run(cmd, **kwargs):
            target = home / 'releases' / '9.9.9' / 'packaging'
            target.mkdir(parents=True, exist_ok=True)
            (target / 'VERSION').write_text('9.9.9\n')
            (home / 'current').write_text('9.9.9\n')
            return _ok_run(cmd, **kwargs)

        _patch_attrs(self, run=fake_run)
        args = self._args(home, '--update', '--feed', FEED)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = install_mod.do_update(
                args, _fetch=lambda url: blob,
                _read_feed=lambda feed, etag: (200, json.dumps(latest).encode(), 'etag-2'),
                _sleep=lambda s: None, _announce=lambda state: None)
        self.assertEqual(rc, 0, buf.getvalue())
        state = json.loads((home / 'mixed-router-state.json').read_text())
        self.assertEqual(state['last_applied_version'], '9.9.9')
        self.assertNotIn('last_error', state)
        self.assertTrue(state['last_check_at'].endswith('Z'))
        self.assertIn('9.9.9', (home / 'logs' / 'update.log').read_text())

    def test_update_failure_records_a_closed_set_code(self):
        home = self._home()
        args = self._args(home, '--update')
        with self.assertRaises(SystemExit):
            install_mod.do_update(
                args,
                _read_feed=lambda feed, etag: (200, b'not json', None),
                _sleep=lambda s: None)
        state = json.loads((home / 'mixed-router-state.json').read_text())
        # Unsigned garbage on the https channel fails verification before
        # parsing (Plan 145); the code stays in the closed set.
        self.assertEqual(state['last_error'], 'feed_signature')
        self.assertIn(state['last_error'], install_mod._updater.ERROR_CODES)
        self.assertTrue(state['last_check_at'].endswith('Z'))
        # A corrupt local state file is not a feed problem, whatever the code.
        (home / 'mixed-router-state.json').write_text('{')
        latest = {'version': '9.9.9', 'url': 'file:///bundle.tar.gz', 'sha256': None}
        file_args = self._args(home, '--update', '--feed', 'file:///latest.json')
        with self.assertRaises(SystemExit) as ctx:
            install_mod.do_update(
                file_args, _read_feed=lambda feed, etag: (200, json.dumps(latest).encode(), None),
                _sleep=lambda s: None)
        self.assertIn('state is missing or unreadable', str(ctx.exception))

    def test_rollback_lists_releases_and_to_stays_a_mutating_alias(self):
        home = self._home()
        (home / 'releases' / '1.0.1' / 'packaging').mkdir(parents=True)
        (home / 'releases' / '1.0.1' / 'packaging' / 'VERSION').write_text('1.0.1\n')
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = install_mod.do_rollback_list(self._args(home, '--rollback'))
        self.assertEqual(rc, 0)
        self.assertIn('current: 1.0.0', buf.getvalue())
        self.assertIn('1.0.1', buf.getvalue())
        for argv in (['--rollback', '--to', '1.0.1'],
                     ['--version', '1.0.1'],
                     ['--to', '1.0.1']):
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit) as ctx:
                    install_mod.main([*argv, '--home', str(home)])
                self.assertIn('--to needs --rollback' if argv[0] == '--to'
                              else 'scratch home', str(ctx.exception))

    def test_rollback_to_reaches_the_rollback_action(self):
        home = self._home()
        (home / 'releases' / '1.0.1' / 'packaging').mkdir(parents=True)
        (home / 'releases' / '1.0.1' / 'packaging' / 'VERSION').write_text('1.0.1\n')
        seen = []
        original = install_mod.do_rollback
        self.addCleanup(setattr, install_mod, 'do_rollback', original)
        install_mod.do_rollback = lambda args: (seen.append(args.version), 0)[1]
        _patch_attrs(self, platform_backend=lambda: SimpleNamespace(
            check=lambda home: None))
        with mock.patch.dict(os.environ, {'ROUTER_LIVE_RUN': '1'}):
            rc = install_mod.main(['--rollback', '--to', '1.0.1', '--home', str(home)])
        self.assertEqual(rc, 0)
        self.assertEqual(seen, ['1.0.1'])

    def test_scheduled_carriers_name_the_applying_verb(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()

            def fake_run(cmd, **kwargs):
                return SimpleNamespace(returncode=0, stdout='', stderr='')

            with mock.patch.dict(os.environ,
                                 {'XDG_CONFIG_HOME': str(Path(tmp) / 'config')}):
                manager = install_mod._linux.Manager(home, fake_run)
                manager.install(sys.executable, ROOT)
            unit = (Path(tmp) / 'config' / 'systemd' / 'user' /
                    'codex-mixed-model-router-update.service').read_text()
            self.assertIn('--update', unit)
            self.assertNotIn('--check-update', unit)
            install_mod.install_launcher(home, ROOT)
            launcher = (home / 'update_launch.py').read_text()
            self.assertIn("'--update'", launcher)
            # The fallback verb keeps a rolled-back pre-147 release updating.
            self.assertIn("verb = '--update' if", launcher)

    def test_support_bundle_carries_no_path_url_or_free_text(self):
        home = self._home()
        (home / 'mixed-models.json').write_text(
            json.dumps({'models': [{'slug': 'm'}]}))
        _patch_attrs(self, health=lambda *a, **k: None)
        doc = {
            'installed': True, 'version': '1.0.0', 'serving': True,
            'key_present': True, 'key_usable': True,
            'feed': 'https://dist.softwarecombined.com/stable/latest.json',
            'channel': 'stable',
            'clients': {'codex': {'attached': True,
                                  'config_path': '/Users/someone/.codex/config.toml'}},
            'providers': {'openrouter': {'key_present': True, 'key_usable': True}},
            'catalogue': {'rows': 3}, 'scheduler': 'current',
            'update': {'last_check_at': '2026-09-13T02:00:00Z',
                       'last_applied_version': '1.0.0',
                       'last_error': '/Users/someone/secret.log sk-or-v1-' + 'a' * 24,
                       'failures': {'9.9.9': 3}},
        }
        operator = install_mod._operator
        bundle = operator._support_document(doc, now='2026-09-13T03:00:00Z')
        blob = json.dumps(bundle)
        self.assertNotIn('://', blob)
        self.assertNotIn('/Users', blob)
        self.assertNotIn('config_path', blob)
        self.assertIsNone(bundle['update']['last_error'])
        self.assertEqual(bundle['update']['last_check_at'], '2026-09-13T02:00:00Z')
        doc['version'] = 'https://evil.example/x'
        doc['channel'] = 'https://evil.example/channel'
        doc['update']['last_check_at'] = 'https://evil.example/now'
        doc['clients']['https://evil.example/key'] = {
            'attached': True, 'config_path': '/Users/someone/.codex/activation.json'}
        hardened = operator._support_document(doc)
        self.assertIsNone(hardened['install']['version'])
        self.assertIsNone(hardened['install']['channel'])
        self.assertIsNone(hardened['update']['last_check_at'])
        self.assertEqual(hardened['clients'], {'codex': True})
        self.assertNotIn('://', json.dumps(hardened))
        self.assertNotRegex(blob, r'sk-or-v1-[A-Za-z0-9]{20,}')
        self.assertNotRegex(blob, r'Bearer [A-Za-z0-9._-]{30,}')
        doc['update']['last_error'] = 'installer_failed'
        self.assertEqual(
            operator._support_document(doc)['update']['last_error'], 'installer_failed')
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = install_mod.do_support(self._args(home, '--support'))
        self.assertEqual(rc, 0)
        path = Path(buf.getvalue().strip())
        self.assertTrue(path.is_file())
        assert_owner_only(self, path)
        self.assertNotIn(str(home), path.read_text())


if __name__ == '__main__':
    unittest.main()
