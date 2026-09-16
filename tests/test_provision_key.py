"""Plan 107 Stages 1-2 operator provisioning against a fake Management API.

No network, no real keys, no secrets in logs. Proves: the created key
carries the verified email, limit, and monthly reset; a failed guardrail
assignment deletes the unbudgeted key; the audit row holds the key id and
never the secret.
"""
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        'router_provision_key_under_test', ROOT / 'tools' / 'provision_key.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


provision_mod = _load()


class _Resp:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *args):
        return self._body


class FakeManagementAPI:
    """Records requests; replays key create, guardrail assign, key delete."""

    def __init__(self, guardrail_ok=True):
        self.calls = []
        self.guardrail_ok = guardrail_ok
        self.deleted = []

    def __call__(self, req, timeout=None):
        url = req.full_url
        payload = json.loads(req.data or b'{}')
        self.calls.append((req.get_method(), url, payload))
        if url.endswith('/api/v1/keys/'):
            body = json.dumps({'data': {'id': 'key-123', 'key': 'sk-live-secret'}}).encode()
            return _Resp(201, body)
        if '/api/v1/guardrails/' in url:
            return _Resp(200 if self.guardrail_ok else 500, b'{}')
        if req.get_method() == 'DELETE':
            self.deleted.append(url)
            return _Resp(200, b'{}')
        raise AssertionError('unexpected ' + url)


class ProvisionTests(unittest.TestCase):
    def _env(self):
        return mock.patch.dict('os.environ', {'OPENROUTER_MANAGEMENT_KEY': 'mgmt-test'})

    def test_created_key_carries_email_limit_and_monthly_reset(self):
        api = FakeManagementAPI()
        with tempfile.TemporaryDirectory() as tmp:
            audit = Path(tmp) / 'sub' / 'audit.jsonl'
            with self._env():
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = provision_mod.main(['--email', 'cyril@softwarecombined.com',
                                             '--machine', 'mac-01', '--limit', '25',
                                             '--guardrail', 'gr-7', '--audit', str(audit)],
                                            _urlopen=api)
            self.assertEqual(rc, 0)
            self.assertEqual(buf.getvalue().strip(), 'sk-live-secret')
            rows = audit.read_text().strip().split('\n')
            audit_text = audit.read_text()
        method, url, payload = api.calls[0]
        self.assertEqual((method, url), ('POST', provision_mod.KEYS_URL))
        self.assertEqual(payload['name'], 'cyril@softwarecombined.com/mac-01')
        self.assertEqual(payload['limit'], 25)
        self.assertEqual(payload['limit_reset'], 'monthly')
        self.assertEqual(len(rows), 1)
        row = json.loads(rows[0])
        self.assertEqual(row['key_id'], 'key-123')
        self.assertEqual(row['email'], 'cyril@softwarecombined.com')
        self.assertNotIn('sk-live-secret', audit_text)
        self.assertNotIn('mgmt-test', audit_text)

    def test_failed_guardrail_assignment_deletes_the_unbudgeted_key(self):
        api = FakeManagementAPI(guardrail_ok=False)
        with tempfile.TemporaryDirectory() as tmp:
            audit = Path(tmp) / 'audit.jsonl'
            with self._env():
                with self.assertRaisesRegex(SystemExit, 'guardrail'):
                    provision_mod.main(['--email', 'cyril@softwarecombined.com',
                                        '--machine', 'mac-01', '--limit', '25',
                                        '--guardrail', 'gr-7', '--audit', str(audit)],
                                       _urlopen=api)
        self.assertTrue(any(u.endswith('/api/v1/keys/key-123') for u in api.deleted))
        self.assertFalse(audit.exists(), 'no audit row for a deleted key')

    def test_revoke_reports_by_id_without_a_secret(self):
        api = FakeManagementAPI()
        with self._env():
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = provision_mod.main(['--email', 'x@y.z', '--machine', 'm', '--limit', '1',
                                         '--audit', '/tmp/nope.jsonl', '--revoke', 'key-9'],
                                        _urlopen=api)
        self.assertEqual(rc, 0)
        self.assertIn('revoked', buf.getvalue())

    def test_failed_revoke_exits_nonzero(self):
        def failing(req, timeout=None):
            class Resp:
                status = 500
                def __enter__(self):
                    return self
                def __exit__(self, *exc):
                    return False
                def read(self, *a):
                    return b'{}'
            return Resp()
        with self._env():
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = provision_mod.main(['--email', 'x@y.z', '--machine', 'm', '--limit', '1',
                                         '--audit', '/tmp/nope.jsonl', '--revoke', 'key-9'],
                                        _urlopen=failing)
        self.assertEqual(rc, 1)
        self.assertIn('revoke failed', buf.getvalue())

    def test_secret_never_reaches_stderr_or_logs(self):
        api = FakeManagementAPI()
        with tempfile.TemporaryDirectory() as tmp:
            with self._env():
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    provision_mod.main(['--email', 'cyril@softwarecombined.com',
                                        '--machine', 'mac-01', '--limit', '25',
                                        '--audit', str(Path(tmp) / 'a.jsonl')], _urlopen=api)
            self.assertNotIn('sk-live-secret', err.getvalue())


if __name__ == '__main__':
    unittest.main()
