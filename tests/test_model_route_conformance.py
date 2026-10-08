"""Every registry row traverses its supported routes, including hidden rows."""
import gzip
import http.client
import json
import unittest
from unittest import mock

from ai_router import (catalogue, outcome, provider_defs, registry, subscription_discovery,
                       wire_shape)
from ai_router import media as media_api
from tests.fakes import FakeUpstream
from tests.model_route_fixtures import (HEADERS, PROTOCOLS, RouteHarness,
                                       media_payload, media_success, overloaded, payload, routes, success)


class ModelRouteConformanceTests(unittest.TestCase):
    def setUp(self):
        self.harness = RouteHarness(self)

    def test_media_streams_complete_on_documented_success_statuses(self):
        for kind, model, code in (('video', 'google/veo-3.1-fast', 202),):
            with self.subTest(kind=kind):
                reply = media_success(model, kind)
                reply.status = code
                status, wire, sends, facts = self.harness.turn(
                    media_payload(model, kind, stream=True),
                    provider_defs.RESPONSES, [reply], projected=False)
                self.assertEqual(status, 200)
                events = [json.loads(line[5:]) for line in wire.splitlines()
                          if line.startswith(b'data:')]
                self.assertTrue(events, 'Codex needs a Responses event stream')
                self.assertEqual(events[-1]['type'], 'response.completed')
                self.assertEqual(events[-1]['response']['status'], 'completed')
                self.assertEqual(events[-1]['response']['output'][0]['type'],
                                 'message')
                self.assertEqual(len(sends), 1)
                self.assertEqual(facts['outcome'], outcome.SUCCESS)

    def test_selected_media_row_accepts_a_normal_codex_turn(self):
        model = 'google/veo-3.1-fast'
        body = media_payload(model, 'video', stream=True)
        body['tools'] = []
        status, wire, sends, _ = self.harness.turn(
            body, provider_defs.RESPONSES, [media_success(model, 'video')],
            projected=False)
        self.assertEqual(status, 200)
        self.assertEqual(len(sends), 1)
        self.assertIn(b'job_fixture', wire)

    def test_image_rows_on_responses_are_refused_before_a_paid_send(self):
        for row in registry.MODELS:
            if row.media_kind == 'image':
                with self.subTest(model=row.slug):
                    status, _, sends, _ = self.harness.turn(
                        media_payload(row.slug, 'image'), provider_defs.RESPONSES,
                        [], sent=False, projected=False)
                    self.assertEqual((status, sends), (400, []))

    def test_media_row_on_claude_is_refused_before_a_send(self):
        status, _, sends, _ = self.harness.turn(
            payload('openai/gpt-image-2', provider_defs.MESSAGES),
            provider_defs.MESSAGES, [], sent=False, projected=False)
        self.assertEqual(status, 409)
        self.assertFalse(sends)

    def test_media_rows_reach_their_own_api_with_the_prompt(self):
        media = [row for row in registry.MODELS if row.media_kind == 'video']
        self.assertTrue(media, 'no media rows registered')
        for row in media:
            with self.subTest(model=row.slug, kind=row.media_kind):
                reply = media_success(row.upstream_id or row.slug, row.media_kind)
                status, wire, sends, facts = self.harness.turn(
                    media_payload(row.slug, row.media_kind), provider_defs.RESPONSES,
                    [reply], projected=False)
                self.assertEqual(status, 200)
                self.assertTrue(wire)
                self.assertEqual(len(sends), 1)
                defn = provider_defs.get(row.provider)
                want = media_api.videos_path(defn)
                self.assertEqual(sends[0][:3], (defn.host, 'POST', want))
                sent = json.loads(sends[0][3])
                self.assertEqual(sent['model'], row.upstream_id or row.slug)
                self.assertEqual(sent['prompt'], 'synthetic media check')
                headers = {key.lower(): value for key, value in sends[0][4].items()}
                self.assertEqual(headers['authorization'], 'Bearer test-key')
                self.assertEqual(facts['outcome'], outcome.SUCCESS)
                attempt, = facts['attempt_evidence']
                self.assertEqual(attempt['requested_model'], row.slug)
                self.assertIn('job_fixture', wire.decode())

    def test_media_tool_on_a_chat_row_is_refused_before_any_send(self):
        chat = next(row for row in registry.MODELS if row.media_kind is None
                    and row.provider == provider_defs.DEFAULT_EXTERNAL)
        for kind in ('image', 'video'):
            with self.subTest(model=chat.slug, kind=kind):
                body = media_payload(chat.slug, kind)
                # Refused in the adapter before projection or dispatch.
                status, _, sends, _ = self.harness.turn(
                    body, provider_defs.RESPONSES, [], sent=False,
                    projected=False)
                self.assertEqual(status, 400)
                self.assertEqual(sends, [])

    def test_every_row_routes_json_and_stream_through_the_common_owners(self):
        # Media rows answer their own Images/Videos API, covered by
        # test_media_rows_reach_their_own_api_with_the_prompt.
        expected = {(row.slug, row.provider, protocol) for row in registry.MODELS
                    if row.media_kind is None
                    for protocol in PROTOCOLS if provider_defs.get(row.provider).serves(protocol)}
        observed = set()
        for row, protocol in routes():
            if row.media_kind is not None:
                continue
            for stream in (False, True):
                with self.subTest(model=row.slug, protocol=protocol, stream=stream):
                    upstream_id = row.upstream_id or row.slug
                    reply = success(upstream_id, protocol, stream)
                    status, wire, sends, facts = self.harness.turn(
                        payload(row.slug, protocol, row.default_reasoning, stream),
                        protocol, [reply])
                    self.assertEqual(status, 200)
                    self.assertTrue(wire)
                    self.assertEqual(len(sends), 1)
                    defn = provider_defs.get(row.provider)
                    path = '/responses' if protocol == provider_defs.RESPONSES else '/v1/messages'
                    self.assertEqual(sends[0][:3], (defn.host, 'POST', defn.path_for(protocol, path)))
                    self.assertEqual(json.loads(sends[0][3])['model'], upstream_id)
                    headers = {key.lower(): value for key, value in sends[0][4].items()}
                    self.assertEqual(headers['authorization'], 'Bearer test-key')
                    for name in ('x-api-key', 'chatgpt-account-id', 'anthropic-beta'):
                        self.assertNotIn(name, headers)
                    self.assertEqual(facts['outcome'], outcome.SUCCESS)
                    attempt, = facts['attempt_evidence']
                    self.assertEqual(attempt['requested_model'], row.slug)
                    self.assertEqual(attempt['upstream_model'], upstream_id)
                    self.assertEqual(attempt['model_status'], 'provider_reported_match')
                    observed.add((row.slug, row.provider, protocol))
        self.assertTrue(observed)
        self.assertEqual(observed, expected)

    def test_each_route_recovers_once_before_output_and_never_after_output(self):
        for row, protocol in routes():
            if row.media_kind is not None:
                continue
            for committed in (False, True):
                with self.subTest(model=row.slug, protocol=protocol, committed=committed):
                    model = row.upstream_id or row.slug
                    replies = [overloaded(model, protocol, committed), success(model, protocol)]
                    _, _, sends, facts = self.harness.turn(
                        payload(row.slug, protocol, row.default_reasoning), protocol, replies)
                    self.assertEqual(len(sends), 1 if committed else 2)
                    self.assertEqual(facts['outcome'], outcome.TRANSIENT if committed else outcome.SUCCESS)
                    self.assertEqual(len(facts['attempt_evidence']), len(sends))
                    self.assertEqual(facts['attempt_evidence'][0]['outcome'], outcome.TRANSIENT)
                    self.assertTrue(all(a['model_status'] == 'provider_reported_match'
                                        for a in facts['attempt_evidence']))

    def test_http_failures_keep_their_category_and_do_not_attest_a_cached_model(self):
        cases = ((400, 'invalid_request_error', outcome.REFUSED),
                 (429, 'rate_limit_error', outcome.RATE_LIMIT),
                 (402, 'insufficient_quota', outcome.QUOTA),
                 (503, 'overloaded_error', outcome.TRANSIENT))
        for row, protocol in routes():
            if row.media_kind is not None:
                continue
            for status, code, expected in cases:
                with self.subTest(model=row.slug, protocol=protocol, code=code):
                    raw = json.dumps({'error': {'code': code, 'type': code}}).encode()
                    reply = FakeUpstream(status, raw, [('Content-Type', 'application/json')])
                    self.harness.server.served_models[row.slug] = 'previous-success'
                    _, _, sends, facts = self.harness.turn(
                        payload(row.slug, protocol, row.default_reasoning), protocol, [reply])
                    self.assertEqual(len(sends), 1)
                    self.assertEqual(facts['outcome'], expected)
                    attempt, = facts['attempt_evidence']
                    self.assertEqual(attempt['outcome'], expected)
                    self.assertEqual(attempt['model_status'], 'unverified')
                    self.assertEqual(attempt['model_reports'], [])

    def test_each_capability_profile_shapes_responses_and_preserves_messages(self):
        recursive = {'type': 'object', 'properties': {'next': {'$ref': '#'}}}
        image = {'type': 'input_image', 'image_url': 'data:image/png;base64,AA=='}
        profiles = set()
        for row, protocol in routes():
            if row.media_kind is not None:
                continue
            with self.subTest(model=row.slug, protocol=protocol):
                body = payload(row.slug, protocol, row.default_reasoning, False)
                if protocol == provider_defs.RESPONSES:
                    body.update(max_output_tokens=10**9, service_tier='priority')
                    body['tools'] = [
                        {'type': 'function', 'name': 'recursive', 'parameters': recursive},
                        {'type': 'function', 'name': 'root_value', 'parameters': {'type': 'string'}}]
                    body['input'] += [
                        {'type': 'function_call', 'name': 'recursive', 'call_id': 'c', 'arguments': '{}'},
                        {'type': 'function_call_output', 'call_id': 'c', 'output': 'synthetic result'},
                        {'type': 'message', 'role': 'user', 'content': [image]},
                        {'type': 'reasoning', 'summary': [], 'encrypted_content': 'OPAQUE-FIXTURE'}]
                else:
                    body['tools'] = [{'name': 'recursive', 'input_schema': recursive}]
                    body['messages'] = [
                        {'role': 'assistant', 'content': [
                            {'type': 'thinking', 'thinking': 'synthetic', 'signature': 'SIGNED-FIXTURE'},
                            {'type': 'tool_use', 'id': 'c', 'name': 'recursive', 'input': {}}]},
                        {'role': 'user', 'content': [
                            {'type': 'tool_result', 'tool_use_id': 'c', 'content': 'synthetic result'},
                            {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png',
                                                       'data': 'AA=='}}]}]
                before = json.dumps(body)
                _, _, sends, facts = self.harness.turn(body, protocol, [
                    success(row.upstream_id or row.slug, protocol, False)])
                self.assertEqual(json.dumps(body), before)
                sent = json.loads(sends[0][3])
                if protocol == provider_defs.RESPONSES:
                    tools = {tool['name']: tool for tool in sent['tools']}
                    for name, wrapped in (('recursive', row.schema_mode == 'json_text'),
                                          ('root_value', row.schema_mode == 'json_text_root')):
                        self.assertEqual('arguments_json' in tools[name]['parameters'].get('properties', {}), wrapped)
                    self.assertEqual('input_image' in json.dumps(sent['input']),
                                     'image' in row.modalities and not row.drop_images)
                    self.assertNotIn('OPAQUE-FIXTURE', json.dumps(sent))
                    self.assertNotIn('service_tier', sent)
                    self.assertEqual(wire_shape.pair_problems(sent['input']), {})
                    self.assertLessEqual(sent['max_output_tokens'], row.max_output_tokens)
                    if row.context_window:
                        self.assertLessEqual(sent['max_output_tokens'], row.context_window // 2)
                    self.assertEqual(sent['reasoning']['effort'], row.default_reasoning)
                else:
                    self.assertEqual(sent, {**body, 'model': row.upstream_id or row.slug})
                    self.assertNotIn('max_output_tokens', sent)
                self.assertEqual(facts['outcome'], outcome.SUCCESS)
                profiles.add((row.schema_mode, row.history_mode, protocol))
        self.assertEqual(profiles, {(row.schema_mode, row.history_mode, protocol)
                                    for row, protocol in routes()
                                    if row.media_kind is None})

    def test_responses_refuses_unsupported_efforts_before_a_send_for_every_row(self):
        for row, protocol in routes():
            if protocol != provider_defs.RESPONSES or row.media_kind is not None:
                continue
            with self.subTest(model=row.slug):
                status, _, sends, _ = self.harness.turn(
                    payload(row.slug, protocol, 'unsupported-fixture'), protocol, [], sent=False)
                self.assertEqual(status, 400)
                self.assertEqual(sends, [])

    def test_every_row_refuses_a_disabled_protocol_before_projection_or_dispatch(self):
        for row, protocol in routes():
            if row.media_kind is not None:
                continue
            with self.subTest(model=row.slug, protocol=protocol), mock.patch.object(
                    provider_defs.get(row.provider), protocol + '_path', None):
                status, _, sends, _ = self.harness.turn(
                    payload(row.slug, protocol, row.default_reasoning), protocol, [],
                    sent=False, projected=False)
                self.assertIn(status, (400, 409))
                self.assertEqual(sends, [])

    def test_declared_tool_ceilings_and_search_capabilities_on_responses(self):
        for row, protocol in routes():
            if protocol != provider_defs.RESPONSES or row.media_kind is not None:
                continue
            with self.subTest(model=row.slug):
                body = payload(row.slug, protocol, row.default_reasoning, False)
                body['tools'] = [{'type': 'web_search'}]
                _, _, sends, _ = self.harness.turn(body, protocol, [
                    success(row.upstream_id or row.slug, protocol, False)])
                self.assertEqual(any(t['type'] == 'web_search' for t in
                                     json.loads(sends[0][3])['tools']), row.web_search)
                if row.max_tools is not None:
                    body['tools'] = [{'type': 'function', 'name': f'tool_{i}',
                                      'parameters': {'type': 'object'}}
                                     for i in range(row.max_tools + 1)]
                    status, _, sends, _ = self.harness.turn(body, protocol, [], sent=False)
                    self.assertEqual((status, sends), (400, []))

    def test_discovered_and_future_native_ids_keep_signed_bytes_auth_and_no_replay(self):
        ids = ('gpt-6-luna', 'gpt-future-conformance')
        with mock.patch.object(subscription_discovery, 'fetch_native', return_value=[
                catalogue.subscription_stub(model) for model in ids]):
            conn = http.client.HTTPConnection('127.0.0.1', self.harness.server.server_port)
            self.addCleanup(conn.close)
            conn.request('GET', '/test-token/models', headers=HEADERS)
            response = conn.getresponse()
            listed = {row['slug'] for row in json.loads(response.read())['models']}
            self.assertTrue(set(ids) <= listed)
        pairs = [(model, provider_defs.RESPONSES) for model in ids] + [
            (model, provider_defs.MESSAGES) for model in ('claude-sonnet-5', 'claude-future-conformance')]
        for model, protocol in pairs:
            for failure in (False, True, 'encoded'):
                with self.subTest(model=model, protocol=protocol, failure=failure):
                    body = payload(model, protocol)
                    if protocol == provider_defs.RESPONSES:
                        body['input'].append({'type': 'reasoning', 'encrypted_content': 'OPAQUE-NATIVE'})
                    else:
                        body['messages'].insert(0, {'role': 'assistant', 'content': [
                            {'type': 'thinking', 'thinking': 'synthetic', 'signature': 'SIGNED-NATIVE'},
                            {'type': 'redacted_thinking', 'data': 'OPAQUE-NATIVE'}]})
                    reply = overloaded(model, protocol) if failure is True else success(model, protocol)
                    if failure == 'encoded':
                        reply = FakeUpstream(200, gzip.compress(reply._buf), [
                            ('Content-Type', 'text/event-stream'), ('Content-Encoding', 'gzip')])
                    original = reply._buf
                    _, wire, sends, facts = self.harness.turn(body, protocol, [reply], native=True)
                    self.assertEqual(len(sends), 1)
                    defn = provider_defs.OPENAI if protocol == provider_defs.RESPONSES else provider_defs.ANTHROPIC
                    self.assertEqual(sends[0][0], defn.host)
                    self.assertEqual(sends[0][3], json.dumps(body).encode())
                    self.assertEqual(sends[0][4]['Authorization'], HEADERS['Authorization'])
                    self.assertNotIn('test-key', json.dumps(sends[0][4]))
                    self.assertEqual(wire, original)
                    expected = (outcome.UNKNOWN if failure == 'encoded' else
                                outcome.TRANSIENT if failure else outcome.SUCCESS)
                    self.assertEqual(facts['outcome'], expected)
                    if failure == 'encoded':
                        self.assertEqual(facts['attempt_evidence'][0]['model_status'], 'unverified')


if __name__ == '__main__':
    unittest.main()
