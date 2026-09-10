"""Plan 054 source slice: token-gated private feed fetch (isolated, no network).

Proves: off-origin fetches refuse before any request; the token header rides
trusted-origin requests only and never appears in errors; rotation persists
the new token with the previous kept; a 403 retries once with the previous
value and restores it; serial acceptance rotates the token.
"""
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from tests.test_install import install_mod

svc = install_mod._svc
CLOUDFRONT = 'https://dist.softwarecombined.com/stable/latest.json'
OFF = 'https://example.com/evil.tar.gz'


def _allow_cloudfront():
    return mock.patch.object(svc, 'TRUSTED_ORIGINS',
                             (svc.RELEASES_PREFIX, 'https://dist.softwarecombined.com/'))


class _Resp:
    def __init__(self, body=b'', etag=None):
        self.status = 200
        self._body = body
        self.headers = {'ETag': etag} if etag else {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *args):
        return self._body


class FeedTokenTests(unittest.TestCase):
    def test_off_origin_fetch_and_feed_refuse_before_any_request(self):
        with mock.patch.object(svc.urllib.request, 'urlopen',
                               side_effect=AssertionError('no request')):
            with self.assertRaisesRegex(SystemExit, 'off-origin fetch'):
                svc.fetch(OFF)
            with self.assertRaisesRegex(SystemExit, 'off-origin feed'):
                svc.fetch_feed(OFF, None)

    def test_token_header_rides_trusted_requests_only(self):
        seen = []

        def fake(req, timeout=None):
            seen.append(dict(req.header_items()))
            return _Resp(body=b'x')
        with _allow_cloudfront(), tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'feed-token').write_text('tok-1')
            svc.fetch_feed(CLOUDFRONT, None, home=tmp, _urlopen=fake)
            self.assertEqual(seen[-1].get('X-scg-feed-token'), 'tok-1')
            seen.clear()
            # No home means no token even on a trusted origin:
            svc._token_request(CLOUDFRONT, None, None, fake)
            self.assertNotIn('X-scg-feed-token', seen[-1])

    def test_rotation_persists_new_token_and_keeps_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'feed-token').write_text('old-tok')
            svc._feed_token.persist(home, {'feed_token': 'new-tok'})
            self.assertEqual((home / 'feed-token').read_text(), 'new-tok')
            self.assertEqual((home / 'feed-token.previous').read_text(), 'old-tok')

    def test_403_retries_once_with_previous_and_restores_it(self):
        calls = []

        def fake(req, timeout=None):
            token = dict(req.header_items()).get('X-scg-feed-token')
            calls.append(token)
            if token == 'new-tok':
                raise urllib.error.HTTPError(req.full_url, 403, 'Forbidden', {}, None)
            return _Resp(body=b'feed-body', etag='e1')
        with _allow_cloudfront(), tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'feed-token').write_text('new-tok')
            (home / 'feed-token.previous').write_text('old-tok')
            status, body, etag = svc.fetch_feed(CLOUDFRONT, None, home=tmp, _urlopen=fake)
            self.assertEqual((status, body, etag), (200, b'feed-body', 'e1'))
            self.assertEqual(calls, ['new-tok', 'old-tok'])
            self.assertEqual((home / 'feed-token').read_text(), 'old-tok')

    def test_token_never_appears_in_refusal_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'feed-token').write_text('tok-secret')
            with mock.patch.object(svc.urllib.request, 'urlopen',
                                   side_effect=AssertionError('no request')):
                with self.assertRaises(SystemExit) as ctx:
                    svc.fetch(OFF)
                self.assertNotIn('tok-secret', str(ctx.exception))

    def test_serial_acceptance_rotates_the_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            svc.check_serial(home, {'serial': 0, 'feed_token': 'rot-tok'})
            self.assertEqual((home / 'feed-token').read_text(), 'rot-tok')


if __name__ == '__main__':
    unittest.main()
