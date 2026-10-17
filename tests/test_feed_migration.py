"""Public feed: origin resolution, channel selection, and fetch."""
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.install_fixtures import _ok_run, _patch_attrs, install_mod

svc = install_mod._svc
ORIGIN = 'https://dist.softwarecombined.com'
GITHUB_BUNDLE = ('https://github.com/software-combined/SC_AI_Router'
                 '/releases/download/v1.0.0/ai-router-1.0.0.tar.gz')


class _Response:
    """urlopen stand-in: fixed body, no ETag header."""
    status = 200
    headers = {}

    def __init__(self, body=b'{}'):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FeedTests(unittest.TestCase):
    def _home(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name) / 'home'
        home.mkdir(parents=True)
        return home

    def test_channel_defaults_to_stable(self):
        self.assertEqual(svc.channel_feed(self._home()),
                         ORIGIN + '/stable/latest.json')

    def test_beta_channel_selects_the_beta_document(self):
        home = self._home()
        (home / 'channel').write_text('beta\n')
        self.assertEqual(svc.channel_feed(home), ORIGIN + '/beta/latest.json')

    def test_pinned_feed_file_wins_over_the_channel(self):
        home = self._home()
        (home / 'channel').write_text('beta\n')
        (home / 'feed').write_text('file:///pinned.json\n')
        self.assertEqual(svc.channel_feed(home), 'file:///pinned.json')

    def test_handoff_bundle_beside_a_local_feed_document_is_preferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed = Path(tmp) / 'latest.json'
            (Path(tmp) / 'ai-router-1.0.0.tar.gz').write_bytes(b'bundle')
            self.assertEqual(
                svc.sibling_bundle('file://' + str(feed), GITHUB_BUNDLE),
                'file://' + str(Path(tmp) / 'ai-router-1.0.0.tar.gz'))
            # No sibling: the document's own URL stands, and the origin
            # guard decides it like any other unattended URL.
            other = GITHUB_BUNDLE.replace('1.0.0', '2.0.0')
            self.assertEqual(svc.sibling_bundle('file://' + str(feed), other), other)
        self.assertEqual(svc.sibling_bundle(ORIGIN + '/stable/latest.json',
                                            GITHUB_BUNDLE), GITHUB_BUNDLE)

    def test_off_origin_bundle_is_refused(self):
        with self.assertRaisesRegex(SystemExit, 'untrusted feed URL'):
            svc.fetch('https://evil.example/bundle.tar.gz')

    def test_refusal_never_echoes_a_query_string(self):
        """A credentialed URL must not reach update.log or stderr."""
        with self.assertRaises(SystemExit) as ctx:
            svc.fetch('https://evil.example/x?sig=SECRET-CRED')
        self.assertNotIn('SECRET-CRED', str(ctx.exception.code))
        self.assertIn('evil.example/x', str(ctx.exception.code))

    def test_conditional_get_sends_no_credential_and_handles_304(self):
        def fake_urlopen(req, timeout=None):
            self.assertEqual(req.get_header('If-none-match'), 'etag-1')
            self.assertIsNone(req.get_header('X-scg-feed-token'))
            raise svc.urllib.error.HTTPError(req.full_url, 304, 'Not Modified', {}, None)

        fake_opener = mock.Mock()
        fake_opener.open.side_effect = fake_urlopen
        with mock.patch.object(svc._feed, 'opener', return_value=fake_opener):
            status, body, etag = svc.fetch_feed(ORIGIN + '/stable/latest.json', 'etag-1')
        self.assertEqual((status, body, etag), (304, b'', 'etag-1'))

    def test_scheduled_poll_reads_feed_and_bundle_without_headers(self):
        """The default scheduled wiring fetches the public feed and bundle.

        A credential or a gh call here would mean a host that cannot update
        itself, so both reads are asserted header-free on the real wiring.
        """
        home = self._home()
        (home / 'mixed-router-state.json').write_text(json.dumps({'port': 1, 'token': 'x'}))
        (home / 'download-auth.json').write_text('{legacy blocked settings')
        (home / 'releases' / '1.0.0' / 'packaging').mkdir(parents=True)
        (home / 'releases' / '1.0.0' / 'packaging' / 'VERSION').write_text('1.0.0\n')
        (home / 'current').write_text('1.0.0\n')
        latest = {'version': '2.0.0', 'url': ORIGIN + '/bundles/2.0.0.tar.gz',
                  'sha256': hashlib.sha256(b'blob').hexdigest(), 'serial': 1,
                  'download_auth': {'legacy': 'ignored'}}
        seen = []
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            'router_feed_verify_mig',
            Path(__file__).resolve().parents[1] / 'packaging' / 'feed_verify.py')
        _fv = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_fv)
        _seed, _pub = _fv.generate_keypair()
        _doc = json.dumps(latest).encode()
        _sig = _fv.sign_hex(_seed, _doc).encode()

        def fake_urlopen(req, timeout=None):
            url = getattr(req, 'full_url', req)
            headers = getattr(req, 'headers', {})
            seen.append((url, {name.lower() for name in headers}))
            if url.endswith('/stable/latest.json.sig'):
                return _Response(_sig)
            if url.endswith('/stable/latest.json'):
                return _Response(_doc)
            return _Response(b'blob')

        def fake_extract(blob, dest):
            (Path(dest) / 'packaging').mkdir(parents=True, exist_ok=True)
            (Path(dest) / 'packaging' / 'install.py').write_text('# installer\n')

        _patch_attrs(self, safe_extract=fake_extract,
                     run=lambda cmd, **kw: _ok_run(cmd, **kw))
        updater_mod = install_mod._updater
        old_key = updater_mod._FEED_VERIFY_KEY
        updater_mod._FEED_VERIFY_KEY = _pub
        args = install_mod.build_parser().parse_args(['--home', str(home)])
        try:
            fake_opener = mock.Mock()
            fake_opener.open.side_effect = fake_urlopen
            with mock.patch.object(svc._feed, 'opener', return_value=fake_opener):
                with mock.patch.object(install_mod._svc._feed, 'opener', return_value=fake_opener):
                    with contextlib.redirect_stdout(io.StringIO()):
                        rc = install_mod.do_update(args, _sleep=lambda s: None)
        finally:
            updater_mod._FEED_VERIFY_KEY = old_key
        self.assertEqual(rc, 0)
        self.assertEqual([url for url, _ in seen],
                         [ORIGIN + '/stable/latest.json', ORIGIN + '/stable/latest.json.sig',
                          ORIGIN + '/bundles/2.0.0.tar.gz'])
        for _url, header_names in seen:
            self.assertNotIn('x-scg-feed-token', header_names)
            self.assertNotIn('cookie', header_names)
            self.assertNotIn('authorization', header_names)
        self.assertEqual((home / 'download-auth.json').read_text(), '{legacy blocked settings')


class LiveHomeGuardTests(unittest.TestCase):
    """main() refuses scratch homes: service names are machine-wide.

    A --home under /tmp still bootstraps, bootouts, or TERMs the real
    launchd/systemd/Scheduler jobs, so only the production home (or an
    explicit ROUTER_LIVE_RUN=1) may reach a mutating action. Read-only
    actions stay exempt.
    """

    def _argv(self, home, *extra):
        return ['--home', str(home), *extra]

    def test_mutating_main_refuses_scratch_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            for extra in ([], ['--check-update'], ['--uninstall'],
                          ['--uninstall', '--dry-run'],
                          ['--feed', 'file:///x.json']):
                with self.subTest(extra=extra):
                    with self.assertRaisesRegex(SystemExit, 'scratch home'):
                        install_mod.main(self._argv(home, *extra))
            # Nothing reached the service layer: no release was activated.
            self.assertFalse((home / 'current').exists())

    def test_uninstall_dry_run_previews_without_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            backend = mock.Mock()
            _patch_attrs(self, platform_backend=lambda: backend)
            with contextlib.redirect_stdout(io.StringIO()) as output, \
                    mock.patch.dict(os.environ, {'ROUTER_LIVE_RUN': '1'}):
                rc = install_mod.main(self._argv(home, '--uninstall', '--dry-run'))
            self.assertEqual(rc, 0)
            self.assertIn('would uninstall', output.getvalue())
            self.assertFalse(home.exists())
            backend.check.assert_not_called()
            backend.uninstall.assert_not_called()

    def test_readonly_main_allows_scratch_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            with contextlib.redirect_stdout(io.StringIO()):
                install_mod.main(self._argv(home, '--preflight', '--client', 'none',
                                            '--python', sys.executable,
                                            '--feed', 'file:///bundle.tar.gz'))
            self.assertFalse(home.exists())

    def test_explicit_live_run_reaches_the_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            with install_mod.install_lock(home):
                with contextlib.redirect_stdout(io.StringIO()), \
                        mock.patch.dict(os.environ, {'ROUTER_LIVE_RUN': '1'}):
                    rc = install_mod.main(self._argv(home))
            self.assertEqual(rc, 0)


if __name__ == '__main__':
    unittest.main()
