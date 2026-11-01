"""V2 compaction_trigger turns: one ocx1 item back, trigger never upstream.

Proven against lidge-jun/opencodex f7f890f (MIT): a trigger turn is a normal
/responses call ending in {"type":"compaction_trigger"} and the client fatals
unless exactly one {"type":"compaction","encrypted_content":...} item and
terminal response.completed event return. V1 /responses/compact and nonstream
V2 remain JSON.
Routed models cannot mint OpenAI blobs, so the router briefs locally and the
summary rides the envelope replay already decodes. No network in these tests:
the summarizer and the upstream are both stubbed.
"""
import json
import unittest
from unittest import mock
from types import SimpleNamespace
from ai_router.compaction import decode_summary, encode_summary
from ai_router import ingress
from ai_router import provider_defs
from ai_router.providers import (
    ExternalResponsesProvider, PreparationError, SubscriptionProvider,
    compaction_call)
from tests.fakes import FakeUpstream, install_fake
from tests.harness import (
    auth_file as _auth_file,
    isolated_home as _isolated_home,
    post as _post,
    start_server as _start_server,
    test_state as _test_state,
)


class CompactTriggerProviderTests(unittest.TestCase):
    def _provider(self, summary='handoff done'):
        _isolated_home(self)
        provider = ExternalResponsesProvider(provider_defs.OPENROUTER)
        seen = {}

        def fake_summarize(_model, _key, items, row=None, context=None,
                           allowed=None, availability_snapshot=None):
            seen['items'] = items
            seen['row'] = row
            seen['context'] = context
            seen['allowed'] = allowed
            seen['availability_snapshot'] = availability_snapshot
            return summary

        provider.summarize = fake_summarize
        provider._require_summary_rows = lambda *args: {}
        return provider, seen

    def test_trigger_returns_exactly_one_decodable_item(self):
        provider, seen = self._provider()
        context = SimpleNamespace(catalogue={'snapshot': 'kept'})
        row = SimpleNamespace(slug='active/model')
        out = provider.compact_trigger('z-ai/glm-5.3-flash', {
            'input': [{'type': 'message', 'role': 'user', 'content': 'do it'},
                      {'type': 'compaction_trigger'}]}, 'key', row=row,
                             context=context, allowed={'active/model'})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['type'], 'compaction')
        self.assertTrue(out[0]['id'].startswith('cmp_'))
        self.assertEqual(decode_summary(out[0]['encrypted_content']), 'handoff done')
        self.assertNotIn({'type': 'compaction_trigger'}, seen['items'])
        self.assertIs(seen['row'], row)
        self.assertIs(seen['context'], context)
        self.assertEqual(seen['allowed'], {'active/model'})

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
    def setUp(self):
        self.enterContext(mock.patch.object(
            ExternalResponsesProvider, '_require_summary_rows', return_value={}))

    def _server(self, **overrides):
        state = _test_state(_auth_file(self))
        state.update(overrides)
        server = _start_server(state)
        self.addCleanup(server.shutdown)
        return server

    def test_trigger_turn_never_reaches_upstream(self):
        _isolated_home(self)
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{"output": []}', []))
        server = self._server()
        with mock.patch.object(ExternalResponsesProvider, 'summarize',
                               return_value='handoff done'):
            response = _post(server.server_port, '/test-token/responses', {
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

    def test_opaque_agent_item_is_rejected_before_compaction(self):
        _isolated_home(self)
        server = self._server()
        response = _post(server.server_port, '/test-token/responses', {
            'model': 'z-ai/glm-5.3-flash',
            'input': [{'type': 'agent_message', 'author': '/root',
                       'content': [{'type': 'input_text', 'text': 'hidden'},
                                   {'type': 'encrypted_content',
                                    'encrypted_content': 'CIPHER'}]},
                      {'type': 'compaction_trigger'}]})
        self.assertEqual(response.status, 400)
        self.assertEqual(json.loads(response.read())['error']['code'],
                         'PROVIDER_REJECTED')

    def test_streamed_trigger_returns_completed_sse_events(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{"output": []}', []))
        server = self._server()
        with mock.patch.object(ExternalResponsesProvider, 'summarize',
                               return_value='handoff done'):
            response = _post(server.server_port, '/test-token/responses', {
                'model': 'z-ai/glm-5.3-flash',
                'stream': True,
                'input': [{'type': 'message', 'role': 'user', 'content': 'do it'},
                          {'type': 'compaction_trigger'}]})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader('Content-Type'), 'text/event-stream')
        self.assertEqual(response.getheader('Connection'), 'close')
        frames = [part for part in response.read().split(b'\n\n') if part]
        events = [json.loads(frame.split(b'data: ', 1)[1]) for frame in frames]
        self.assertEqual([event['type'] for event in events], [
            'response.output_item.done', 'response.completed'])
        item = events[0]['item']
        self.assertEqual(item['type'], 'compaction')
        self.assertEqual(decode_summary(item['encrypted_content']), 'handoff done')
        completed = events[1]['response']
        self.assertTrue(completed['id'])
        self.assertEqual(completed['output'], [item])
        self.assertEqual(recorded, [])

    def test_stream_write_failure_is_contained_after_one_reply(self):
        writes = []

        class BrokenWriter:
            def write(self, body):
                writes.append(body)
                raise OSError('client disconnected')

        handler = SimpleNamespace(
            wfile=BrokenWriter(), close_connection=False,
            send_response=mock.Mock(), send_header=mock.Mock(),
            end_headers=mock.Mock())
        item = {'type': 'compaction', 'id': 'cmp_test',
                'encrypted_content': encode_summary('handoff done')}

        ingress.send_compaction_stream(handler, [item])

        self.assertEqual(len(writes), 1)
        handler.send_response.assert_called_once_with(200)
        handler.end_headers.assert_called_once_with()
        self.assertTrue(handler.close_connection)

    def test_subscription_trigger_forwards_after_replay_normalization(self):
        recorded = install_fake(
            self, lambda: FakeUpstream(200, b'{"output": []}', []))
        server = self._server(openai_models=['gpt-6-astra'])
        response = _post(server.server_port, '/test-token/responses', {
            'model': 'gpt-6-astra',
            'input': [{'type': 'message', 'role': 'developer', 'content': [
                          {'type': 'input_text', 'text': '<model_switch> hop'}]},
                      {'type': 'agent_message', 'author': '/root/child',
                       'recipient': '/root',
                       'content': [{'type': 'input_text', 'text': 'done'}]},
                      {'type': 'compaction_trigger'}]},
            {'Authorization': 'Bearer subscription-secret'})
        self.assertEqual(response.status, 200)
        self.assertEqual(len(recorded), 1)
        sent = json.loads(recorded[0][3])
        kinds = [item.get('type') for item in sent['input']]
        self.assertIn({'type': 'compaction_trigger'}, sent['input'])
        self.assertNotIn('agent_message', kinds)
        self.assertIn('function_call', kinds)
        self.assertIn('function_call_output', kinds)


if __name__ == '__main__':
    unittest.main()
