"""A downloaded native installer must not become a service dependency."""
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(
        'test_router_' + name, ROOT / 'packaging' / (name + '.py'))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


payload = module('native_payload')


def resources(root, version='1.2.0', channel='stable'):
    root.mkdir(parents=True)
    for folder in ('runtime/python/bin', 'router/packaging', 'payload'):
        (root / folder).mkdir(parents=True)
    (root / 'runtime/python/bin/python3.14').write_text('bundled Python')
    for name in ('install.py', 'native_setup.py'):
        (root / 'router/packaging' / name).write_text('# packaged entrypoint\n')
    blob = b'packaged-router'
    sha = hashlib.sha256(blob).hexdigest()
    (root / 'payload/bundle.tar.gz').write_bytes(blob)
    doc = dict(version=version, channel=channel, sha256=sha,
               target=payload.target(), runtime_exec='python/bin/python3.14')
    (root / 'installer.json').write_text(json.dumps(doc))
    (root / 'payload/latest.json').write_text(json.dumps(
        dict(version=version, sha256=sha, url='file://bundle.tar.gz')))
    return root


class NativePayloadTests(unittest.TestCase):
    def test_desktop_only_guides_missing_plugin_setup_tools_before_installing(self):
        setup = module('native_setup')
        dialog = mock.Mock()
        dialog.confirm.return_value = False
        with mock.patch('shutil.which', return_value=None), \
                mock.patch.object(setup.webbrowser, 'open') as browser:
            self.assertTrue(setup._missing_assistant(['--clients', 'none', '--desktop'], dialog))
        self.assertIn('Claude desktop', dialog.confirm.call_args.args[0])
        browser.assert_not_called()

    def test_retains_files_before_the_download_is_deleted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            download = resources(root / 'download')
            kept = payload.retained(download, root / 'installed')
            shutil.rmtree(download)
            args = payload.install_arguments(kept, root / 'installed')
            self.assertTrue(Path(args[0]).is_file())
            self.assertTrue(Path(args[1]).is_file())
            self.assertTrue((kept / 'payload/bundle.tar.gz').is_file())
            self.assertNotIn(str(download), ' '.join(args))

    def test_reopening_keeps_existing_client_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = resources(root / 'download', channel='stable')
            home = root / 'home'
            home.mkdir()
            (home / 'channel').write_text('beta\n')
            (home / 'feed').write_text('file:///managed/feed.json\n')
            args = payload.install_arguments(source, home, {'clients': 'claude'})
            self.assertEqual(args[args.index('--clients') + 1], 'claude')
            self.assertNotIn('--choose-clients', args)
            self.assertEqual((home / 'channel').read_text(), 'beta\n')
            self.assertEqual((home / 'feed').read_text(), 'file:///managed/feed.json\n')

    def test_refuses_a_tampered_bundle_before_creating_the_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = resources(root / 'download')
            (source / 'payload/bundle.tar.gz').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'verification'):
                payload.retained(source, root / 'home')
            self.assertFalse((root / 'home').exists())

    def test_refuses_a_foreign_runtime_and_an_escaping_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = resources(Path(temporary) / 'download')
            with self.assertRaisesRegex(ValueError, 'not for this computer'):
                payload.metadata(source, 'unsupported/cpu')
            path = source / 'installer.json'
            doc = json.loads(path.read_text())
            doc['runtime_exec'] = '../outside'
            path.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError, 'Python'):
                payload.metadata(source)


class IndependentControllerTests(unittest.TestCase):
    def test_rollback_and_pruning_do_not_change_the_update_controller(self):
        controller = module('native_controller')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / 'home'
            source = root / 'source'
            (source / 'packaging').mkdir(parents=True)
            files = {'packaging/install.py': b'# independent updater\n',
                     'packaging/VERSION': b'1.2.0\n'}
            for name, content in files.items():
                (source / name).write_bytes(content)
            (source / 'MANIFEST.json').write_text(json.dumps(dict(
                version='1.2.0', files={name: hashlib.sha256(content).hexdigest()
                                       for name, content in files.items()})))
            controller.install(home, source)
            (home / 'current').write_text('0.9.0\n')
            shutil.rmtree(source)
            selected = controller.installer(home)
            self.assertEqual(selected.read_text(), '# independent updater\n')
            self.assertNotIn('/releases/', str(selected))


if __name__ == '__main__':
    unittest.main()
