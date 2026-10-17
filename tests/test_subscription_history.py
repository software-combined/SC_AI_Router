"""Cross-provider replay never rewrites the client's saved history."""
import copy
import http.client
import json
import unittest
from compression import zstd
from unittest import mock

from ai_router import compaction, providers, subscription_history, upstream
from tests.fakes import FakeUpstream, install_fake
from tests.harness import isolated_home, post, start_server


def reasoning(**extra):
    return {'type': 'reasoning', 'id': 'rs_foreign', 'summary': [],
            'content': [{'type': 'reasoning_text', 'text': 'PRIVATE-CANARY'}], **extra}


class SubscriptionHistoryTests(unittest.TestCase):
    def test_mixed_history_preserves_every_other_item_and_original_payload(self):
        user = {'type': 'message', 'role': 'user', 'content': 'Remember MARKER'}
        call = {'type': 'function_call', 'call_id': 'call_1', 'name': 'echo', 'arguments': '{}'}
        result = {'type': 'function_call_output', 'call_id': 'call_1', 'output': 'MARKER'}
        delegation = {'type': 'function_call_output', 'name': 'create_thread', 'output': 'assignment'}
        compact = {'type': 'compaction', 'encrypted_content': 'opaque'}
        assistant = {'type': 'message', 'role': 'assistant', 'content': 'MARKER'}
        native = {'type': 'reasoning', 'id': 'rs_native', 'summary': [],
                  'encrypted_content': 'opaque'}
        kept = [user, call, result, delegation, compact, assistant, native]
        for count in (1, 19):
            with self.subTest(count=count):
                payload = {'input': [user, *[reasoning() for _ in range(count)], *kept[1:]]}
                before = copy.deepcopy(payload)
                normalized = subscription_history.normalize(payload)
                self.assertEqual(normalized['input'], kept)
                self.assertEqual(payload, before)
                self.assertIs(subscription_history.normalize(normalized), normalized)
                for actual, original in zip(normalized['input'], kept):
                    self.assertIs(actual, original)

    def test_encrypted_reasoning_keeps_identity_summary_and_opaque_data(self):
        item = reasoning(encrypted_content='opaque', summary=[{'type': 'summary_text', 'text': 'summary'}])
        payload = {'input': [item]}
        normalized = subscription_history.normalize(payload)
        self.assertEqual(normalized['input'], [{k: v for k, v in item.items() if k != 'content'}])
        self.assertIn('content', item)

    def test_model_switch_replay_drops_foreign_reasoning_and_projects_agent_messages(self):
        marker = {'type': 'message', 'role': 'developer', 'content': [
            {'type': 'input_text', 'text': '<model_switch> hop'}]}
        foreign = reasoning(encrypted_content='FOREIGN')
        native = reasoning(id='rs_native', encrypted_content='NATIVE',
                           summary=[{'type': 'summary_text', 'text': 'current'}])
        agent = {'type': 'agent_message', 'author': '/root/child',
                 'recipient': '/root',
                 'content': [{'type': 'input_text', 'text': 'done'}]}
        trigger = {'type': 'compaction_trigger'}
        payload = {'model': 'gpt-6-astra',
                   'input': [foreign, marker, native, agent, trigger]}
        prepared = providers.SubscriptionProvider().prepare(
            'gpt-6-astra', '/responses', payload,
            json.dumps(payload).encode(), {}, None)
        sent = json.loads(prepared.body)['input']
        self.assertEqual([item['type'] for item in sent],
                         ['message', 'reasoning', 'function_call',
                          'function_call_output', 'compaction_trigger'])
        self.assertEqual(sent[1]['encrypted_content'], 'NATIVE')
        self.assertNotIn('content', sent[1])
        self.assertEqual(sent[2]['call_id'], sent[3]['call_id'])
        self.assertIn('done', sent[3]['output'])
        self.assertNotIn('FOREIGN', json.dumps(sent))

    def test_native_child_replies_and_app_deliveries_replay_untouched(self):
        # Even after a switch the subscription backend reads both native shapes
        # itself; projecting them would withhold the encrypted reply or recast
        # an assignment.
        marker = {'type': 'message', 'role': 'developer', 'content': [
            {'type': 'input_text', 'text': '<model_switch> hop'}]}
        reply = {'type': 'agent_message', 'author': '/root/child', 'recipient': '/root',
                 'content': [{'type': 'input_text', 'text': 'done'},
                             {'type': 'encrypted_content', 'encrypted_content': 'NATIVE'}]}
        delivery = {'type': 'function_call_output', 'name': 'create_thread',
                    'output': 'Review the staged diff.'}
        payload = {'model': 'gpt-6-astra', 'input': [marker, reply, delivery]}
        prepared = providers.SubscriptionProvider().prepare(
            'gpt-6-astra', '/responses', payload,
            json.dumps(payload).encode(), {}, None)
        self.assertEqual(json.loads(prepared.body)['input'], [marker, reply, delivery])

    def test_unswitched_turn_replays_exactly_as_sent(self):
        # Without a model switch the subscription route forwards the client's
        # body as it did before, including an external child's readable reply.
        reply = {'type': 'agent_message', 'author': '/root/child', 'recipient': '/root',
                 'content': [{'type': 'input_text', 'text': 'done'}]}
        payload = {'model': 'gpt-6-astra', 'input': [reply, {'type': 'compaction_trigger'}]}
        raw = json.dumps(payload).encode()
        prepared = providers.SubscriptionProvider().prepare(
            'gpt-6-astra', '/responses', payload, raw, {}, None)
        self.assertEqual(prepared.body, raw)

    def test_noop_shapes_keep_identity(self):
        for items in (None, 'prompt', [], [None], [reasoning(content=[])],
                      [reasoning(content='invalid')], [{'type': 'reasoning', 'summary': []}]):
            with self.subTest(items=items):
                payload = {'input': items}
                self.assertIs(subscription_history.normalize(payload), payload)

    def test_empty_router_summary_blob_is_not_rewritten_or_repaired(self):
        item = {'type': 'compaction', 'id': 'cmp_empty',
                'encrypted_content': compaction.encode_summary('')}
        payload = {'input': [item]}
        self.assertIs(subscription_history.normalize(payload), payload)
        self.assertIsNone(subscription_history.repair_input([item]))

    def test_unicode_format_router_summary_round_trips_and_remains_owned(self):
        summary = 'text\u200dtext'
        item = {'type': 'compaction', 'id': 'cmp_format',
                'encrypted_content': compaction.encode_summary(summary)}
        self.assertEqual(compaction.decode_summary(item['encrypted_content']), summary)
        self.assertTrue(subscription_history.removable_encrypted(item))
        normalized = subscription_history.normalize({'input': [item]})
        self.assertEqual(normalized['input'][0]['content'][0]['text'],
                         compaction.SUMMARY_PREFIX + '\n\n' + summary)

    def test_control_character_router_summary_is_rejected_by_the_producer(self):
        summary = 'before\x1bafter'
        with self.assertRaises(ValueError):
            compaction.encode_summary(summary)
        with self.assertRaises(ValueError):
            compaction.v2_compaction_item(summary)

    def test_nested_encrypted_compaction_is_not_rewritten_or_repaired(self):
        item = {'type': 'compaction', 'id': 'cmp_mixed',
                'encrypted_content': compaction.encode_summary('summary'),
                'content': [{'type': 'encrypted_content',
                             'encrypted_content': 'NATIVE'}]}
        payload = {'input': [item]}
        before = copy.deepcopy(payload)
        self.assertIs(subscription_history.normalize(payload), payload)
        self.assertIsNone(subscription_history.repair_input([item]))
        self.assertEqual(payload, before)

    def test_deeply_nested_encrypted_compaction_is_not_rewritten_or_repaired(self):
        item = {'type': 'compaction', 'id': 'cmp_deep',
                'encrypted_content': compaction.encode_summary('summary'),
                'content': [{'content': [{'type': 'encrypted_content',
                                          'encrypted_content': 'NATIVE'}]}]}
        payload = {'input': [item]}
        self.assertIs(subscription_history.normalize(payload), payload)
        self.assertIsNone(subscription_history.repair_input([item]))

    def test_unowned_encrypted_field_in_non_object_item_blocks_repair(self):
        items = [{'type': 'reasoning', 'id': 'rs_owned',
                  'encrypted_content': 'OWNED'},
                 [{'type': 'message', 'encrypted_content': 'UNOWNED'}]]
        before = copy.deepcopy(items)
        self.assertIsNone(subscription_history.repair_input(items))
        self.assertEqual(items, before)

    def test_nested_only_encrypted_reasoning_is_preserved(self):
        item = {'type': 'reasoning', 'id': 'rs_nested',
                'content': [{'type': 'encrypted_content',
                             'encrypted_content': 'NATIVE'}]}
        payload = {'input': [item]}
        before = copy.deepcopy(payload)
        self.assertIs(subscription_history.normalize(payload), payload)
        self.assertIsNone(subscription_history.repair_input([item]))
        self.assertEqual(payload, before)

    def test_empty_or_null_reasoning_blob_is_preserved_and_not_repaired(self):
        for value in (None, '', ' ', '\t'):
            with self.subTest(value=value):
                item = {'type': 'reasoning', 'id': 'rs_empty',
                        'encrypted_content': value,
                        'content': [{'type': 'reasoning_text',
                                     'text': 'READABLE'}]}
                payload = {'input': [item]}
                before = copy.deepcopy(payload)
                self.assertIs(subscription_history.normalize(payload), payload)
                self.assertIsNone(subscription_history.repair_input([item]))
                self.assertEqual(payload, before)

    def test_whitespace_blob_does_not_hide_reasoning_from_compaction(self):
        for value in (' ', '\t'):
            with self.subTest(value=value):
                text = compaction.transcript_for_summary([
                    {'type': 'reasoning',
                     'summary': [{'type': 'summary_text', 'text': 'sum-marker'}],
                     'content': [{'type': 'reasoning_text', 'text': 'content-marker'}],
                     'encrypted_content': value},
                ])
                self.assertIn('sum-marker', text)
                self.assertIn('content-marker', text)

    def test_malformed_router_summary_envelopes_are_not_rewritten_or_repaired(self):
        for blob in ('ocx1:YWJj!!', 'ocx1:AAAA', 'ocx1:!!!!', 'ocx1:AEE=', 'ocx1:TQ'):
            with self.subTest(blob=blob):
                item = {'type': 'compaction', 'id': 'cmp_bad',
                        'encrypted_content': blob}
                payload = {'input': [item]}
                self.assertIs(subscription_history.normalize(payload), payload)
                self.assertIsNone(subscription_history.repair_input([item]))

    def test_adapter_reencodes_only_changed_history_or_handoffs(self):
        provider = providers.SubscriptionProvider()
        for path in ('/responses', '/responses/compact'):
            for foreign in (False, True):
                for readable in (False, True):
                    with self.subTest(path=path, foreign=foreign, readable=readable):
                        payload = {'model': 'gpt-6-astra', 'input': [reasoning()] if foreign else []}
                        raw = zstd.compress(json.dumps(payload).encode())
                        names = {'spawn_agent'} if readable and path == '/responses' else set()
                        # Readable schemas come back on a copy; none leave the payload as sent.
                        hinted = lambda payload, readable, catalogue=None, names=names: (dict(payload) if names else payload, names)
                        with mock.patch('ai_router.agent_handoffs.native_handoffs', hinted):
                            prepared = provider.prepare('gpt-6-astra', path, payload, raw,
                                {'Content-Encoding': 'zstd', 'Accept-Encoding': 'zstd',
                                 'Authorization': 'Bearer synthetic', 'Content-Length': str(len(raw))}, None)
                        if foreign or names:
                            self.assertEqual(json.loads(prepared.body)['input'], [])
                            self.assertNotIn('Content-Encoding', prepared.headers)
                            self.assertEqual(prepared.headers['Accept-Encoding'], 'identity')
                        else:
                            self.assertIs(prepared.body, raw)
                            self.assertEqual(prepared.headers['Content-Encoding'], 'zstd')
                        self.assertNotIn('Content-Length', prepared.headers)
                        self.assertEqual(prepared.headers['Authorization'], 'Bearer synthetic')

    def test_native_service_payload_is_not_normalized(self):
        payload = {'input': [reasoning()]}
        raw = json.dumps(payload).encode()
        prepared = providers.SubscriptionProvider().prepare('gpt-6-astra', '/guardian', payload, raw, {}, None)
        self.assertIs(prepared.body, raw)


class ReplayHandlerTests(unittest.TestCase):
    def setUp(self):
        isolated_home(self)
        self.server = start_server({'port': 0, 'token': 'test-token', 'openai_models': ['gpt-6-astra']})
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_compressed_replay_and_compaction_reach_upstream_without_foreign_items(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{"output": []}', []))
        for path in ('/responses', '/responses/compact'):
            payload = {'model': 'gpt-6-astra', 'input': [reasoning(),
                {'type': 'message', 'role': 'user', 'content': 'MARKER'}]}
            conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
            self.addCleanup(conn.close)
            conn.request('POST', '/test-token' + path,
                         zstd.compress(json.dumps(payload).encode()),
                         {'Content-Encoding': 'zstd',
                          'Content-Type': 'application/json'})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            self.assertEqual(json.loads(recorded[-1][3])['input'], payload['input'][1:])

    def test_validation_failure_is_final_and_diagnostics_are_structural(self):
        body = json.dumps({'error': {'code': 'array_above_max_length', 'param': 'input[0].content',
                                    'message': 'invalid PRIVATE-CANARY'}}).encode()
        install_fake(self, lambda: FakeUpstream(400, body, []))
        for model in ('gpt-6-astra', 'deepseek/deepseek-v4.1-flash-1017'):
            with mock.patch('ai_router.router.log_event') as log:
                response = post(self.server.server_port, '/test-token/responses',
                                {'model': model, 'input': [], 'stream': True})
                self.assertEqual(response.status, 400)
                message = json.loads(response.read())['error']['message']
                self.assertNotIn('array_above_max_length', message)
                self.assertNotIn('input[0].content', message)
                self.assertNotIn('PRIVATE-CANARY', message + str(log.call_args_list))
                rejected = next(c.kwargs for c in log.call_args_list if c.args == ('upstream_rejected',))
                self.assertEqual(rejected['code'], 'array_above_max_length')
                self.assertEqual(rejected['parameter'], 'input[0].content')


class RejectionParameterTests(unittest.TestCase):
    def test_direct_nested_and_untrusted_parameters(self):
        for param in ('input[0].content', 'tools[12].parameters.required', 'reasoning.effort'):
            body = json.dumps({'error': {'param': param}})
            self.assertEqual(upstream.rejection_parameter(body), param)
            nested = json.dumps({'error': {'metadata': {'raw': body}}})
            self.assertEqual(upstream.rejection_parameter(nested), param)
        for param in ('input[0].PRIVATE-CANARY', 'input[0].content\n', 'https://secret.invalid',
                      'input[9999999].content', 'input[0].content PRIVATE-CANARY', None, []):
            self.assertIsNone(upstream.rejection_parameter(json.dumps({'error': {'param': param}})))
        for body in (b'\xff', 'bad json', '[]', '{"error":null}', '{"error":{"metadata":null}}'):
            self.assertIsNone(upstream.rejection_parameter(body))

    def test_only_responses_validation_changes_status(self):
        for protocol in ('responses', 'messages', None):
            for http_status in (400, 401, 403, 500, 503):
                status, _, _ = upstream.describe_failure(None,
                    {'status': http_status, 'body': b'{"error":{"message":"rejected"}}'},
                    {'model': 'm', 'protocol': protocol})
                if protocol == 'responses':
                    expected = 503 if http_status in (500, 503) else 400
                else:
                    expected = 409
                self.assertEqual(status, expected)
