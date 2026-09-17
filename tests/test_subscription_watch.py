"""Subscription watch: turn evidence on the request path.

Protects the contract that only ChatGPT subscription model turns move the
gate, that a change rewrites the picker catalogue at once, that a hostile
response can never fail a turn, and that the handler path records a refusal
and a recovery exactly once.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from ai_router import catalogue, subscription_gate, subscription_watch
from ai_router.subscription_roster import SUBSCRIPTION_SLUGS
from tests.fakes import FakeUpstream, install_fake
from tests.harness import auth_file as _auth_file
from tests.harness import post as _post
from tests.harness import start_server as _start_server

HELPER = 'gpt-5.6-luna'


def _state(home, **extra):
    """Router state beside the picker file: every roster slug is a row."""
    doc = {'port': 0, 'token': 'test-token',
           'openai_models': list(SUBSCRIPTION_SLUGS)}
    doc.update(extra)
    Path(home, 'mixed-router-state.json').write_text(json.dumps(doc))


def _rows(home):
    doc = json.loads(Path(home, 'mixed-models.json').read_text())
    return {row['slug'] for row in doc['models']}


class _Response:
    """Response surface for observe(): status plus its header pairs."""
    def __init__(self, status, headers=()):
        self.status, self._headers = status, list(headers)

    def getheaders(self):
        return list(self._headers)


class ObserveTests(unittest.TestCase):
    def _observe(self, home, status, metrics=None, provider='openai',
                 response=None):
        subscription_watch.observe(
            home,
            {'model': HELPER, 'path': '/responses'} if metrics is None else metrics,
            mock.Mock(provider=provider),
            response if response is not None else _Response(status))

    def test_only_subscription_model_turns_move_the_gate(self):
        with tempfile.TemporaryDirectory() as home:
            cases = ({'provider': 'openrouter'},
                     {'metrics': {'model': HELPER, 'path': '/alpha/x'}},
                     {'metrics': {'model': 'z-ai/glm-5.3', 'path': '/responses'}},
                     {'metrics': {'model': None, 'path': '/responses'}})
            for kwargs in cases:
                with self.subTest(kwargs=kwargs):
                    self._observe(home, 429, **kwargs)
            subscription_watch.observe(None, {'model': HELPER, 'path': '/responses'},
                                       mock.Mock(provider='openai'), _Response(429))
            self.assertFalse(subscription_gate.path(home).exists())

    def test_a_refusal_gates_the_slug_and_rewrites_the_picker(self):
        with tempfile.TemporaryDirectory() as home:
            _state(home)
            catalogue.merge_file(Path(home) / 'mixed-models.json')
            self._observe(home, 429)
            self.assertEqual(subscription_gate.blocked(home), {HELPER})
            self.assertNotIn(HELPER, _rows(home))
            self._observe(home, 200)
            self.assertEqual(subscription_gate.blocked(home), set())
            self.assertIn(HELPER, _rows(home))

    def test_a_hostile_response_never_raises(self):
        class Hostile:
            status = 429

            def getheaders(self):
                raise ValueError('no headers')

        with tempfile.TemporaryDirectory() as home:
            self._observe(home, 429, response=Hostile())
            self.assertEqual(subscription_gate.blocked(home), set())

    def test_a_login_with_nothing_blocked_never_outlives_the_turn(self):
        with tempfile.TemporaryDirectory() as home:
            subscription_gate.remember_login('openai', {'Authorization': 'bearer y'})
            self.assertIsNotNone(subscription_gate.login())
            self._observe(home, 200)
            self.assertIsNone(subscription_gate.login())
            self._observe(home, 429)
            subscription_gate.remember_login('openai', {'Authorization': 'bearer y'})
            self.assertIsNotNone(subscription_gate.login())


class _HomeCredentials:
    """Credential surface the handler reads: the gate needs the router home."""
    def __init__(self, home):
        self.home = home

    def key_for(self, provider_id=None):
        return 'test-key'


class HandlerEvidenceTests(unittest.TestCase):
    def _server(self, home):
        _state(home)
        state = {'port': 0, 'token': 'test-token',
                 'openai_models': list(SUBSCRIPTION_SLUGS),
                 'opencode_auth': _auth_file(self)}
        server = _start_server(state, credentials=_HomeCredentials(home))
        self.addCleanup(server.shutdown)
        return server

    def _turn(self, server, body):
        return _post(server.server_port, '/test-token/responses', body)

    def test_a_refused_subscription_turn_gates_the_slug(self):
        with tempfile.TemporaryDirectory() as home:
            server = self._server(home)
            catalogue.merge_file(Path(home) / 'mixed-models.json')
            install_fake(self, lambda: FakeUpstream(429, b'{}', []))
            self.assertEqual(
                self._turn(server, {'model': HELPER, 'input': []}).status, 503)
            self.assertEqual(subscription_gate.blocked(home), {HELPER})
            self.assertNotIn(HELPER, _rows(home))

    def test_a_served_subscription_turn_releases_the_slug(self):
        with tempfile.TemporaryDirectory() as home:
            server = self._server(home)
            catalogue.merge_file(Path(home) / 'mixed-models.json')
            now = time.time()
            subscription_gate.record(
                home, HELPER, ('block', 'refusal', now + 3600), now)
            install_fake(self, lambda: FakeUpstream(
                200, b'{"output": []}', [('Content-Type', 'application/json')]))
            self.assertEqual(
                self._turn(server, {'model': HELPER, 'input': []}).status, 200)
            self.assertEqual(subscription_gate.blocked(home), set())
            self.assertIn(HELPER, _rows(home))

    def test_an_external_refusal_leaves_the_gate_alone(self):
        with tempfile.TemporaryDirectory() as home:
            server = self._server(home)
            install_fake(self, lambda: FakeUpstream(429, b'{}', []))
            response = self._turn(server, {'model': 'z-ai/glm-5.3-flash',
                                           'input': []})
            self.assertEqual(response.status, 503)
            self.assertFalse(subscription_gate.path(home).exists())

    def test_an_auth_refusal_records_the_auth_source(self):
        with tempfile.TemporaryDirectory() as home:
            server = self._server(home)
            install_fake(self, lambda: FakeUpstream(401, b'{}', []))
            self._turn(server, {'model': HELPER, 'input': []})
            self.assertEqual(subscription_gate.read(home)[HELPER]['source'], 'auth')


if __name__ == '__main__':
    unittest.main()
