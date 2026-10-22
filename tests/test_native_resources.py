"""Signed native delivery repairs missing controls without changing routing."""
import hashlib
import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_native_setup import module, resources


class NativeResourcesTests(unittest.TestCase):
    def fixture(self, root):
        owner = module('native_resources')
        original = owner.load
        owner.load = lambda name: (SimpleNamespace(reconcile=lambda _: 'inactive')
            if name == 'runtime_rebind' else original(name))
        source = resources(root / 'Resources', version='1.3.0.9')
        helper = source / 'control/scg-router-menu'
        if owner.target().startswith('windows/'):
            helper = helper.with_suffix('.exe')
        helper.parent.mkdir()
        helper.write_bytes(b'native helper')
        helper.chmod(0o755)
        doc = json.loads((source / 'installer.json').read_text())
        doc['menu_sha256'] = hashlib.sha256(helper.read_bytes()).hexdigest()
        (source / 'installer.json').write_text(json.dumps(doc))
        blob = io.BytesIO()
        with tarfile.open(fileobj=blob, mode='w:gz') as stream:
            stream.add(source, arcname='Resources')
        data = blob.getvalue()
        row = dict(url='https://dist.softwarecombined.com/bundles/resources.tar.gz',
                   version=doc['version'], bundle_sha256=doc['sha256'],
                   sha256=hashlib.sha256(data).hexdigest(), size=len(data))
        latest = dict(version=doc['version'], sha256=doc['sha256'], native_resources={owner.target(): row})
        home = root / 'home'
        home.mkdir()
        (home / 'releases' / doc['version']).mkdir(parents=True)
        (home / 'current').write_text(doc['version'])
        return owner, home, latest, data

    def test_only_matching_target_is_downloaded_and_opt_out_survives(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home, latest, data = self.fixture(Path(temporary))
            latest['native_resources']['unused/cpu'] = {'url': 'https://untrusted.invalid'}
            (home / 'desktop-preferences.json').write_text('{"autostart":false}')
            fetch = mock.Mock(return_value=data)
            original = owner.load
            def install(home, permanent, python):
                (home / 'setup-current').write_text(permanent.name)
            with mock.patch.object(owner, 'load', side_effect=lambda name:
                    SimpleNamespace(install=install) if name == 'native_shortcuts' else original(name)):
                self.assertTrue(owner.deliver(home, latest, 'https://dist.softwarecombined.com/stable/latest.json', fetch))
                self.assertTrue(owner.deliver(home, latest, 'https://dist.softwarecombined.com/stable/latest.json', fetch))
            fetch.assert_called_once_with(latest['native_resources'][owner.target()]['url'])
            self.assertTrue(owner.ready(home))
            self.assertEqual((home / 'desktop-preferences.json').read_text(), '{"autostart":false}')
            self.assertEqual((home / 'current').read_text(), latest['version'])

    def test_corrupt_archive_keeps_previous_menu_pointer_and_reports_delivery_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home, latest, data = self.fixture(Path(temporary))
            (home / 'setup-current').write_text('previous-menu\n')
            self.assertFalse(owner.deliver(home, latest, 'https://dist.softwarecombined.com/stable/latest.json',
                                           lambda url: data + b'changed'))
            self.assertEqual((home / 'setup-current').read_text(), 'previous-menu\n')
            self.assertEqual(json.loads((home / 'desktop-delivery.json').read_text()), {'status': 'failed'})
            self.assertEqual((home / 'current').read_text(), latest['version'])

    def test_wrong_bundle_is_refused_before_download(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home, latest, data = self.fixture(Path(temporary))
            latest['native_resources'][owner.target()]['bundle_sha256'] = 'f' * 64
            fetch = mock.Mock(return_value=data)
            self.assertFalse(owner.deliver(home, latest, 'https://dist.softwarecombined.com/stable/latest.json', fetch))
            fetch.assert_not_called()
            self.assertFalse((home / 'setup-current').exists())

    def test_an_older_channel_skips_delivery_without_inventing_a_controls_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home, latest, data = self.fixture(Path(temporary))
            (home / 'current').write_text('9.9.10')
            state = home / 'mixed-router-state.json'
            for outcome in ('ready', 'failed'):
                state.write_text(json.dumps(dict(component_repairs={'controls': outcome})))
                before = state.read_bytes()
                fetch = mock.Mock(return_value=data)
                self.assertFalse(owner.deliver(home, latest,
                    'https://dist.softwarecombined.com/stable/latest.json', fetch))
                fetch.assert_not_called()
                self.assertEqual(state.read_bytes(), before)
                self.assertFalse((home / 'desktop-delivery.json').exists())

    def test_failed_shortcut_update_restores_previous_pointer(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home, latest, data = self.fixture(Path(temporary))
            previous = b'previous-menu\r\n'
            (home / 'setup-current').write_bytes(previous)
            original = owner.load
            fdopen = os.fdopen
            def windows_text(fd, mode, **kwargs):
                if kwargs.get('newline') is None:
                    kwargs['newline'] = '\r\n'
                return fdopen(fd, mode, **kwargs)
            def install(home, permanent, python):
                (home / 'setup-current').write_text(permanent.name)
                raise OSError('shortcut failure')
            with mock.patch.object(owner, 'load', side_effect=lambda name:
                    SimpleNamespace(install=install) if name == 'native_shortcuts' else original(name)), \
                    mock.patch.object(os, 'fdopen', side_effect=windows_text):
                self.assertFalse(owner.deliver(home, latest, 'https://dist.softwarecombined.com/stable/latest.json', lambda url: data))
            self.assertEqual((home / 'setup-current').read_bytes(), previous)

    def test_runtime_links_stay_inside_resources_and_escape_links_are_refused(self):
        owner = module('native_resources')
        for link in ('../../outside', '/outside'):
            with self.subTest(link=link), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = root / 'resources.tar.gz'
                with tarfile.open(archive, 'w:gz') as stream:
                    entry = tarfile.TarInfo('Resources/runtime/link')
                    entry.type, entry.linkname = tarfile.SYMTYPE, link
                    stream.addfile(entry)
                with self.assertRaises(ValueError):
                    owner.unpack(archive, root / 'extract')
                self.assertFalse((root / 'outside').exists())

    def test_same_version_repairs_damaged_retention_without_overwriting_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owner, home, latest, data = self.fixture(root)
            previous = owner.retained(root / 'Resources', home)
            helper = previous / 'control' / ('scg-router-menu.exe' if owner.target().startswith('windows/') else 'scg-router-menu')
            helper.write_bytes(b'damaged helper')
            self.assertFalse(owner.ready(home))
            original = owner.load
            def install(home, permanent, python):
                (home / 'setup-current').write_text(permanent.name)
            with mock.patch.object(owner, 'load', side_effect=lambda name:
                    SimpleNamespace(install=install) if name == 'native_shortcuts' else original(name)):
                self.assertTrue(owner.deliver(home, latest, 'https://dist.softwarecombined.com/stable/latest.json', lambda url: data))
            self.assertEqual(helper.read_bytes(), b'damaged helper')
            self.assertNotEqual(owner.current(home), previous)
            self.assertTrue(owner.ready(home))

    def test_newer_retained_resources_never_clear_an_unverified_controls_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owner, home, latest, data = self.fixture(root)
            source = root / 'Resources'
            doc = json.loads((source / 'installer.json').read_text())
            doc['version'] = '2.0.0'
            (source / 'installer.json').write_text(json.dumps(doc))
            feed = source / 'payload/latest.json'
            feed.write_text(json.dumps(dict(json.loads(feed.read_text()), version='2.0.0')))
            previous = owner.retained(source, home)
            (home / 'setup-current').write_text(previous.name)
            (home / 'desktop-delivery.json').write_text('{"status":"failed"}')
            state = home / 'mixed-router-state.json'
            state.write_text('{"component_repairs":{"controls":"failed"}}')
            before = state.read_bytes()
            fetch = mock.Mock(return_value=data)
            self.assertFalse(owner.deliver(home, latest,
                'https://dist.softwarecombined.com/stable/latest.json', fetch))
            self.assertEqual(state.read_bytes(), before)
            fetch.assert_not_called()
            self.assertFalse(owner.ready(home))
            self.assertFalse(owner.confirm_controls(home, source))
            self.assertEqual(state.read_bytes(), before)
            self.assertTrue(owner.confirm_controls(home, previous))
            self.assertTrue(owner.ready(home))
            self.assertEqual(json.loads(state.read_text())['component_repairs']['controls'], 'ready')

    def test_failed_delivery_receipt_retries_shortcuts_even_when_archive_hash_matches(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home, latest, data = self.fixture(Path(temporary))
            original = owner.load
            shortcuts = mock.Mock()
            shortcuts.install.side_effect = lambda home, permanent, python: (
                home / 'setup-current').write_text(permanent.name)
            fetch = mock.Mock(return_value=data)
            with mock.patch.object(owner, 'load', side_effect=lambda name:
                    shortcuts if name == 'native_shortcuts' else original(name)):
                self.assertTrue(owner.deliver(home, latest, 'file:///latest.json', fetch))
                receipt = home / 'desktop-delivery.json'
                receipt.write_text(json.dumps(dict(json.loads(receipt.read_text()), status='failed')))
                self.assertTrue(owner.deliver(home, latest, 'file:///latest.json', fetch))
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(shortcuts.install.call_count, 2)
            self.assertTrue(owner.ready(home))

    def test_controls_confirmation_preserves_an_independent_or_unapplied_install_warning(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owner, home, latest, _ = self.fixture(root)
            previous = owner.retained(root / 'Resources', home)
            (home / 'setup-current').write_text(previous.name)
            for assistants, applied in (('failed', latest['version']), ('unknown', latest['version']),
                                        ('ready', '0.0.0')):
                state = dict(component_repairs={'assistants': assistants, 'controls': 'failed'},
                             last_applied_version=applied, last_error='installer_failed',
                             installation_repair_required=True)
                path = home / 'mixed-router-state.json'
                path.write_text(json.dumps(state))
                self.assertTrue(owner.confirm_controls(home, previous))
                after = json.loads(path.read_text())
                self.assertEqual(after['component_repairs']['controls'], 'ready')
                self.assertEqual(after['component_repairs']['assistants'], assistants)
                self.assertTrue(after['installation_repair_required'])
                self.assertEqual(after['last_error'], 'installer_failed')

    def test_older_resources_cannot_confirm_newer_core_or_clear_repair_warnings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owner, home, _, _ = self.fixture(root)
            previous = owner.retained(root / 'Resources', home)
            (home / 'setup-current').write_text(previous.name)
            (home / 'releases/2.0.0').mkdir()
            (home / 'current').write_text('2.0.0')
            state = home / 'mixed-router-state.json'
            state.write_text(json.dumps(dict(last_applied_version='2.0.0',
                component_repairs={'assistants': 'ready', 'controls': 'failed'},
                last_error='installer_failed', installation_repair_required=True)))
            before = state.read_bytes()
            self.assertFalse(owner.confirm_controls(home, previous))
            self.assertFalse(owner.ready(home))
            self.assertEqual(state.read_bytes(), before)
            self.assertFalse((home / 'desktop-delivery.json').exists())
