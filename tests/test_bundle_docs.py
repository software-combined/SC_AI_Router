"""Plan 134: the release bundle carries the documentation.

An installed host had no README and no docs directory; the update and
attachment behaviour is only diagnosable from those pages.
tests/test_packaging.py derives its expected tarball from bundle_files()
itself, so it cannot catch a dropped docs rule; the pages below are pinned
here instead. Plan 158 adds the exact-set and index gates: every page under
`docs/` ships, and `docs/README.md` names every one of them.
"""
import importlib.util
import re
import unittest
from pathlib import Path


def _bundled(root):
    spec = importlib.util.spec_from_file_location(
        'router_release_docs', root / 'packaging' / 'release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.bundle_files(root)


class BundleDocsTests(unittest.TestCase):
    def test_required_pages_are_bundled_as_markdown(self):
        root = Path(__file__).resolve().parents[1]
        names = set(_bundled(root))
        for required in ('README.md', 'docs/README.md',
                         'docs/operations.md', 'docs/troubleshooting.md',
                         'docs/architecture.md'):
            self.assertIn(required, names)
        # docs/assets holds a repository-only image, so a widened glob that
        # starts shipping non-markdown files also fails this gate.
        bundled_docs = [name for name in names if name.startswith('docs/')]
        self.assertTrue(bundled_docs)
        self.assertTrue(all(name.endswith('.md') for name in bundled_docs))

    def test_the_shipped_docs_set_is_exactly_the_repository_set(self):
        # Asserted, not inferred: the bundle carries every docs page and
        # nothing else is claimed to.
        root = Path(__file__).resolve().parents[1]
        shipped = sorted(name for name in _bundled(root)
                         if name.startswith('docs/'))
        present = sorted(path.relative_to(root).as_posix()
                         for path in (root / 'docs').rglob('*.md'))
        self.assertEqual(shipped, present)

    def test_the_docs_index_names_every_page(self):
        root = Path(__file__).resolve().parents[1]
        index = (root / 'docs' / 'README.md').read_text()
        linked = set(re.findall(r'\]\(([\w.-]+\.md)\)', index))
        pages = {path.name for path in (root / 'docs').glob('*.md')}
        self.assertEqual(pages - linked, {'README.md'})


if __name__ == '__main__':
    unittest.main()
