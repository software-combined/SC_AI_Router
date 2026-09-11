"""V2 compaction_trigger turns: one ocx1 item back, trigger never upstream.

Proven against lidge-jun/opencodex f7f890f (MIT): a trigger turn is a normal
/responses call ending in {"type":"compaction_trigger"} and the client fatals
unless exactly one {"type":"compaction","encrypted_content":...} item returns.
Routed models cannot mint OpenAI blobs, so the router briefs locally and the
summary rides the envelope replay already decodes. No network in these tests:
the summarizer and the upstream are both stubbed.
"""
import http.client
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock
from ai_router.compaction import decode_summary, encode_summary
from ai_router.discovered import _MEMORY
from ai_router import provider_defs
from ai_router.providers import (
    ExternalResponsesProvider, PreparationError, SubscriptionProvider,
    compaction_call)
from tests.fakes import FakeUpstream, install_fake
from tests.test_mixed_router import _start_server, _test_state


def _auth_file(test):
    auth = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
    json.dump({'openrouter': {'type': 'api', 'key': 'test-key'}}, auth)
    auth.close()
    test.addCleanup(os.unlink, auth.name)
    return auth.name


def _isolated_home(test):
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    _MEMORY.clear()
    test.addCleanup(_MEMORY.clear)
    patcher = mock.patch.dict(os.environ, {'ROUTER_HOME': tmp})
    patcher.start()
    test.addCleanup(patcher.stop)


class CompactTriggerProviderTests(unittest.TestCase):
    def _provider(self, summary='handoff done'):
        _isolated_home(self)
        provider = ExternalResponsesProvider(provider_defs.OPENROUTER)
        seen = {}

        def fake_summarize(model, key, items):
            seen['items'] = items
            return summary

        provider.summarize = fake_summarize
        return provider, seen

    def test_trigger_returns_exactly_one_decodable_item(self):
        provider, seen = self._provider()
        out = provider.compact_trigger('z-ai/glm-5.3-flash', {
            'input': [{'type': 'message', 'role': 'user', 'content': 'do it'},
                      {'type': 'compaction_trigger'}]}, 'key')
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['type'], 'compaction')
        self.assertTrue(out[0]['id'].startswith('cmp_'))
        self.assertEqual(decode_summary(out[0]['encrypted_content']), 'handoff done')
        self.assertNotIn({'type': 'compaction_trigger'}, seen['items'])

    def test_trigger_without_user_messages_is_409_shape(self):
        provider, _ = self._provider()
        with self.assertRaises(PreparationError):
            provider.compact_trigger('z-ai/glm-5.3-flash',
                                     {'input': [{'type': 'compaction_trigger'}]}, 'key')

    def test_trigger_remembers_discovered_schemas(self):
        provider, _ = self._provider()
        tool = {'type': 'function', 'name': 'echo', 'parameters': {'type': 'object'}}
        provider.compact_trigger('z-ai/glm-5.3-flash', {
            'input': [{'type': 'tool_search_output', 'call_id': 's', 'tools': [tool]},
                      {'type': 'message', 'role': 'user', 'content': 'do it'},
                      {'type': 'compaction_trigger'}]}, 'key')
        from ai_router.discovered import recall
        defs = recall([{'type': 'compaction',
                        'encrypted_content': encode_summary('handoff done')}])
        self.assertEqual([t['name'] for t in defs], ['echo'])


class CompactionCallSelectionTests(unittest.TestCase):
    def test_only_openrouter_compact_turns_serve_locally(self):
        provider = ExternalResponsesProvider(provider_defs.OPENROUTER)
        trigger = [{'type': 'message', 'role': 'user', 'content': 'hi'},
                   {'type': 'compaction_trigger'}]
        plain = [{'type': 'message', 'role': 'user', 'content': 'hi'}]
        self.assertIsNotNone(compaction_call(provider, 'm', '/responses/compact',
                                             {'input': plain}))
        self.assertIsNotNone(compaction_call(provider, 'm', '/responses',
                                             {'input': trigger}))
        self.assertIsNone(compaction_call(provider, 'm', '/responses',
                                          {'input': plain}))
        self.assertIsNone(compaction_call(SubscriptionProvider(), 'm',
                                          '/responses/compact', {'input': plain}))
        self.assertIsNone(compaction_call(SubscriptionProvider(), 'm', '/responses',
                                          {'input': trigger}))


class CompactTriggerHandlerTests(unittest.TestCase):
    def _server(self, **overrides):
        state = _test_state(_auth_file(self))
        state.update(overrides)
        server = _start_server(state)
        self.addCleanup(server.shutdown)
        return server

    def _post(self, port, path, payload, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        conn.request('POST', path, body=json.dumps(payload),
                     headers={'Content-Type': 'application/json', **(headers or {})})
        return conn.getresponse()

    def test_trigger_turn_never_reaches_upstream(self):
        _isolated_home(self)
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{"output": []}', []))
        server = self._server()
        with mock.patch.object(ExternalResponsesProvider, 'summarize',
                               return_value='handoff done'):
            response = self._post(server.server_port, '/test-token/responses', {
                'model': 'z-ai/glm-5.3-flash',
                'input': [{'type': 'message', 'role': 'user', 'content': 'do it'},
                          {'type': 'compaction_trigger'}]})
        self.assertEqual(response.status, 200)
        body = json.loads(response.read())
        self.assertEqual(len(body['output']), 1)
        item = body['output'][0]
        self.assertEqual(item['type'], 'compaction')
        self.assertEqual(decode_summary(item['encrypted_content']), 'handoff done')
        self.assertEqual(recorded, [])

    def test_subscription_trigger_forwards_untouched(self):
        recorded = install_fake(
            self, lambda: FakeUpstream(200, b'{"output": []}', []))
        server = self._server(openai_models=['gpt-6-astra'])
        response = self._post(server.server_port, '/test-token/responses', {
            'model': 'gpt-6-astra',
            'input': [{'type': 'message', 'role': 'user', 'content': 'do it'},
                      {'type': 'compaction_trigger'}]},
            {'Authorization': 'Bearer subscription-secret'})
        self.assertEqual(response.status, 200)
        self.assertEqual(len(recorded), 1)
        sent = json.loads(recorded[0][3])
        self.assertIn({'type': 'compaction_trigger'}, sent['input'])


if __name__ == '__main__':
    unittest.main()
