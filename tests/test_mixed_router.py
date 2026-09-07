import http.client
import io
import logging
import logging.handlers
import json
from codex_router import router as mixed_router
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
import unittest
from unittest import mock
from codex_router.router import Router, route, prepare_openrouter
from codex_router.runtime import LOG, load_state

class RoutingTests(unittest.TestCase):
    def test_subscription_credentials_stay_on_openai(self):
        incoming = {'Authorization': 'Bearer subscription-secret', 'ChatGPT-Account-ID': 'account',
                    'Host': 'localhost', 'Connection': 'keep-alive'}
        host, path, headers = route('gpt-6-astra', '/responses', incoming, ['gpt-6-astra'], 'router-secret')
        self.assertEqual((host, path), ('chatgpt.com', '/backend-api/codex/responses'))
        self.assertEqual(headers, {'Authorization': 'Bearer subscription-secret', 'ChatGPT-Account-ID': 'account'})
        self.assertNotIn('router-secret', str(headers))

    def test_openrouter_never_receives_subscription_headers(self):
        incoming = {'Authorization': 'Bearer subscription-secret', 'Cookie': 'sensitive-cookie',
                    'ChatGPT-Account-ID': 'account', 'OpenAI-Organization': 'org'}
        host, path, headers = route('z-ai/glm-5.3', '/responses', incoming, ['gpt-6-astra'], 'router-secret')
        self.assertEqual((host, path), ('openrouter.ai', '/api/v1/responses'))
        self.assertEqual(headers, {'Authorization': 'Bearer router-secret', 'Content-Type': 'application/json'})

    def test_approval_review_retains_openai_subscription_route(self):
        host, path, headers = route('codex-auto-review', '/guardian',
            {'Authorization': 'Bearer subscription-secret'}, ['codex-auto-review'], 'router-secret')
        self.assertEqual((host, path), ('chatgpt.com', '/backend-api/codex/guardian'))

    def test_native_services_keep_the_subscription_route_without_model(self):
        for endpoint in ['/alpha/search', '/alpha/notes/v2/thread_hint']:
            host, path, headers = route(None, endpoint,
                {'Authorization': 'Bearer subscription-secret'}, [], 'router-secret')
            self.assertEqual((host, path), ('chatgpt.com', '/backend-api/codex' + endpoint))
            self.assertEqual(headers, {'Authorization': 'Bearer subscription-secret'})

    def test_native_compact_keeps_subscription_route(self):
        host, path, _ = route('gpt-6-astra', '/responses/compact', {}, ['gpt-6-astra'], 'k')
        self.assertEqual((host, path), ('chatgpt.com', '/backend-api/codex/responses/compact'))

    def test_unknown_models_and_unsupported_routes_fail_closed(self):
        with self.assertRaises(ValueError):
            route('unknown/model', '/responses', {}, ['gpt-6-astra'], 'router-secret')
        with self.assertRaises(ValueError):
            route('z-ai/glm-5.3', '/responses/compact', {}, ['gpt-6-astra'], 'router-secret')

    def test_compact_path_rewrites_visibly(self):
        data = json.loads(prepare_openrouter(
            {'input': [{'type': 'compaction', 'encrypted_content': 'opaque'}]}, '/responses/compact'))
        self.assertIn('cannot read', json.dumps(data['input']))

    def test_opaque_history_stays_visible_never_silent(self):
        data = json.loads(prepare_openrouter(
            {'input': [{'type': 'compaction', 'encrypted_content': 'opaque'}]}, '/responses'))
        self.assertIn('cannot read', json.dumps(data['input']))

    def test_normal_tool_history_retained_and_subscription_tier_removed(self):
        items = [{'type': 'reasoning', 'encrypted_content': 'provider-owned'},
                 {'type': 'function_call_output', 'call_id': 'test', 'output': 'result'}]
        data = json.loads(prepare_openrouter({'input': items, 'service_tier': 'priority'}, '/responses'))
        self.assertEqual(data['input'], items)
        self.assertNotIn('service_tier', data)
        self.assertEqual(data['max_output_tokens'], 32768)

    def test_contributor_rejects_max_effort_with_actionable_message(self):
        with self.assertRaisesRegex(ValueError, "does not support reasoning effort 'max'"):
            prepare_openrouter({'model': 'meta/muse-spark-1.3-contributor', 'input': [],
                                'reasoning': {'effort': 'max'}}, '/responses')

    def test_contributor_accepts_low_and_high_effort(self):
        for effort in ('low', 'high', 'xhigh'):
            data = json.loads(prepare_openrouter(
                {'model': 'meta/muse-spark-1.3-contributor', 'input': [],
                 'reasoning': {'effort': effort}}, '/responses'))
            self.assertEqual(data['reasoning'], {'effort': effort})

    def test_kimi_and_muse_still_accept_max_effort(self):
        for model in ('moonshotai/kimi-k3', 'meta/muse-spark-1.3'):
            data = json.loads(prepare_openrouter(
                {'model': model, 'input': [], 'reasoning': {'effort': 'max'}}, '/responses'))
            self.assertEqual(data['reasoning'], {'effort': 'max'})

    def test_missing_or_malformed_reasoning_passes_through(self):
        for payload in ({'input': []}, {'input': [], 'reasoning': None},
                        {'input': [], 'reasoning': 'max'}):
            data = json.loads(prepare_openrouter(dict(payload), '/responses'))
            self.assertIn('input', data)

def _test_state(auth_path):
    return {'port': 0, 'token': 'test-token',
            'openai_models': [], 'opencode_auth': auth_path}

def _start_server(state):
    server = Router(state)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server

def _start_auth_server(test):
    auth = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
    json.dump({'openrouter': {'type': 'api', 'key': 'test-key'}}, auth)
    auth.close()
    server = _start_server(_test_state(auth.name))
    test.addCleanup(server.shutdown)
    test.addCleanup(os.unlink, auth.name)
    return server

class LoopbackBoundaryTests(unittest.TestCase):
    def test_health_requires_bearer_token_and_rejects_origin(self):
        server = _start_server(_test_state('/nonexistent'))
        self.addCleanup(server.shutdown)
        port = server.server_port
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        conn.request('GET', '/health')
        self.assertEqual(conn.getresponse().status, 403)
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        conn.request('GET', '/test-token/health')
        self.assertEqual(conn.getresponse().status, 200)
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        conn.request('GET', '/test-token/health', headers={'Origin': 'https://x.example'})
        self.assertEqual(conn.getresponse().status, 403)

class _FakeResp:
    def __init__(self, status, payload):
        self.status = status
        self._buf = io.BytesIO(json.dumps(payload).encode())
    def read(self, *a):
        return self._buf.read(*a)

def _fake_conn_class(status, payload, seen=None):
    class FakeConn:
        def __init__(self, *a, **k):
            pass
        def request(self, method, path, body=None, headers=None):
            if seen is not None and body is not None:
                seen['body'] = json.loads(body)
        def getresponse(self):
            return _FakeResp(status, payload)
        def close(self):
            pass
    return FakeConn

class CompactBranchTests(unittest.TestCase):
    def _server(self):
        self._started = _start_auth_server(self)

    def _post(self, path, payload):
        conn = http.client.HTTPConnection('127.0.0.1', self._started.server_port, timeout=10)
        conn.request('POST', '/test-token' + path, body=json.dumps(payload),
                     headers={'Content-Type': 'application/json'})
        return conn.getresponse()

    def test_compact_returns_v1_output(self):
        with mock.patch.object(mixed_router, 'summarize_for_compact', lambda *a: 'progress and next steps'):
            self._server()
            response = self._post('/responses/compact',
                {'model': 'z-ai/glm-5.3', 'input': [
                    {'type': 'message', 'role': 'user', 'content': 'do the task'}]})
            self.assertEqual(response.status, 200)
            body = json.loads(response.read())
            self.assertEqual(len(body['output']), 2)
            self.assertIn('progress and next steps', body['output'][-1]['content'][0]['text'])

    def test_compact_without_user_messages_is_rejected(self):
        self._server()
        response = self._post('/responses/compact',
            {'model': 'z-ai/glm-5.3', 'input': [{'type': 'message', 'role': 'assistant', 'content': 'hi'}]})
        self.assertEqual(response.status, 409)

    def test_compact_transport_failure_is_502(self):
        def boom(*a):
            raise OSError('reset')
        with mock.patch.object(mixed_router, 'summarize_for_compact', boom):
            self._server()
            response = self._post('/responses/compact',
                {'model': 'z-ai/glm-5.3', 'input': [
                    {'type': 'message', 'role': 'user', 'content': 'do the task'}]})
            self.assertEqual(response.status, 502)

    def test_compact_non_list_input_is_rejected(self):
        self._server()
        response = self._post('/responses/compact',
            {'model': 'z-ai/glm-5.3', 'input': 'do the task'})
        self.assertEqual(response.status, 409)

    def test_summarizer_receives_flattened_transcript(self):
        seen = {}
        with mock.patch.object(mixed_router.http.client, 'HTTPSConnection', _fake_conn_class(200, {'output': [
                {'type': 'message', 'content': [
                    {'type': 'output_text', 'text': 'summary'}]}]}, seen)):
            summary = mixed_router.summarize_for_compact('z-ai/glm-5.3', 'key', [
                {'type': 'message', 'role': 'user', 'content': 'user bit'},
                {'type': 'function_call_output', 'call_id': 'c', 'output': 'tool bit'}])
        self.assertEqual(summary, 'summary')
        prompt = seen['body']['input'][0]['content'][0]['text']
        self.assertIn('user bit', prompt)
        self.assertIn('tool bit', prompt)

    def test_compact_empty_summary_is_rejected(self):
        with mock.patch.object(mixed_router, 'summarize_for_compact', lambda *a: '   '):
            self._server()
            response = self._post('/responses/compact',
                {'model': 'z-ai/glm-5.3', 'input': [
                    {'type': 'message', 'role': 'user', 'content': 'do the task'}]})
            self.assertEqual(response.status, 409)

class SummarizerParsingTests(unittest.TestCase):
    def _fake_conn(self, status, payload):
        patcher = mock.patch.object(mixed_router.http.client, 'HTTPSConnection',
                                    _fake_conn_class(status, payload))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_non_200_fails_closed(self):
        self._fake_conn(500, {'error': 'busy'})
        with self.assertRaises(OSError):
            mixed_router.summarize_for_compact('z-ai/glm-5.3', 'key', [])

    def test_malformed_output_shape_fails_closed(self):
        self._fake_conn(200, {'output': 'not-a-list'})
        with self.assertRaisesRegex(ValueError, 'no output list'):
            mixed_router.summarize_for_compact('z-ai/glm-5.3', 'key', [])
        self._fake_conn(200, {'output': ['not-an-object']})
        with self.assertRaisesRegex(ValueError, 'not an object'):
            mixed_router.summarize_for_compact('z-ai/glm-5.3', 'key', [])

    def test_message_and_output_text_extraction(self):
        self._fake_conn(200, {'output': [
            {'type': 'message', 'content': [{'type': 'output_text', 'text': 'part one'}]},
            {'type': 'output_text', 'text': 'part two'}]})
        summary = mixed_router.summarize_for_compact('z-ai/glm-5.3', 'key', [])
        self.assertIn('part one', summary)
        self.assertIn('part two', summary)

    def test_empty_extraction_fails_closed(self):
        self._fake_conn(200, {'output': []})
        with self.assertRaisesRegex(ValueError, 'empty'):
            mixed_router.summarize_for_compact('z-ai/glm-5.3', 'key', [])
