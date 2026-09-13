"""CI scope stays one owner: the installer path list and the native test list.

Plan 156: an installer-changing PR pays for macOS, Windows and Python 3.9
checks; a router-only PR keeps the single Ubuntu check. tools/ci_scope.py is
the only place either list lives, so this test pins its contract, including
that every installer-surface file and every singleton installer test file
reaches the native jobs.
"""
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools' / 'ci_scope.py'


def scope_module():
    spec = importlib.util.spec_from_file_location('router_ci_scope', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_scope(*args, stdin=''):
    return subprocess.run([sys.executable, str(TOOL), *args],
                          input=stdin, capture_output=True, text=True)


class InstallerScopeTests(unittest.TestCase):
    def scope(self, *paths):
        result = run_scope('--installer', stdin='\n'.join(paths))
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_installer_paths_select_the_native_checks(self):
        for path in ('packaging/install.py', 'packaging/platforms/windows.py',
                     '.github/actions/setup/action.yml',
                     '.github/workflows/check.yml',
                     '.github/workflows/release.yml',
                     'config/installer-python-surface.txt',
                     'tests/test_install_config.py', 'tests/test_windows_acl.py',
                     'tests/_platform.py',
                     'ai_router/key_dialog.py', 'ai_router/key_prompt.py',
                     'tools/check_installer_python39.py'):
            with self.subTest(path=path):
                self.assertEqual(self.scope(path), 'installer=true')

    def test_every_surface_file_selects_the_native_checks(self):
        module = scope_module()
        for path in module.surface_paths():
            with self.subTest(path=path):
                self.assertTrue(module.installer_scope([path]), path)

    def test_router_only_paths_keep_the_ubuntu_check(self):
        for path in ('ai_router/router.py', 'ai_router/catalogue.py',
                     'tests/test_ingress_guards.py', 'tests/test_handler.py',
                     'docs/compatibility.md', 'README.md'):
            with self.subTest(path=path):
                self.assertEqual(self.scope(path), 'installer=false')

    def test_an_empty_diff_is_not_installer(self):
        self.assertEqual(self.scope(), 'installer=false')

    def test_one_matching_path_selects_the_scope(self):
        self.assertEqual(
            self.scope('README.md', 'packaging/service.py', 'docs/compatibility.md'),
            'installer=true')

    def test_every_singleton_installer_test_file_runs_on_the_native_jobs(self):
        module = scope_module()
        listed = set(module.INSTALLER_TESTS)
        for path in module.INSTALLER_PATHS:
            if path.startswith('tests/test_') and path.endswith('.py'):
                with self.subTest(path=path):
                    self.assertIn(path[:-3].replace('/', '.'), listed)

    def test_native_list_names_real_test_modules(self):
        result = run_scope('--installer-tests')
        self.assertEqual(result.returncode, 0, result.stderr)
        modules = result.stdout.split()
        self.assertTrue(modules)
        for module in modules:
            with self.subTest(module=module):
                self.assertTrue((ROOT / (module.replace('.', '/') + '.py')).is_file())


if __name__ == '__main__':
    unittest.main()
