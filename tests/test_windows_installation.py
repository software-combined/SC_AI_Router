"""Required Windows payloads are staged before any live component changes."""
import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_maintenance_recovery import payload
from tests.test_native_setup import module
from tests import test_windows_task_cohort as task_fixtures


class InstallationRecoveryTests(unittest.TestCase):
    def fixture(self, root):
        owner = module('windows_installation')
        home = root / 'home'
        home.mkdir()
        old, new = '1.3.21.215', '1.3.23.216'
        from tests.test_native_setup import resources
        for version in (old, new):
            source = home / 'control' / version
            (source / 'packaging').mkdir(parents=True)
            (source / 'packaging/install.py').write_text('# installer')
            (source / 'packaging/VERSION').write_text(version)
            for name in owner.LAUNCHERS:
                origin = 'update_launch.py' if name == 'express_launch.py' else name
                (source / 'packaging' / origin).write_bytes((version + origin + '\n').encode())
            (source / 'MANIFEST.json').write_text(json.dumps(dict(version=version, files={
                path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (source / 'packaging').iterdir()})))
            release = home / 'releases' / version / 'packaging'
            release.mkdir(parents=True)
            (release / 'VERSION').write_text(version)
            native = resources(home / 'setup' / version, version=version)
            (native / 'control').mkdir()
            helper = native / 'control/scg-router-menu'
            if module('native_payload').target().startswith('windows/'):
                helper = helper.with_suffix('.exe')
            helper.write_bytes(b'native-menu')
            doc = json.loads((native / 'installer.json').read_text())
            doc['menu_sha256'] = hashlib.sha256(helper.read_bytes()).hexdigest()
            (native / 'installer.json').write_text(json.dumps(doc))
        (home / 'current').write_text(old)
        (home / 'control-version').write_text(old)
        (home / 'setup-current').write_text(old)
        for name in owner.LAUNCHERS:
            origin = 'update_launch.py' if name == 'express_launch.py' else name
            (home / name).write_bytes((home / 'control' / old / 'packaging' / origin).read_bytes())
        (home / 'desktop-preferences.json').write_bytes(b'{"autostart":false}')
        (home / 'mixed-models.json').write_bytes(b'old catalogue')
        (home / 'openrouter.key').write_bytes(b'private-key')
        (home / 'mixed-router-state.json').write_text(json.dumps(dict(token='private-token',
            chosen_model='model-choice', component_repairs={name: 'ready' for name in
            ('controller', 'scheduler', 'controls', 'updater_launcher', 'controls_launchers')})))
        bindings = {'version': old}
        shortcuts = SimpleNamespace(snapshot=lambda _: dict(bindings),
            restore=lambda _, saved: (bindings.clear(), bindings.update(saved)),
            fingerprint=lambda _: dict(bindings), verify=mock.Mock())
        def install(home, retained, python):
            (home / 'setup-current').write_text(retained.name)
            bindings['version'] = json.loads((retained / 'installer.json').read_text())['version']
        shortcuts.install = mock.Mock(side_effect=install)
        real = owner.load
        owner.load = lambda name: shortcuts if name == 'native_shortcuts' else (
            SimpleNamespace(start=mock.Mock()) if name == 'desktop_menu' else real(name))
        backend, table = task_fixtures.TaskCohortTests().fixture(home)
        backend.preserve_cohort(home, backend.snapshot_cohort(home),
                              str(home / 'setup' / old / 'runtime/python/bin/python3.14'))
        health = mock.patch.object(backend._svc, 'health', side_effect=lambda *_args, **_kw:
                                  dict(version=(home / 'current').read_text().strip()))
        health.start()
        self.addCleanup(health.stop)
        def shutdown(_):
            for legacy, name in table.rows:
                if name == next(iter(table.rows))[1]:
                    table.call(name, home, 'stop', legacy=legacy)
        patcher = mock.patch('tests.test_windows_backend.backend._post_shutdown', side_effect=shutdown)
        patcher.start()
        self.addCleanup(patcher.stop)
        (home / owner.RECEIPT).write_text(json.dumps(owner.parts(home)[0]))
        return owner, home, backend, table, shortcuts, old, new

    def activate(self, owner, home, new):
        for name in ('current', 'control-version'):
            (home / name).write_text(new)
        for name in owner.LAUNCHERS:
            origin = 'update_launch.py' if name == 'express_launch.py' else name
            (home / name).write_bytes((home / 'control' / new / 'packaging' / origin).read_bytes())
        return dict(resources=home / 'setup' / new)

    def test_completion_is_last_and_mixed_versions_refuse_readiness(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home, backend, table, _, old, new = self.fixture(Path(temporary))
            owner.begin(home, new, backend)
            self.assertFalse(owner.ready(home))
            self.assertNotIn('private-', (home / owner.JOURNAL).read_text())
            prepared = self.activate(owner, home, new)
            backend._run_task(owner.TASKS[0], home)
            owner.complete(home, prepared, backend)
            self.assertFalse(owner.pending(home))
            self.assertTrue(owner.ready(home))
            self.assertEqual((home / 'desktop-preferences.json').read_bytes(), b'{"autostart":false}')
            (home / 'control-version').write_text(old)
            self.assertFalse(owner.ready(home))

    def test_preparation_stages_complete_candidate_without_activating_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home, _, _, _, old, new = self.fixture(Path(temporary))
            before = {name: (home / name).read_bytes() for name in owner.FILES if (home / name).exists()}
            doc = module('native_payload').metadata(home / 'setup' / new)
            with mock.patch.dict(os.environ, {'SCG_NATIVE_RESOURCES': str(home / 'setup' / new)}):
                staged = owner.prepare(home, home / 'control' / new,
                    dict(version=new, sha256=doc['sha256']), 'file:///latest.json')
            self.assertEqual(staged['version'], new)
            self.assertEqual({name: (home / name).read_bytes() for name in before}, before)
            self.assertFalse(owner.pending(home))

    def test_matching_repair_after_rollback_reconciles_a_newer_retained_controller(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home, backend, _, _, current, newer = self.fixture(Path(temporary))
            (home / 'control-version').write_text(newer)
            doc = module('native_payload').metadata(home / 'setup' / current)
            launcher = home / 'control' / current / 'packaging/router_launch.py'
            before = launcher.read_bytes()
            launcher.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                owner.prepare(home, launcher.parent.parent, dict(version=current, sha256=doc['sha256']),
                              'file:///latest.json', resources=home / 'setup' / current)
            self.assertEqual((home / 'control-version').read_text(), newer)
            launcher.write_bytes(before)
            prepared = owner.prepare(home, home / 'control' / current,
                dict(version=current, sha256=doc['sha256']), 'file:///latest.json', resources=home / 'setup' / current)
            self.assertEqual((home / 'control-version').read_text(), newer)
            owner.activate(home, prepared, backend)
            self.assertTrue(owner.pending(home))
            self.assertEqual((home / 'control-version').read_text().strip(), current)
            backend._run_task(owner.TASKS[0], home)
            owner.complete(home, prepared, backend)
            self.assertTrue(owner.ready(home))
            self.assertTrue((home / 'control' / newer).exists())

    def test_failed_control_delivery_restores_old_cohort_and_preserves_model_edits(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home, backend, _, shortcuts, old, new = self.fixture(Path(temporary))
            owner.begin(home, new, backend)
            prepared = self.activate(owner, home, new)
            (home / 'mixed-models.json').write_bytes(b'concurrent model edit')
            shortcuts.verify.side_effect = ValueError('readback failed')
            backend._run_task(owner.TASKS[0], home)
            with self.assertRaises(ValueError):
                owner.complete(home, prepared, backend)
            self.assertEqual(owner.restore(home, backend), 'restored')
            self.assertTrue(owner.ready(home))
            self.assertEqual((home / 'current').read_text(), old)
            self.assertEqual((home / 'mixed-models.json').read_bytes(), b'concurrent model edit')
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.assertEqual(state['chosen_model'], 'model-choice')
            self.assertEqual((home / 'openrouter.key').read_bytes(), b'private-key')

    def test_incomplete_restoration_retains_journal_and_both_runtimes(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home, backend, _, _, old, new = self.fixture(Path(temporary))
            owner.begin(home, new, backend)
            self.activate(owner, home, new)
            backend.restore_cohort = mock.Mock(side_effect=OSError('unavailable scheduler'))
            self.assertEqual(owner.restore(home, backend), 'failed')
            self.assertTrue(owner.pending(home))
            self.assertFalse(owner.ready(home))
            self.assertTrue(all((home / 'setup' / version).is_dir() for version in (old, new)))
            self.assertTrue(json.loads((home / 'mixed-router-state.json').read_text())['installation_repair_required'])

    def test_catalogue_edits_before_completion_are_not_owned_by_the_installer(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home, backend, _, _, _, new = self.fixture(Path(temporary))
            owner.begin(home, new, backend)
            for name in ('mixed-models.json', 'routed-models.json'):
                (home / name).write_bytes(b'independent model refresh')
            # Exercise the old publication hook when checking the pre-fix implementation.
            if hasattr(owner, 'checkpoint'):
                owner.checkpoint(home, catalogue=True)
            self.assertEqual(owner.restore(home, backend), 'restored')
            for name in ('mixed-models.json', 'routed-models.json'):
                self.assertEqual((home / name).read_bytes(), b'independent model refresh')

    def test_same_version_finish_cannot_run_unjournaled_windows_maintenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, home, _, _, _, old, _ = self.fixture(Path(temporary))
            delivery, native = module('install_delivery'), SimpleNamespace(deliver=mock.Mock(return_value=True))
            original = delivery._load
            skills = SimpleNamespace(sync=mock.Mock(return_value='ready'))
            with mock.patch.object(delivery, 'sys', SimpleNamespace(platform='win32'), create=True), \
                    mock.patch.object(delivery, 'maintain', side_effect=AssertionError('outside transaction')) as maintain, \
                    mock.patch.object(delivery, '_load', side_effect=lambda name: native if name == 'native_resources'
                                      else skills if name == 'agent_skills' else original(name)):
                delivery.finish(home, native=dict(latest=dict(version=old), feed='file:///latest.json'))
            maintain.assert_not_called()
            native.deliver.assert_called_once()

    def test_repair_keeps_a_newer_installed_release_when_the_channel_is_older(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home, _, _, _, current, newer = self.fixture(Path(temporary))
            (home / 'control-version').write_text(newer)
            (home / 'setup-current').write_text(newer)
            resources = home / 'setup' / current
            doc = module('native_payload').metadata(resources)
            resources.rename(resources.with_name(current + '-' + doc['sha256'][:16]))
            source = home / 'releases' / current
            for path in (home / 'control' / current).rglob('*'):
                if path.is_file():
                    target = source / path.relative_to(home / 'control' / current)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(path.read_bytes())
            blob, manifest, latest = payload('1.3.20.214')
            delivery = module('install_delivery')
            record = dict(platform='win32', repair_version=current, feed='file:///latest.json')
            delivery.prepare(home, blob, latest, manifest, {}, 'python', None, record)
            self.assertEqual(record['cohort']['version'], current)
            self.assertEqual((home / 'current').read_text(), current)
            self.assertEqual((home / 'control-version').read_text(), newer)
            self.assertEqual((home / 'setup-current').read_text(), newer)
            self.assertFalse(owner.pending(home))

    def test_shared_completion_records_success_only_after_required_delivery(self):
        for failure in (None, OSError('shortcut unavailable'), SystemExit(7)):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as temporary:
                owner, home, backend, _, shortcuts, _, new = self.fixture(Path(temporary))
                if isinstance(failure, OSError):
                    (home / owner.RECEIPT).unlink()  # An older coherent install has no cohort receipt.
                    launcher = home / 'native_launch.py'
                    launcher.write_bytes(launcher.read_bytes().replace(b'\n', b'\r\n'))
                    statefile = home / 'mixed-router-state.json'
                    state = dict(json.loads(statefile.read_text()), last_error='installer_failed')
                    statefile.write_text(json.dumps(state))
                delivery = module('install_delivery')
                real = delivery._load
                delivery._load = lambda name: owner if name == 'windows_installation' else real(name)
                args = SimpleNamespace(home=str(home), dry_run=False)
                def install(record):
                    owner.begin(home, new, backend)
                    prepared = dict(self.activate(owner, home, new), version=new, started=True)
                    record.update(cohort=prepared, backend=backend, installed_version=new)
                    backend._run_task(owner.TASKS[0], home)
                    if isinstance(failure, OSError):
                        def verify(_, retained, *args, **kwargs):
                            if retained.name == new:
                                raise failure
                        shortcuts.verify.side_effect = verify
                    elif failure:
                        raise failure  # Attachment failure is outside the required cohort.
                    return 0
                with mock.patch.object(delivery, 'finish'), contextlib.redirect_stdout(io.StringIO()) as output:
                    if failure:
                        with self.assertRaises(SystemExit) as stopped:
                            delivery.run_install(args, install, run=mock.Mock(), fetch=None)
                        self.assertEqual(stopped.exception.code, 0 if isinstance(failure, OSError) else 7)
                    else:
                        self.assertEqual(delivery.run_install(args, install, run=mock.Mock(), fetch=None), 0)
                log = home / 'logs/update.log'
                if isinstance(failure, OSError):
                    self.assertFalse(log.exists())
                    self.assertIn('deferred:', output.getvalue())
                    state = json.loads((home / 'mixed-router-state.json').read_text())
                    self.assertFalse(module('update_status').summary(state)['offer_repair'])
                else:
                    self.assertIn('installed ' + new, log.read_text())
                self.assertTrue(owner.ready(home))

    def test_unavailable_snapshot_before_activation_retries_without_repair(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home, backend, _, _, _, new = self.fixture(Path(temporary))
            backend.snapshot_cohort = mock.Mock(side_effect=OSError('temporary scheduler failure'))
            with self.assertRaises(SystemExit) as stopped, contextlib.redirect_stdout(io.StringIO()):
                owner.activate(home, dict(version=new), backend)
            self.assertEqual(stopped.exception.code, 0)
            self.assertFalse(owner.pending(home))
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.assertFalse(module('update_status').summary(state)['offer_repair'])

    def test_retry_recaptures_a_schedule_disabled_after_legacy_restoration(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home, backend, table, _, _, new = self.fixture(Path(temporary))
            (home / owner.RECEIPT).unlink()
            (home / 'control-version').write_text('1.3.20.214')  # An actually mixed prior installation.
            owner.begin(home, new, backend)
            self.activate(owner, home, new)
            self.assertEqual(owner.restore(home, backend), 'restored_mixed')
            table.call(owner.TASKS[2], home, 'disable')
            owner.begin(home, new, backend)
            saved = json.loads((home / owner.JOURNAL).read_text())
            self.assertFalse(saved['tasks']['current'][owner.TASKS[2]]['enabled'])
            prepared = self.activate(owner, home, new)
            backend._run_task(owner.TASKS[0], home)
            owner.complete(home, prepared, backend)
            self.assertFalse(table.rows[False, owner.TASKS[2]]['enabled'])
