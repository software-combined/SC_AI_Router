"""Refused ChatGPT helper turns: plan, scope, and the twin-row fallback.

Protects the title contract: desktop titles come from helper turns on a
subscription slug, so an exhausted allowance must either keep the existing
503 (flag off) or be answered by the registry's OpenRouter twin (flag on),
and nothing else may be redirected.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ai_router import subscription_fallback
from ai_router.registry import by_slug
from ai_router.runtime import load_state
from tests.fakes import FakeUpstream, install_fake
from tests.harness import (
    auth_file as _auth_file,
    post as _post,
    start_server as _start_server,
    test_state as _test_state,
)

HELPER = 'gpt-5.6-luna'
HEADERS = {'x-codex-turn-metadata': json.dumps({'thread_source': 'thread_title'})}


def _sequence(*responses):
    """One FakeUpstream per upstream call; the last response repeats."""
    pending = list(responses)

    def responder():
        return FakeUpstream(*(pending.pop(0) if len(pending) > 1 else pending[0]))

    return responder


class HelperTurnTests(unittest.TestCase):
    def test_every_helper_source_is_recognised_regardless_of_header_case(self):
        for source in sorted(subscription_fallback.HELPER_SOURCES):
            with self.subTest(source=source):
                headers = {'X-Codex-Turn-Metadata': json.dumps({'thread_source': source})}
                self.assertTrue(subscription_fallback.helper_turn(headers))

    def test_user_turns_and_unreadable_metadata_are_never_helpers(self):
        cases = [
            {},
            {'x-codex-turn-metadata': json.dumps({'thread_source': 'user'})},
            {'x-codex-turn-metadata': json.dumps({'turn_trigger': 'thread_title'})},
            {'x-codex-turn-metadata': 'not json'},
            {'x-codex-turn-metadata': json.dumps(['thread_title'])},
            {'x-codex-turn-metadata': json.dumps({'thread_source': ['thread_title']})},
            {'x-codex-turn-metadata': json.dumps({'thread_source': {'name': 'thread_title'}})},
            {'x-codex-turn-metadata': 'x' * (subscription_fallback.MAX_METADATA_BYTES + 1)},
        ]
        for headers in cases:
            with self.subTest(headers=headers):
                self.assertFalse(subscription_fallback.helper_turn(headers))

    def test_twin_is_the_openrouter_row_only(self):
        self.assertEqual(by_slug('openai/gpt-5.6-luna').provider, 'openrouter')
        self.assertEqual(subscription_fallback.twin_slug(HELPER), 'openai/gpt-5.6-luna')
        for absent in ('gpt-5.5', 'gpt-5.3-codex-spark', 'openai/gpt-5.6-luna', None):
            with self.subTest(model=absent):
                self.assertIsNone(subscription_fallback.twin_slug(absent))

    def test_only_enabled_helper_turns_with_a_twin_get_a_plan(self):
        base = dict(state={'openai_helper_fallback': True},
                    prepared=SimpleNamespace(provider='openai'),
                    path='/responses', payload={'model': HELPER},
                    raw_body=b'{}', headers=HEADERS, credentials=object())
        self.assertIsNotNone(subscription_fallback.plan(**base))
        disqualified = (('state', {}),
                        ('state', {'openai_helper_fallback': False}),
                        ('path', '/alpha/search'),
                        ('prepared', SimpleNamespace(provider='openrouter')),
                        ('payload', {'model': HELPER, 'tools': [{'type': 'custom'}]}),
                        ('headers', {}),
                        ('payload', {'model': 'gpt-5.5'}))
        # Plan 068: a provisioned portco list gates the redispatch too.
        allowed_twin = {'openai_helper_fallback': True,
                        'allowed_models': ['openai/gpt-5.6-luna']}
        self.assertIsNotNone(subscription_fallback.plan(**dict(base, state=allowed_twin)))
        for policy in ({'openai_helper_fallback': True, 'allowed_models': []},
                       {'openai_helper_fallback': True, 'allowed_models': ['z-ai/glm-5.3']}):
            with self.subTest(policy=policy):
                self.assertIsNone(subscription_fallback.plan(**dict(base, state=policy)))
        disqualified += (('state', {'openai_helper_fallback': True, 'allowed_models': []}),
                         ('state', {'openai_helper_fallback': True,
                                    'allowed_models': ['z-ai/glm-5.3']}))
        for field, value in disqualified:
            with self.subTest(field=field, value=value):
                self.assertIsNone(subscription_fallback.plan(**dict(base, **{field: value})))


class RefusedHelperTurnTests(unittest.TestCase):
    def _server(self, **overrides):
        credentials = overrides.pop('credentials', None)
        state = _test_state(_auth_file(self))
        state['openai_models'] = [HELPER, 'gpt-5.5']
        state.update(overrides)
        server = _start_server(state, credentials=credentials)
        self.addCleanup(server.shutdown)
        return server

    def _turn(self, server, headers=None, payload=None):
        body = {'model': HELPER, 'input': []}
        body.update(payload or {})
        return _post(server.server_port, '/test-token/responses', body, headers)

    def _refusal(self):
        return _sequence((429, b'{}', []),
                         (200, b'{"output": [], "model": "openai/gpt-5.6-luna"}',
                          [('Content-Type', 'application/json')]))

    def test_flag_off_keeps_the_existing_503(self):
        recorded = install_fake(self, self._refusal())
        server = self._server()
        response = self._turn(server, HEADERS)
        self.assertEqual(response.status, 503)
        self.assertEqual(json.loads(response.read())['error']['code'],
                         'UPSTREAM_RATE_LIMITED')
        self.assertEqual([call[0] for call in recorded], ['chatgpt.com'])

    def test_enabled_flag_answers_the_helper_turn_from_the_twin_row(self):
        recorded = install_fake(self, self._refusal())
        server = self._server(openai_helper_fallback=True)
        response = self._turn(server, HEADERS)
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.read())['model'], 'openai/gpt-5.6-luna')
        self.assertEqual([call[0] for call in recorded], ['chatgpt.com', 'openrouter.ai'])
        _host, method, path, body, headers = recorded[1]
        self.assertEqual((method, path), ('POST', '/api/v1/responses'))
        self.assertEqual(json.loads(body)['model'], 'openai/gpt-5.6-luna')
        self.assertEqual(headers['Authorization'], 'Bearer test-key')
        self.assertEqual(server.inflight, 0)

    def test_ordinary_and_tool_turns_keep_the_refusal(self):
        for headers, payload in ((None, None),
                                 (HEADERS, {'tools': [{'type': 'custom', 'name': 'exec'}]})):
            with self.subTest(headers=headers, payload=payload):
                recorded = install_fake(self, self._refusal())
                server = self._server(openai_helper_fallback=True)
                response = self._turn(server, headers, payload)
                self.assertEqual(response.status, 503)
                response.read()
                self.assertEqual([call[0] for call in recorded], ['chatgpt.com'])

    def test_missing_key_falls_back_to_the_refusal(self):
        class _NoKey:
            def key_for(self, provider_id=None):
                raise LookupError('no key')

        recorded = install_fake(self, self._refusal())
        server = self._server(openai_helper_fallback=True, credentials=_NoKey())
        with self.assertLogs('codex_router', level='INFO') as logs:
            response = self._turn(server, HEADERS)
        self.assertEqual(response.status, 503)
        response.read()
        self.assertEqual([call[0] for call in recorded], ['chatgpt.com'])
        events = [json.loads(record.getMessage()) for record in logs.records]
        self.assertIn('subscription_fallback_unavailable',
                      [event.get('event') for event in events])

    def test_twin_fallback_carries_the_responses_protocol_in_its_metrics(self):
        # Plan 141: transport.emit_terminal_failure keys on metrics['protocol'],
        # so the twin hand-off must carry it or a mid-stream failure on the
        # fallback loses its terminal frame (it emitted one before the move).
        from ai_router.router import Handler
        recorded = install_fake(self, self._refusal())
        server = self._server(openai_helper_fallback=True)
        calls = []
        real_relay = Handler.relay

        def relay(self, provider, prepared, metrics, started, has_image=False):
            calls.append(dict(metrics))
            return real_relay(self, provider, prepared, metrics, started, has_image)

        import unittest.mock as mock
        with mock.patch.object(Handler, 'relay', relay):
            response = self._turn(server, HEADERS)
        self.assertEqual(response.status, 200)
        response.read()
        twin = [c for c in calls if c.get('helper_fallback')]
        self.assertEqual(len(twin), 1, calls)
        self.assertEqual(twin[0].get('protocol'), 'responses')
        self.assertEqual(twin[0].get('model'), 'openai/gpt-5.6-luna')

    def test_policy_excluded_twin_keeps_the_refusal(self):
        # Plan 068: the provisioned portco list gates the redispatch, so an
        # excluded twin must never be billed through the helper path.
        recorded = install_fake(self, self._refusal())
        server = self._server(openai_helper_fallback=True, allowed_models=['z-ai/glm-5.3'])
        response = self._turn(server, HEADERS)
        self.assertEqual(response.status, 503)
        self.assertEqual(json.loads(response.read())['error']['code'],
                         'UPSTREAM_RATE_LIMITED')
        self.assertEqual([call[0] for call in recorded], ['chatgpt.com'])

    def test_subscription_slug_without_a_twin_keeps_the_refusal(self):
        recorded = install_fake(self, self._refusal())
        server = self._server(openai_helper_fallback=True)
        response = self._turn(server, HEADERS, payload={'model': 'gpt-5.5'})
        self.assertEqual(response.status, 503)
        response.read()
        self.assertEqual([call[0] for call in recorded], ['chatgpt.com'])

    def test_unpreparable_twin_keeps_the_refusal_and_its_retry_after(self):
        # 'ultra' is offered for the subscription slug but not the twin row,
        # so the twin prepare raises before any OpenRouter dispatch.
        recorded = install_fake(self, self._refusal())
        server = self._server(openai_helper_fallback=True)
        with self.assertLogs('codex_router', level='INFO') as logs:
            response = self._turn(server, HEADERS, payload={'reasoning': {'effort': 'ultra'}})
        self.assertEqual(response.status, 503)
        self.assertEqual(response.getheader('Retry-After'), '2')
        response.read()
        self.assertEqual([call[0] for call in recorded], ['chatgpt.com'])
        events = [json.loads(record.getMessage()) for record in logs.records]
        self.assertIn('subscription_fallback_unavailable',
                      [event.get('event') for event in events])


class StateValidationTests(unittest.TestCase):
    def test_flag_must_be_boolean(self):
        state = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
        json.dump({'port': 1, 'token': 't' * 32, 'openai_models': [],
                   'openai_helper_fallback': 'yes'}, state)
        state.close()
        self.addCleanup(Path(state.name).unlink)
        with mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': 'sk-or'}):
            with self.assertRaises(SystemExit) as ctx:
                load_state(Path(state.name))
        self.assertIn('openai_helper_fallback', str(ctx.exception))
