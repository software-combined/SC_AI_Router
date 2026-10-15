"""Offline native staging contracts and archive boundary checks."""

import gzip
import hashlib
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'packaging' / 'native'))
import native_stage as stage  # noqa: E402


def _archive(files, *, special=None, duplicates=()):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as tar:
        for name, data in files.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            tar.addfile(entry, io.BytesIO(data))
        for name, data in duplicates:
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            tar.addfile(entry, io.BytesIO(data))
        if special is not None:
            tar.addfile(special)
    return gzip.compress(stream.getvalue(), mtime=0)


def _bundle(channel='stable', *, extra=None, bad_digest=False,
            duplicate=None):
    version = '1.2.3.4'
    files = {
        'packaging/VERSION': (version + '\n').encode(),
        'packaging/native_setup.py': b'print("setup")\n',
        'packaging/install.py': b'print("install")\n',
        'packaging/assets/router-icon.png': b'PNG fixture',
    }
    files.update(extra or {})
    digests = {name: hashlib.sha256(data).hexdigest()
               for name, data in files.items()}
    if bad_digest:
        digests['packaging/native_setup.py'] = '0' * 64
    manifest = {'version': version, 'channel': channel, 'files': digests}
    files['MANIFEST.json'] = json.dumps(manifest).encode()
    return _archive(files, duplicates=[duplicate] if duplicate else ())


def _runtime(target, *, special=None):
    windows = target.startswith('windows/')
    if windows:
        files = {'python/python.exe': b'console interpreter',
                 'python/pythonw.exe': b'GUI interpreter',
                 'python/LICENSE.txt': b'Python licence'}
    else:
        files = {'python/bin/python3.14': b'private interpreter',
                 'python/lib/python3.14/LICENSE.txt': b'Python licence'}
    return _archive(files, special=special)


def _lock(target, blob):
    os_name, cpu = target.split('/')
    windows = os_name == 'windows'
    entry = {
        'os': os_name, 'cpu': cpu, 'triple': 'fixture',
        'url': 'https://example.invalid/runtime.tar.gz',
        'mirror': 'runtimes/fixture.tar.gz', 'format': 'tar.gz',
        'sha256': hashlib.sha256(blob).hexdigest(),
        'exec': 'python/python.exe' if windows else 'python/bin/python3.14',
        'licences': (['python/LICENSE.txt'] if windows else
                     ['python/lib/python3.14/LICENSE.txt']),
    }
    if os_name == 'linux':
        entry['libc'] = 'glibc'
    return {'cpython': '3.14.7', 'build': 'fixture', 'targets': [entry]}


class NativeStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _inputs(self, target, *, bundle=None, runtime=None):
        bundle = _bundle() if bundle is None else bundle
        runtime = _runtime(target) if runtime is None else runtime
        paths = [self.root / 'bundle.tar.gz', self.root / 'runtime.tar.gz',
                 self.root / 'runtime.lock']
        paths[0].write_bytes(bundle)
        paths[1].write_bytes(runtime)
        paths[2].write_text(json.dumps(_lock(target, runtime)))
        return paths

    def test_stages_each_target_with_local_sibling_feed(self):
        for target in stage.TARGETS:
            with self.subTest(target=target):
                bundle, runtime, lock = self._inputs(target)
                resources = self.root / target.replace('/', '-')
                meta = stage.stage(bundle, runtime, target, 'stable',
                                   resources, lock_path=lock)
                self.assertEqual(meta['target'], target)
                self.assertEqual(meta['native_signature'], 'unsigned')
                self.assertEqual(meta['runtime_sha256'],
                                 hashlib.sha256(runtime.read_bytes()).hexdigest())
                self.assertTrue((resources / 'runtime' / meta['runtime_exec']).is_file())
                self.assertTrue((resources / 'router' / 'MANIFEST.json').is_file())
                payload = resources / 'payload'
                latest = json.loads((payload / 'latest.json').read_text())
                self.assertEqual(latest['url'], 'file://bundle.tar.gz')
                self.assertEqual(latest['sha256'],
                                 hashlib.sha256((payload / 'bundle.tar.gz').read_bytes()).hexdigest())
                self.assertEqual(json.loads((resources / 'installer.json').read_text()), meta)

    def test_runtime_for_other_target_is_refused_before_staging(self):
        bundle, runtime, lock = self._inputs('linux/x86_64')
        runtime.write_bytes(_runtime('linux/arm64') + b'other target')
        resources = self.root / 'Resources'
        with self.assertRaisesRegex(ValueError, 'pinned target sha256'):
            stage.stage(bundle, runtime, 'linux/x86_64', 'stable',
                        resources, lock_path=lock)
        self.assertFalse(resources.exists())

    def test_malicious_bundle_paths_and_symlinks_are_refused(self):
        for member in ('../escape', '/absolute', 'C:/drive', 'folder\\escape'):
            with self.subTest(member=member):
                bundle, runtime, lock = self._inputs(
                    'darwin/arm64', bundle=_bundle(extra={member: b'bad'}))
                with self.assertRaisesRegex(ValueError, 'unsafe'):
                    stage.stage(bundle, runtime, 'darwin/arm64', 'stable',
                                self.root / 'Resources', lock_path=lock)
        link = tarfile.TarInfo('escape-link')
        link.type = tarfile.SYMTYPE
        link.linkname = '../../outside'
        bundle, runtime, lock = self._inputs(
            'darwin/arm64', runtime=_runtime('darwin/arm64', special=link))
        with self.assertRaises((ValueError, tarfile.TarError)):
            stage.stage(bundle, runtime, 'darwin/arm64', 'stable',
                        self.root / 'Resources', lock_path=lock)

    def test_bundle_manifest_and_channel_must_match(self):
        bundle, runtime, lock = self._inputs('windows/x86_64',
                                             bundle=_bundle(bad_digest=True))
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            stage.stage(bundle, runtime, 'windows/x86_64', 'stable',
                        self.root / 'Resources', lock_path=lock)
        bundle.write_bytes(_bundle('beta'))
        with self.assertRaisesRegex(ValueError, 'channel'):
            stage.stage(bundle, runtime, 'windows/x86_64', 'stable',
                        self.root / 'Resources', lock_path=lock)

    def test_only_manifest_identical_duplicate_files_are_accepted(self):
        identical = ('packaging/install.py', b'print("install")\n')
        bundle, runtime, lock = self._inputs('darwin/arm64',
                                             bundle=_bundle(duplicate=identical))
        stage.stage(bundle, runtime, 'darwin/arm64', 'stable',
                    self.root / 'Resources', lock_path=lock)
        bundle.write_bytes(_bundle(duplicate=('packaging/install.py', b'changed')))
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            stage.stage(bundle, runtime, 'darwin/arm64', 'stable',
                        self.root / 'other-Resources', lock_path=lock)

    def test_windows_requires_private_gui_interpreter(self):
        runtime = _archive({'python/python.exe': b'console interpreter',
                            'python/LICENSE.txt': b'Python licence'})
        bundle, runtime_path, lock = self._inputs('windows/x86_64', runtime=runtime)
        with self.assertRaisesRegex(ValueError, 'GUI interpreter'):
            stage.stage(bundle, runtime_path, 'windows/x86_64', 'stable',
                        self.root / 'Resources', lock_path=lock)

    def test_optional_public_download_config_rejects_credentials_and_url_tricks(self):
        bundle, runtime, lock = self._inputs('darwin/arm64')
        public = {
            'version': 1,
            'distribution_origin': 'https://dist.softwarecombined.com',
            'tenant_id': '11111111-1111-4111-8111-111111111111',
            'client_id': '22222222-2222-4222-8222-222222222222',
            'scope': 'api://33333333-3333-4333-8333-333333333333/Download.Read',
            'exchange_url':
                'https://abcd1234.execute-api.ap-southeast-2.amazonaws.com/download-access',
        }
        config = self.root / 'download-auth.json'
        config.write_text(json.dumps(public))
        resources = self.root / 'Resources'
        stage.stage(bundle, runtime, 'darwin/arm64', 'stable', resources,
                    lock_path=lock, download_config=config)
        self.assertEqual(json.loads((resources / 'download-auth.json').read_text()),
                         public)
        for change in ({'bearer_token': 'secret'},
                       {'exchange_url': public['exchange_url'] + '?token=secret'},
                       {'scope': 'api://wrong/Download.Read'}):
            with self.subTest(change=change):
                config.write_text(json.dumps(public | change))
                with self.assertRaises(ValueError):
                    stage.stage(bundle, runtime, 'darwin/arm64', 'stable',
                                self.root / 'bad-resources', lock_path=lock,
                                download_config=config)
                self.assertFalse((self.root / 'bad-resources').exists())


if __name__ == '__main__':
    unittest.main()
