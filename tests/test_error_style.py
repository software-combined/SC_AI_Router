"""Every in-app message is plain, and the detail rides the rejection log (Plan 178).

`ai_router/errors.py` is the one catalogue of client-facing wording and
`upstream.describe_failure` the one dynamic producer. This test pins the
style rule for both, and proves the half that moved out of the message:
provider status, code, tool and credential detail reach the rejection line.
"""
import json
import re
import unittest
from types import SimpleNamespace
from unittest import mock

from ai_router import errors, ingress, subscription_fallback, upstream
from tests.fakes import FakeUpstream, install_fake
from tests.harness import (
    auth_file as _auth_file,
    post as _post,
    start_server as _start_server,
    test_state as _test_state,
)

# Internals a person reading a failed turn should never meet.
JARGON = (r'http', r'catalog', r'payload', r'upstream', r'summaris', r'summariz',
          r'\bnonce\b', r'\bloopback\b', r'\bendpoint\b', r'\bdaemon\b',
          r'\bprocess\b', r'\btoken\b', r'\bport\b', r'\bjson\b', r'traceback',
          r'[A-Za-z]:\\', r'/[Uu]sers/', r'\.codex')


def _catalogue_text():
    """Every message the catalogue itself owns, with its branches."""
    cases = (errors.forbidden(), errors.websocket_rejected(),
             errors.unsupported_route(), errors.missing_model(),
             errors.invalid_size('Decoded request is too large'),
             errors.invalid_size('anything else'),
             errors.bearer_for_no_subscription_only(),
             errors.unknown_model(None), errors.unknown_model('z-ai/glm-5.3', ('z-ai/glm-5.3',)),
             errors.subscription_required(), errors.claude_subscription_required(),
             errors.credential_problem(), errors.credential_permission('denied'),
             errors.too_many_inflight(), errors.unsupported_media_type(),
             errors.invalid_payload(), errors.internal_error(),
             errors.context_window(), errors.upstream_invalid_prompt(),
             errors.guardian_needs_subscription(), errors.native_unavailable(),
             errors.draining(), errors.upstream_rate_limited(),
             errors.compaction_unavailable(), errors.upstream_failed())
    return [case.message for case in cases]


def _dynamic_text():
    """The dynamic producers: provider failures and a refused subscription."""
    inner = ('{"code": "invalid-argument", "error": "Failed to start sampling: '
             '[invalid_client_tool_schema] probe__echo: root must be an object type"}')
    rejected = json.dumps({'error': {'message': 'Provider returned error',
                                     'metadata': {'raw': inner, 'provider_name': 'xAI'}}}).encode()
    info = {'model': 'x-ai/grok-4.7', 'provider': 'openrouter', 'protocol': 'responses',
            'elapsed_ms': 1831.8, 'timeout_s': 120, 'has_image': False}
    texts = [upstream.describe_failure(None, {'status': 502, 'body': b'{}'}, info)[1],
             upstream.describe_failure(None, {'status': 400, 'body': rejected}, info)[1],
             upstream.describe_failure(None, {'status': 400, 'body': rejected},
                                       dict(info, routed=True))[1],
             upstream.describe_failure(TimeoutError('slow'), None, info)[1],
             upstream.describe_failure(TimeoutError('slow'), None,
                                       dict(info, has_image=True))[1],
             upstream.describe_failure(OSError('no route to host'), None, info)[1],
             subscription_fallback.refusal_message(SimpleNamespace(provider='openrouter'), {}),
             subscription_fallback.refusal_message(SimpleNamespace(provider='openai'),
                                                   {'model': 'gpt-6-astra'})]
    return texts


class MessageStyleTests(unittest.TestCase):
    def test_every_fixed_message_is_plain(self):
        for text in _catalogue_text():
            with self.subTest(text=text):
                self.assertTrue(text and text.strip())
                for pattern in JARGON:
                    self.assertIsNone(re.search(pattern, text, re.I), pattern)

    def test_every_dynamic_message_is_plain(self):
        for text in _dynamic_text():
            with self.subTest(text=text):
                for pattern in JARGON:
                    self.assertIsNone(re.search(pattern, text, re.I), pattern)

    def test_the_wire_contract_is_unchanged(self):
        for factory, expected in ((errors.forbidden, (403, 'FORBIDDEN')),
                                  (lambda: errors.unknown_model('z-ai/glm-5.3'),
                                   (400, 'UNKNOWN_MODEL')),
                                  (errors.internal_error, (500, 'INTERNAL_ERROR')),
                                  (errors.draining, (503, 'SERVER_DRAINING')),
                                  (errors.upstream_failed, (502, 'UPSTREAM_FAILED')),
                                  (errors.credential_permission, (401, 'CREDENTIAL_PERMISSION')),
                                  (errors.too_many_inflight, (429, 'TOO_MANY_REQUESTS'))):
            case = factory()
            with self.subTest(code=case.code):
                self.assertEqual((case.status, case.code), expected)


class DetailStaysInTheLogTests(unittest.TestCase):
    def _handler(self, sent):
        return SimpleNamespace(server=SimpleNamespace(state={'token': 'token'}),
                               path='/token/responses',
                               send_json=lambda status, obj, headers=None: sent.append(obj))

    def test_credential_detail_is_log_only_and_path_redacted(self):
        err = errors.credential_problem(
            detail='No OpenRouter key: create /Users/x/.codex/openrouter.key')
        body = json.dumps(err.body())
        self.assertNotIn('No OpenRouter key', body)
        self.assertNotIn('.codex', body)
        self.assertIn('[path]', err.detail)
        self.assertNotIn('/Users/x', err.detail)

    def test_a_retryable_rejection_logs_the_line_and_the_delay(self):
        events = []
        ingress.error(self._handler([]), errors.draining(),
                      log_event=lambda event, **fields: events.append((event, fields)),
                      retry_after='2')
        self.assertEqual(events[0][0], 'request_rejected')
        self.assertEqual(events[0][1]['code'], 'SERVER_DRAINING')
        self.assertEqual(events[0][1]['retry_after'], '2')

    def test_the_logged_detail_is_bounded(self):
        events, sent = [], []
        ingress.error(self._handler(sent), errors.credential_problem(detail='x' * 5000),
                      log_event=lambda event, **fields: events.append((event, fields)))
        self.assertEqual(len(events[0][1]['detail']), ingress.MAX_LOG_DETAIL)
        self.assertNotIn('xxxxx', json.dumps(sent[0]))


class RefusalLogTests(unittest.TestCase):
    """A refusal a person sees must leave exactly one log line behind."""

    def _server(self):
        server = _start_server(_test_state(_auth_file(self)))
        self.addCleanup(server.shutdown)
        return server

    def test_provider_code_and_tool_reach_the_log_not_the_message(self):
        inner = ('{"code": "invalid-argument", "error": "Failed to start sampling: '
                 '[invalid_client_tool_schema] probe__echo: root must be an object type"}')
        body = json.dumps({'error': {'message': 'Provider returned error',
                                     'code': 'invalid_request',
                                     'metadata': {'raw': inner, 'provider_name': 'xAI'}}})
        install_fake(self, lambda: FakeUpstream(400, body.encode(),
                                                [('Content-Type', 'application/json')]))
        server = self._server()
        with mock.patch('ai_router.router.log_event') as log:
            response = _post(server.server_port, '/test-token/responses',
                             {'model': 'x-ai/grok-4.7', 'input': []})
            message = json.loads(response.read())['error']['message']
        self.assertEqual(response.status, 400)
        self.assertIn('x-ai/grok-4.7', message)
        for leaked in ('xAI', 'probe__echo', 'invalid_request'):
            self.assertNotIn(leaked, message)
        rejected = next(c.kwargs for c in log.call_args_list
                        if c.args == ('upstream_rejected',))
        self.assertEqual(rejected['tool'], 'probe__echo')
        self.assertEqual(rejected['code'], 'invalid_request')
        self.assertEqual(rejected['status'], 400)

    def test_a_refused_turn_logs_the_rejection_and_its_delay(self):
        install_fake(self, lambda: FakeUpstream(429, b'{"error": "slow"}',
                                                [('Content-Type', 'application/json')]))
        server = self._server()
        with mock.patch('ai_router.router.log_event') as log:
            response = _post(server.server_port, '/test-token/responses',
                             {'model': 'z-ai/glm-5.3', 'input': []})
            response.read()
        self.assertEqual(response.status, 503)
        self.assertEqual(response.getheader('Retry-After'), '2')
        rejected = next(c.kwargs for c in log.call_args_list
                        if c.args == ('request_rejected',))
        self.assertEqual(rejected['code'], 'UPSTREAM_RATE_LIMITED')
        self.assertEqual(rejected['retry_after'], '2')


if __name__ == '__main__':
    unittest.main()
