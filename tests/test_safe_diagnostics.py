"""Plan 060: synthetic upstream/exception content must not reach logs.

A fake upstream error carrying a synthetic private-text marker must still
produce a useful client failure, but the marker must appear in no captured
log argument or record. No paid request, no real credentials, no user data.
"""
import json
import logging
import unittest
from types import SimpleNamespace
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
            {'model': 'z-ai/glm-5.3', 'provider': 'openrouter', 'protocol': 'responses',
             'elapsed_ms': 1.0, 'timeout_s': 120, 'has_image': False})
        self.assertIsNotNone(described)
        status, message, _ = described
        self.assertEqual(status, 400)
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
            {'model': 'z-ai/glm-5.3', 'provider': 'openrouter', 'protocol': 'responses',
             'elapsed_ms': 1.0, 'timeout_s': 120, 'has_image': False})
        self.assertIsNotNone(described)
        status, message, _ = described
        self.assertEqual(status, 400)
        self.assertNotIn(MARKER, message)
        self.assertNotIn(MARKER, _logged_text(handler))

    def test_fingerprint_carries_counts_only(self):
        body = json.dumps({
            'model': 'm',
            'input': [
                {'type': 'message', 'role': 'user',
                 'content': [{'type': 'input_text', 'text': f'secret {MARKER}'}]},
                {'type': 'function_call', 'name': 'exec', 'call_id': 'c1',
                 'arguments': json.dumps({'input': f'run {MARKER}'})}],
            'tools': [{'type': 'function', 'name': 'exec',
                       'description': f'does {MARKER}',
                       'parameters': {'type': 'object'}}]}).encode()
        fingerprint = upstream.rejection_fingerprint(body)
        self.assertEqual(fingerprint,
                         {'items': 2,
                          'item_kinds': {'message': 1, 'function_call': 1},
                          'tools': 1})
        blob = json.dumps(fingerprint)
        self.assertNotIn(MARKER, blob)
        for banned in ('text', 'arguments', 'description', 'name'):
            self.assertNotIn(f"'{banned}'", blob.replace('"', "'"))
        self.assertEqual(upstream.rejection_fingerprint(b'not json'), {})
        self.assertEqual(upstream.rejection_fingerprint(
            json.dumps({'input': 'a string, not a list'}).encode()), {})
        # The Messages wire has no `input`; its counts would be misleading.
        self.assertEqual(upstream.rejection_fingerprint(
            json.dumps({'messages': [{'role': 'user', 'content': 'hi'}],
                        'tools': [{'name': 'exec'}]}).encode()), {})

    def test_cached_rejection_log_carries_counts_only(self):
        from ai_router import relay
        from ai_router.transport import Prepared
        handler = _captured(self)
        LOG.setLevel(logging.DEBUG)
        self.addCleanup(LOG.setLevel, logging.WARNING)
        body = json.dumps({
            'model': 'm',
            'input': [{'type': 'message', 'role': 'user',
                       'content': [{'type': 'input_text',
                                    'text': f'secret {MARKER}'}]}],
            'tools': []}).encode()
        upstream.remember_refusal('openrouter', 'z-ai/glm-5.3', body,
                                  'cached 400 message', now=100.0)
        self.addCleanup(upstream.clear_refusals)
        prepared = Prepared('openrouter.ai', '/responses', {}, body, {}, 'openrouter')
        metrics = {'provider': 'openrouter', 'protocol': 'responses',
                   'model': 'z-ai/glm-5.3', 'path': '/responses'}
        inst = SimpleNamespace(
            server=SimpleNamespace(credentials=SimpleNamespace(
                key_rejected=lambda provider: False)),
            error=lambda err: None)
        from ai_router import provider_defs
        emit = lambda event, **fields: LOG.info(json.dumps({'event': event, **fields}))
        with mock.patch('ai_router.relay.time.monotonic', return_value=110.0):
            relay.relay(inst, SimpleNamespace(defn=provider_defs.OPENROUTER),
                        prepared, metrics, 0.0, log_event=emit)
        text = _logged_text(handler)
        self.assertIn('upstream_rejected_cached', text)
        self.assertNotIn(MARKER, text)
        for line in text.splitlines():
            if 'upstream_rejected_cached' in line:
                for banned in ('text', 'arguments', 'description'):
                    self.assertNotIn(f"'{banned}'", line.replace('"', "'"))

    def test_rejection_log_carries_code_not_message_content(self):
        # Drive the real Handler.error path with a marker-bearing failure:
        # the client still gets its 400 body, but the marker must not reach
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
