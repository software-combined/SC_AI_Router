"""Verified maintenance delivery survives attachment refusal and runtime rollback."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import unittest
from unittest import mock

from tests import test_systemd as fixtures
from tests._platform import unix_only
from tests.install_fixtures import _static_fetch, _tarball, install_mod
from tests.test_native_setup import module

delivery = module('install_delivery')
ROOT = Path(__file__).resolve().parents[1]
NEW = '1.3.2.999'


def payload(version=NEW):
    files = {
        'packaging/VERSION': (version + '\n').encode(),
        'packaging/install.py': b'# synthetic maintenance installer\n',
        'packaging/native_controller.py': b'# synthetic controller marker\n',
        'packaging/router_launch.py': (ROOT / 'packaging/router_launch.py').read_bytes(),
        'packaging/update_launch.py': (ROOT / 'packaging/update_launch.py').read_bytes(),
        'packaging/native_launch.py': (ROOT / 'packaging/native_launch.py').read_bytes(),
        'packaging/desktop_launch.py': (ROOT / 'packaging/desktop_launch.py').read_bytes(),
    }
    manifest = dict(version=version, files={name: hashlib.sha256(data).hexdigest()
                                          for name, data in files.items()})
    blob = _tarball(files=[('MANIFEST.json', json.dumps(manifest)), *files.items()])
    latest = dict(version=version, url='file:///bundle.tar.gz',
                  sha256=hashlib.sha256(blob).hexdigest(), min_python='3.14')
    return blob, manifest, latest


@unix_only
class MaintenanceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.rig = fixtures.SystemdTests()
        self.rig.setUp()
        self.addCleanup(self.rig.doCleanups)
        self.rig.install('1.2.6.174')
        self.home = self.rig.home
        self.blob, self.manifest, self.latest = payload()
        self.state = install_mod.ensure_state(self.home)
        self.backend = SimpleNamespace(repair_updates=mock.Mock())

    def prepare(self, owner=delivery):
        return owner.prepare(self.home, self.blob, self.latest, self.manifest,
                             self.state, '/managed/python3.14', self.backend)

    def test_preparation_does_not_read_the_broken_attachment(self):
        receipt = self.home / 'activation.json'
        receipt.write_text('{broken receipt')
        (self.home / 'download-auth.json').write_text('{legacy sign-in state')
        self.backend.repair_updates.side_effect = lambda *_: self.assertTrue(
            (self.home / 'update_launch.py').is_file())
        selected = self.prepare()
        self.assertEqual(selected, self.home / 'control' / NEW)
        self.assertEqual((self.home / 'control-version').read_text().strip(), NEW)
        self.assertEqual(receipt.read_text(), '{broken receipt')
        for name in ('native_launch.py', 'desktop_launch.py'):
            self.assertEqual((self.home / name).read_bytes(), (ROOT / 'packaging' / name).read_bytes())
        self.assertEqual((self.home / 'download-auth.json').read_text(), '{legacy sign-in state')
        self.backend.repair_updates.assert_called_once_with('/managed/python3.14', self.home)
        self.assertEqual(self.state['component_repairs'],
                         dict(assistants='ready', controller='ready', updater_launcher='ready',
                              controls_launchers='ready', scheduler='ready'))

    def test_launcher_retry_clears_only_its_own_failure_without_native_resources(self):
        service, original = module('service'), delivery._load
        copy = service._install_home_file
        failed = False
        def copy_once(home, source, name, target=None):
            nonlocal failed
            if name == 'native_launch.py' and not failed:
                failed = True
                raise OSError('interrupted launcher copy')
            return copy(home, source, name, target)
        service._install_home_file = copy_once
        self.state['component_repairs']['controls'] = 'failed'
        with mock.patch.object(delivery, '_load', side_effect=lambda name:
                service if name == 'service' else original(name)):
            self.prepare()
            self.assertEqual(self.state['component_repairs']['controls_launchers'], 'failed')
            self.prepare()
        self.assertEqual(self.state['component_repairs']['controls_launchers'], 'ready')
        self.assertEqual(self.state['component_repairs']['controls'], 'failed')
        self.assertNotIn('native_resources', self.latest)

    def test_failed_controller_delivery_keeps_launchers_and_records_its_own_failure(self):
        before = (self.home / 'update_launch.py').read_bytes()
        original = delivery._load
        controller = SimpleNamespace(install=mock.Mock(side_effect=OSError('write failed')))
        with mock.patch.object(delivery, '_load', side_effect=lambda name:
                controller if name == 'native_controller' else original(name)):
            self.assertIsNone(self.prepare())
        self.assertEqual((self.home / 'update_launch.py').read_bytes(), before)
        self.backend.repair_updates.assert_not_called()
        self.assertEqual(self.state['component_repairs'], {'assistants': 'ready', 'controller': 'failed'})

    def test_an_old_runtime_cannot_replace_the_newer_updater(self):
        selected = self.prepare()
        before = (self.home / 'update_launch.py').read_bytes()
        old = self.home / 'releases/1.2.6.174'
        blob, _, _ = payload('1.2.6.174')
        module('service').safe_extract(blob, old)
        (old / 'packaging/update_launch.py').write_text('# legacy launcher\n')
        result = delivery.maintain(self.home, old, self.state)
        self.assertEqual(result, selected)
        self.assertEqual((self.home / 'update_launch.py').read_bytes(), before)
        self.assertEqual(module('native_controller').installer(self.home),
                         selected / 'packaging/install.py')

    def test_stable_launchers_work_before_the_legacy_main_job_is_migrated(self):
        pointer = self.home / 'current'
        release = self.home / 'releases/1.2.6.174'
        pointer.unlink()
        pointer.symlink_to(release, target_is_directory=True)
        self.backend.repair_updates.side_effect = lambda *_: self.assertTrue(pointer.is_symlink())
        selected = self.prepare()
        self.assertTrue(pointer.is_symlink())
        (selected / 'packaging/install.py').write_text("# '--update'\nprint('stable updater ran')\n")
        (release / 'ai_router').mkdir(exist_ok=True)
        (release / 'ai_router/__main__.py').write_text("print('stable runtime ran')\n")
        for name, expected in (('update_launch.py', 'stable updater ran'),
                               ('router_launch.py', 'stable runtime ran')):
            result = subprocess.run([sys.executable, str(self.home / name)],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(expected, result.stdout)
        self.backend.repair_updates.assert_called_once()

    def test_intermediate_runtime_upgrade_keeps_the_newer_controller_launchers(self):
        self.prepare()
        before = (self.home / 'update_launch.py').read_bytes()
        self.rig.install('1.3.1')
        self.assertEqual(install_mod.current_version(self.home), '1.3.1')
        self.assertEqual((self.home / 'update_launch.py').read_bytes(), before)

    def test_unreadable_receipt_cannot_block_real_installer_maintenance(self):
        (self.home / 'activation.json').write_text('{broken receipt')
        key = self.home / 'openrouter.key'
        key.write_text('synthetic-key\n')
        key.chmod(0o600)
        self.rig.calls.clear()
        args = install_mod.build_parser().parse_args(
            ['--home', str(self.home), '--feed', 'file:///latest.json'])
        with self.assertRaisesRegex(SystemExit, 'receipts are unreadable'), \
                contextlib.redirect_stdout(io.StringIO()):
            install_mod.do_install(args, _fetch=_static_fetch(self.latest, self.blob))
        self.assertEqual((self.home / 'control-version').read_text().strip(), NEW)
        self.assertEqual(install_mod.current_version(self.home), '1.2.6.174')
        unit = self.rig.root / 'config/systemd/user' / install_mod._linux.UPDATE
        self.assertIn(str(self.home / 'update_launch.py'), unit.read_text())
        self.assertNotIn('/releases/', unit.read_text())
        self.assertEqual(key.read_text(), 'synthetic-key\n')
        self.assertFalse(any(command[2:3] == ['restart'] for command in self.rig.calls))

    def test_attachment_exit_still_finishes_delivery_without_masking_the_exit(self):
        args = SimpleNamespace(home=str(self.home), dry_run=False)
        def install(record):
            record.update(maintenance_done=True, latest=self.latest, feed='file:///latest.json')
            raise SystemExit('settings conflict')
        for failure in (None, OSError('optional delivery failed')):
            with self.subTest(failure=type(failure).__name__), \
                    mock.patch.object(delivery, 'finish', side_effect=failure) as finish, \
                    self.assertRaisesRegex(SystemExit, 'settings conflict'), \
                    contextlib.redirect_stdout(io.StringIO()):
                delivery.run_install(args, install, run=mock.Mock(), fetch=mock.Mock())
            finish.assert_called_once()

    def test_failure_before_verification_does_not_deliver_anything(self):
        args = SimpleNamespace(home=str(self.home), dry_run=False)
        with mock.patch.object(delivery, 'finish') as finish, self.assertRaises(SystemExit):
            delivery.run_install(args, lambda _: (_ for _ in ()).throw(SystemExit('unverified')),
                                 run=mock.Mock(), fetch=mock.Mock())
        finish.assert_not_called()
