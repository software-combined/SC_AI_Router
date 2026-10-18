"""A signed Resources map covers five untampered targets from one core bundle."""
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tests import test_publish_feed as feed_fixtures
from tests.test_native_setup import module

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_resources_publish', ROOT / 'tools/native_resources_publish.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class ResourcesPublicationTests(unittest.TestCase):
    def fixture(self, root, core='a' * 64):
        latest = dict(version='1.3.0.9', sha256=core)
        for target in publisher.stage.TARGETS:
            name = 'scg-router-resources-1.3.0.9-' + target.replace('/', '-') + '.tar.gz'
            data = ('validated ' + target).encode()
            (root / name).write_bytes(data)
            (root / (name + '.resources.json')).write_text(json.dumps(dict(
                file=name, target=target, version=latest['version'], bundle_sha256=latest['sha256'],
                sha256=hashlib.sha256(data).hexdigest(), size=len(data))))
        return latest

    def test_five_exact_archives_become_public_descriptors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            latest = self.fixture(root)
            rows = publisher.records(root, latest)
            self.assertEqual(set(rows), set(publisher.stage.TARGETS))
            for target, row in rows.items():
                self.assertTrue(row['url'].startswith(publisher.ORIGIN + '/bundles/'))
                self.assertEqual(row['bundle_sha256'], latest['sha256'])
                self.assertNotIn('file', row)

    def test_tampered_missing_and_wrong_core_archives_are_refused(self):
        for defect in ('tampered', 'missing', 'wrong-core'):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                latest = self.fixture(root)
                receipt = next(root.glob('*.resources.json'))
                doc = json.loads(receipt.read_text())
                if defect == 'tampered':
                    (root / doc['file']).write_bytes(b'changed')
                elif defect == 'missing':
                    receipt.unlink()
                else:
                    doc['bundle_sha256'] = 'b' * 64
                    receipt.write_text(json.dumps(doc))
                with self.assertRaises(ValueError):
                    publisher.records(root, latest)

    def test_publication_signs_map_and_uploads_every_archive_before_channel_pointer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist, native = root / 'dist', root / 'native'
            dist.mkdir()
            native.mkdir()
            core = b'core bundle'
            latest = self.fixture(native, hashlib.sha256(core).hexdigest())
            name = 'ai-router-' + latest['version'] + '.tar.gz'
            latest.update(url=feed_fixtures.GITHUB_BASE + '/v1.3.0/' + name, serial=9, min_python='3.14')
            (dist / name).write_bytes(core)
            (dist / 'latest.json').write_text(json.dumps(latest))
            verify = module('feed_verify')
            seed, public = verify.generate_keypair()
            (root / 'seed').write_text(seed)
            runner = feed_fixtures._Aws()
            with mock.patch.object(feed_fixtures.publish, 'run', runner), redirect_stdout(io.StringIO()):
                self.assertEqual(feed_fixtures.publish.main(['--dist', str(dist), '--channel', 'beta',
                    '--bucket', 'fixture', '--sign', str(root / 'seed'), '--native-resources', str(native)]), 0)
            body = (dist / 'feed-latest.json').read_bytes()
            signature = (dist / 'feed-latest.json.sig').read_text().strip()
            self.assertTrue(verify.verify_hex(public, body, signature))
            rows = json.loads(body)['native_resources']
            self.assertEqual(set(rows), set(publisher.stage.TARGETS))
            changed = json.loads(body)
            changed['native_resources'][next(iter(rows))]['size'] += 1
            self.assertFalse(verify.verify_hex(public, json.dumps(changed).encode(), signature))
            pointer = next(i for i, call in enumerate(runner.calls) if 's3://fixture/beta/latest.json' in call)
            uploads = [(i, call[call.index('--key') + 1]) for i, call in enumerate(runner.calls)
                       if 'put-object' in call]
            self.assertEqual(len(uploads), 6)
            self.assertTrue(all(i < pointer for i, _ in uploads))
            self.assertEqual({key for _, key in uploads}, {'bundles/' + name} |
                             {'bundles/' + row['url'].rsplit('/', 1)[1] for row in rows.values()})

    def test_missing_native_target_aborts_publication_before_any_remote_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            latest = self.fixture(root, hashlib.sha256(b'core').hexdigest())
            next(root.glob('*.resources.json')).unlink()
            name = 'ai-router-' + latest['version'] + '.tar.gz'
            latest.update(url=feed_fixtures.GITHUB_BASE + '/v1.3.0/' + name, serial=9, min_python='3.14')
            (root / name).write_bytes(b'core')
            (root / 'latest.json').write_text(json.dumps(latest))
            runner = feed_fixtures._Aws()
            with mock.patch.object(feed_fixtures.publish, 'run', runner), self.assertRaises(ValueError):
                feed_fixtures.publish.main(['--dist', str(root), '--channel', 'beta', '--bucket', 'fixture',
                    '--native-resources', str(root)])
            self.assertEqual(runner.calls, [])
