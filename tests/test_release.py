import hashlib
import json
import shutil
import subprocess
import sys
import importlib.util
import tarfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _release_mod():
    spec = importlib.util.spec_from_file_location('router_release', _ROOT / 'packaging' / 'release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release_mod = _release_mod()


class ReleaseTests(unittest.TestCase):
    def test_bundle_contains_manifest_with_matching_hashes(self):
        out = _ROOT / 'dist-test-tmp'
        self.addCleanup(shutil.rmtree, str(out), True)
        release_mod.main(['--out', str(out), '--url-base', 'file:///tmp/feed'])
        files = list(out.iterdir())
        self.assertEqual(len(files), 2)
        tarball = next(p for p in files if p.suffix == '.gz')
        latest = json.loads((out / 'latest.json').read_text())
        self.assertEqual(latest['sha256'], hashlib.sha256(tarball.read_bytes()).hexdigest())
        with tarfile.open(tarball, mode='r') as tar:
            manifest = json.loads(tar.extractfile('MANIFEST.json').read())
            for name, want in manifest['files'].items():
                got = hashlib.sha256(tar.extractfile(name).read()).hexdigest()
                self.assertEqual(got, want, name)
        self.assertIn('packaging/install.py', manifest['files'])

    def test_build_is_deterministic(self):
        outs = []
        for tag in ('det-a', 'det-b'):
            out = _ROOT / f'dist-test-{tag}'
            outs.append(out)
            self.addCleanup(shutil.rmtree, str(out), True)
            result = subprocess.run([sys.executable, 'packaging/release.py', '--out', str(out)],
                                    cwd=str(_ROOT), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        first = sorted(outs[0].glob('*.tar.gz'))[0].read_bytes()
        second = sorted(outs[1].glob('*.tar.gz'))[0].read_bytes()
        self.assertEqual(hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest())

    def test_bundle_has_no_pycache(self):
        out = _ROOT / 'dist-test-nocache'
        self.addCleanup(shutil.rmtree, str(out), True)
        release_mod.main(['--out', str(out)])
        tarball = next(iter(out.glob('*.tar.gz')))
        with tarfile.open(tarball, mode='r') as tar:
            names = tar.getnames()
        self.assertFalse([n for n in names if '__pycache__' in n or n.endswith('.pyc')])
        self.assertIn('MANIFEST.json', names)

    def test_bundle_covers_runtime_import_closure(self):
        out = _ROOT / 'dist-test-closure'
        self.addCleanup(shutil.rmtree, str(out), True)
        release_mod.main(['--out', str(out)])
        tarball = next(iter(out.glob('*.tar.gz')))
        with tarfile.open(tarball, mode='r') as tar:
            names = tar.getnames()
        for dep in ('codex_router/models.json',
                    'codex_router/openrouter_base_instructions.txt',
                    'packaging/router_launch.py',
                    'packaging/service.py',
                    'packaging/updater.py',
                    'packaging/platforms/__init__.py',
                    'packaging/platforms/darwin.py',
                    'packaging/platforms/linux.py'):
            self.assertIn(dep, names, dep)
        extract = out / 'extracted'
        extract.mkdir()
        with tarfile.open(tarball, mode='r') as tar:
            tar.extractall(extract, filter='data')
        result = subprocess.run(
            [sys.executable, '-c',
             'from codex_router.registry import MODELS; print(len(MODELS))'],
            cwd=str(extract), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater(int(result.stdout.strip()), 0)
        # The full runtime import closure must load from the extraction:
        # handler, providers, setup, catalogue, and installer backends.
        result = subprocess.run(
            [sys.executable, '-c',
             'from codex_router import router, providers, setup, catalogue;'
             'from codex_router import registry, compaction, tool_adapter;'
             'print(len(registry.MODELS))'],
            cwd=str(extract), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater(int(result.stdout.strip()), 0)
        # A deliberately incomplete extraction must fail its smoke with a
        # specific missing dependency, proving the check is not vacuous.
        missing = extract / 'codex_router' / 'providers.py'
        missing.unlink()
        result = subprocess.run(
            [sys.executable, '-c',
             'from codex_router import router'],
            cwd=str(extract), capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('providers', result.stderr)
        # The extracted installer must reach its extracted updater helper
        # without checkout imports; omitting updater.py must fail the smoke.
        result = subprocess.run(
            [sys.executable, 'packaging/install.py', '--help'],
            cwd=str(extract), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
