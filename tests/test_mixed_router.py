import http.client
import io
import json
import os
import tempfile
import threading
import unittest
from unittest import mock
from codex_router import providers
from codex_router.registry import by_slug
from codex_router.router import Router

class _StubCredentials:
    def __init__(self, key='router-secret'):
        self.key = key

    def openrouter_key(self):
        return self.key


def _prepared(model, path, payload, headers=None, openai_models=None):
    provider = providers.select(model, path, openai_models or [])
    return provider.prepare(model, path, dict(payload), b'raw', dict(headers or {}),
                            _StubCredentials())


class RoutingTests(unittest.TestCase):
    def test_approval_review_retains_openai_subscription_route(self):
        prepared = _prepared('codex-auto-review', '/guardian', {'model': 'x'},
            {'Authorization': 'Bearer subscription-secret'}, ['codex-auto-review'])
        self.assertEqual((prepared.host, prepared.path),
                         ('chatgpt.com', '/backend-api/codex/guardian'))

    def test_native_services_keep_the_subscription_route_without_model(self):
        for endpoint in ['/alpha/search', '/alpha/notes/v2/thread_hint']:
            prepared = _prepared(None, endpoint, {},
                {'Authorization': 'Bearer subscription-secret'}, [])
            self.assertEqual((prepared.host, prepared.path),
                             ('chatgpt.com', '/backend-api/codex' + endpoint))
            self.assertEqual(prepared.headers, {'Authorization': 'Bearer subscription-secret'})

    def test_native_compact_keeps_subscription_route(self):
        prepared = _prepared('gpt-6-astra', '/responses/compact', {'model': 'x'},
                             {'Authorization': 'Bearer subscription-secret'}, ['gpt-6-astra'])
        self.assertEqual((prepared.host, prepared.path),
                         ('chatgpt.com', '/backend-api/codex/responses/compact'))

    def test_unknown_model_fails_closed(self):
        with self.assertRaises(ValueError):
            providers.select('unknown/model', '/responses', ['gpt-6-astra'])

    def test_opaque_history_stays_visible_never_silent(self):
        for path in ('/responses', '/responses/compact'):
            with self.subTest(path=path):
                prepared = _prepared('z-ai/glm-5.3', path,
                    {'input': [{'type': 'compaction', 'encrypted_content': 'opaque'}]})
                self.assertIn('cannot read', json.dumps(json.loads(prepared.body)['input']))

    def test_reasoning_blobs_stripped_but_summaries_and_results_kept(self):
        summary = [{'type': 'text', 'text': 'chose X'}]
        items = [{'type': 'reasoning', 'encrypted_content': 'blob', 'summary': summary},
                 {'type': 'reasoning', 'encrypted_content': 'blob'},
                 {'type': 'function_call_output', 'call_id': 't', 'output': 'r'}]
        prepared = _prepared('z-ai/glm-5.3', '/responses', {'input': items})
        data = json.loads(prepared.body)['input']
        self.assertEqual(data[0], {'type': 'reasoning', 'summary': summary})
        self.assertEqual(data[1], items[2])
        self.assertEqual(len(data), 2)

    def test_contributor_rejects_max_effort_with_actionable_message(self):
        with self.assertRaisesRegex(ValueError, "does not support reasoning effort 'max'"):
            _prepared('meta/muse-spark-1.3-contributor', '/responses',
                      {'model': 'meta/muse-spark-1.3-contributor', 'input': [],
                       'reasoning': {'effort': 'max'}})

    def test_contributor_accepts_low_and_high_effort(self):
        for effort in ('low', 'high', 'xhigh'):
            prepared = _prepared('meta/muse-spark-1.3-contributor', '/responses',
                                 {'model': 'meta/muse-spark-1.3-contributor', 'input': [],
                                  'reasoning': {'effort': effort}})
            self.assertEqual(json.loads(prepared.body)['reasoning'], {'effort': effort})

    def test_kimi_and_muse_still_accept_max_effort(self):
        for model in ('moonshotai/kimi-k3', 'meta/muse-spark-1.3'):
            prepared = _prepared(model, '/responses',
                                 {'model': model, 'input': [],
                                  'reasoning': {'effort': 'max'}})
            self.assertEqual(json.loads(prepared.body)['reasoning'], {'effort': 'max'})

    def test_missing_or_malformed_reasoning_passes_through(self):
        for payload in ({'input': []}, {'input': [], 'reasoning': None},
                        {'input': [], 'reasoning': 'max'}):
            prepared = _prepared('z-ai/glm-5.3', '/responses',
                                 dict(payload, model='z-ai/glm-5.3'))
            self.assertIn('input', json.loads(prepared.body))

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
        return self._post_to(self._started, path, payload)

    def _post_to(self, server, path, payload):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('POST', '/test-token' + path, body=json.dumps(payload),
                     headers={'Content-Type': 'application/json'})
        return conn.getresponse()

    def test_compact_returns_v1_output(self):
        with mock.patch.object(providers.OpenRouterProvider, 'summarize', lambda *a: 'progress and next steps'):
            self._server()
            response = self._post('/responses/compact',
                {'model': 'z-ai/glm-5.3', 'input': [
                    {'type': 'message', 'role': 'user', 'content': 'do the task'}]})
            self.assertEqual(response.status, 200)
            body = json.loads(response.read())
            self.assertEqual(len(body['output']), 2)
            self.assertIn('progress and next steps', body['output'][-1]['content'][0]['text'])

    def test_compact_with_broken_credentials_is_400(self):
        cases = {
            'non-api': {'openrouter': {'type': 'other', 'key': 'k'}},
            'corrupt': 'not-json{{{',
            'empty-object': {},
            'api-without-key': {'openrouter': {'type': 'api'}},
            'null-entry': {'openrouter': None},
            'missing': None,
        }
        for name, content in cases.items():
            with self.subTest(name=name):
                if content is None:
                    state = _test_state('/nonexistent-auth.json')
                else:
                    auth = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
                    auth.write(content if isinstance(content, str) else json.dumps(content))
                    auth.close()
                    self.addCleanup(os.unlink, auth.name)
                    state = _test_state(auth.name)
                server = _start_server(state)
                self.addCleanup(server.shutdown)
                response = self._post_to(server, '/responses/compact',
                    {'model': 'z-ai/glm-5.3', 'input': [
                        {'type': 'message', 'role': 'user', 'content': 'do the task'}]})
                self.assertEqual(response.status, 400)

    def test_compact_without_user_messages_is_rejected(self):
        self._server()
        response = self._post('/responses/compact',
            {'model': 'z-ai/glm-5.3', 'input': [{'type': 'message', 'role': 'assistant', 'content': 'hi'}]})
        self.assertEqual(response.status, 409)

    def test_compact_transport_failure_is_502(self):
        def boom(*a):
            raise OSError('reset')
        with mock.patch.object(providers.OpenRouterProvider, 'summarize', boom):
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
        with mock.patch.object(providers.http.client, 'HTTPSConnection', _fake_conn_class(200, {'output': [
                {'type': 'message', 'content': [
                    {'type': 'output_text', 'text': 'summary'}]}]}, seen)):
            summary = providers.OpenRouterProvider().summarize('z-ai/glm-5.3', 'key', [
                {'type': 'message', 'role': 'user', 'content': 'user bit'},
                {'type': 'function_call_output', 'call_id': 'c', 'output': 'tool bit'}])
        self.assertEqual(summary, 'summary')
        prompt = seen['body']['input'][0]['content'][0]['text']
        self.assertIn('user bit', prompt)
        self.assertIn('tool bit', prompt)

    def test_compact_empty_summary_is_rejected(self):
        with mock.patch.object(providers.OpenRouterProvider, 'summarize', lambda *a: '   '):
            self._server()
            response = self._post('/responses/compact',
                {'model': 'z-ai/glm-5.3', 'input': [
                    {'type': 'message', 'role': 'user', 'content': 'do the task'}]})
            self.assertEqual(response.status, 409)

    def test_compact_ignores_rejected_effort(self):
        req = {'model': 'z-ai/glm-5.3', 'reasoning': {'effort': 'medium'}, 'input': [
            {'type': 'message', 'role': 'user', 'content': 'x'}]}
        with mock.patch.object(providers.OpenRouterProvider, 'summarize', lambda *a: 'progress'):
            self._server()
            out = json.loads(self._post('/responses/compact', req).read())
            self.assertIn('progress', out['output'][-1]['content'][0]['text'])

    def test_compact_holds_inflight_slot(self):
        entered, release = threading.Event(), threading.Event()
        def slow(*a):
            entered.set()
            return 'progress' if release.wait(timeout=10) else 'stalled'
        job = {'model': 'z-ai/glm-5.3', 'input': [
            {'type': 'message', 'role': 'user', 'content': 'x'}]}
        with mock.patch.object(providers.OpenRouterProvider, 'summarize', slow):
            self._server()
            worker = threading.Thread(target=lambda: self._post('/responses/compact', job))
            worker.start()
            self.assertTrue(entered.wait(timeout=10))
            self.assertEqual(self._started.inflight, 1)
            release.set()
            worker.join(timeout=10)
            self.assertEqual(self._started.inflight, 0)

class SummarizerParsingTests(unittest.TestCase):
    def _fake_conn(self, status, payload):
        patcher = mock.patch.object(providers.http.client, 'HTTPSConnection',
                                    _fake_conn_class(status, payload))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_non_200_fails_closed(self):
        self._fake_conn(500, {'error': 'busy'})
        with self.assertRaises(OSError):
            providers.OpenRouterProvider().summarize('z-ai/glm-5.3', 'key', [])

    def test_malformed_output_shape_fails_closed(self):
        self._fake_conn(200, {'output': 'not-a-list'})
        with self.assertRaisesRegex(ValueError, 'no output list'):
            providers.OpenRouterProvider().summarize('z-ai/glm-5.3', 'key', [])
        self._fake_conn(200, {'output': ['not-an-object']})
        with self.assertRaisesRegex(ValueError, 'not an object'):
            providers.OpenRouterProvider().summarize('z-ai/glm-5.3', 'key', [])

    def test_message_and_output_text_extraction(self):
        self._fake_conn(200, {'output': [
            {'type': 'message', 'content': [{'type': 'output_text', 'text': 'part one'}]},
            {'type': 'output_text', 'text': 'part two'}]})
        summary = providers.OpenRouterProvider().summarize('z-ai/glm-5.3', 'key', [])
        self.assertIn('part one', summary)
        self.assertIn('part two', summary)

    def test_empty_extraction_fails_closed(self):
        self._fake_conn(200, {'output': []})
        with self.assertRaisesRegex(ValueError, 'empty'):
            providers.OpenRouterProvider().summarize('z-ai/glm-5.3', 'key', [])
