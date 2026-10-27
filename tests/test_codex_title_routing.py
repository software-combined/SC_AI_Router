"""Codex helper IDs select Luna without changing ordinary chat routing."""
import json
import unittest
from unittest import mock

from ai_router import availability, routed_models
from tests.fakes import FakeUpstream, install_fake
from tests.harness import auth_file, post, start_server, test_state, tmp_home

LUNA = 'openai/gpt-6-luna'
FABLE = 'anthropic/claude-fable-5.1'
ALIASES = {'gpt-6-luna', 'gpt-5.6-luna'}
ROUTED = {'X-SCG-Codex-Route': 'routed'}
HELPER = {'X-Codex-Turn-Metadata': json.dumps({'thread_source': 'thread_title'})}


class CodexTitleRoutingTests(unittest.TestCase):
    def _send(self, model, headers, **overrides):
        calls = install_fake(self, lambda: FakeUpstream(
            200, b'{"output": []}', [('Content-Type', 'application/json')]))
        state = test_state(auth_file(self))
        state.update(openai_models=list(ALIASES))
        state.update(overrides)
        server = start_server(state)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        response = post(server.server_port, '/test-token/responses',
                        {'model': model, 'input': []}, headers)
        raw = response.read()
        return response.status, calls, raw

    def test_routed_picker_supplies_hidden_current_and_legacy_luna_ids(self):
        home = tmp_home(self)
        self.assertTrue(routed_models.sync(home, {FABLE, LUNA}, None))
        rows = json.loads((home / routed_models.NAME).read_text())['models']
        aliases = {r['slug']: r for r in rows if r['slug'] in ALIASES}
        self.assertEqual(set(aliases), ALIASES)
        self.assertTrue(all(r['visibility'] == 'hide' for r in aliases.values()))
        self.assertEqual({r['slug'] for r in rows if r['visibility'] == 'list'},
                         {FABLE, LUNA})

    def test_hidden_aliases_follow_luna_availability_and_company_policy(self):
        home = tmp_home(self)
        for available, allowed in (({FABLE}, None), ({FABLE, LUNA}, [FABLE])):
            with self.subTest(available=available, allowed=allowed):
                self.assertTrue(routed_models.sync(home, available, allowed))
                rows = json.loads((home / routed_models.NAME).read_text())['models']
                self.assertFalse(ALIASES & {r['slug'] for r in rows})

    def test_switched_helpers_use_luna_even_after_client_fallback_to_fable(self):
        for model in (*sorted(ALIASES), FABLE):
            with self.subTest(model=model):
                status, calls, _ = self._send(model, {**ROUTED, **HELPER})
                self.assertEqual(status, 200)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][0], 'openrouter.ai')
                self.assertEqual(json.loads(calls[0][3])['model'], LUNA)

    def test_no_subscription_install_also_routes_titles_to_luna(self):
        status, calls, _ = self._send(FABLE, HELPER, openai_mode='none')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(calls[0][3])['model'], LUNA)

    def test_subscription_titles_keep_the_subscription_route(self):
        status, calls, _ = self._send('gpt-6-luna', HELPER)
        self.assertEqual(status, 200)
        self.assertEqual(calls[0][0], 'chatgpt.com')
        self.assertEqual(json.loads(calls[0][3])['model'], 'gpt-6-luna')

    def test_ordinary_chat_and_invalid_helper_metadata_keep_the_chosen_model(self):
        for meta in ({}, {'X-Codex-Turn-Metadata': 'invalid'},
                     {'X-Codex-Turn-Metadata': '{"thread_source":"user"}'},
                     {'X-Codex-Turn-Metadata': '{"turn_trigger":"thread_title"}'}):
            with self.subTest(meta=meta):
                status, calls, _ = self._send(FABLE, {**ROUTED, **meta})
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(calls[0][3])['model'], FABLE)

    def test_denied_luna_never_falls_back_to_fable_or_subscription(self):
        status, calls, _ = self._send(FABLE, {**ROUTED, **HELPER},
                                      allowed_models=[FABLE])
        self.assertEqual(status, 400)
        self.assertEqual(calls, [])

    def test_unavailable_luna_never_falls_back_to_fable_or_subscription(self):
        permitted = availability.permitted
        with mock.patch.object(availability, 'permitted',
                               side_effect=lambda model, **kw: model != LUNA and permitted(model, **kw)):
            status, calls, _ = self._send(FABLE, {**ROUTED, **HELPER})
        self.assertEqual(status, 400)
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
