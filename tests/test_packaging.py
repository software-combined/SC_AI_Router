import unittest
from pathlib import Path

FILES = [
         'codex_router/router.py',
         'codex_router/providers.py',
         'codex_router/registry.py',
         'codex_router/credentials.py',
         'codex_router/tool_adapter.py',
         'codex_router/capabilities.py',
         'codex_router/compaction.py',
         'codex_router/runtime.py',
         'codex_router/catalogue.py',
         'codex_router/local_services.py',
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

    def test_file_list_covers_the_runtime_import_closure(self):
        # A fresh copy-install following FILES must start: every package
        # module plus the data files read at import must be listed.
        root = Path(__file__).resolve().parents[1]
        for path in sorted((root / 'codex_router').glob('*.py')):
            self.assertIn('codex_router/%s' % path.name, FILES,
                          'runtime module missing from deploy list')
        for dep in ('codex_router/models.json',
                    'codex_router/openrouter_base_instructions.txt'):
            self.assertIn(dep, FILES, dep)
        for tool in ('tools/probe_codex_runtime.py', 'tools/disable.py'):
            self.assertIn(tool, FILES, tool)

    def test_readme_runtime_list_matches_files(self):
        import re
        readme = (Path(__file__).resolve().parents[1] / 'README.md').read_text()
        listed = set(re.findall(r'`((?:codex_router|tools)/[^`]+)`', readme))
        self.assertEqual(listed, set(FILES))

    def test_version_is_pinned(self):
        version = (Path(__file__).resolve().parents[1] / 'packaging' / 'VERSION').read_text().strip()
        self.assertRegex(version, r'^\d+\.\d+\.\d+$')

if __name__ == '__main__':
    unittest.main()
