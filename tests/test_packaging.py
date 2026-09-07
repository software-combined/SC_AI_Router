import re
import unittest
from pathlib import Path

FILES = [
         'codex_router/router.py',
         'codex_router/providers.py',
         'codex_router/registry.py',
         'codex_router/tool_adapter.py',
         'codex_router/capabilities.py',
         'codex_router/compaction.py',
         'codex_router/runtime.py',
         'codex_router/catalogue.py',
         'codex_router/update_reasoning_catalog.py',
         'codex_router/apply_catalogue.py',
         'codex_router/__init__.py',
         'codex_router/__main__.py',
         'codex_router/models.json',
         'codex_router/openrouter_base_instructions.txt',
         'tools/probe_codex_runtime.py',
         'tools/disable.py',
         ]

class PackagingTests(unittest.TestCase):
    def test_both_installers_name_the_same_runtime_files(self):
        root = Path(__file__).resolve().parents[1] / 'packaging'
        sh, ps1 = (root / 'install.sh').read_text(), (root / 'install.ps1').read_text()
        for name in FILES:
            self.assertIn(name, sh, name)
            self.assertIn(name, ps1, name)

    def test_version_is_pinned(self):
        version = (Path(__file__).resolve().parents[1] / 'packaging' / 'VERSION').read_text().strip()
        self.assertRegex(version, r'^\d+\.\d+\.\d+$')

if __name__ == '__main__':
    unittest.main()
