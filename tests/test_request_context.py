"""Plan 188 slice 1: one registry generation per request, on every route.

A refresh (`model_refresh.apply`) can land while a request is in flight.
These tests swap the generation, or poison every live lookup, right after
the router resolved a request, then read the wire bodies the fake upstream
received: the in-flight request keeps the rows it resolved, and the next
request sees the new generation.
"""
import contextlib
import dataclasses
import json
import unittest
from unittest import mock

from ai_router import (agent_handoffs, capabilities, catalogue, claude, model_refresh,
                       providers, registry, request_context, subscription_discovery)
from tests.fakes import FakeUpstream, install_fake
from tests.harness import (auth_file, isolated_home, post, start_server, test_state)
from tests.test_claude_ingress import _messages

RESPONSES_SLUG = 'google/gemini-3.1-pro-preview'
MESSAGES_SLUG = 'moonshotai/kimi-k3'
NATIVE_HEADERS = {'Authorization': 'Bearer subscription-secret', 'x-api-key': 'client-secret',
                  'chatgpt-account-id': 'acct'}
OK = (200, b'{"output": [], "model": "served"}', [('Content-Type', 'application/json')])
IMAGE = {'type': 'message', 'role': 'user', 'content': [
    {'type': 'input_text', 'text': 'look'},
    {'type': 'input_image', 'image_url': 'data:image/png;base64,AA=='}]}


def _turn(effort):
    """Every Responses fact a row decides: tools, schema, images, effort, cap."""
    return {'model': RESPONSES_SLUG, 'input': [IMAGE], 'max_output_tokens': 5000,
            'reasoning': {'effort': effort},
            'tools': [{'type': 'web_search'},
                      {'type': 'function', 'name': 'pick', 'parameters': {'type': 'string'}}]}


def _refreshed(slug, **changes):
    """The live roster with one row changed, or added from RESPONSES_SLUG."""
    rows = {m.slug: m for m in registry.MODELS}
    base = rows.get(slug) or dataclasses.replace(rows[RESPONSES_SLUG], slug=slug)
    rows[slug] = dataclasses.replace(base, **changes)
    return tuple(rows.values())


@contextlib.contextmanager
def _generation():
    """Put the live generation back, however many refreshes ran inside."""
    saved = (registry.MODELS, registry.BY_SLUG, catalogue.MODELS)
    try:
        yield
    finally:
        registry.MODELS, registry.BY_SLUG, catalogue.MODELS = saved
        capabilities.rebuild(saved[0])


def _after(target, name, action):
    """Patch `target.name` to run `action` once its real call returns."""
    real = getattr(target, name)

    def hooked(*args, **kwargs):
        result = real(*args, **kwargs)
        action()
        return result
    return mock.patch.object(target, name, hooked)


def _after_resolution(action):
    # The router resolves before it asks for live subscription membership.
    return _after(subscription_discovery, 'request_models', action)


def _poison(stack):
    """Every live registry and capability lookup raises until `stack` closes."""
    def dead(*_args, **_kwargs):
        raise AssertionError('live registry read after resolution')

    class Dead(dict):
        __getitem__ = get = __contains__ = __iter__ = __len__ = keys = values = items = dead
    for module, name in ((registry, 'BY_SLUG'), (registry, 'MODELS'),
                         (capabilities, 'EXTERNAL_MODELS'), (capabilities, 'IMAGE_INPUT_MODELS'),
                         (capabilities, 'REASONING_LEVELS'), (capabilities, 'EXCLUDED_EFFORTS')):
        stack.enter_context(mock.patch.object(module, name, Dead()))
    for module in (registry, providers, claude):
        stack.enter_context(mock.patch.object(module, 'by_slug', dead))


class RequestContextTests(unittest.TestCase):
    def test_capture_is_one_read_only_generation(self):
        rows = request_context.capture()
        before = rows[RESPONSES_SLUG]
        with self.assertRaises(TypeError):
            rows['x'] = before
        with _generation():
            model_refresh.apply(_refreshed(RESPONSES_SLUG, upstream_id='fresh'))
            self.assertIs(rows[RESPONSES_SLUG], before)
            self.assertEqual(request_context.capture()[RESPONSES_SLUG].upstream_id, 'fresh')
        self.assertIs(request_context.capture()[RESPONSES_SLUG], before)

    def test_resolution_keeps_a_native_id_and_retargets_within_its_generation(self):
        rows = request_context.capture()
        native = request_context.resolve('gpt-6-astra', rows)
        self.assertEqual((native.slug, native.row), ('gpt-6-astra', None))
        twin = request_context.retarget(native, 'openai/gpt-6-luna')
        self.assertEqual(twin.request_id, native.request_id)
        self.assertIs(twin.row, rows['openai/gpt-6-luna'])
        self.assertIs(twin.catalogue, rows)
        self.assertNotEqual(request_context.resolve('gpt-6-astra', rows).request_id,
                            native.request_id)


class RoutedGenerationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(_generation())
        self.server = start_server(test_state(auth_file(self)))
        self.addCleanup(self.server.shutdown)
        self.server.state['openai_models'] = ['gpt-6-astra']

    def _send(self, path, payload, headers=NATIVE_HEADERS):
        response = post(self.server.server_port, '/test-token' + path, payload, headers)
        return response.status, response.read()

    def _refresh(self, slug, **changes):
        return lambda: model_refresh.apply(_refreshed(slug, **changes))

    def test_responses_turn_keeps_its_row_through_a_refresh(self):
        new = dict(upstream_id='google/fresh', schema_mode='json_text_root', web_search=False,
                   max_tools=1, modalities=('text',), reasoning=('low',),
                   default_reasoning='low', max_output_tokens=1000,
                   provider_prefs={'order': ['fresh']})
        hooks = ((subscription_discovery, 'request_models'),
                 (agent_handoffs, 'add_plaintext_tools'))
        for target, name in hooks:
            with self.subTest(hook=name), _generation():
                recorded = install_fake(self, lambda: FakeUpstream(*OK))
                with _after(target, name, self._refresh(RESPONSES_SLUG, **new)):
                    status, _ = self._send('/responses', _turn('high'))
                self.assertEqual(status, 200)
                self.assertEqual(self._send('/responses', _turn('low'))[0], 200)
                old, fresh = (json.loads(call[3]) for call in recorded)
                self.assertEqual(old['model'], RESPONSES_SLUG)
                self.assertEqual([t['type'] for t in old['tools']], ['web_search', 'function'])
                self.assertEqual(old['tools'][1]['parameters'], {'type': 'string'})
                self.assertIn('input_image', json.dumps(old['input']))
                self.assertEqual((old['max_output_tokens'], old['reasoning']['effort']),
                                 (5000, 'high'))
                self.assertNotIn('provider', old)
                # The next request resolves against the refreshed generation.
                self.assertEqual(fresh['model'], 'google/fresh')
                self.assertEqual([t['name'] for t in fresh['tools']], ['pick'])
                self.assertIn('arguments_json', json.dumps(fresh['tools'][0]['parameters']))
                self.assertNotIn('input_image', json.dumps(fresh['input']))
                self.assertEqual(fresh['max_output_tokens'], 1000)
                self.assertEqual(fresh['provider'], {'order': ['fresh']})
                for call in recorded:
                    self.assertEqual(call[4]['Authorization'], 'Bearer test-key')
                    self.assertNotIn('chatgpt-account-id', call[4])

    def test_provider_prefs_edited_after_resolution_reach_only_the_next_request(self):
        def nested(prefs):
            prefs['order'].append('changed')
            prefs['sort']['by'] = 'latency'
        cases = (({}, lambda prefs: prefs.update(order=['changed']), None, {'order': ['changed']}),
                 ({'order': ['original'], 'sort': {'by': 'price'}}, nested,
                  {'order': ['original'], 'sort': {'by': 'price'}},
                  {'order': ['original', 'changed'], 'sort': {'by': 'latency'}}))
        for prefs, edit, before, after in cases:
            with self.subTest(empty=not prefs), _generation():
                model_refresh.apply(_refreshed(RESPONSES_SLUG, provider_prefs=prefs))
                recorded = install_fake(self, lambda: FakeUpstream(*OK))
                with _after_resolution(lambda: edit(prefs)):
                    self.assertEqual(self._send('/responses', _turn('low'))[0], 200)
                self.assertEqual(self._send('/responses', _turn('low'))[0], 200)
                old, new = (json.loads(call[3]).get('provider') for call in recorded)
                self.assertEqual(old, before)
                self.assertEqual(new, after)

    def test_every_route_serves_from_its_resolution_with_live_lookups_poisoned(self):
        alias = claude.claude_alias(MESSAGES_SLUG)
        cases = (('/responses', _turn('high'), 'openrouter.ai', RESPONSES_SLUG),
                 ('/v1/messages', _messages(alias), 'openrouter.ai', MESSAGES_SLUG),
                 ('/responses', {'model': 'gpt-6-astra', 'input': []}, 'chatgpt.com',
                  'gpt-6-astra'),
                 ('/v1/messages', _messages('claude-opus-4-6'), 'api.anthropic.com',
                  'claude-opus-4-6'))
        for path, payload, host, sent_model in cases:
            with self.subTest(path=path, model=payload['model']):
                recorded = install_fake(self, lambda: FakeUpstream(*OK))
                with contextlib.ExitStack() as stack:
                    with _after_resolution(lambda: _poison(stack)):
                        status, _ = self._send(path, payload)
                self.assertEqual(status, 200)
                (called, _method, _path, body, headers), = recorded
                self.assertEqual(called, host)
                self.assertEqual(json.loads(body)['model'], sent_model)
                external = host == 'openrouter.ai'
                self.assertEqual(headers.get('Authorization'),
                                 'Bearer test-key' if external else 'Bearer subscription-secret')
                if external:
                    self.assertFalse({'x-api-key', 'chatgpt-account-id'} & set(headers))

    def test_a_native_id_stays_native_while_a_refresh_adds_its_row(self):
        for path, payload in (('/responses', {'model': 'gpt-6-astra', 'input': []}),
                              ('/v1/messages', _messages('claude-opus-4-6'))):
            with self.subTest(path=path), _generation():
                recorded = install_fake(self, lambda: FakeUpstream(*OK))
                with _after_resolution(self._refresh(payload['model'], upstream_id='')):
                    self.assertEqual(self._send(path, payload)[0], 200)
                self.assertEqual(self._send(path, payload)[0], 200)
                (native, _, _, body, headers), (routed, *_rest) = recorded
                self.assertEqual(json.loads(body)['model'], payload['model'])
                self.assertNotEqual(native, 'openrouter.ai')
                self.assertNotIn('Bearer test-key', headers.values())
                self.assertEqual(routed, 'openrouter.ai')

    def test_messages_alias_keeps_its_upstream_id_through_a_refresh(self):
        recorded = install_fake(self, lambda: FakeUpstream(*OK))
        payload = _messages(claude.claude_alias(MESSAGES_SLUG))
        with _after_resolution(self._refresh(MESSAGES_SLUG, upstream_id='moonshotai/fresh')):
            self.assertEqual(self._send('/v1/messages', payload)[0], 200)
        self.assertEqual(self._send('/v1/messages', payload)[0], 200)
        self.assertEqual([json.loads(call[3])['model'] for call in recorded],
                         [MESSAGES_SLUG, 'moonshotai/fresh'])

    def test_compaction_summary_ignores_an_active_row_refresh(self):
        isolated_home(self)
        summary = json.dumps({'model': 'xiaomi/mimo-v2.6-flash',
                              'output': [{'type': 'message', 'content': [
            {'type': 'output_text', 'text': 'kept'}]}]}).encode()
        recorded = install_fake(self, lambda: FakeUpstream(200, summary, []))
        payload = {'model': RESPONSES_SLUG,
                   'input': [{'type': 'message', 'role': 'user', 'content': 'hello'}]}
        fresh = dict(upstream_id='google/fresh', reasoning=('high',),
                     provider_prefs={'order': ['fresh']})
        with _after_resolution(self._refresh(RESPONSES_SLUG, **fresh)):
            self.assertEqual(self._send('/responses/compact', payload)[0], 200)
        self.assertEqual(self._send('/responses/compact', payload)[0], 200)
        old, new = (json.loads(call[3]) for call in recorded)
        self.assertEqual((old['model'], old['reasoning'], old.get('provider')),
                         ('xiaomi/mimo-v2.6-flash', {'effort': 'none'}, None))
        self.assertEqual((new['model'], new['reasoning'], new.get('provider')),
                         ('xiaomi/mimo-v2.6-flash', {'effort': 'none'}, None))
        self.assertEqual((old['max_output_tokens'], new['max_output_tokens']),
                         (4000, 4000))

    def test_helper_fallback_prepares_the_twin_from_the_refused_generation(self):
        self.server.state.update(openai_helper_fallback=True, openai_models=['gpt-6-luna'])
        pending = [FakeUpstream(429, b'{}', []), FakeUpstream(*OK)]
        recorded = install_fake(self, lambda: pending.pop(0))
        helper = {'x-codex-turn-metadata': json.dumps({'thread_source': 'thread_title'}),
                  **NATIVE_HEADERS}
        refresh = self._refresh('openai/gpt-6-luna', upstream_id='openai/fresh')
        with self.assertLogs('codex_router', level='INFO') as logs, _after_resolution(refresh):
            status, _ = self._send('/responses', {'model': 'gpt-5.6-luna', 'input': []}, helper)
        self.assertEqual(status, 200)
        self.assertEqual([call[0] for call in recorded], ['chatgpt.com', 'openrouter.ai'])
        self.assertEqual(json.loads(recorded[1][3])['model'], 'openai/gpt-6-luna')
        self.assertEqual(recorded[1][4]['Authorization'], 'Bearer test-key')
        events = [json.loads(record.getMessage()) for record in logs.records]
        started = [e for e in events if e['event'] == 'request_started']
        final = [e for e in events if e['event'] == 'request_completed']
        self.assertEqual(len(started), 1)
        self.assertEqual(len(started[0]['request_id']), 32)
        self.assertEqual([e['request_id'] for e in final], [started[0]['request_id']])
        self.assertTrue(final[0]['helper_fallback'])

    def test_each_request_gets_its_own_correlation_id(self):
        install_fake(self, lambda: FakeUpstream(*OK))
        with self.assertLogs('codex_router', level='INFO') as logs:
            for _ in range(2):
                self.assertEqual(self._send('/responses', _turn('low'))[0], 200)
        events = [json.loads(record.getMessage()) for record in logs.records]
        ids = {kind: [e['request_id'] for e in events if e['event'] == kind]
               for kind in ('request_started', 'request_completed')}
        self.assertEqual(ids['request_started'], ids['request_completed'])
        self.assertEqual(len(set(ids['request_started'])), 2)


if __name__ == '__main__':
    unittest.main()
