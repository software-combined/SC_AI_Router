"""Plan 060: synthetic upstream/exception content must not reach logs.

A fake upstream error carrying a synthetic private-text marker must still
produce a useful client failure, but the marker must appear in no captured
log argument or record. No paid request, no real credentials, no user data.
"""
import json
import logging
import unittest
from unittest import mock

from ai_router import errors, upstream
from ai_router.runtime import LOG

MARKER = 'SYNTH-CANARY-060-9f2c'


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


def _captured(test):
    handler = _ListHandler()
    LOG.addHandler(handler)
    test.addCleanup(LOG.removeHandler, handler)
    return handler


def _logged_text(handler):
    return '\n'.join(handler.records)


class SafeDiagnosticsTests(unittest.TestCase):
    def test_generic_upstream_message_stays_out_of_logs(self):
        handler = _captured(self)
        body = json.dumps({'error': {
            'message': f'Upstream blew up on {MARKER} with details',
            'metadata': {'provider_name': 'TestProv'}}}).encode()
        described = upstream.describe_failure(
            None, {'status': 400, 'body': body},
            {'model': 'z-ai/glm-5.3', 'provider': 'openrouter',
             'elapsed_ms': 1.0, 'timeout_s': 120, 'has_image': False})
        self.assertIsNotNone(described)
        status, message = described
        self.assertEqual(status, 409)
        LOG.info(json.dumps({'event': 'upstream_rejected_test', 'code': 'PROVIDER_REJECTED'}))
        self.assertNotIn(MARKER, message)
        self.assertNotIn(MARKER, _logged_text(handler))

    def test_nested_raw_upstream_prose_stays_out_of_client_and_logs(self):
        handler = _captured(self)
        raw = json.dumps({'error': f'nested failure on {MARKER}'})
        body = json.dumps({'error': {'message': 'Provider returned error',
                                     'metadata': {'raw': raw,
                                                  'provider_name': 'TestProv'}}}).encode()
        described = upstream.describe_failure(
            None, {'status': 400, 'body': body},
            {'model': 'z-ai/glm-5.3', 'provider': 'openrouter',
             'elapsed_ms': 1.0, 'timeout_s': 120, 'has_image': False})
        self.assertIsNotNone(described)
        status, message = described
        self.assertEqual(status, 409)
        self.assertNotIn(MARKER, message)
        self.assertNotIn(MARKER, _logged_text(handler))

    def test_rejection_log_carries_code_not_message_content(self):
        # Drive the real Handler.error path with a marker-bearing failure:
        # the client still gets its 409 body, but the marker must not reach
        # the structured log. Catches a reintroduction of reason=err.message.
        from types import SimpleNamespace
        from ai_router.router import Handler
        handler = _captured(self)
        err = errors.preparation(f'bad turn mentioning {MARKER}')
        inst = Handler.__new__(Handler)
        inst.path = '/test-token/responses'
        inst.server = SimpleNamespace(state={'token': 'test-token'})
        inst.send_json = lambda status, obj, headers=None: None
        with mock.patch.object(LOG, 'info',
                                side_effect=lambda *a: handler.records.append(a[0] if a else '')):
            inst.error(err)
        for line in _logged_text(handler).splitlines():
            if 'request_rejected' in line:
                self.assertNotIn(MARKER, line)
                self.assertIn('PROVIDER_REJECTED', line)
