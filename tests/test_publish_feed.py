"""Feed publication (Plan 139): offline against a recorded aws runner.

No AWS call, no token in a log. Proves the feed document points at the feed
origin and carries the token, the release document keeps the GitHub URL and
only carries the token while the transition switch is on, bundles are
immutable (an unreadable bundle state aborts), the channel feed is
invalidated, and --dry-run touches nothing.
"""
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'f' * 32
GITHUB_BASE = ('https://github.com/software-combined/SC_OpenRouter_adapter'
               '/releases/download')


def _load():
    spec = importlib.util.spec_from_file_location(
        'router_publish_feed_under_test', ROOT / 'tools' / 'publish_feed.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


publish = _load()


class _Result:
    def __init__(self, stdout='', returncode=0, stderr=''):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _Aws:
    """Recorded aws CLI: answers get-parameter and head-object, else ''."""

    def __init__(self, existing=None, token=TOKEN, head_error=None):
        self.existing = existing
        self.token = token
        self.head_error = head_error
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append([str(word) for word in argv])
        if 'get-parameter' in argv:
            return _Result(self.token + '\n')
        if 'head-object' in argv:
            if self.head_error:
                return _Result('', returncode=255, stderr=self.head_error)
            if self.existing is None:
                return _Result('', returncode=1, stderr='404 Not Found')
            return _Result(self.existing + '\n')
        if 'create-invalidation' in argv:
            return _Result('INV1\n')
        return _Result('')

    def flat(self):
        return [word for call in self.calls for word in call]


class PublishFeedTests(unittest.TestCase):
    def _dist(self, version='0.6.21.7', channel='beta'):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dist = Path(tmp.name)
        bundle = f'ai-router-{version}.tar.gz'
        (dist / bundle).write_bytes(b'bundle-bytes')
        latest = {
            'version': version,
            'url': f'{GITHUB_BASE}/v{version}-{channel}/{bundle}',
            'sha256': hashlib.sha256(b'bundle-bytes').hexdigest(),
            'min_python': '3.14',
            'serial': 7,
            'published': '2026-09-11T00:00:00+00:00',
        }
        (dist / 'latest.json').write_text(json.dumps(latest))
        return dist

    def _run(self, dist, runner, channel='beta', extra=()):
        argv = ['--dist', str(dist), '--channel', channel, '--bucket', 'feed-bucket']
        out = io.StringIO()
        with mock.patch.object(publish, 'run', runner), \
                redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = publish.main(list(argv) + list(extra))
        return code, out.getvalue()

    def test_feed_document_points_at_feed_origin_and_carries_token(self):
        dist = self._dist()
        latest = json.loads((dist / 'latest.json').read_text())
        bundle = publish.bundle_name(latest)
        feed_doc, release_doc = publish.documents(latest, bundle, TOKEN, False)
        self.assertEqual(feed_doc['url'],
                         publish.FEED_ORIGIN + '/bundles/' + bundle)
        self.assertEqual(feed_doc['feed_token'], TOKEN)
        self.assertEqual(release_doc['url'], latest['url'])
        self.assertNotIn('feed_token', release_doc)

    def test_transition_embeds_token_in_release_document(self):
        dist = self._dist()
        latest = json.loads((dist / 'latest.json').read_text())
        _, release_doc = publish.documents(latest, 'b.tar.gz', TOKEN, True)
        self.assertEqual(release_doc['feed_token'], TOKEN)
        self.assertEqual(release_doc['url'], latest['url'])

    def test_stale_token_never_carries_into_the_release_copy(self):
        latest = {'version': '1.0.0', 'url': GITHUB_BASE + '/v1.0.0/b.tar.gz',
                  'sha256': 'a' * 64, 'serial': 1, 'min_python': '3.14',
                  'feed_token': 'stale'}
        feed_doc, release_doc = publish.documents(latest, 'b.tar.gz', TOKEN, False)
        self.assertEqual(feed_doc['feed_token'], TOKEN)
        self.assertNotIn('feed_token', release_doc)

    def test_bundle_name_refuses_an_incomplete_document(self):
        for field in ('version', 'url', 'sha256', 'serial', 'min_python'):
            with self.subTest(field=field):
                with self.assertRaises(SystemExit):
                    publish.bundle_name({'version': '1.0.0', 'url': 'u',
                                         'sha256': 'a', 'serial': 1,
                                         'min_python': '3.14', field: ''})

    def test_url_must_name_this_versions_bundle(self):
        with self.assertRaises(SystemExit):
            publish.bundle_name({'version': '1.0.0', 'url': 'https://x/other.tar.gz',
                                 'sha256': 'a', 'serial': 1, 'min_python': '3.14'})

    def test_bundle_conflict_is_refused(self):
        dist = self._dist()
        with self.assertRaises(SystemExit) as caught:
            with mock.patch.object(publish, 'run', _Aws(existing='b' * 64)):
                publish.main(['--dist', str(dist), '--channel', 'beta'])
        self.assertIn('immutable', str(caught.exception))

    def test_unreadable_bundle_state_is_refused(self):
        """A head-object failure that is not a 404 must not skip the guard."""
        dist = self._dist()
        runner = _Aws(head_error='AccessDenied')
        with self.assertRaises(SystemExit) as caught:
            self._run(dist, runner)
        self.assertIn('cannot read', str(caught.exception))
        self.assertFalse([call for call in runner.calls if 'cp' in call])

    def test_publishes_bundle_feed_and_invalidation(self):
        """The channel document uploaded is the feed copy, not the release one.

        Bound at the CLI level and not only in the documents() unit test: a
        swap of the two files would leave every repo-free host reading a
        private GitHub URL with no token while CI stayed green.
        """
        dist = self._dist()
        runner = _Aws()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('ROUTER_FEED_EMBED_TOKEN', None)
            code, out = self._run(dist, runner,
                                  extra=['--distribution-id', 'EDIST'])
        self.assertEqual(code, 0)
        bundle = 'ai-router-0.6.21.7.tar.gz'
        uploaded = [call for call in runner.calls if call[1:3] == ['s3', 'cp']]
        self.assertIn(str(dist / bundle), [call[3] for call in uploaded])
        self.assertIn('s3://feed-bucket/beta/latest.json',
                      [call[4] for call in uploaded])
        channel_uploads = [call for call in uploaded
                           if call[4].endswith('/latest.json')]
        self.assertEqual([(call[3], call[4]) for call in channel_uploads],
                         [(str(dist / 'feed-latest.json'),
                           's3://feed-bucket/beta/latest.json')])
        invalidations = [call for call in runner.calls if 'create-invalidation' in call]
        self.assertEqual([[call[call.index('--paths') + 1]] for call in invalidations],
                         [['/beta/latest.json']])
        feed_doc = json.loads((dist / 'feed-latest.json').read_text())
        self.assertEqual(feed_doc['feed_token'], TOKEN)
        release_doc = json.loads((dist / 'release-latest.json').read_text())
        self.assertNotIn('feed_token', release_doc)
        self.assertIn('token feed document only', out)

    def test_stable_channel_key_and_contract_passthrough(self):
        """Stable publishes under stable/, and the client contract survives."""
        dist = self._dist(channel='stable')
        runner = _Aws()
        code, _ = self._run(dist, runner, channel='stable',
                            extra=['--distribution-id', 'EDIST'])
        self.assertEqual(code, 0)
        uploaded = [call for call in runner.calls if call[1:3] == ['s3', 'cp']]
        self.assertIn('s3://feed-bucket/stable/latest.json',
                      [call[4] for call in uploaded])
        invalidations = [call for call in runner.calls if 'create-invalidation' in call]
        self.assertEqual([[call[call.index('--paths') + 1]] for call in invalidations],
                         [['/stable/latest.json']])
        feed_doc = json.loads((dist / 'feed-latest.json').read_text())
        original = json.loads((dist / 'latest.json').read_text())
        for field in ('version', 'sha256', 'serial', 'min_python'):
            self.assertEqual(feed_doc[field], original[field])
        self.assertIsInstance(feed_doc['serial'], int)

    def test_transition_switch_reaches_the_release_document(self):
        dist = self._dist()
        runner = _Aws()
        with mock.patch.dict(os.environ, {'ROUTER_FEED_EMBED_TOKEN': 'true'}):
            code, out = self._run(dist, runner)
        self.assertEqual(code, 0)
        released = json.loads((dist / 'release-latest.json').read_text())
        self.assertEqual(released['feed_token'], TOKEN)
        self.assertIn('also in the GitHub Release document', out)

    def test_token_never_reaches_argv_or_output(self):
        dist = self._dist()
        runner = _Aws()
        code, out = self._run(dist, runner, extra=['--distribution-id', 'EDIST'])
        self.assertEqual(code, 0)
        self.assertNotIn(TOKEN, out)
        self.assertNotIn(TOKEN, ' '.join(runner.flat()))

    def test_empty_token_parameter_is_refused(self):
        """A blank SSM value must not publish: it would stall every host."""
        dist = self._dist()
        with self.assertRaises(SystemExit) as caught:
            self._run(dist, _Aws(token=''))
        self.assertIn('empty', str(caught.exception))
        self.assertFalse((dist / 'feed-latest.json').exists())

    def test_existing_identical_bundle_is_not_uploaded_twice(self):
        dist = self._dist()
        sha = json.loads((dist / 'latest.json').read_text())['sha256']
        runner = _Aws(existing=sha)
        code, out = self._run(dist, runner)
        self.assertEqual(code, 0)
        uploaded = [call for call in runner.calls if call[1:3] == ['s3', 'cp']]
        self.assertNotIn(str(dist / 'ai-router-0.6.21.7.tar.gz'),
                         [call[3] for call in uploaded])
        self.assertIn('bundle already published', out)

    def test_dry_run_calls_nothing_and_writes_nothing(self):
        dist = self._dist()

        def _boom(argv, **kwargs):
            raise AssertionError(f'dry run ran {argv}')

        code, out = self._run(dist, _boom, extra=['--dry-run'])
        self.assertEqual(code, 0)
        self.assertIn('dry run', out)
        self.assertFalse((dist / 'feed-latest.json').exists())
        self.assertFalse((dist / 'release-latest.json').exists())

    def test_unknown_channel_is_refused(self):
        dist = self._dist()
        with self.assertRaises(SystemExit):
            self._run(dist, _Aws(), channel='nightly')

    def test_bundle_checksum_mismatch_is_refused(self):
        dist = self._dist()
        latest = json.loads((dist / 'latest.json').read_text())
        latest['sha256'] = 'c' * 64
        (dist / 'latest.json').write_text(json.dumps(latest))
        with self.assertRaises(SystemExit) as caught:
            self._run(dist, _Aws())
        self.assertIn('does not match', str(caught.exception))

    def test_missing_dist_directory_is_refused(self):
        with self.assertRaises(SystemExit) as caught:
            self._run(self._dist() / 'absent', _Aws())
        self.assertIn('release.py', str(caught.exception))

    def test_missing_aws_cli_is_reported(self):
        dist = self._dist()

        def _no_cli(argv, **kwargs):
            raise FileNotFoundError('aws')

        with self.assertRaises(SystemExit) as caught:
            self._run(dist, _no_cli)
        self.assertIn('cannot run the aws CLI', str(caught.exception))

    def test_aws_failure_reports_one_clean_line(self):
        dist = self._dist()

        def _failing(argv, **kwargs):
            return _Result('', returncode=255, stderr='An error occurred\n(AccessDenied)')

        with self.assertRaises(SystemExit) as caught:
            self._run(dist, _failing)
        self.assertIn('AccessDenied', str(caught.exception))
        self.assertNotIn('\n', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
