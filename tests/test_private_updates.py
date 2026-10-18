"""Private downloads must pause updates without disturbing a working router."""
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.install_fixtures import install_mod

feed = install_mod._svc._feed
ROOT = Path(__file__).resolve().parents[1]
models = install_mod._svc.load('private_control_models', ROOT / 'packaging/control_models.py')


class PrivateTransportTests(unittest.TestCase):
    def test_shipped_renewal_notice_stays_pending_without_a_dialog_tool(self):
        release = install_mod._svc.load('private_release', ROOT / 'packaging/release.py')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release.main(['--out', str(root / 'dist')])
            source = root / 'shipped'
            with tarfile.open(next((root / 'dist').glob('*.tar.gz'))) as archive:
                archive.extractall(source, filter='data')
            notice = install_mod._svc.load('shipped_download_notice',
                                          source / 'packaging/download_notice.py')
            with mock.patch('shutil.which', return_value=None):
                self.assertFalse(notice.show(root / 'home', now=100000))
            self.assertFalse((root / 'home/download-notice.json').exists())

    def test_public_downloads_send_no_staff_credentials(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(feed, '_home', Path(temporary)):
            (Path(temporary) / 'download-auth.json').write_text('{}')
            with mock.patch.object(feed._auth, 'ensure_access', return_value='CloudFront-Policy=private'):
                req = feed._request(feed.FEED_ORIGIN + '/stable/latest.json')
                self.assertIsNone(req.get_header('Cookie'))
                for url in ('https://other.example/file', 'http://dist.softwarecombined.com/file',
                            'https://dist.softwarecombined.com.attacker.invalid/file'):
                    with self.subTest(url=url), self.assertRaises(SystemExit):
                        feed.fetch(url)
                with self.assertRaises(SystemExit):
                    feed._PinnedRedirects().redirect_request(
                        req, None, 302, 'redirect', {}, 'https://other.example/file')

    def test_expired_signin_does_not_count_as_a_bad_router_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / 'mixed-router-state.json').write_text(json.dumps(
                {'port': 1, 'token': 'synthetic', 'update_failures': {'2.0.0': 1}}))
            args = install_mod.build_parser().parse_args(['--home', str(home)])
            def denied(*args):
                raise feed.SignInRequired()
            with mock.patch.object(install_mod._updater, '_offer_notices'), \
                    mock.patch.object(install_mod._updater._svc, 'load'), \
                    self.assertRaisesRegex(SystemExit, 'Sign in'):
                install_mod.do_update(args, _read_feed=denied, _sleep=lambda *_: None)
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.assertEqual(state['last_error'], 'download_signin_required')
            self.assertEqual(state['update_failures'], {'2.0.0': 1})


class ControlledModelTests(unittest.TestCase):
    def test_verified_models_refresh_without_a_download_account(self):
        import hashlib
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            body = b'[]'
            self.assertTrue(models.accept(home, {
                'models_url': feed.FEED_ORIGIN + '/stable/models.json',
                'models_sha256': hashlib.sha256(body).hexdigest()}))
            run = mock.Mock(return_value=SimpleNamespace(returncode=0))
            self.assertTrue(models.refresh(home, lambda _: body, run=run, now=4000))
            self.assertEqual((home / 'models-cache.json').read_bytes(), body)
            self.assertFalse((home / 'download-auth.json').exists())
            run.assert_called_once()

    def test_tampered_model_download_keeps_the_last_good_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / 'download-auth.json').write_text('{}')
            models.accept(home, {'models_url': feed.FEED_ORIGIN + '/stable/models.json',
                                 'models_sha256': 'a' * 64})
            cache = home / 'models-cache.json'
            cache.write_text('last good model list')
            called = mock.Mock()
            self.assertFalse(models.refresh(home, lambda _: b'changed', run=called, now=4000))
            self.assertEqual(cache.read_text(), 'last good model list')
            called.assert_not_called()

    def test_untrusted_feed_cannot_choose_a_model_download(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertFalse(models.accept(temporary, {
                'models_url': 'https://other.example/models.json', 'models_sha256': 'a' * 64}))
            self.assertFalse((Path(temporary) / 'controlled-models.json').exists())


if __name__ == '__main__':
    unittest.main()
