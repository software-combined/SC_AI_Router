"""Claude Code without a Claude subscription: every request goes to OpenRouter.

Synthetic settings and listings only; never touches the operator's settings.
"""
import json
import tempfile
import unittest
from pathlib import Path

from tests.install_fixtures import install_mod

claude_config = install_mod._claude_config

SONNET = 'anthropic/claude-sonnet-5.5'
LISTING = {'data': [
    {'id': 'anthropic/claude-fable-5.1', 'anthropic_family_tier': 'fable'},
    {'id': 'anthropic/claude-haiku-5.5', 'anthropic_family_tier': 'haiku'},
    {'id': 'anthropic/claude-opus-5.5', 'anthropic_family_tier': 'opus'},
    {'id': SONNET, 'anthropic_family_tier': 'sonnet'},
    {'id': 'openai/gpt-6-luna', 'display_name': 'OpenAI: GPT-6 Luna · OpenRouter'},
    {'id': 'z-ai/glm-5.3-flash'}]}
# Settings in the shared writer's layout, so a detach must give back these bytes.
USER_SETTINGS = json.dumps({'theme': 'dark', 'env': {'KEEP': '1'}}, indent=2) + '\n'


def _state(mode='none'):
    return {'port': 1, 'token': 'test-token', 'openai_models': [], 'claude_mode': mode}


def _listing(*drop):
    return {'data': [row for row in LISTING['data'] if row.get('anthropic_family_tier') not in drop]}


class NoSubscriptionAttachTests(unittest.TestCase):
    def setUp(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = tmp / 'home'
        self.home.mkdir()
        self.path = tmp / 'settings.json'
        self.path.write_text(USER_SETTINGS)

    def attach(self, mode='none', listing=LISTING):
        install_mod.attach_claude(self.home, _state(mode), settings_path=self.path, listing=listing)
        return json.loads(self.path.read_text())['env']

    def receipt(self):
        return install_mod._codex_config.read_receipt(self.home)['clients']['claude']

    def test_attach_signs_in_to_nothing_and_names_only_listed_models(self):
        # Without these keys Claude Code asks for a Claude login, and a bare
        # tier word the router cannot route returns a 400.
        env = self.attach()
        self.assertEqual(env['ANTHROPIC_AUTH_TOKEN'], claude_config.AUTH_PLACEHOLDER)
        self.assertEqual(env['ANTHROPIC_MODEL'], 'openai/gpt-6-luna')
        self.assertEqual(env['CLAUDE_CODE_EFFORT_LEVEL'], 'max')
        for tier in ('opus', 'sonnet', 'haiku', 'fable'):
            self.assertIn(env['ANTHROPIC_DEFAULT_%s_MODEL' % tier.upper()],
                          {row['id'] for row in LISTING['data']})
        self.assertEqual(env['ANTHROPIC_DEFAULT_HAIKU_MODEL'], 'anthropic/claude-haiku-5.5')
        self.assertEqual(env['KEEP'], '1')
        self.assertEqual(set(self.receipt()['written']),
                         set(claude_config.OWNED_KEYS + claude_config.NONE_KEYS))

    def test_missing_tier_or_default_model_uses_the_sonnet_row(self):
        listing = _listing('haiku')
        listing['data'] = [row for row in listing['data'] if row['id'] != 'openai/gpt-6-luna']
        env = self.attach(listing=listing)
        self.assertEqual(env['ANTHROPIC_DEFAULT_HAIKU_MODEL'], SONNET)
        self.assertEqual(env['ANTHROPIC_MODEL'], SONNET)

    def test_no_sonnet_row_or_no_listing_refuses_before_writing(self):
        for listing in (_listing('sonnet'), None):
            with self.subTest(listing=listing):
                with self.assertRaises(SystemExit):
                    self.attach(listing=listing)
                self.assertEqual(self.path.read_text(), USER_SETTINGS)
                self.assertFalse((self.home / 'activation.json').exists())

    def test_update_replaces_a_model_id_this_installer_wrote(self):
        # A registry update renames rows; refusing our own old id would stop updates.
        self.attach()
        renamed = json.loads(json.dumps(LISTING).replace('claude-haiku-5.5', 'claude-haiku-5.6'))
        env = self.attach(listing=renamed)
        self.assertEqual(env['ANTHROPIC_DEFAULT_HAIKU_MODEL'], 'anthropic/claude-haiku-5.6')
        self.assertEqual(self.receipt()['written']['ANTHROPIC_DEFAULT_HAIKU_MODEL'],
                         'anthropic/claude-haiku-5.6')

    def test_hand_set_tier_key_refuses_before_any_write(self):
        self.path.write_text('{"env": {"ANTHROPIC_DEFAULT_HAIKU_MODEL": "my-proxy-haiku"}}')
        before = self.path.read_bytes()
        with self.assertRaisesRegex(SystemExit, 'ANTHROPIC_DEFAULT_HAIKU_MODEL'):
            self.attach()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((self.home / 'activation.json').exists())

    def test_subscription_choice_removes_keys_and_restores_an_earlier_value(self):
        # The person had set max effort themselves before the router came.
        self.path.write_text('{"env": {"CLAUDE_CODE_EFFORT_LEVEL": "max", "KEEP": "1"}}')
        self.attach()
        env = self.attach('subscription')
        self.assertEqual(env, {'KEEP': '1', 'CLAUDE_CODE_EFFORT_LEVEL': 'max',
                               **claude_config.desired_env(self.home, _state())})
        self.assertEqual(set(self.receipt()['written']), set(claude_config.OWNED_KEYS))
        install_mod.detach_claude(self.home, settings_path=self.path)
        self.assertEqual(json.loads(self.path.read_text()),
                         {'env': {'CLAUDE_CODE_EFFORT_LEVEL': 'max', 'KEEP': '1'}})

    def test_subscription_choice_keeps_a_value_changed_by_hand(self):
        self.attach()
        doc = json.loads(self.path.read_text())
        doc['env']['ANTHROPIC_MODEL'] = 'opus'
        self.path.write_text(json.dumps(doc))
        self.assertEqual(self.attach('subscription')['ANTHROPIC_MODEL'], 'opus')

    def test_detach_after_none_mode_restores_bytes(self):
        self.attach()
        self.attach()  # an update keeps the original pre-attach values
        install_mod.detach_claude(self.home, settings_path=self.path)
        self.assertEqual(self.path.read_text(), USER_SETTINGS)
        self.assertFalse((self.home / 'activation.json').exists())

    def test_removed_base_url_never_records_router_values_as_originals(self):
        # Removing the base URL by hand made the next attach save the placeholder
        # token and model overrides as the person's own, so a later subscription
        # choice kept them and the real Claude login failed.
        self.attach()
        doc = json.loads(self.path.read_text())
        del doc['env']['ANTHROPIC_BASE_URL']
        self.path.write_text(json.dumps(doc, indent=2) + '\n')
        self.attach()
        env = self.attach('subscription')
        self.assertFalse(set(env) & set(claude_config.NONE_KEYS))
        install_mod.detach_claude(self.home, settings_path=self.path)
        self.assertEqual(self.path.read_text(), USER_SETTINGS)

    def test_unknown_written_key_still_reports_a_damaged_receipt(self):
        self.attach()
        receipt = json.loads((self.home / 'activation.json').read_text())
        receipt['clients']['claude']['written']['ANTHROPIC_API_KEY'] = 'x'
        (self.home / 'activation.json').write_text(json.dumps(receipt))
        with self.assertRaisesRegex(SystemExit, 'damaged_receipt'):
            install_mod.detach_claude(self.home, settings_path=self.path)
        self.assertIn('ANTHROPIC_AUTH_TOKEN', json.loads(self.path.read_text())['env'])


if __name__ == '__main__':
    unittest.main()
