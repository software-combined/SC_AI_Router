"""Cheap release-record checks run in the core suite, before beta publication."""
from pathlib import Path
import re
import tomllib
import unittest

from tests.test_packaging import _release_module

ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def test_runtime_file_list_matches_files(self):
        doc = (ROOT / 'docs' / 'runtime-files.md').read_text()
        listed = set(re.findall(r'`((?:ai_router|tools)/[^`]+)`', doc))
        bundled = set(_release_module().bundle_files(ROOT))
        # The page names modules, while the bundle also includes data files.
        self.assertTrue(listed <= bundled,
                        'runtime-files.md names a file the bundle omits: '
                        + ', '.join(sorted(listed - bundled)))
        for module in sorted((ROOT / 'ai_router').rglob('*.py')):
            if '__pycache__' in module.parts:
                continue
            rel = module.relative_to(ROOT).as_posix()
            with self.subTest(module=rel):
                self.assertIn(rel, listed, 'runtime module missing from the page')

    def test_pyproject_version_matches_packaging_version(self):
        version = (ROOT / 'packaging' / 'VERSION').read_text().strip()
        pyproject = tomllib.loads((ROOT / 'pyproject.toml').read_text())
        self.assertEqual(pyproject['project']['version'], version)


if __name__ == '__main__':
    unittest.main()
