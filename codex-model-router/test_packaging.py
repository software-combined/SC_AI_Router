import re
import unittest
from pathlib import Path

FILES = ['mixed_router.py', 'tool_adapter.py', 'capabilities.py', 'compaction.py',
         'probe_codex_runtime.py', 'update_reasoning_catalog.py', 'apply_catalogue.py',
         'disable.py']

class PackagingTests(unittest.TestCase):
    def test_both_installers_name_the_same_eight_files(self):
        root = Path(__file__).resolve().parent / 'packaging'
        sh, ps1 = (root / 'install.sh').read_text(), (root / 'install.ps1').read_text()
        for name in FILES:
            self.assertIn(name, sh, name)
            self.assertIn(name, ps1, name)

    def test_version_is_pinned(self):
        version = (Path(__file__).resolve().parent / 'packaging' / 'VERSION').read_text().strip()
        self.assertRegex(version, r'^\d+\.\d+\.\d+$')

if __name__ == '__main__':
    unittest.main()
