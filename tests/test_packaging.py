import importlib.util
import shutil
import tarfile
import json
import unittest
from pathlib import Path

FILES = [
         'ai_router/router.py',
         'ai_router/providers.py',
         'ai_router/claude.py',
         'ai_router/registry.py',
         'ai_router/credentials.py',
         'ai_router/tool_adapter.py',
         'ai_router/agent_handoffs.py',
         'ai_router/sse.py',
         'ai_router/capabilities.py',
         'ai_router/compaction.py',
'ai_router/discovered.py',
'ai_router/errors.py',
'ai_router/feed_verify.py',
'ai_router/candidate.py',
'ai_router/setup.py',
         'ai_router/runtime.py',
         'ai_router/catalogue.py',
         'ai_router/local_services.py',
         'ai_router/live_refresh.py',
         'ai_router/models.py',
         'ai_router/apply_catalogue.py',
         'ai_router/activation.py',
         'ai_router/__init__.py',
         'ai_router/__main__.py',
         'ai_router/model_metadata.py',
         'ai_router/model_refresh.py',
         'ai_router/winacl.py',
         'ai_router/image_items.py',
          'ai_router/model_policy.py',
         'ai_router/subscription_roster.py',
         'ai_router/retired_slugs.py',
          'ai_router/clients/__init__.py',
         'ai_router/clients/codex.py',
         'ai_router/transport.py',
         'ai_router/subscription_fallback.py',
         'ai_router/protocols/__init__.py',
         'ai_router/protocols/responses.py',
         'ai_router/protocols/messages.py',
         'ai_router/models.json',
         'ai_router/openrouter_base_instructions.txt',
         'ai_router/agents.py',
         'ai_router/agents_general.txt',
         'ai_router/agents_dev.txt',
         'tools/probe_codex_runtime.py',
         'tools/global_instructions.py',
         'tools/disable.py',
         ]

# Explicit required-files assertion (Plan 123 STOP condition): every member
# an installed release needs to boot and to update itself. Kept independent
# of release.py's inventory so a dropped member fails the bundle gate.
REQUIRED_PACKAGING = (
    'packaging/router_launch.py', 'packaging/update_launch.py',
    'packaging/launchd.py', 'packaging/service.py',
    'packaging/feed.py', 'packaging/atomic_write.py',
    'packaging/notice.py', 'packaging/assets/router-icon.png',
    'packaging/install.py', 'packaging/updater.py',
    'packaging/codex_config.py', 'packaging/claude_config.py',
    'packaging/claude_desktop_config.py', 'packaging/systemd.py',
    'packaging/diagnostics.py',
    'packaging/runtime.lock', 'packaging/runtime_lock.py',
    'packaging/platforms/__init__.py',
    'packaging/platforms/darwin.py',
    'packaging/platforms/linux.py',
    'packaging/platforms/windows.py',
    'packaging/install.sh', 'packaging/install.ps1',
)


class PackagingTests(unittest.TestCase):
    def test_wrappers_call_install_py(self):
        root = Path(__file__).resolve().parents[1] / 'packaging'
        sh, ps1 = (root / 'install.sh').read_text(), (root / 'install.ps1').read_text()
        self.assertIn('install.py', sh)
        self.assertIn('install.py', ps1)

    def test_file_list_covers_the_runtime_import_closure(self):
        # A fresh copy-install following FILES must start: every package
        # module plus the data files read at import must be listed.
        root = Path(__file__).resolve().parents[1]
        for path in sorted((root / 'ai_router').rglob('*.py')):
            if '__pycache__' in path.parts:
                continue
            self.assertIn(path.relative_to(root).as_posix(), FILES,
                          'runtime module missing from deploy list')
        for dep in ('ai_router/models.json',
                    'ai_router/openrouter_base_instructions.txt'):
            self.assertIn(dep, FILES, dep)
        for tool in ('tools/probe_codex_runtime.py', 'tools/disable.py'):
            self.assertIn(tool, FILES, tool)

    def test_packaging_modules_are_all_bundled(self):
        # Every packaging module an installed release can load must be in the
        # release inventory; release.py is the publish-time tool and is the
        # one deliberate exclusion.
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            'release_scan', root / 'packaging' / 'release.py')
        release_scan = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release_scan)
        bundled = set(release_scan.bundle_files(root))
        for path in sorted((root / 'packaging').rglob('*.py')):
            if '__pycache__' in path.parts:
                continue
            rel = path.relative_to(root).as_posix()
            if rel == 'packaging/release.py':
                continue
            self.assertIn(rel, bundled, 'packaging module missing from the release inventory')

    def test_readme_runtime_list_matches_files(self):
        import re
        readme = (Path(__file__).resolve().parents[1] / 'README.md').read_text()
        listed = set(re.findall(r'`((?:ai_router|tools)/[^`]+)`', readme))
        self.assertEqual(listed, set(FILES))

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
        # extra. REQUIRED_PACKAGING below stays an explicit list so a member
        # dropped from the inventory still fails this gate.
        self.assertEqual(names, set(release_mod.bundle_files(root)) | {'MANIFEST.json'})
        for name in FILES:
            self.assertIn(name, names, name)
        for name in REQUIRED_PACKAGING:
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

    def test_installer_surface_parses_as_python39(self):
        # Plan 061: the installer runs on Python 3.9+ while the router
        # needs 3.14. No 3.9 interpreter exists in CI, so pin the grammar
        # instead: every installer-surface file must parse as 3.9 syntax.
        # feature_version misses PEP 604 unions (`X | Y` parses as BinOp
        # but raises at runtime on 3.9), so annotations get their own walk.
        import ast
        root = Path(__file__).resolve().parents[1]
        surface = [
            'packaging/install.py', 'packaging/service.py',
            'packaging/feed.py', 'packaging/atomic_write.py',
            'packaging/notice.py',
            'packaging/launchd.py', 'packaging/router_launch.py',
            'packaging/systemd.py', 'packaging/update_launch.py',
            'packaging/updater.py', 'packaging/codex_config.py',
            'packaging/claude_config.py', 'packaging/diagnostics.py',
            'packaging/runtime_lock.py', 'packaging/platforms/__init__.py',
            'packaging/platforms/darwin.py', 'packaging/platforms/linux.py',
            'packaging/platforms/windows.py', 'ai_router/feed_verify.py',
            'ai_router/subscription_roster.py',
            'ai_router/retired_slugs.py',
            'tools/disable.py', 'tools/global_instructions.py',
        ]
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
        import importlib.util
        root = Path(__file__).resolve().parents[1]
        base = (root / 'packaging' / 'VERSION').read_text().strip()
        spec = importlib.util.spec_from_file_location(
            'router_release', root / 'packaging' / 'release.py')
        release_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release_mod)
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
            latest['url'].endswith(f'/v{base}.57-beta/ai-router-{base}.57.tar.gz'),
            latest['url'])

    def test_default_channel_builds_stable_url(self):
        import importlib.util
        root = Path(__file__).resolve().parents[1]
        base = (root / 'packaging' / 'VERSION').read_text().strip()
        spec = importlib.util.spec_from_file_location(
            'router_release', root / 'packaging' / 'release.py')
        release_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release_mod)
        out = root / 'dist-test-stable'
        self.addCleanup(shutil.rmtree, str(out), True)
        release_mod.main(['--out', str(out)])
        latest = json.loads((out / 'latest.json').read_text())
        self.assertTrue(
            latest['url'].endswith(f'/v{base}.0/ai-router-{base}.0.tar.gz'),
            latest['url'])

if __name__ == '__main__':
    unittest.main()
