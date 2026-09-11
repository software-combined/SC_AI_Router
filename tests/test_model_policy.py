"""Plan 068 Step 0: per-portco model allowlists as resolved data.

Two synthetic policies over one registry: the picker shows only the
allowed subset, routing rejects a disallowed OpenRouter slug with the
existing closed error, and subscription rows are unaffected in both.
Absent policy on a never-provisioned install equals today's output.
"""
import os
import unittest
from unittest import mock
from ai_router.catalogue import merge
from ai_router import providers
from ai_router import model_policy

ALLOWED = ('z-ai/glm-5.3-flash', 'moonshotai/kimi-k3')

needs_posix = unittest.skipIf(os.name == 'nt', 'POSIX permission bits only')


class ModelPolicyTests(unittest.TestCase):
    def test_picker_shows_only_allowed_subset(self):
        full = {m['slug'] for m in merge({'models': []})['models']}
        subset = {m['slug'] for m in
                  merge({'models': []}, allowed=ALLOWED)['models']}
        self.assertIn('z-ai/glm-5.3-flash', subset)
        self.assertIn('moonshotai/kimi-k3', subset)
        self.assertNotIn('meta/muse-spark-1.3', subset)
        self.assertTrue(subset < full)

    def test_absent_policy_equals_today(self):
        self.assertEqual(merge({'models': []}, allowed=None),
                         merge({'models': []}))

    def test_routing_rejects_disallowed_openrouter_slug(self):
        with self.assertRaisesRegex(ValueError, 'not in the configured catalog'):
            providers.select('meta/muse-spark-1.3', '/responses', (),
                             'subscription', allowed=ALLOWED)

    def test_disallowed_reject_leaks_no_candidate(self):
        # The near-miss hint must not disclose a slug the portco policy
        # excludes: a bare id for an allowlisted-out tilde row rejects
        # with an empty candidate list.
        from ai_router.errors import UnknownModel
        with self.assertRaises(UnknownModel) as caught:
            providers.select('anthropic/claude-opus-latest', '/responses', (),
                             'subscription', allowed=ALLOWED)
        self.assertEqual(caught.exception.candidates, ())
        self.assertIn('not in the configured catalog',
                      str(caught.exception))

    def test_allowed_openrouter_slug_still_routes(self):
        provider = providers.select('z-ai/glm-5.3-flash', '/responses', (),
                                    'subscription', allowed=ALLOWED)
        self.assertIsInstance(provider, providers.ExternalResponsesProvider)

    def test_subscription_rows_unaffected(self):
        subset = {m['slug'] for m in merge(
            {'models': []}, roster=('gpt-6-astra',), allowed=ALLOWED)['models']}
        self.assertIn('gpt-6-astra', subset)
        provider = providers.select('gpt-6-astra', '/responses',
                                    ('gpt-6-astra',), 'subscription',
                                    allowed=ALLOWED)
        self.assertIsInstance(provider, providers.SubscriptionProvider)

    def test_loader_absent_means_no_policy(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(model_policy.load(Path(tmp)),
                             (None, None, None))

    def test_loader_reads_valid_policy(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'model-policy.json').write_text(json.dumps(
                {'portco': 'acme', 'department': None,
                 'allowed_models': list(ALLOWED), 'version': 3}))
            (home / 'model-policy.json').chmod(0o600)
            self.assertEqual(model_policy.load(home),
                             ('acme', None, ALLOWED))

    def test_loader_malformed_keeps_last_good(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'model-policy.json').write_text('not json{')
            self.assertEqual(model_policy.load(home)[2], ())

    def test_loader_malformed_fails_closed(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'model-policy.json').write_text('{"portco": 7}')
            self.assertEqual(model_policy.load(home)[2], ())

    @needs_posix
    def test_loader_rejects_group_readable_file(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'model-policy.json').write_text(json.dumps(
                {'portco': 'acme', 'department': None,
                 'allowed_models': list(ALLOWED)}))
            (home / 'model-policy.json').chmod(0o640)
            self.assertEqual(model_policy.load(home)[2], ())

    def test_loader_windows_widened_acl_is_refused(self):
        import json
        import tempfile
        from pathlib import Path
        import ai_router.model_policy as policy_mod
        import ai_router.winacl as winacl_mod
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'model-policy.json').write_text(json.dumps(
                {'portco': 'acme', 'department': None,
                 'allowed_models': list(ALLOWED)}))
            with mock.patch.object(policy_mod, '_ON_WINDOWS', True), \
                    mock.patch.object(winacl_mod, 'check',
                                      side_effect=SystemExit('readable by X')):
                self.assertEqual(model_policy.load(home)[2], ())

    def test_unknown_policy_slug_ignored_not_fatal(self):
        merged = merge({'models': []},
                       allowed=ALLOWED + ('no/such-model',))
        slugs = {m['slug'] for m in merged['models']}
        self.assertIn('z-ai/glm-5.3-flash', slugs)
        self.assertNotIn('no/such-model', slugs)

    def test_department_subset_invariant(self):
        # Synthetic grant rows: a department list must stay within its
        # portco list; the machine enforces the resolved list only.
        portco = ['z-ai/glm-5.3-flash', 'moonshotai/kimi-k3']
        department = ['z-ai/glm-5.3-flash', 'meta/muse-spark-1.3']
        self.assertTrue(set(department) - set(portco))
        merged = merge({'models': []}, allowed=tuple(portco))['models']
        slugs = {m['slug'] for m in merged}
        self.assertIn('z-ai/glm-5.3-flash', slugs)
        self.assertNotIn('meta/muse-spark-1.3', slugs)

    def test_load_state_carries_allowed_models(self):
        import json
        import tempfile
        from pathlib import Path
        from ai_router.runtime import load_state
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            auth = home / 'auth.json'
            auth.write_text(json.dumps(
                {'openrouter': {'type': 'api', 'key': 'k'}}))
            state_path = home / 'mixed-router-state.json'
            state_path.write_text(json.dumps(
                {'port': 0, 'token': 't', 'openai_models': [],
                 'opencode_auth': str(auth)}))
            policy = home / 'model-policy.json'
            policy.write_text(json.dumps(
                {'portco': 'acme', 'department': None,
                 'allowed_models': list(ALLOWED)}))
            policy.chmod(0o600)
            state = load_state(state_path)
            self.assertEqual(state['allowed_models'], list(ALLOWED))
            policy.unlink()
            plain = load_state(state_path)
            self.assertNotIn('allowed_models', plain)

    def test_protocol_threading_rejects_disallowed_model(self):
        from ai_router.protocols import responses, messages
        state = {'openai_models': ['gpt-6-astra'],
                 'allowed_models': list(ALLOWED)}
        with self.assertRaisesRegex(ValueError, 'not in the configured catalog'):
            responses.POLICY.select_provider(
                'meta/muse-spark-1.3', '/responses', state, 'subscription')
        provider = responses.POLICY.select_provider(
            'z-ai/glm-5.3-flash', '/responses', state, 'subscription')
        self.assertIsInstance(provider, providers.ExternalResponsesProvider)
        provider = responses.POLICY.select_provider(
            'gpt-6-astra', '/responses', state, 'subscription')
        self.assertIsInstance(provider, providers.SubscriptionProvider)
        # Unknown Claude ids stay subscription passthrough (unalias leaves
        # them untouched); a known alias for a disallowed slug rejects.
        provider = messages.POLICY.select_provider(
            'claude/moonshotai/kimi-k3-x', '/v1/messages', state,
            'subscription')
        self.assertEqual(provider.name, 'anthropic')
        with self.assertRaisesRegex(ValueError, 'not in the configured catalog'):
            messages.POLICY.select_provider(
                'claude/meta/muse-spark-1.3', '/v1/messages', state,
                'subscription')

    def test_allowed_flag_round_trips_through_cli(self):
        import json
        import subprocess
        import sys
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'catalogue.json'
            target.write_text('{"models": []}')
            result = subprocess.run(
                [sys.executable, '-m', 'ai_router.catalogue',
                 '--allowed', ','.join(ALLOWED), '--merge', str(target)],
                capture_output=True, text=True, cwd=str(Path('.').resolve()))
            self.assertEqual(result.returncode, 0, result.stderr)
            slugs = {m['slug'] for m in
                     json.loads(target.read_text())['models']}
            self.assertIn('z-ai/glm-5.3-flash', slugs)
            self.assertNotIn('meta/muse-spark-1.3', slugs)
            check = subprocess.run(
                [sys.executable, '-m', 'ai_router.catalogue',
                 '--allowed', ','.join(ALLOWED), '--check', str(target)],
                capture_output=True, text=True, cwd=str(Path('.').resolve()))
            self.assertEqual(check.returncode, 0, check.stderr + check.stdout)


if __name__ == '__main__':
    unittest.main()
