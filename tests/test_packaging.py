import importlib.util
import re
import shutil
import tarfile
import json
import unittest
from pathlib import Path

# Only the members `packaging/release.py` cannot discover by globbing need an
# explicit contract: modules under ai_router/, tools/ and docs/ travel
# automatically, so a new module cannot be forgotten here.
EXPLICIT_FILES = (
    'LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md', 'README.md',
    'packaging/VERSION', 'packaging/install.py', 'packaging/bundle.py',
    'packaging/updater.py', 'packaging/router_launch.py',
    'packaging/service.py', 'packaging/feed.py', 'packaging/runtime.lock',
    'packaging/assets/router-icon.png',
    'packaging/install.sh', 'packaging/install.ps1',
)


def _release_module():
    spec = importlib.util.spec_from_file_location(
        'router_release', Path(__file__).resolve().parents[1] / 'packaging' / 'release.py')
    release_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release_mod)
    return release_mod

class PackagingTests(unittest.TestCase):
    def test_apache_only_licence_gate(self):
        root = Path(__file__).resolve().parents[1]
        for rel in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md',
                    'pyproject.toml', 'README.md',
                    '.codex-plugin/plugin.json', '.claude-plugin/plugin.json',
                    'packaging/release.py'):
            text = (root / rel).read_text().lower()
            for token in ('polyform', 'licenseref-polyform',
                          'commercial_license', 'unlicensed'):
                self.assertNotIn(token, text, rel)
        self.assertFalse((root / 'COMMERCIAL_LICENSE.md').exists())

    def test_wrappers_call_install_py(self):
        root = Path(__file__).resolve().parents[1] / 'packaging'
        sh, ps1 = (root / 'install.sh').read_text(), (root / 'install.ps1').read_text()
        self.assertIn('install.py', sh)
        self.assertIn('install.py', ps1)

    def test_file_list_covers_the_runtime_import_closure(self):
        # A fresh copy-install following the bundle inventory must start: every
        # module and data file ships, and the explicit contract below still
        # names the members globbing cannot discover.
        root = Path(__file__).resolve().parents[1]
        bundled = set(_release_module().bundle_files(root))
        for path in sorted((root / 'ai_router').rglob('*.py')):
            if '__pycache__' in path.parts:
                continue
            self.assertIn(path.relative_to(root).as_posix(), bundled,
                          'runtime module missing from the bundle')
        for dep in ('ai_router/models.json',
                    'ai_router/routed_base_instructions.txt',
                    'ai_router/subscription_base_instructions.txt'):
            self.assertIn(dep, bundled, dep)
        for tool in ('tools/probe_codex_runtime.py', 'tools/disable.py'):
            self.assertIn(tool, bundled, tool)
        for name in EXPLICIT_FILES:
            self.assertIn(name, bundled, name)

    def test_packaging_modules_are_all_bundled(self):
        # Every packaging module an installed release can load must be in the
        # release inventory; release.py is the publish-time tool and is the
        # one deliberate exclusion.
        root = Path(__file__).resolve().parents[1]
        bundled = set(_release_module().bundle_files(root))
        for path in sorted((root / 'packaging').rglob('*.py')):
            if '__pycache__' in path.parts:
                continue
            rel = path.relative_to(root).as_posix()
            if rel == 'packaging/release.py':
                continue
            self.assertIn(rel, bundled, 'packaging module missing from the release inventory')

    def test_runtime_file_list_matches_files(self):
        root = Path(__file__).resolve().parents[1]
        doc = (root / 'docs' / 'runtime-files.md').read_text()
        listed = set(re.findall(r'`((?:ai_router|tools)/[^`]+)`', doc))
        bundled = set(_release_module().bundle_files(root))
        # The page names the modules a reader looks for, not every member of the
        # inventory (release.py globs tools/ and docs/ wholesale), so each name
        # it does carry must resolve, and no runtime module may go unnamed.
        self.assertTrue(listed <= bundled,
                        'runtime-files.md names a file the bundle omits: '
                        + ', '.join(sorted(listed - bundled)))
        for module in sorted((root / 'ai_router').rglob('*.py')):
            if '__pycache__' in module.parts:
                continue
            rel = module.relative_to(root).as_posix()
            with self.subTest(module=rel):
                self.assertIn(rel, listed, 'runtime module missing from the page')

    def test_readme_quick_start_installs_its_own_build(self):
        # --url-base keeps the built feed pointing at the local tarball.
        root = Path(__file__).resolve().parents[1]
        blocks = re.findall(r'```(?:sh|powershell)\n(.*?)```',
                            (root / 'README.md').read_text(), re.S)
        release_blocks = [block for block in blocks if 'packaging/release.py' in block]
        self.assertEqual(len(release_blocks), 2)
        for block in release_blocks:
            self.assertIn('--url-base "file://$PWD/dist"', block)
        out = root / 'dist-test-readme-quick-start'
        self.addCleanup(shutil.rmtree, str(out), True)
        spec = importlib.util.spec_from_file_location(
            'release_quick_start', root / 'packaging' / 'release.py')
        release_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release_mod)
        release_mod.main(['--out', str(out), '--url-base', 'file://' + str(out)])
        latest = json.loads((out / 'latest.json').read_text())
        self.assertTrue(latest['url'].startswith('file://'))
        self.assertTrue(Path(latest['url'][len('file://'):]).is_file())

    def test_release_bundle_contains_deploy_list(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            'router_release', root / 'packaging' / 'release.py')
        release_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release_mod)
        out = root / 'dist-test-packaging'
        self.addCleanup(shutil.rmtree, str(out), True)
        release_mod.main(['--out', str(out)])
        tarball = next(out.glob('*.tar.gz'))
        with tarfile.open(tarball, mode='r') as tar:
            names = set(tar.getnames())
        # Single inventory (Plan 123): the tarball must match release.py's
        # bundle_files() exactly, neither missing a member nor shipping an
        # extra. EXPLICIT_FILES below stays an explicit list so a member
        # dropped from the inventory still fails this gate.
        self.assertEqual(names, set(release_mod.bundle_files(root)) | {'MANIFEST.json'})
        for name in EXPLICIT_FILES:
            self.assertIn(name, names, name)

    def test_activation_receipt_has_a_single_writer(self):
        # Plan 095: activation.json is written in exactly one module
        # (codex_config.py, through the shared atomic writer). A second
        # writer literal fails this closed so receipt schema changes
        # cannot silently drift across adapters again.
        root = Path(__file__).resolve().parents[1] / 'packaging'
        writers = sorted(path.relative_to(root).as_posix()
                         for path in root.rglob('*.py')
                         if '__pycache__' not in path.parts
                         and 'activation.json' in path.read_text())
        self.assertEqual(writers, ['codex_config.py'])

    def test_version_is_semver(self):
        version = (Path(__file__).resolve().parents[1] / 'packaging' / 'VERSION').read_text().strip()
        self.assertRegex(version, r'^\d+\.\d+\.\d+$')

    def test_pyproject_version_matches_packaging_version(self):
        # Plan 104: pyproject's version is a checked duplicate of the release
        # version; nothing else reads it, so drift is otherwise invisible.
        import tomllib
        root = Path(__file__).resolve().parents[1]
        version = (root / 'packaging' / 'VERSION').read_text().strip()
        pyproject = tomllib.loads((root / 'pyproject.toml').read_text())
        self.assertEqual(pyproject['project']['version'], version)

    def test_installer_surface_parses_as_python39(self):
        # Plan 061: the installer runs on Python 3.9+ while the router
        # needs 3.14. Plan 156 adds a real 3.9 import check
        # (tools/check_installer_python39.py); this test keeps the grammar
        # pin for every surface file, including the parse-only entry points.
        # feature_version misses PEP 604 unions (`X | Y` parses as BinOp
        # but raises at runtime on 3.9), so annotations get their own walk.
        import ast
        root = Path(__file__).resolve().parents[1]
        surface = []
        for line in (root / 'config' / 'installer-python-surface.txt').read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            mode, name = line.split()
            self.assertIn(mode, ('load', 'parse'))
            surface.append(name)
        self.assertTrue(surface)
        for name in surface:
            with self.subTest(name=name):
                src = (root / name).read_text()
                tree = ast.parse(src, filename=name, feature_version=(3, 9))
                for node in ast.walk(tree):
                    ann = None
                    if isinstance(node, ast.arg):
                        ann = node.annotation
                    elif isinstance(node, (ast.FunctionDef,
                                           ast.AsyncFunctionDef)):
                        ann = node.returns
                    elif isinstance(node, ast.AnnAssign):
                        ann = node.annotation
                    if (isinstance(ann, ast.BinOp)
                            and isinstance(ann.op, ast.BitOr)):
                        self.fail('%s:%s uses a PEP 604 union, '
                                  'unavailable on Python 3.9' % (name, ann.lineno))

    def test_build_composes_full_version_and_manifest(self):
        root = Path(__file__).resolve().parents[1]
        base = (root / 'packaging' / 'VERSION').read_text().strip()
        release = int(base.split('.')[2])
        short = f'v{release // 100}.{release % 100:02d}'
        release_mod = _release_module()
        out = root / 'dist-test-build'
        self.addCleanup(shutil.rmtree, str(out), True)
        release_mod.main(['--out', str(out), '--build', '57',
                          '--sha', 'abc123', '--channel', 'beta'])
        tarball = next(out.glob('*.tar.gz'))
        self.assertEqual(tarball.name, f'ai-router-{base}.57.tar.gz')
        with tarfile.open(tarball, mode='r') as tar:
            manifest = json.loads(tar.extractfile('MANIFEST.json').read())
        self.assertEqual(manifest['version'], f'{base}.57')
        self.assertEqual(manifest['git_sha'], 'abc123')
        self.assertEqual(manifest['channel'], 'beta')
        with tarfile.open(tarball, mode='r') as tar:
            marker = tar.extractfile('packaging/VERSION').read().decode()
            self.assertEqual(marker, f'{base}.57\n')
        latest = json.loads((out / 'latest.json').read_text())
        self.assertTrue(
            latest['url'].endswith(f'/{short}-beta/ai-router-{base}.57.tar.gz'),
            latest['url'])

    def test_default_channel_builds_stable_url(self):
        root = Path(__file__).resolve().parents[1]
        base = (root / 'packaging' / 'VERSION').read_text().strip()
        release = int(base.split('.')[2])
        short = f'v{release // 100}.{release % 100:02d}'
        release_mod = _release_module()
        out = root / 'dist-test-stable'
        self.addCleanup(shutil.rmtree, str(out), True)
        release_mod.main(['--out', str(out)])
        latest = json.loads((out / 'latest.json').read_text())
        self.assertTrue(
            latest['url'].endswith(f'/{short}/ai-router-{base}.0.tar.gz'),
            latest['url'])

if __name__ == '__main__':
    unittest.main()
