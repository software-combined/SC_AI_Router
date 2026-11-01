"""Canonical file URIs must work in Windows source and native setup."""
import os
import tempfile
import unittest
from pathlib import Path

from tests.install_fixtures import install_mod

svc = install_mod._svc


class LocalFeedTests(unittest.TestCase):
    def test_native_setup_emits_an_encoded_local_feed_uri(self):
        from tests.test_native_setup import payload, resources
        with tempfile.TemporaryDirectory(prefix='router \u00e9 %25 ') as temporary:
            source = resources(Path(temporary) / 'download')
            args = payload.install_arguments(source, Path(temporary) / 'home')
            uri = args[args.index('--feed') + 1]
            self.assertEqual(uri, (source / 'payload/latest.json').as_uri())
            self.assertEqual(svc.fetch(uri), (source / 'payload/latest.json').read_bytes())

    def test_file_uri_decodes_windows_drives_spaces_unicode_and_percent(self):
        with tempfile.TemporaryDirectory(prefix='router \u00e9 %25 ') as temporary:
            feed = Path(temporary) / 'latest.json'
            feed.write_bytes(b'{"version":"1.0.0"}')
            self.assertEqual(svc.fetch(feed.as_uri()), feed.read_bytes())

    def test_handoff_uses_the_bundle_beside_an_encoded_feed_uri(self):
        with tempfile.TemporaryDirectory(prefix='router \u00e9 %25 ') as temporary:
            feed = Path(temporary) / 'latest.json'
            bundle = Path(temporary) / 'ai-router-1.0.0.tar.gz'
            bundle.write_bytes(b'local bundle')
            uri = svc.sibling_bundle(feed.as_uri(), 'file://ai-router-1.0.0.tar.gz')
            self.assertEqual(uri, bundle.as_uri())
            self.assertEqual(svc.fetch(uri), b'local bundle')

    def test_legacy_unescaped_native_path_is_still_accepted(self):
        with tempfile.TemporaryDirectory(prefix='router feed ') as temporary:
            feed = Path(temporary) / 'latest.json'
            feed.write_bytes(b'legacy')
            self.assertEqual(svc.fetch('file://' + str(feed)), b'legacy')

    @unittest.skipUnless(os.name == 'nt', 'legacy Windows native path')
    def test_legacy_windows_percent_sign_is_not_decoded(self):
        with tempfile.TemporaryDirectory(prefix='router %25 ') as temporary:
            feed = Path(temporary) / 'latest.json'
            feed.write_bytes(b'legacy')
            self.assertEqual(svc.fetch('file://' + str(feed)), b'legacy')
