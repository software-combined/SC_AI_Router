"""Feed publication (Plan 139): offline against a recorded aws runner.

No AWS call. Proves the feed document points at the public feed origin, the
release document keeps the GitHub URL, neither carries a credential, bundles
are immutable (an unreadable bundle state aborts), the channel feed is
invalidated, and --dry-run touches nothing.
"""
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
GITHUB_BASE = ('https://github.com/software-combined/SC_AI'
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
    """Recorded aws CLI: answers head-object, else ''."""

    def __init__(self, existing=None, head_error=None, put_error=None):
        self.existing = existing
        self.head_error = head_error
        self.put_error = put_error
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append([str(word) for word in argv])
        if 'head-object' in argv:
            if self.head_error:
                return _Result('', returncode=255, stderr=self.head_error)
            if self.existing is None:
                return _Result('', returncode=1, stderr='404 Not Found')
            return _Result(self.existing + '\n')
        if 'put-object' in argv:
            # S3's create-only refusal, as the CLI reports it on a 412.
            return _Result('', returncode=1, stderr=self.put_error) if self.put_error \
                else _Result('{}')
        if 'create-invalidation' in argv:
            return _Result('INV1\n')
        return _Result('')


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

    def _seed(self, dist):
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location(
            'router_feed_verify_seed',
            Path(__file__).resolve().parents[1] / 'packaging' / 'feed_verify.py')
        fv = _ilu.module_from_spec(spec)
        spec.loader.exec_module(fv)
        seed, _pub = fv.generate_keypair()
        key = dist / 'seed'
        key.parent.mkdir(parents=True, exist_ok=True)
        key.write_text(seed + '\n')
        return key

    def _run(self, dist, runner, channel='beta', extra=()):
        argv = ['--dist', str(dist), '--channel', channel, '--bucket', 'feed-bucket']
        if not any(a == '--sign' or str(a).startswith('--sign=') for a in extra):
            argv += ['--sign', str(self._seed(dist))]
        out = io.StringIO()
        with mock.patch.object(publish, 'run', runner), \
                redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = publish.main(list(argv) + list(extra))
        return code, out.getvalue()

    def test_documents_are_public_and_keep_both_origins(self):
        dist = self._dist()
        latest = json.loads((dist / 'latest.json').read_text())
        bundle = publish.bundle_name(latest)
        feed_doc, release_doc = publish.documents(latest, bundle)
        self.assertEqual(feed_doc['url'],
                         publish.FEED_ORIGIN + '/bundles/' + bundle)
        self.assertEqual(release_doc['url'], latest['url'])
        self.assertNotIn('feed_token', feed_doc)
        self.assertNotIn('feed_token', release_doc)

    def test_a_stale_embedded_token_never_survives_publication(self):
        latest = {'version': '1.0.0', 'url': GITHUB_BASE + '/v1.0.0/b.tar.gz',
                  'sha256': 'a' * 64, 'serial': 1, 'min_python': '3.14',
                  'feed_token': 'stale'}
        feed_doc, release_doc = publish.documents(latest, 'b.tar.gz')
        self.assertNotIn('feed_token', feed_doc)
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
                publish.main(['--dist', str(dist), '--channel', 'beta',
                              '--bucket', 'feed-bucket',
                              '--sign', str(self._seed(dist))])
        self.assertIn('immutable', str(caught.exception))

    def test_a_missing_bucket_is_refused(self):
        # No default exists, so a fork cannot publish to someone else's
        # bucket by running the tool with no arguments (Plan 160).
        dist = self._dist()
        err = io.StringIO()
        with redirect_stderr(err):
            with self.assertRaises(SystemExit) as caught:
                publish.main(['--dist', str(dist), '--channel', 'beta'])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn('--bucket', err.getvalue())

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
        swap of the two files would leave every host reading a GitHub Release
        asset URL instead of the feed while CI stayed green.
        """
        dist = self._dist()
        runner = _Aws()
        code, out = self._run(dist, runner, extra=['--distribution-id', 'EDIST'])
        self.assertEqual(code, 0)
        bundle = 'ai-router-0.6.21.7.tar.gz'
        writes = [call for call in runner.calls if call[1:3] == ['s3api', 'put-object']]
        self.assertEqual(len(writes), 1, 'the bundle is written once, create-only')
        write = writes[0]
        self.assertEqual(write[write.index('--body') + 1], str(dist / bundle))
        self.assertEqual(write[write.index('--key') + 1], f'bundles/{bundle}')
        self.assertEqual(write[write.index('--if-none-match') + 1], '*')
        uploaded = [call for call in runner.calls if call[1:3] == ['s3', 'cp']]
        self.assertIn('s3://feed-bucket/beta/latest.json',
                      [call[4] for call in uploaded])
        channel_uploads = [call for call in uploaded
                           if call[4].endswith('/latest.json')]
        self.assertEqual([(call[3], call[4]) for call in channel_uploads],
                         [(str(dist / 'feed-latest.json'),
                           's3://feed-bucket/beta/latest.json')])
        invalidations = [call for call in runner.calls if 'create-invalidation' in call]
        self.assertEqual([[call[call.index('--paths') + 1]] for call in invalidations],
                         [['/beta/latest.json'], ['/beta/latest.json.sig']])
        feed_doc = json.loads((dist / 'feed-latest.json').read_text())
        self.assertNotIn('feed_token', feed_doc)
        release_doc = json.loads((dist / 'release-latest.json').read_text())
        self.assertNotIn('feed_token', release_doc)
        self.assertIn('published beta 0.6.21.7', out)

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
                         [['/stable/latest.json'], ['/stable/latest.json.sig'], ['/install/*']])
        feed_doc = json.loads((dist / 'feed-latest.json').read_text())
        original = json.loads((dist / 'latest.json').read_text())
        for field in ('version', 'sha256', 'serial', 'min_python'):
            self.assertEqual(feed_doc[field], original[field])
        self.assertIsInstance(feed_doc['serial'], int)

    def test_existing_identical_bundle_is_not_uploaded_twice(self):
        dist = self._dist()
        sha = json.loads((dist / 'latest.json').read_text())['sha256']
        runner = _Aws(existing=sha)
        code, out = self._run(dist, runner)
        self.assertEqual(code, 0)
        writes = [call for call in runner.calls if call[1:3] == ['s3api', 'put-object']]
        self.assertEqual(writes, [], 'an identical bundle is never re-written')
        self.assertIn('bundle already published', out)

    def test_a_precondition_failure_is_an_immutability_refusal(self):
        # S3's own create-only refusal, in the CLI's real wording, maps to the
        # same message as the pre-check (Plan 167).
        dist = self._dist()
        runner = _Aws(put_error=(
            'An error occurred (PreconditionFailed) when calling the PutObject '
            'operation: At least one of the pre-conditions you specified did '
            'not hold'))
        with self.assertRaises(SystemExit) as caught:
            self._run(dist, runner)
        self.assertIn('immutable', str(caught.exception))

    def test_dry_run_calls_nothing_and_writes_nothing(self):
        dist = self._dist()

        def _boom(argv, **kwargs):
            raise AssertionError(f'dry run ran {argv}')

        code, out = self._run(dist, _boom, extra=['--dry-run'])
        self.assertEqual(code, 0)
        self.assertIn('dry run', out)
        self.assertFalse((dist / 'feed-latest.json').exists())
        self.assertFalse((dist / 'release-latest.json').exists())

    def test_publish_without_sign_is_refused(self):
        dist = self._dist()
        runner = _Aws()
        with self.assertRaisesRegex(SystemExit, 'unsigned'):
            with mock.patch.object(publish, 'run', runner), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                publish.main(['--dist', str(dist), '--channel', 'beta',
                              '--bucket', 'feed-bucket'])

    def test_sidecar_signs_served_bytes(self):
        import importlib.util as _ilu
        dist = self._dist()
        runner = _Aws()
        self._run(dist, runner)
        spec = _ilu.spec_from_file_location(
            'router_feed_verify_sidecar',
            Path(__file__).resolve().parents[1] / 'packaging' / 'feed_verify.py')
        fv = _ilu.module_from_spec(spec)
        spec.loader.exec_module(fv)
        seed = (dist / 'seed').read_text().strip()
        pub = fv.public_key_hex(seed)
        body = (dist / publish.FEED_DOCUMENT).read_bytes()
        sig = (dist / publish.FEED_SIG_DOCUMENT).read_text()
        with mock.patch.object(fv, 'FEED_PUBLIC_KEY', pub):
            self.assertEqual(fv.checked_feed(body, sig.encode())['serial'], 7)
        served = dict(json.loads(body.decode()))
        served['url'] = 'https://other.example/x.tar.gz'
        with mock.patch.object(fv, 'FEED_PUBLIC_KEY', pub):
            with self.assertRaises(SystemExit):
                fv.checked_feed((json.dumps(served, indent=2) + '\n').encode(), sig.encode())

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
