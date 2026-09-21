"""Plan 134: the release bundle carries the documentation.

An installed host had no README and no docs directory; the update and
attachment behaviour is only diagnosable from those pages.
tests/test_packaging.py derives its expected tarball from bundle_files()
itself, so it cannot catch a dropped docs rule; the pages below are pinned
here instead. Plan 158 adds the exact-set and index gates: every page under
`docs/` ships, and `docs/README.md` names every one of them.
"""
import importlib.util
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests.install_fixtures import _patch_attrs, install_mod


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


class HomeReadmeTests(unittest.TestCase):
    """The page beside the state directory belongs to the installed release."""

    def _install(self, home, release_dir):
        install_mod._bundle.install_home_readme(home, release_dir)

    def test_a_stale_home_readme_is_replaced(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'README.md').write_text(
                '# Codex mixed-provider compatibility adapter\n'
                'Only the six configured OpenRouter models use the key.\n')
            self._install(home, root)
            self.assertEqual((home / 'README.md').read_bytes(),
                             (root / 'README.md').read_bytes())

    def test_the_home_readme_covers_the_clients_this_release_serves(self):
        # The stale page named Codex alone and an old model count, so a
        # reader could not find the Claude setup or the client chooser.
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self._install(home, root)
            page = (home / 'README.md').read_text()
            self.assertIn('Claude', page)
            self.assertNotIn('six configured OpenRouter models', page)

    def test_a_release_without_a_readme_leaves_the_home_copy_alone(self):
        # A rollback can name a version that predates the bundled page.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'README.md').write_text('kept\n')
            release = Path(tmp) / 'release'
            release.mkdir()
            self._install(home, release)
            self.assertEqual((home / 'README.md').read_text(), 'kept\n')

    def test_a_planted_tmp_symlink_is_not_followed(self):
        # shutil.copyfile follows a symlink at the destination, so a link
        # planted at the tmp name would aim the write at its target.
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            victim = Path(tmp) / 'victim.key'
            victim.write_text('key material\n')
            os.symlink(victim, home / 'README.md.tmp')
            self._install(home, root)
            self.assertEqual(victim.read_text(), 'key material\n')
            self.assertFalse((home / 'README.md.tmp').is_symlink())
            self.assertTrue((home / 'README.md').is_file())

    def test_a_directory_at_the_tmp_name_is_cleared(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            (home / 'README.md.tmp').mkdir(parents=True)
            self._install(home, root)
            self.assertTrue((home / 'README.md').is_file())

    def test_a_write_that_cannot_land_is_not_an_error(self):
        # The launchers fail closed; this page must never fail an install,
        # and must never fail a rollback that already passed its health gate.
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            self._install(Path(tmp) / 'no-such-home', root)

    def test_installing_a_bundle_refreshes_the_page(self):
        # The wiring, not just the helper: a bundle install must land it.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'

            def fake_extract(blob, dest):
                (dest / 'packaging').mkdir(parents=True, exist_ok=True)
                (dest / 'packaging' / 'VERSION').write_text('9.9.9\n')
                (dest / 'README.md').write_text('current page\n')

            _patch_attrs(self, self_test=lambda *a: None,
                         write_catalogue=lambda *a: None,
                         safe_extract=fake_extract,
                         install_launcher=lambda *a: None,
                         swap_current=lambda *a: None)
            install_mod.install_bundle(home, '9.9.9', b'blob',
                                       {'version': '9.9.9', 'files': {}},
                                       '/nonexistent/python')
            self.assertEqual((home / 'README.md').read_text(), 'current page\n')

    def test_a_rollback_refreshes_the_page_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            target = home / 'releases' / '1.0.1'
            (target / 'packaging').mkdir(parents=True)
            (target / 'packaging' / 'VERSION').write_text('1.0.1\n')
            (target / 'README.md').write_text('page for 1.0.1\n')
            (home / 'mixed-router-state.json').write_text(
                json.dumps({'port': 1, 'token': 't'}))
            args = SimpleNamespace(home=str(home), version='1.0.1', dry_run=False)
            rc = install_mod._bundle.do_rollback(
                args,
                platform_backend=lambda: SimpleNamespace(check=lambda home: None),
                restart_router=lambda home: None,
                wait_version=lambda state, version: True,
                current_version=lambda home: '1.0.0',
                swap_current=lambda home, release: None)
            self.assertEqual(rc, 0)
            self.assertEqual((home / 'README.md').read_text(), 'page for 1.0.1\n')


if __name__ == '__main__':
    unittest.main()
