"""Plan 134: the release bundle carries the documentation.

An installed host had no README and no docs directory; the update and
attachment behaviour is only diagnosable from those pages.
tests/test_packaging.py derives its expected tarball from bundle_files()
itself, so it cannot catch a dropped docs rule; the pages below are pinned
here instead.
"""
import importlib.util
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


if __name__ == '__main__':
    unittest.main()
