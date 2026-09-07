import http.client
import json
import logging
import logging.handlers
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from codex_router.runtime import LOG, load_state
from tests.test_mixed_router import _start_auth_server


def _capture_log(test):
    log = tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False)
    log.close()
    test.addCleanup(os.unlink, log.name)
    handler = logging.handlers.RotatingFileHandler(log.name, maxBytes=1024 * 1024, backupCount=1)
    old_level = LOG.level
    LOG.setLevel(logging.INFO)
    test.addCleanup(LOG.setLevel, old_level)
    LOG.addHandler(handler)
    test.addCleanup(LOG.removeHandler, handler)
    test.addCleanup(handler.close)
    return log.name, handler


class LoadStateTests(unittest.TestCase):
    def _write(self, obj):
        f = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
        json.dump(obj, f)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_load_state_reports_missing_keys(self):
        path = self._write({'port': 1})
        with self.assertRaises(SystemExit) as ctx:
            load_state(Path(path))
        for key in ('token', 'openai_models', 'opencode_auth'):
            self.assertIn(key, str(ctx.exception))

    def test_load_state_rejects_missing_credential_file(self):
        path = self._write({'port': 0, 'token': 't', 'openai_models': [],
                            'opencode_auth': '/nonexistent-auth.json'})
        with self.assertRaises(SystemExit) as ctx:
            load_state(Path(path))
        self.assertIn('credential file', str(ctx.exception))

    def test_load_state_accepts_valid_file(self):
        auth = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
        auth.close()
        self.addCleanup(os.unlink, auth.name)
        path = self._write({'port': 0, 'token': 't', 'openai_models': [],
                            'opencode_auth': auth.name})
        self.assertEqual(load_state(Path(path))['token'], 't')

class LoggingAndHealthTests(unittest.TestCase):
    def _server(self):
        return _start_auth_server(self)

    def test_rejections_are_logged_with_timestamp(self):
        log_name, handler = _capture_log(self)
        server = self._server()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('GET', '/wrong-token/health')
        self.assertEqual(conn.getresponse().status, 403)
        handler.flush()
        lines = [json.loads(line) for line in open(log_name) if line.strip()]
        rejected = [e for e in lines if e.get('event') == 'request_rejected']
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]['status'], 403)
        datetime.fromisoformat(rejected[0]['ts'])
        self.assertNotIn('test-token', open(log_name).read())
        self.assertNotIn('wrong-token', open(log_name).read())

    def test_authorized_rejection_logs_stripped_path_without_token(self):
        log_name, handler = _capture_log(self)
        server = self._server()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('GET', '/test-token/secret-path?x=1')
        self.assertEqual(conn.getresponse().status, 404)
        handler.flush()
        lines = [json.loads(line) for line in open(log_name) if line.strip()]
        rejected = [e for e in lines if e.get('event') == 'request_rejected']
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]['path'], '/secret-path')
        self.assertNotIn('test-token', open(log_name).read())

    def test_health_reports_version_and_inflight(self):
        server = self._server()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('GET', '/test-token/health')
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        body = json.loads(response.read())
        self.assertEqual(body['status'], 'ok')
        self.assertIsInstance(body['version'], str)
        self.assertEqual(body['inflight'], 0)

if __name__ == '__main__':
    unittest.main()
