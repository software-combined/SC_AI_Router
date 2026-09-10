"""Token-gated feed migration: gh route until a token arrives (Plan 054 T)."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_install import _craft_bundle, _ok_run, _patch_attrs, install_mod

svc = install_mod._svc
ORIGIN = 'https://dist.softwarecombined.com'


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


class FeedMigrationTests(unittest.TestCase):
    def _home(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name) / 'home'
        home.mkdir(parents=True)
        return home

    def test_no_token_stays_on_github_route(self):
        home = self._home()
        self.assertEqual(svc.channel_feed(home),
                         svc.RELEASES_PREFIX + 'latest/download/latest.json')
        self.assertIsNone(svc.feed_token(home))

    def test_token_switches_origin_and_beta(self):
        home = self._home()
        svc.persist_feed_token(home, {'feed_token': 'tok-1'})
        self.assertEqual(svc.channel_feed(home), ORIGIN + '/stable/latest.json')
        (home / 'channel').write_text('beta\n')
        self.assertEqual(svc.channel_feed(home), ORIGIN + '/beta/latest.json')

    def test_persist_learns_token_and_keeps_previous(self):
        home = self._home()
        self.assertTrue(svc.persist_feed_token(home, {'feed_token': 'tok-a'}))
        self.assertEqual(svc.feed_token(home), 'tok-a')
        self.assertTrue(svc.persist_feed_token(home, {'feed_token': 'tok-b'}))
        self.assertEqual((home / 'feed-token.previous').read_text(), 'tok-a\n')
        self.assertFalse(svc.persist_feed_token(home, {'version': '1.0.0'}))

    def test_off_origin_bundle_is_refused(self):
        home = self._home()
        with self.assertRaisesRegex(SystemExit, 'untrusted feed URL'):
            svc.fetch('https://evil.example/bundle.tar.gz', home)

    def test_refusal_never_echoes_a_query_string(self):
        """A credentialed URL must not reach update.log or stderr."""
        home = self._home()
        with self.assertRaises(SystemExit) as ctx:
            svc.fetch('https://evil.example/x?sig=SECRET-CRED', home)
        self.assertNotIn('SECRET-CRED', str(ctx.exception.code))
        self.assertIn('evil.example/x', str(ctx.exception.code))

    def test_token_header_reaches_only_the_feed_origin(self):
        home = self._home()
        svc.persist_feed_token(home, {'feed_token': 'tok-1'})
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen['header'] = req.get_header('X-scg-feed-token')
            return _Response()

        with mock.patch.object(svc.urllib.request, 'urlopen', side_effect=fake_urlopen):
            svc.fetch_feed(ORIGIN + '/stable/latest.json', None, home=home)
            self.assertEqual(seen['header'], 'tok-1')
            svc.fetch(ORIGIN + '/bundles/x.tar.gz', home)
            self.assertEqual(seen['header'], 'tok-1')

    def test_403_retries_once_with_previous_token(self):
        home = self._home()
        (home / 'feed-token').write_text('tok-new\n')
        (home / 'feed-token.previous').write_text('tok-old\n')
        calls = []

        def fake_urlopen(req, timeout=None):
            token = req.get_header('X-scg-feed-token')
            calls.append(token)
            if token == 'tok-new':
                raise svc.urllib.error.HTTPError(req.full_url, 403, 'Forbidden', {}, None)
            return _Response(b'{"version": "1.0.0"}')

        with mock.patch.object(svc.urllib.request, 'urlopen', side_effect=fake_urlopen):
            status, body, _etag = svc.fetch_feed(ORIGIN + '/stable/latest.json', None, home=home)
        self.assertEqual((status, body), (200, b'{"version": "1.0.0"}'))
        self.assertEqual(calls, ['tok-new', 'tok-old'])

    def test_double_403_is_actionable_and_secret_free(self):
        home = self._home()
        (home / 'feed-token').write_text('tok-new\n')
        (home / 'feed-token.previous').write_text('tok-old\n')

        def fake_urlopen(req, timeout=None):
            raise svc.urllib.error.HTTPError(req.full_url, 403, 'Forbidden', {}, None)

        with mock.patch.object(svc.urllib.request, 'urlopen', side_effect=fake_urlopen):
            with self.assertRaisesRegex(SystemExit, 'Technology library') as ctx:
                svc.fetch_feed(ORIGIN + '/stable/latest.json', None, home=home)
        self.assertNotIn('tok-new', str(ctx.exception.code))
        self.assertNotIn('tok-old', str(ctx.exception.code))

    def test_current_host_learns_token_and_migrates_next_poll(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir(parents=True)
            (home / 'mixed-router-state.json').write_text(json.dumps({'port': 1, 'token': 'x'}))
            (home / 'releases' / '1.0.0' / 'packaging').mkdir(parents=True)
            (home / 'releases' / '1.0.0' / 'packaging' / 'VERSION').write_text('1.0.0\n')
            (home / 'current').write_text('1.0.0\n')
            blob, _ = _craft_bundle('1.0.0')
            latest = {'version': '1.0.0', 'url': 'file:///bundle.tar.gz',
                      'sha256': None, 'serial': 0, 'feed_token': 'tok-new'}
            _patch_attrs(self, run=lambda cmd, **kw: _ok_run(cmd, **kw))
            args = install_mod.build_parser().parse_args(['--check-update', '--home', str(home)])
            with mock.patch.dict('os.environ', {'HOME': str(Path(tmp) / 'fakehome'),
                                                'OPENROUTER_API_KEY': 'k'}):
                with mock.patch('time.sleep'):
                    rc = install_mod.do_check_update(
                        args, _fetch=lambda url: blob,
                        _read_feed=lambda f, e: (200, json.dumps(latest).encode(), 'etag-1'),
                        _sleep=lambda s: None)
            self.assertEqual(rc, 0)
            self.assertEqual((home / 'feed-token').read_text(), 'tok-new\n')
            self.assertEqual(svc.channel_feed(home), ORIGIN + '/stable/latest.json')

    def test_scheduled_poll_carries_token_on_default_wiring(self):
        """The real scheduled path must not bypass the token header.

        install.do_check_update supplies a home-bound fetch by default; the
        feed poll and the bundle download must both send X-SCG-Feed-Token,
        or a migrated host 403s and every update parks.
        """
        home = self._home()
        svc.persist_feed_token(home, {'feed_token': 'tok-1'})
        (home / 'mixed-router-state.json').write_text(json.dumps({'port': 1, 'token': 'x'}))
        (home / 'releases' / '1.0.0' / 'packaging').mkdir(parents=True)
        (home / 'releases' / '1.0.0' / 'packaging' / 'VERSION').write_text('1.0.0\n')
        (home / 'current').write_text('1.0.0\n')
        latest = {'version': '2.0.0', 'url': ORIGIN + '/bundles/2.0.0.tar.gz',
                  'sha256': None, 'serial': 1}
        seen = []

        def fake_urlopen(req, timeout=None):
            url = getattr(req, 'full_url', req)
            token = req.get_header('X-scg-feed-token') if hasattr(req, 'get_header') else None
            seen.append((url, token))
            if url.endswith('/stable/latest.json'):
                return _Response(json.dumps(latest).encode())
            return _Response(b'blob')

        def fake_extract(blob, dest):
            (Path(dest) / 'packaging').mkdir(parents=True, exist_ok=True)
            (Path(dest) / 'packaging' / 'install.py').write_text('# installer\n')

        _patch_attrs(self, safe_extract=fake_extract,
                     run=lambda cmd, **kw: _ok_run(cmd, **kw))
        args = install_mod.build_parser().parse_args(['--home', str(home)])
        with mock.patch.object(svc.urllib.request, 'urlopen', side_effect=fake_urlopen):
            with contextlib.redirect_stdout(io.StringIO()):
                rc = install_mod.do_check_update(args, _sleep=lambda s: None)
        self.assertEqual(rc, 0)
        self.assertEqual(seen, [(ORIGIN + '/stable/latest.json', 'tok-1'),
                                (ORIGIN + '/bundles/2.0.0.tar.gz', 'tok-1')])

    def test_github_route_still_uses_authenticated_cli(self):
        prefix = svc.RELEASES_PREFIX
        with mock.patch.object(svc.shutil, 'which', return_value='/usr/bin/gh'), \
                mock.patch.object(svc, 'run', return_value=subprocess.CompletedProcess(
                    [], 0, b'asset bytes', b'')) as run, \
                mock.patch.object(svc.urllib.request, 'urlopen',
                                  side_effect=AssertionError('anonymous fetch')):
            self.assertEqual(svc.fetch(prefix + 'latest/download/latest.json'), b'asset bytes')
            cmd = run.call_args.args[0]
            self.assertEqual(cmd[:5], ['/usr/bin/gh', 'release', 'download', '--repo',
                                       'software-combined/SC_OpenRouter_adapter'])


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

    def test_readonly_main_allows_scratch_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            with contextlib.redirect_stdout(io.StringIO()):
                install_mod.main(self._argv(home, '--preflight', '--client', 'none',
                                            '--python', sys.executable))
            self.assertFalse(home.exists())

    def test_explicit_live_run_reaches_the_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            with install_mod.install_lock(home):
                with contextlib.redirect_stdout(io.StringIO()), \
                        mock.patch.dict(os.environ, {'ROUTER_LIVE_RUN': '1'}):
                    rc = install_mod.main(self._argv(home))
            self.assertEqual(rc, 0)


class BetaChannelTests(unittest.TestCase):
    def _home(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name) / 'home'
        home.mkdir(parents=True)
        return home

    def _patch_gh(self, func):
        feed_mod = install_mod._svc._feed
        return mock.patch.object(feed_mod, '_gh_run', func)

    def test_beta_no_token_resolves_prerelease_asset_via_gh(self):
        home = self._home()
        (home / 'channel').write_text('beta\n')
        seen = []

        def fake_run(cmd, **kwargs):
            seen.append(cmd)
            return type('R', (), {'returncode': 0,
                                  'stdout': 'v0.6.14.29-beta\n',
                                  'stderr': ''})()

        with self._patch_gh(fake_run):
            url = svc.channel_feed(home)
        self.assertEqual(seen[0][:4], ['gh', 'release', 'list', '--repo'])
        self.assertTrue(url.endswith(
            '/releases/download/v0.6.14.29-beta/latest-beta.json'))

    def test_beta_no_token_fails_closed_on_gh_error(self):
        home = self._home()
        (home / 'channel').write_text('beta\n')

        def raising_gh(exc):
            def _gh(*a, **k):
                raise exc
            return _gh

        cases = (
            ('nonzero', type('R', (), {'returncode': 2,
                                       'stdout': '', 'stderr': 'nope'})()),
            ('empty', type('R', (), {'returncode': 0,
                                     'stdout': '\n', 'stderr': ''})()),
            ('missing-gh', FileNotFoundError(2, 'gh')),
        )
        for name, outcome in cases:
            if isinstance(outcome, BaseException):
                gh = raising_gh(outcome)
            else:
                gh = lambda *a, **k: outcome  # noqa: E731
            with self.subTest(name=name), self._patch_gh(gh):
                with self.assertRaisesRegex(SystemExit, 'Cannot resolve beta'):
                    svc.channel_feed(home)

    def test_beta_no_token_rejects_malformed_tag(self):
        home = self._home()
        (home / 'channel').write_text('beta\n')
        for bad in ('a/b', 'a?b', 'a#b', 'a b'):
            result = type('R', (), {'returncode': 0, 'stdout': bad + '\n',
                                    'stderr': ''})()
            with self.subTest(tag=bad), self._patch_gh(lambda *a, **k: result):
                with self.assertRaisesRegex(SystemExit, 'malformed beta release'):
                    svc.channel_feed(home)

    def test_beta_no_token_takes_first_prerelease_behind_stable(self):
        home = self._home()
        (home / 'channel').write_text('beta\n')
        result = type('R', (), {'returncode': 0,
                                'stdout': 'v0.6.14.29-beta\nv0.6.13.28\n',
                                'stderr': ''})()
        with self._patch_gh(lambda *a, **k: result):
            url = svc.channel_feed(home)
        self.assertTrue(url.endswith(
            '/releases/download/v0.6.14.29-beta/latest-beta.json'))

    def test_beta_token_stays_on_cloudfront_beta_path(self):
        home = self._home()
        svc.persist_feed_token(home, {'feed_token': 'tok-1'})
        (home / 'channel').write_text('beta\n')
        self.assertEqual(svc.channel_feed(home),
                         'https://dist.softwarecombined.com/beta/latest.json')


if __name__ == '__main__':
    unittest.main()
