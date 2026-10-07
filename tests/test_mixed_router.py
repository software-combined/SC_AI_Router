import http.client
import io
import json
import os
import pathlib
import tempfile
import threading
import time
import unittest
from unittest import mock
from ai_router import compaction_summary, providers
from ai_router.credentials import Credentials
from tests.harness import (
    StubCredentials as _StubCredentials,
    start_auth_server as _start_auth_server,
    start_server as _start_server,
    test_state as _test_state,
)


def _external_responses():
    """OpenRouter Codes adapter; Plan 141 makes adapters per-provider."""
    from ai_router import provider_defs as _defs
    return providers.ExternalResponsesProvider(_defs.OPENROUTER)


class SummaryAvailabilityTest(unittest.TestCase):
    def setUp(self): self.enterContext(mock.patch.object(compaction_summary.availability, 'current', return_value={'key': compaction_summary.availability.key_fingerprint('key'), 'region': 'global', 'models': frozenset((*compaction_summary.SUMMARY_MODEL_SLUGS, 'z-ai/glm-5.3'))})); self.enterContext(mock.patch.object(providers.ExternalResponsesProvider, '_require_summary_rows', return_value={}))


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
        call = {'type': 'function_call', 'name': 'e', 'call_id': 't',
                'arguments': '{"v": 1}'}
        items = [{'type': 'reasoning', 'encrypted_content': 'blob', 'summary': summary},
                 {'type': 'reasoning', 'encrypted_content': 'blob'},
                 call,
                 {'type': 'function_call_output', 'call_id': 't', 'output': 'r'}]
        prepared = _prepared('z-ai/glm-5.3', '/responses', {'input': items})
        data = json.loads(prepared.body)['input']
        self.assertEqual(data[0], {'type': 'reasoning', 'summary': summary})
        self.assertEqual(data[1], call)
        self.assertEqual(data[2]['output'], 'r')
        self.assertEqual(len(data), 3)

    def test_reasoning_null_blob_keeps_content_text_drops_unreadable(self):
        readable = {'type': 'reasoning', 'id': 'rs_a', 'summary': [],
                    'content': [{'type': 'reasoning_text', 'text': 'read first'}],
                    'encrypted_content': None}
        empty = {'type': 'reasoning', 'id': 'rs_b', 'summary': [],
                 'content': [], 'encrypted_content': None}
        following = {'type': 'message', 'role': 'user', 'content': 'Continue.'}
        data = json.loads(_prepared('z-ai/glm-5.3', '/responses', {'input': [readable, empty, following]}).body)['input']
        self.assertEqual(data, [{'type': 'reasoning', 'id': 'rs_a', 'summary': [],
                                 'content': [{'type': 'reasoning_text',
                                              'text': 'read first'}]}, following])

    def test_reasoning_blob_stripped_but_readable_text_survives(self):
        summary = [{'type': 'text', 'text': 'chose X'}]
        content = [{'type': 'reasoning_text', 'text': 'tried Y'}]
        call = {'type': 'function_call', 'name': 'e', 'call_id': 't',
                'arguments': '{"v": 1}'}
        result = {'type': 'function_call_output', 'call_id': 't', 'output': 'r'}
        items = [{'type': 'reasoning', 'id': 'rs_s', 'summary': summary,
                  'content': [], 'encrypted_content': 'YmxvYg=='},
                 {'type': 'reasoning', 'id': 'rs_c', 'summary': [],
                  'content': content, 'encrypted_content': 'YmxvYg=='},
                 call, result]
        prepared = _prepared('z-ai/glm-5.3', '/responses', {'input': items})
        data = json.loads(prepared.body)['input']
        self.assertEqual(data, [
            {'type': 'reasoning', 'id': 'rs_s', 'summary': summary, 'content': []},
            {'type': 'reasoning', 'id': 'rs_c', 'summary': [], 'content': content},
            call, result])
        blob = json.dumps(data)
        self.assertNotIn('YmxvYg==', blob)
        self.assertNotIn('encrypted_content', blob)

    def test_fragment_history_with_declared_tools_prepares_cleanly(self):
        # A fragment custom_tool_call used to KeyError inside prepare_tools.
        payload = {'model': 'meta/muse-spark-1.3-contributor',
                   'tools': [{'type': 'custom', 'name': 'exec', 'description': 'x'}],
                   'input': [{'type': 'message', 'role': 'user', 'content': 'hi'},
                             {'type': 'custom_tool_call', 'name': 'exec', 'call_id': 'c1'}],
                   'reasoning': {'effort': 'xhigh'}}
        data = json.loads(_prepared('meta/muse-spark-1.3-contributor', '/responses',
                                    payload).body)['input']
        self.assertEqual([i.get('type') for i in data], ['message'])

    def test_standalone_delegation_reaches_openrouter_as_tool_pair(self):
        # Codex Desktop injects cross-task messages with no call_id; they
        # used to vanish in the scrub and never reach OpenRouter models.
        # Assistant plaintext was read but not acted on, so the router
        # now ships a matched call+output pair carrying the delegation.
        item = {'type': 'function_call_output', 'name': 'create_thread',
                'namespace': 'codex_app',
                'output': '<codex_delegation>SYNTH_HANDOFF_MARKER_719</codex_delegation>'}
        data = json.loads(_prepared(
            'deepseek/deepseek-v4.1-flash', '/responses',
            {'model': 'deepseek/deepseek-v4.1-flash', 'input': [item]}).body)['input']
        self.assertEqual(len(data), 2)
        call, result = data
        self.assertEqual(call['type'], 'function_call')
        self.assertEqual(result['type'], 'function_call_output')
        self.assertEqual(call['call_id'], result['call_id'])
        self.assertIn('SYNTH_HANDOFF_MARKER_719', result['output'])

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

    def test_astra_history_replays_on_contributor_mid_thread(self):
        # Picker switch: Astra blobs/compaction/tool history prepare cleanly
        # on Contributor; carried xhigh passes, carried max fails closed.
        items = [{'type': 'reasoning', 'encrypted_content': 'astra-blob',
                  'summary': [{'type': 'text', 'text': 'ten-call cap'}]},
                 {'type': 'compaction', 'encrypted_content': 'opaque'},
                 {'type': 'function_call', 'call_id': 'c1', 'name': 'echo_probe',
                  'arguments': '{"value": "probe"}'},
                 {'type': 'function_call_output', 'call_id': 'c1', 'output': 'ok'}]
        prepared = _prepared('meta/muse-spark-1.3-contributor', '/responses',
                             {'model': 'meta/muse-spark-1.3-contributor',
                              'input': items, 'reasoning': {'effort': 'xhigh'}})
        data = json.loads(prepared.body)['input']
        self.assertNotIn('astra-blob', json.dumps(data))
        call = next(i for i in data if i.get('type') == 'function_call')
        self.assertEqual((call['call_id'], call['name'],
                          json.loads(call['arguments'])),
                         ('c1', 'echo_probe', {'value': 'probe'}))
        result = next(i for i in data if i.get('type') == 'function_call_output')
        self.assertEqual((result['call_id'], result['output']), ('c1', 'ok'))
        blob = json.dumps(data)
        for keep in ('ten-call cap', 'cannot read'):
            self.assertIn(keep, blob)
        with self.assertRaisesRegex(ValueError, "does not support reasoning effort 'max'"):
            _prepared('meta/muse-spark-1.3-contributor', '/responses',
                      {'model': 'meta/muse-spark-1.3-contributor', 'input': [],
                       'reasoning': {'effort': 'max'}})


# Broken-credential tests need the real lookup against a home whose key-file
# leg always misses (this path never exists on any OS), so only the state's
# opencode_auth contract is exercised.
_ISOLATED_CREDENTIAL_HOME = pathlib.Path('/nonexistent-codex-router-home')


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
    def read(self, *a): return self._buf.read(*a)

def _fake_conn_class(status, payload, seen=None):
    class FakeConn:
        def __init__(self, *a, **k):
            self._request_model = None
        def connect(self):
            pass
        def request(self, method, path, body=None, headers=None):
            if seen is not None and body is not None:
                seen['body'] = json.loads(body)
            if body is not None:
                self._request_model = json.loads(body).get('model')
        def getresponse(self):
            response = dict(payload)
            response.setdefault('model', self._request_model)
            return _FakeResp(status, response)
        def close(self): pass
    return FakeConn

class CompactBranchTests(SummaryAvailabilityTest):
    def _server(self):
        self._started = _start_auth_server(self)

    def _post(self, path, payload):
        return self._post_to(self._started, path, payload)

    def _post_to(self, server, path, payload):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('POST', '/test-token' + path, body=json.dumps(payload),
                     headers={'Content-Type': 'application/json'})
        return conn.getresponse()

    def _await_quiet(self, server, timeout=10):
        deadline = time.monotonic() + timeout
        while server.inflight and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(server.inflight, 0)
    def test_compact_returns_v1_output(self):
        with mock.patch.object(providers.ExternalResponsesProvider, 'summarize', lambda *a: 'progress and next steps'):
            self._server()
            response = self._post('/responses/compact',
                {'model': 'z-ai/glm-5.3', 'input': [
                    {'type': 'message', 'role': 'user', 'content': 'do the task'}]})
            self.assertEqual(response.status, 200)
            body = json.loads(response.read())
            self.assertEqual(len(body['output']), 2)
            self.assertIn('progress and next steps', body['output'][-1]['content'][0]['text'])
            self._await_quiet(self._started)

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
                # The point of the test: real broken credentials, not the stub.
                server = _start_server(state, credentials=Credentials(
                    state, _ISOLATED_CREDENTIAL_HOME, env={}))
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
        with mock.patch.object(providers.ExternalResponsesProvider, 'summarize', boom):
            self._server()
            response = self._post('/responses/compact',
                {'model': 'z-ai/glm-5.3', 'input': [
                    {'type': 'message', 'role': 'user', 'content': 'do the task'}]})
            self.assertEqual(response.status, 502)
            self._await_quiet(self._started)  # no slot may leak on failure

    def test_compact_non_list_input_is_rejected(self):
        self._server()
        response = self._post('/responses/compact',
            {'model': 'z-ai/glm-5.3', 'input': 'do the task'})
        self.assertEqual(response.status, 409)

    def test_summarizer_receives_flattened_transcript(self):
        seen = {}
        with mock.patch.object(compaction_summary.http.client, 'HTTPSConnection', _fake_conn_class(200, {'output': [
                                      {'type': 'message', 'content': [
                                          {'type': 'output_text', 'text': 'summary'}]}]}, seen)):
            summary = _external_responses().summarize('z-ai/glm-5.3', 'key', [
                {'type': 'message', 'role': 'user', 'content': 'user bit'},
                {'type': 'function_call_output', 'call_id': 'c', 'output': 'tool bit'}])
        self.assertEqual(summary, 'summary')
        prompt = seen['body']['input'][0]['content'][0]['text']
        self.assertIn('user bit', prompt)
        self.assertIn('tool bit', prompt)

    def test_compact_empty_summary_is_rejected(self):
        with mock.patch.object(providers.ExternalResponsesProvider, 'summarize', lambda *a: '   '):
            self._server()
            response = self._post('/responses/compact',
                {'model': 'z-ai/glm-5.3', 'input': [
                    {'type': 'message', 'role': 'user', 'content': 'do the task'}]})
            self.assertEqual(response.status, 409)

    def test_compact_ignores_rejected_effort(self):
        req = {'model': 'z-ai/glm-5.3', 'reasoning': {'effort': 'medium'}, 'input': [
            {'type': 'message', 'role': 'user', 'content': 'x'}]}
        with mock.patch.object(providers.ExternalResponsesProvider, 'summarize', lambda *a: 'progress'):
            self._server()
            out = json.loads(self._post('/responses/compact', req).read())
            self.assertIn('progress', out['output'][-1]['content'][0]['text'])

    def test_compact_holds_inflight_slot(self):
        entered, release, responded = threading.Event(), threading.Event(), threading.Event()
        def slow(*a):
            entered.set()
            return 'progress' if release.wait(timeout=10) else 'stalled'
        job = {'model': 'z-ai/glm-5.3', 'input': [
            {'type': 'message', 'role': 'user', 'content': 'x'}]}
        def post():
            self._post('/responses/compact', job)
            responded.set()
        with mock.patch.object(providers.ExternalResponsesProvider, 'summarize', slow):
            self._server()
            worker = threading.Thread(target=post)
            worker.start()
            self.assertTrue(entered.wait(timeout=10))
            self.assertEqual(self._started.inflight, 1)
            release.set()
            # The slot releases after the response bytes leave the socket: the
            # worker may observe the reply before the handler reaps the slot.
            worker.join(timeout=10)
            self.assertTrue(responded.wait(timeout=10))
            self._await_quiet(self._started)

class SummarizerParsingTests(SummaryAvailabilityTest):
    def _fake_conn(self, status, payload):
        self.enterContext(mock.patch.object(
            compaction_summary.http.client, 'HTTPSConnection', _fake_conn_class(status, payload)))

    def test_non_200_fails_closed(self):
        self._fake_conn(500, {'error': 'busy'})
        with self.assertRaises(OSError):
            _external_responses().summarize('z-ai/glm-5.3', 'key', [])

    def test_malformed_output_shape_fails_closed(self):
        self._fake_conn(200, {'output': 'not-a-list'})
        with self.assertRaisesRegex(ValueError, 'no output list'):
            _external_responses().summarize('z-ai/glm-5.3', 'key', [])
        self._fake_conn(200, {'output': ['not-an-object']})
        with self.assertRaisesRegex(ValueError, 'not an object'):
            _external_responses().summarize('z-ai/glm-5.3', 'key', [])

    def test_message_and_output_text_extraction(self):
        self._fake_conn(200, {'output': [
            {'type': 'message', 'content': [{'type': 'output_text', 'text': 'part one'}]},
            {'type': 'output_text', 'text': 'part two'}]})
        summary = _external_responses().summarize('z-ai/glm-5.3', 'key', [])
        self.assertIn('part one', summary)
        self.assertIn('part two', summary)

    def test_empty_extraction_fails_closed(self):
        self._fake_conn(200, {'output': []})
        with self.assertRaisesRegex(ValueError, 'empty'):
            _external_responses().summarize('z-ai/glm-5.3', 'key', [])
