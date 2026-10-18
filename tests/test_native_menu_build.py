"""Native menu build and Resources export contracts; no graphical session needed."""
import hashlib
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'packaging/native'))
import native_menu_build as build
import native_resources_archive as archive
from tests.test_native_setup import payload, resources as make_resources


class NativeMenuBuildTests(unittest.TestCase):
    def test_damaged_menu_is_detected_and_repair_retains_the_original_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = make_resources(root / 'Resources')
            helper = source / 'control' / ('scg-router-menu.exe' if sys.platform == 'win32' else 'scg-router-menu')
            helper.parent.mkdir()
            helper.write_bytes(b'original helper')
            doc = json.loads((source / 'installer.json').read_text())
            doc['menu_sha256'] = hashlib.sha256(helper.read_bytes()).hexdigest()
            (source / 'installer.json').write_text(json.dumps(doc))
            previous = payload.retained(source, root / 'home')
            damaged = previous / helper.relative_to(source)
            damaged.write_bytes(b'damaged')
            with self.assertRaisesRegex(ValueError, 'menu files'):
                payload.metadata(previous)
            repaired = payload.retained(source, root / 'home', repair=True)
            self.assertNotEqual(repaired, previous)
            self.assertEqual(damaged.read_bytes(), b'damaged')
            self.assertEqual(payload.metadata(repaired), doc)

    def test_foreign_runner_is_refused_before_build_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            resources = Path(temporary)
            with mock.patch.object(build.sys, 'platform', 'linux'), \
                    mock.patch.object(build.platform, 'machine', return_value='aarch64'):
                with self.assertRaisesRegex(ValueError, 'matching native'):
                    build.build(resources, 'windows/x86_64')
            self.assertEqual(list(resources.iterdir()), [])

    def test_native_compiler_result_is_bound_to_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            resources = Path(temporary)
            (resources / 'installer.json').write_text('{}')
            def run(command, **kwargs):
                Path(command[-1]).write_bytes(b'compiled helper')
            with mock.patch.object(build.sys, 'platform', 'darwin'), \
                    mock.patch.object(build.platform, 'machine', return_value='arm64'):
                helper = build.build(resources, 'darwin/arm64', run)
            self.assertEqual(json.loads((resources / 'installer.json').read_text())['menu_sha256'],
                             hashlib.sha256(helper.read_bytes()).hexdigest())
            self.assertTrue((resources / 'control/THIRD_PARTY_NOTICES.txt').is_file())

    def test_export_retains_runtime_links_and_binds_the_exact_core(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            resources = root / 'Resources'
            resources.mkdir()
            (resources / 'python').write_text('runtime')
            if sys.platform != 'win32':
                (resources / 'python3').symlink_to('python')
            metadata = dict(version='1.3.0.9', target='linux/arm64', sha256='a' * 64)
            path = archive.export(resources, root, metadata)
            descriptor = json.loads(path.with_suffix('.resources.json').read_text())
            self.assertEqual(descriptor['bundle_sha256'], 'a' * 64)
            self.assertEqual(descriptor['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(descriptor['size'], path.stat().st_size)
            with tarfile.open(path) as stream:
                self.assertIn('Resources/python', stream.getnames())
                if sys.platform != 'win32':
                    self.assertTrue(stream.getmember('Resources/python3').issym())
            with self.assertRaises(ValueError):
                archive.export(resources, root, metadata)
