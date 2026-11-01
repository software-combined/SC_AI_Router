"""The stable launcher outlives the source package rename."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RouterPackageCompatibilityTests(unittest.TestCase):
    def _package(self, release, name, message):
        package = release / name
        package.mkdir(parents=True)
        (package / '__init__.py').write_text('', encoding='utf-8')
        (package / '__main__.py').write_text(
            'print(%r)\n' % message, encoding='utf-8')

    def _launch(self, home):
        result = subprocess.run(
            [sys.executable, '-I', str(home / 'router_launch.py')],
            cwd=home, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_same_launcher_supports_upgrade_and_rollback(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            shutil.copyfile(ROOT / 'packaging/router_launch.py',
                            home / 'router_launch.py')
            self._package(home / 'releases/1.0.0', 'codex_router', 'older runtime')
            self._package(home / 'releases/2.0.0', 'ai_router', 'shared runtime')
            for version, expected in (('1.0.0', 'older runtime'),
                                      ('2.0.0', 'shared runtime'),
                                      ('1.0.0', 'older runtime')):
                with self.subTest(version=version, expected=expected):
                    (home / 'current').write_text(version + '\n', encoding='utf-8')
                    self.assertEqual(self._launch(home), expected)

    def test_canonical_package_wins_when_both_names_exist(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            shutil.copyfile(ROOT / 'packaging/router_launch.py',
                            home / 'router_launch.py')
            release = home / 'releases/2.0.0'
            self._package(release, 'ai_router', 'shared runtime')
            self._package(release, 'codex_router', 'obsolete runtime')
            (home / 'current').write_text('2.0.0\n', encoding='utf-8')
            self.assertEqual(self._launch(home), 'shared runtime')


if __name__ == '__main__':
    unittest.main()
