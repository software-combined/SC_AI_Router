"""First-install publication: offline against recorded aws and download seams.

No AWS call and no network. Proves the runtimes table matches
packaging/runtime.lock, every pinned runtime is verified before it is
uploaded, identical artifacts are skipped, different bytes under a runtime
key are refused, a changed wrapper is replaced, the wrappers are published
only after the table they read, and --dry-run touches nothing.
"""
import hashlib
import importlib.util
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED = ('darwin/arm64', 'darwin/x86_64', 'linux/x86_64', 'windows/x86_64')


def _load():
    spec = importlib.util.spec_from_file_location(
        'router_publish_first_install_under_test',
        ROOT / 'tools' / 'publish_first_install.py')
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
    """Recorded aws CLI: head-object answers from `existing`, else success."""

    def __init__(self, existing=None, head_error=None):
        self.existing = dict(existing or {})
        self.head_error = head_error
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append([str(word) for word in argv])
        if 'head-object' in argv:
            if self.head_error:
                return _Result('', returncode=255, stderr=self.head_error)
            key = argv[argv.index('--key') + 1]
            if key in self.existing:
                return _Result(self.existing[key] + '\n')
            return _Result('', returncode=1, stderr='404 Not Found')
        return _Result('')

    def uploaded(self):
        return [call for call in self.calls if call[1:3] == ['s3', 'cp']]


def _lock():
    """A valid lock whose digests match the bytes _Downloads serves."""
    targets = []
    for target in SUPPORTED:
        os_name, cpu = target.split('/')
        mirror = 'runtimes/cpython-test-%s-%s.tar.gz' % (os_name, cpu)
        body = ('runtime-bytes-' + mirror).encode()
        targets.append({
            'os': os_name, 'cpu': cpu, 'triple': 'test', 'format': 'tar.gz',
            'url': 'https://example.invalid/' + mirror, 'mirror': mirror,
            'sha256': hashlib.sha256(body).hexdigest(),
            'exec': 'python/bin/python3.14', 'licences': ['LICENSE']})
    return {'cpython': '3.14.7', 'build': 'test', 'targets': targets}


class _Downloads:
    """Serves the lock's bytes; `corrupt` URLs get tampered bytes instead."""

    def __init__(self, lock, corrupt=()):
        self.payload = {}
        for entry in lock['targets']:
            self.payload[entry['url']] = ('runtime-bytes-' + entry['mirror']).encode()
        self.corrupt = set(corrupt)
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        return io.BytesIO(b'tampered' if url in self.corrupt else self.payload[url])


class FirstInstallTests(unittest.TestCase):
    def _run(self, lock, runner, downloads, extra=()):
        out = io.StringIO()
        with mock.patch.object(publish, 'load_lock', lambda: lock), \
                mock.patch.object(publish, 'run', runner), \
                mock.patch.object(publish, 'download', downloads), \
                redirect_stdout(out):
            code = publish.main(['--bucket', 'feed-bucket'] + list(extra))
        return code, out.getvalue()

    def test_real_lock_table_covers_every_supported_target(self):
        doc = publish.load_lock()
        table = publish.runtimes_document(doc)['targets']
        self.assertEqual(set(table), set(SUPPORTED))
        for target, entry in table.items():
            with self.subTest(target=target):
                self.assertTrue(entry['mirror'].startswith('runtimes/'))
                self.assertRegex(entry['sha256'], r'^[0-9a-f]{64}$')
                self.assertTrue(entry['exec'])

    def test_publishes_runtimes_then_table_then_bootstrap(self):
        lock = _lock()
        runner = _Aws()
        downloads = _Downloads(lock)
        code, out = self._run(lock, runner, downloads)
        self.assertEqual(code, 0)
        keys = [call[4].split('s3://feed-bucket/')[1] for call in runner.uploaded()]
        mirrors = [entry['mirror'] for entry in lock['targets']]
        self.assertEqual(keys[:len(mirrors)], mirrors)
        self.assertEqual(keys[len(mirrors)], publish.RUNTIMES_DOCUMENT)
        self.assertEqual(keys[len(mirrors) + 1:],
                         ['bootstrap/' + name for name in publish.BOOTSTRAP_FILES])
        self.assertEqual(sorted(downloads.calls),
                         sorted(entry['url'] for entry in lock['targets']))
        for call in runner.uploaded():
            key = call[4].split('s3://feed-bucket/')[1]
            if key == publish.RUNTIMES_DOCUMENT:
                self.assertIn('application/json', call)
                continue
            if key.startswith('bootstrap/'):
                expected = hashlib.sha256(
                    (ROOT / 'packaging' / key.split('/', 1)[1]).read_bytes()).hexdigest()
                self.assertIn(publish.BOOTSTRAP_CACHE_CONTROL, call)
            else:
                expected = next(entry['sha256'] for entry in lock['targets']
                                if entry['mirror'] == key)
                self.assertIn(publish.IMMUTABLE_CACHE_CONTROL, call)
            self.assertEqual(call[call.index('--metadata') + 1], 'sha256=' + expected)
        self.assertIn('runtimes.json: published', out)

    def test_changed_bootstrap_replaces_the_old_bytes(self):
        """The wrappers are the mutable entry point: a fix must ship."""
        lock = _lock()
        runner = _Aws(existing={'bootstrap/bootstrap.sh': 'd' * 64})
        code, _ = self._run(lock, runner, _Downloads(lock))
        self.assertEqual(code, 0)
        uploaded = [call[4] for call in runner.uploaded()]
        self.assertIn('s3://feed-bucket/bootstrap/bootstrap.sh', uploaded)

    def test_identical_runtime_is_skipped(self):
        lock = _lock()
        first = lock['targets'][0]
        runner = _Aws(existing={first['mirror']: first['sha256']})
        downloads = _Downloads(lock)
        code, _ = self._run(lock, runner, downloads)
        self.assertEqual(code, 0)
        self.assertNotIn(first['url'], downloads.calls)
        uploaded = [call[4] for call in runner.uploaded()]
        self.assertNotIn('s3://feed-bucket/' + first['mirror'], uploaded)

    def test_different_runtime_is_refused(self):
        lock = _lock()
        first = lock['targets'][0]
        runner = _Aws(existing={first['mirror']: 'd' * 64})
        downloads = _Downloads(lock)
        with self.assertRaises(SystemExit) as caught:
            self._run(lock, runner, downloads)
        self.assertIn('immutable', str(caught.exception))
        self.assertNotIn(first['url'], downloads.calls)

    def test_unreadable_state_is_refused(self):
        """A head-object failure that is not a 404 must not skip the guard."""
        lock = _lock()
        runner = _Aws(head_error='AccessDenied')
        downloads = _Downloads(lock)
        with self.assertRaises(SystemExit) as caught:
            self._run(lock, runner, downloads)
        self.assertIn('cannot read', str(caught.exception))
        self.assertFalse(runner.uploaded())
        self.assertFalse(downloads.calls)

    def test_checksum_mismatch_blocks_the_table(self):
        lock = _lock()
        corrupt = lock['targets'][0]['url']
        runner = _Aws()
        with self.assertRaises(SystemExit) as caught:
            self._run(lock, runner, _Downloads(lock, corrupt=[corrupt]))
        self.assertIn('pinned sha256', str(caught.exception))
        uploaded = [call[4].split('s3://feed-bucket/')[1] for call in runner.uploaded()]
        self.assertNotIn(publish.RUNTIMES_DOCUMENT, uploaded)
        self.assertNotIn(lock['targets'][0]['mirror'], uploaded)
        self.assertFalse([key for key in uploaded if key.startswith('bootstrap/')])

    def test_dry_run_touches_nothing(self):
        lock = _lock()

        def _boom(*args, **kwargs):
            raise AssertionError('dry run ran ' + repr(args))

        out = io.StringIO()
        with mock.patch.object(publish, 'load_lock', lambda: lock), \
                mock.patch.object(publish, 'run', _boom), \
                mock.patch.object(publish, 'download', _boom), \
                redirect_stdout(out):
            code = publish.main(['--bucket', 'feed-bucket', '--dry-run'])
        self.assertEqual(code, 0)
        self.assertIn('dry run', out.getvalue())

    def test_a_missing_bucket_is_refused(self):
        # No default exists, so a fork cannot publish to someone else's
        # bucket by running the tool with no arguments (Plan 160).
        err = io.StringIO()
        with redirect_stderr(err):
            with self.assertRaises(SystemExit) as caught:
                publish.main([])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn('--bucket', err.getvalue())

    def test_missing_bootstrap_is_refused(self):
        lock = _lock()
        runner = _Aws()
        with mock.patch.object(publish, 'ROOT', Path('/nonexistent-router-root')):
            with self.assertRaises(SystemExit) as caught:
                self._run(lock, runner, _Downloads(lock))
        self.assertIn('missing', str(caught.exception))
        self.assertFalse(runner.uploaded())


if __name__ == '__main__':
    unittest.main()
