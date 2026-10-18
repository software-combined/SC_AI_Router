"""Canonical installs and cached update checks repair the independently delivered menu."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests import test_native_resources as resource_fixtures
from tests.test_native_setup import module


class DesktopDeliveryTests(unittest.TestCase):
    def fixture(self, root):
        resources, home, latest, data = resource_fixtures.NativeResourcesTests().fixture(root)
        latest.update(url='file:///core.tar.gz', min_python='3.14', serial=1)
        state = {'clients': 'none'}
        module('update_status').verified(state, latest, 'file:///latest.json', 'stable', 'cached')
        (home / 'mixed-router-state.json').write_text(json.dumps(state))
        (home / 'update-etag').write_text('cached\n')
        return resources, home, latest, data

    def shortcuts(self, owner):
        original = owner.load
        def install(home, permanent, python):
            (home / 'setup-current').write_text(permanent.name + '\n')
        return mock.patch.object(owner, 'load', side_effect=lambda name:
            SimpleNamespace(install=install) if name == 'native_shortcuts' else original(name))

    def update(self, owner, home, latest, data, reader):
        args = SimpleNamespace(home=str(home), feed='file:///latest.json', express_only=False)
        fetch = mock.Mock(return_value=data)
        with mock.patch.object(owner._models, 'refresh'), self.shortcuts(owner._resources), \
                mock.patch.object(owner, '_offer_notices'), contextlib.redirect_stdout(io.StringIO()):
            rc = owner.do_update(args, _fetch=fetch, _read_feed=reader,
                                 _sleep=lambda _: None, _announce=lambda *_: None)
        self.assertEqual(rc, 0)
        return fetch

    def test_cached_same_version_repairs_then_uses_cache_without_redownloading(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, home, latest, data = self.fixture(Path(temporary))
            updater = module('updater')
            reader = mock.Mock(side_effect=[(304, b'', 'cached'),
                (200, json.dumps(latest).encode(), 'fresh')])
            fetch = self.update(updater, home, latest, data, reader)
            self.assertEqual(reader.call_args_list, [mock.call('file:///latest.json', 'cached'),
                                                    mock.call('file:///latest.json', None)])
            fetch.assert_called_once_with(latest['native_resources'][updater._resources.target()]['url'])
            self.assertTrue(updater._resources.ready(home))
            reader = mock.Mock(return_value=(304, b'', 'fresh'))
            self.update(updater, home, latest, data, reader).assert_not_called()
            reader.assert_called_once_with('file:///latest.json', 'fresh')

    def test_failed_menu_delivery_retries_cached_feed_and_preserves_core(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, home, latest, data = self.fixture(Path(temporary))
            updater = module('updater')
            (home / 'setup-current').write_text('previous-menu\n')
            reader = mock.Mock(return_value=(200, json.dumps(latest).encode(), 'fresh'))
            self.update(updater, home, latest, data + b'corrupt', reader)
            self.assertEqual((home / 'current').read_text(), latest['version'])
            self.assertEqual((home / 'setup-current').read_text(), 'previous-menu\n')
            self.assertEqual(json.loads((home / 'desktop-delivery.json').read_text())['status'], 'failed')
            reader = mock.Mock(side_effect=[(304, b'', 'fresh'),
                (200, json.dumps(latest).encode(), 'fresh')])
            self.update(updater, home, latest, data, reader)
            self.assertTrue(updater._resources.ready(home))
            self.assertEqual((home / 'current').read_text(), latest['version'])

    def test_menu_delivery_defers_during_client_transition_and_keeps_etag(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, home, latest, data = self.fixture(Path(temporary))
            updater = module('updater')
            with updater._svc.install_lock(home) as held:
                self.assertTrue(held)
                reader = mock.Mock(return_value=(200, json.dumps(latest).encode(), 'fresh'))
                self.update(updater, home, latest, data, reader).assert_not_called()
            self.assertEqual((home / 'update-etag').read_text(), 'cached\n')
            self.assertFalse((home / 'setup-current').exists())

    def test_canonical_same_version_installer_delivers_menu_without_core_or_key_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, home, latest, data = self.fixture(Path(temporary))
            installer = module('install')
            args = installer.build_parser().parse_args(['--home', str(home), '--feed', 'file:///latest.json'])
            fetch = mock.Mock(side_effect=lambda url: json.dumps(latest).encode()
                              if url.endswith('latest.json') else data)
            real = installer._delivery._load
            owner = module('native_resources')
            with self.shortcuts(owner), mock.patch.object(installer._delivery, '_load',
                    side_effect=lambda name: owner if name == 'native_resources' else real(name)), \
                    mock.patch.object(installer, 'platform_backend', return_value=mock.Mock()), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(installer.do_install(args, _fetch=fetch), 0)
            self.assertTrue(owner.ready(home))
            self.assertEqual((home / 'current').read_text(), latest['version'])
            self.assertFalse((home / 'openrouter.key').exists())

    def test_runtime_rollback_keeps_newer_working_menu(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home, latest, data = self.fixture(Path(temporary))
            with self.shortcuts(owner):
                self.assertTrue(owner.deliver(home, latest, 'file:///latest.json', lambda _: data))
            pointer = (home / 'setup-current').read_bytes()
            (home / 'releases/1.2.11').mkdir()
            (home / 'current').write_text('1.2.11')
            self.assertTrue(owner.ready(home))
            self.assertEqual((home / 'setup-current').read_bytes(), pointer)
            record = (home / 'desktop-delivery.json').read_bytes()
            older = json.loads(json.dumps(latest))
            older.update(version='1.2.11', sha256='b' * 64)
            older['native_resources'][owner.target()].update(version='1.2.11', bundle_sha256='b' * 64)
            fetch = mock.Mock(return_value=data)
            with self.shortcuts(owner):
                self.assertFalse(owner.deliver(home, older, 'file:///latest.json', fetch))
            fetch.assert_not_called()
            self.assertEqual((home / 'setup-current').read_bytes(), pointer)
            self.assertEqual((home / 'desktop-delivery.json').read_bytes(), record)
