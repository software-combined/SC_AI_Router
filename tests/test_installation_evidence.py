"""Scheduled launches and health-verified installs leave content-free evidence."""
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

from tests import test_client_choice as fixtures
from tests.install_fixtures import _craft_bundle, install_mod_factory

ROOT = Path(__file__).resolve().parents[1]


class TaskEvidenceTests(unittest.TestCase):
    def test_consoleless_launch_with_closed_standard_descriptors_keeps_its_log_open(self):
        for closed in ((1, 2), (2,), (0, 1, 2)):
            with self.subTest(closed=closed), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                launcher = home / 'task_launch.py'
                launcher.write_bytes((ROOT / 'packaging/task_launch.py').read_bytes())
                (home / 'router_launch.py').write_text('pass', encoding='utf-8')
                child = ('import os,runpy,sys\n'
                         'for fd in ' + repr(closed) + ': os.close(fd)\n'
                         'sys.argv=[sys.argv[1],"task.log","router_launch.py"]\n'
                         'runpy.run_path(sys.argv[0],run_name="__main__")\n')
                result = subprocess.run([sys.executable, '-I', '-c', child, str(launcher)],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0)
                rows = [json.loads(line) for line in (home / 'logs/task.log').read_text().splitlines()]
                self.assertEqual([row['event'] for row in rows], ['launch', 'completed'])
                self.assertEqual(rows[-1]['status'], 0)

    def test_launch_completion_and_pre_target_failures_preserve_status_without_exception_text(self):
        for script, text, status, reason in (
                ('router_launch.py', 'pass', 0, None),
                ('update_launch.py', 'raise SystemExit(7)', 7, 'target_exit'),
                ('express_launch.py', None, 1, 'missing_target'),
                ('express_launch.py', "raise RuntimeError('private settings')", 1, 'target_failed')):
            with self.subTest(script=script, text=text), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                (home / 'task_launch.py').write_bytes((ROOT / 'packaging/task_launch.py').read_bytes())
                if text is not None:
                    (home / script).write_text(text)
                result = subprocess.run([sys.executable, str(home / 'task_launch.py'), 'task.log', script],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, status)
                raw = (home / 'logs/task.log').read_text()
                rows = [json.loads(line) for line in raw.splitlines()]
                self.assertEqual(rows[0]['event'], 'launch')
                self.assertEqual(rows[-1]['event'], 'completed' if status == 0 else 'failed')
                self.assertEqual(rows[-1]['status'], status)
                self.assertEqual(rows[-1].get('error'), reason)
                self.assertEqual(rows[0]['task'], {'router_launch.py': 'router',
                    'update_launch.py': 'regular', 'express_launch.py': 'express'}[script])
                self.assertNotIn('private settings', raw)
                self.assertNotIn(str(home), raw)
                self.assertTrue(all(set(row) <= {'at', 'task', 'event', 'status', 'error'} for row in rows))


class InstallationEvidenceTests(unittest.TestCase):
    def test_install_text_waits_for_required_completion(self):
        delivery = fixtures.install_mod._delivery
        with tempfile.TemporaryDirectory() as temporary:
            home = fixtures._home(temporary)
            def fail_completion(*_):
                self.assertNotIn('installed 1.0.1', sys.stdout.getvalue())
                raise SystemExit(9)
            with mock.patch.object(fixtures.install_mod, 'platform_backend'), \
                    mock.patch.object(delivery, '_finalize', side_effect=fail_completion):
                with self.assertRaises(SystemExit) as stopped:
                    fixtures._full_install(self, temporary, home, '1.0.1', ['--clients', 'none'])
            self.assertEqual(stopped.exception.code, 9)
            self.assertFalse((home / 'logs/update.log').exists())

    def test_windows_update_requires_completed_components_even_when_target_is_healthy(self):
        for coherent, status in ((False, 0), (False, 7), (True, 0), (True, 7)):
            with self.subTest(coherent=coherent, status=status), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                (home / 'current').write_text('1.0.0')
                (home / 'releases/1.0.0').mkdir(parents=True)
                (home / 'mixed-router-state.json').write_text(json.dumps(dict(port=1, token='synthetic', clients='none')))
                install = install_mod_factory()
                updater = install._updater
                blob, latest = _craft_bundle('1.0.1')
                args = install.build_parser().parse_args(['--home', str(home), '--update', '--feed', 'file:///latest.json'])
                def child(*_, **__):
                    self.assertEqual(__['env'].get('ROUTER_AUTOMATIC_UPDATE'), '1')
                    (home / 'releases/1.0.1').mkdir()
                    (home / 'current').write_text('1.0.1')
                    if not coherent:
                        (home / 'installation-pending.json').write_text('{}')
                    return SimpleNamespace(returncode=status, stdout='', stderr='')
                output = io.StringIO()
                with mock.patch.object(updater, 'sys', SimpleNamespace(platform='win32', executable=sys.executable, exc_info=sys.exc_info)), \
                        mock.patch.object(updater._svc, 'run', side_effect=child), \
                        mock.patch.object(updater._svc, 'wait_version', return_value=True), \
                        mock.patch.object(updater._svc.notice, 'show_pending'), \
                        mock.patch.object(updater._resources, 'ready', return_value=coherent), \
                        mock.patch.object(updater._models, 'refresh'), mock.patch.object(updater._models, 'accept'), \
                        mock.patch.object(updater._reconcile, 'run'), mock.patch.object(updater, '_offer_notices'), \
                        contextlib.redirect_stdout(output):
                    try:
                        result = install.do_update(args, _fetch=lambda _: blob,
                            _read_feed=lambda *_: (200, json.dumps(latest).encode(), None),
                            _sleep=lambda _: None, _announce=lambda *_: None)
                    except SystemExit as error:
                        result = error.code
                self.assertEqual(result, status)
                state = json.loads((home / 'mixed-router-state.json').read_text())
                self.assertEqual(state.get('last_applied_version'), '1.0.1' if coherent else None)
                self.assertEqual('installed 1.0.1' in output.getvalue(), coherent)
                self.assertEqual((home / 'logs/update.log').exists(), coherent)

    def test_direct_regular_express_and_beta_installs_share_the_verified_completion_record(self):
        installer = fixtures.install_mod
        for route in ('direct', 'regular', 'express', 'beta'):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as temporary:
                home = fixtures._home(temporary)
                def child(*_, **__):
                    rc = fixtures._full_install(self, temporary, home, '1.0.1', ['--clients', 'codex'])[0]
                    return SimpleNamespace(returncode=rc, stdout='', stderr='')
                with mock.patch.object(installer, 'platform_backend'), contextlib.redirect_stdout(io.StringIO()):
                    if route == 'direct':
                        child()
                    else:
                        blob, latest = _craft_bundle('1.0.1')
                        latest['express'] = True
                        feed = 'file:///beta/latest.json' if route == 'beta' else 'file:///latest.json'
                        args = installer.build_parser().parse_args(['--home', str(home), '--feed', feed, '--update'])
                        args.express_only = route == 'express'
                        with mock.patch.object(installer._svc, 'run', side_effect=child), \
                                mock.patch.object(installer._updater, '_offer_notices'), \
                                mock.patch.object(installer._svc.notice, 'show_pending'):
                            self.assertEqual(installer._updater.do_update(args, _fetch=lambda _: blob,
                                _read_feed=lambda *_: (200, json.dumps(latest).encode(), None),
                                _sleep=lambda _: None, _announce=lambda *_: None), 0)
                text = (home / 'logs/update.log').read_text()
                self.assertIn('installed 1.0.1; health verified', text)
                before = text
                with mock.patch.object(installer, 'platform_backend'):
                    fixtures._install(temporary, home, [])
                self.assertEqual((home / 'logs/update.log').read_text(), before)

    def test_unhealthy_or_rolled_back_completion_never_claims_an_install(self):
        delivery = fixtures.install_mod._delivery
        for healthy in (False, True):
            with self.subTest(healthy=healthy), tempfile.TemporaryDirectory() as temporary:
                home = fixtures._home(temporary)
                args = SimpleNamespace(home=str(home), dry_run=False)
                def install(record):
                    if healthy:
                        record['installed_version'] = '1.0.1'  # The current pointer stayed on 1.0.0.
                    return 1
                self.assertEqual(delivery.run_install(args, install, run=mock.Mock(), fetch=mock.Mock()), 1)
                self.assertFalse((home / 'logs/update.log').exists())

    def test_attachment_failure_keeps_health_evidence_and_records_failure_separately(self):
        delivery = fixtures.install_mod._delivery
        with tempfile.TemporaryDirectory() as temporary:
            home = fixtures._home(temporary)
            args = SimpleNamespace(home=str(home), dry_run=False)
            def install(record):
                record['installed_version'] = '1.0.0'
                raise SystemExit('private configuration')
            with self.assertRaises(SystemExit):
                delivery.run_install(args, install, run=mock.Mock(), fetch=mock.Mock())
            self.assertIn('installed 1.0.0; health verified', (home / 'logs/update.log').read_text())
            text = (home / 'logs/maintenance.jsonl').read_text()
            self.assertIn('attachment_failed', text)
            self.assertNotIn('private configuration', text)


class AutomaticRemovalTests(unittest.TestCase):
    def test_native_components_never_use_the_legacy_unjournaled_recovery_path(self):
        delivery = fixtures.install_mod._delivery
        with tempfile.TemporaryDirectory() as temporary:
            home, backend = Path(temporary), mock.Mock()
            record = dict(platform='win32', dry_run=False, latest={}, backend=backend)
            with mock.patch.dict(os.environ, {'SCG_NATIVE_RESOURCES': ''}):
                for marker in ('setup-current', 'control-version'):
                    (home / marker).touch()
                    delivery.recover_current(home, record, 'python', '1.0.0')
                    (home / marker).unlink()
                record['latest']['native_resources'] = {'windows/x86_64': {}}
                delivery.recover_current(home, record, 'python', '1.0.0')
                record['latest'].clear()
                with mock.patch.dict(os.environ, {'SCG_NATIVE_RESOURCES': 'candidate'}):
                    delivery.recover_current(home, record, 'python', '1.0.0')
            backend.recover_pending.assert_not_called()

    def test_automatic_child_cannot_reinstall_after_removal_but_explicit_setup_can(self):
        delivery = fixtures.install_mod._delivery
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / '.router-removed').touch()
            args = SimpleNamespace(home=str(home), dry_run=False)
            owner = SimpleNamespace(pending=mock.Mock(return_value=False), restore=mock.Mock())
            original = delivery._load
            def install(record):
                record.update(platform='win32', backend=mock.Mock())
                delivery.recover(home, record)
                return 7
            with mock.patch.object(delivery, '_load', side_effect=lambda name:
                    owner if name == 'windows_installation' else original(name)), \
                    mock.patch.dict(os.environ, {'ROUTER_AUTOMATIC_UPDATE': '1'}), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as stopped:
                    delivery.run_install(args, install, run=mock.Mock(), fetch=None)
                self.assertEqual(stopped.exception.code, 0)
                self.assertNotIn('ROUTER_AUTOMATIC_UPDATE', os.environ)
                owner.pending.assert_not_called()
                with mock.patch.dict(os.environ, {'ROUTER_AUTOMATIC_UPDATE': '0'}):
                    self.assertEqual(delivery.run_install(args, install, run=mock.Mock(), fetch=None), 7)
            owner.pending.assert_called_once()
            owner.restore.assert_not_called()
            self.assertFalse((home / 'logs/update.log').exists())
