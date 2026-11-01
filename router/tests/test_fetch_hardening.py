"""Update-chain fetch hardening (Plan 161).

Fake upstream only; never opens a real network connection. Fixtures follow
tests/test_feed_migration.py; the installer module comes from
tests/install_fixtures.py.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import urllib.error
import urllib.request

from ai_router import key_store, setup, subscription_discovery
from tests.install_fixtures import install_mod

svc = install_mod._svc
ORIGIN = 'https://dist.softwarecombined.com'


class DiscoveryFetchTests(unittest.TestCase):
    def test_subscription_catalogue_uses_the_no_redirect_transport(self):
        seen = []
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{\"models\": []}'

        def no_redirect(request, timeout):
            seen.append(request.full_url)
            return response

        with mock.patch.object(subscription_discovery, '_open_without_redirects',
                               no_redirect):
            subscription_discovery.fetch_native({'Authorization': 'Bearer client'})
        self.assertEqual(len(seen), 1)


class ChecksumRefusalTests(unittest.TestCase):
    def test_updater_refuses_a_feed_without_a_checksum(self):
        updater = install_mod._updater
        for bad in ({'version': '9.9.9', 'url': 'x'}, {'sha256': 'not-hex'},
                    {'sha256': 'z' * 64}):
            with self.subTest(bad=bad):
                with self.assertRaises(updater.UpdateError) as ctx:
                    updater._required_sha256(dict({'version': '9.9.9'}, **bad))
                self.assertEqual(ctx.exception.error_code, 'feed_invalid')
        good = updater._required_sha256(
            {'sha256': 'A' * 64})
        self.assertEqual(good, 'a' * 64)

    def test_installer_refuses_a_feed_without_a_checksum(self):
        latest = {'version': '9.9.9', 'url': 'file:///bundle.tar.gz',
                  'min_python': '3.14'}
        extracted = []

        def fake_fetch(url):
            return json.dumps(latest).encode() if url.endswith('.json') else b'blob'

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            with mock.patch.object(install_mod._bundle, 'safe_extract',
                                   lambda blob, dest: extracted.append(blob)):
                with self.assertRaisesRegex(SystemExit, 'no usable bundle checksum'):
                    install_mod.do_install(args, _fetch=fake_fetch)
        self.assertEqual(extracted, [])


class RedirectPinningTests(unittest.TestCase):
    def test_feed_redirect_off_origin_is_refused(self):
        pinned = svc._feed._PinnedRedirects()
        req = urllib.request.Request(ORIGIN + '/stable/latest.json')
        with self.assertRaises(SystemExit):
            pinned.redirect_request(req, None, 302, 'Found', {},
                                    'https://evil.example/x')
        with self.assertRaises(SystemExit):
            pinned.redirect_request(req, None, 302, 'Found', {},
                                    'file:///tmp/x')
        kept = pinned.redirect_request(req, None, 302, 'Found', {},
                                       ORIGIN + '/stable/other.json')
        self.assertEqual(kept.full_url, ORIGIN + '/stable/other.json')

    def test_key_check_never_follows_a_redirect(self):
        url = 'https://example.invalid/keyinfo'

        def redirecting(req, timeout=None):
            raise urllib.error.HTTPError(url, 302, 'Found', {}, None)

        with self.assertRaises(OSError):
            key_store.check_key('openrouter', 'sk-live', redirecting)
        self.assertIn(key_store._NoRedirects,
                      [type(h) for h in urllib.request.build_opener(
                          key_store._NoRedirects()).handlers])
        self.assertIsNone(key_store._NoRedirects().redirect_request(
            urllib.request.Request(url), None, 302, 'Found', {}, url))

    def test_the_default_opener_resolves_at_call_time(self):
        # Plan 161 follow-up: the two-argument call (the router's
        # credentials.key_rejected probe) must honour a swapped seam.
        called = []

        def fake(req, timeout=None):
            called.append(req.full_url)
            response = mock.Mock()
            response.read.return_value = b'{"data": {"label": "probe"}}'
            response.__enter__ = lambda s: s
            response.__exit__ = lambda s, *a: False
            return response

        with mock.patch.object(key_store, '_open_without_redirects', fake):
            label, _limit, _usage = key_store.check_key('openrouter', 'sk-live')
        self.assertEqual(label, 'probe')
        self.assertEqual(len(called), 1)

    def test_a_redirect_through_the_default_path_is_an_oserror(self):
        # Fail closed on the default path too: a 3xx is unreachable, never a
        # dead key, so key_rejected cannot mistake it for a 401/403.
        def redirecting(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 302, 'Found', {}, None)

        with mock.patch.object(key_store, '_open_without_redirects', redirecting):
            with self.assertRaises(OSError) as caught:
                key_store.check_key('openrouter', 'sk-live')
        self.assertNotIsInstance(caught.exception, key_store.KeyRejected)

    def test_setup_submit_uses_the_no_redirect_opener(self):
        state = {'setup': {'nonce': 'n' * 16, 'expires': 9_999_999_999},
                 'port': 1, 'token': 'x'}
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            seen = []

            def redirecting(req, timeout=None):
                seen.append(req.full_url)
                raise urllib.error.HTTPError(req.full_url, 302, 'Found', {}, None)

            with mock.patch.object(key_store, '_open_without_redirects',
                                   side_effect=redirecting):
                with mock.patch.object(urllib.request, 'urlopen',
                                       side_effect=AssertionError('must not follow')):
                    status, result = setup._submit(
                        state, home, b'key=sk-live&mode=subscription', None)
        self.assertEqual(status, 502)
        self.assertIn('could not reach', result['error'])
        self.assertEqual(len(seen), 1)

    def test_feed_and_bundle_fetches_go_through_the_pinned_opener(self):
        opened = []

        class _FakeOpener:
            def open(self, req, timeout=None):
                opened.append(req.full_url)
                resp = mock.Mock()
                resp.status = 200
                resp.read.return_value = b'{}'
                resp.headers = {}
                resp.__enter__ = lambda s: s
                resp.__exit__ = lambda s, *a: False
                return resp

        recorder = mock.Mock(return_value=_FakeOpener())
        with mock.patch.object(svc._feed, 'opener', return_value=recorder()):
            svc.fetch(ORIGIN + '/bundles/x.tar.gz')
            svc._feed._get(ORIGIN + '/stable/latest.json', {}, None)
        self.assertEqual(opened, [ORIGIN + '/bundles/x.tar.gz',
                                  ORIGIN + '/stable/latest.json'])
        self.assertTrue(any(isinstance(h, svc._feed._PinnedRedirects)
                            for h in svc._feed.opener().handlers))


if __name__ == '__main__':
    unittest.main()
