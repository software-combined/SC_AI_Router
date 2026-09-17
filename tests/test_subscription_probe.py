"""Subscription probe: the bounded four-hour recheck.

Protects the contract that the recheck cannot send anything without a login
the client presented, that its cadence and per-pass cap are fixed, that a
200 clears a blocked slug while a refusal or an auth answer keeps it, and
that an install without a subscription never probes at all.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path

from ai_router import subscription_gate, subscription_probe
from ai_router.subscription_roster import SUBSCRIPTION_SLUGS

HELPER = 'gpt-5.6-luna'


def _state(home, **extra):
    """Router state beside the picker file: every roster slug is a row."""
    doc = {'port': 0, 'token': 'test-token',
           'openai_models': list(SUBSCRIPTION_SLUGS)}
    doc.update(extra)
    Path(home, 'mixed-router-state.json').write_text(json.dumps(doc))


class RecheckTests(unittest.TestCase):
    def setUp(self):
        subscription_gate.forget_login()
        self.addCleanup(subscription_gate.forget_login)

    def _blocked(self, home, now):
        subscription_gate.record(home, HELPER, ('block', 'refusal', now + 60), now)

    def _answer(self, status):
        return lambda *args: (status, {})

    def test_due_waits_four_hours_and_caps_the_pass(self):
        now = time.time()
        fresh = {slug: {'probed': now - subscription_probe.PROBE_AGE_S + 1}
                 for slug in SUBSCRIPTION_SLUGS}
        self.assertEqual(subscription_probe.due(fresh, now), [])
        stale = {slug: {'probed': 0} for slug in SUBSCRIPTION_SLUGS}
        self.assertEqual(len(subscription_probe.due(stale, now)),
                         subscription_probe.PROBE_LIMIT)

    def test_no_login_skips_the_probe_and_notes_the_attempt(self):
        with tempfile.TemporaryDirectory() as home:
            now = time.time()
            self._blocked(home, now)
            sent = []
            self.assertEqual(
                subscription_probe.probe(home, HELPER, now,
                                         send=lambda *args: sent.append(args)),
                'skipped')
            self.assertEqual(sent, [])
            self.assertEqual(subscription_gate.read(home)[HELPER]['probed'], now)

    def test_probe_outcomes_update_the_gate(self):
        cases = ((200, 'ok', False), (429, 'refusal', True),
                 (401, 'auth', True), (500, 'unknown', True))
        for status, outcome, blocked_after in cases:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as home:
                now = time.time()
                self._blocked(home, now)
                subscription_gate.remember_login('openai', {'Authorization': 'b'})
                self.assertEqual(
                    subscription_probe.probe(home, HELPER, now,
                                             send=self._answer(status)),
                    outcome)
                self.assertEqual(bool(subscription_gate.blocked(home)), blocked_after)

    def test_a_dead_probe_keeps_the_block(self):
        with tempfile.TemporaryDirectory() as home:
            now = time.time()
            self._blocked(home, now)
            subscription_gate.remember_login('openai', {'Authorization': 'b'})

            def dead(*args):
                raise OSError('down')

            self.assertEqual(subscription_probe.probe(home, HELPER, now, send=dead),
                             'unknown')
            self.assertEqual(subscription_gate.blocked(home), {HELPER})

    def test_an_attempt_stamps_itself_even_when_the_expiry_holds(self):
        # Without the stamp the slug stays due and the next tick probes
        # again twenty minutes later instead of in four hours.
        with tempfile.TemporaryDirectory() as home:
            now = time.time()
            headers = {'x-codex-secondary-used-percent': '100',
                       'x-codex-secondary-resets-in-seconds': '3600'}
            change = subscription_gate.verdict(200, headers, now)
            subscription_gate.record(home, HELPER, change, now)
            same = ('block', 'headers', change[2])
            self.assertFalse(subscription_gate.record(home, HELPER, same, now + 60))
            self.assertTrue(subscription_gate.record(
                home, HELPER, same, now + 60, probed=now + 60))
            self.assertEqual(subscription_gate.read(home)[HELPER]['probed'], now + 60)

    def test_an_auth_answer_drops_the_login(self):
        # A refused login is dead or another account's: replaying it every
        # four hours would keep acting for a client that no longer signs in.
        with tempfile.TemporaryDirectory() as home:
            now = time.time()
            self._blocked(home, now)
            subscription_gate.remember_login('openai', {'Authorization': 'b'})
            self.assertEqual(
                subscription_probe.probe(home, HELPER, now, send=self._answer(401)),
                'auth')
            self.assertIsNone(subscription_gate.login())

    def test_expired_and_pinned_entries_are_never_probed(self):
        with tempfile.TemporaryDirectory() as home:
            now = time.time()
            subscription_gate.write(home, {
                HELPER: {'source': 'refusal', 'since': now, 'until': now + 60,
                         'probed': 0},
                'gpt-5.5': {'source': 'refusal', 'since': now - 7200,
                            'until': now - 60, 'probed': 0},
                'gpt-5.4-mini': {'source': 'refusal', 'since': now,
                                 'until': None, 'probed': 0}})
            subscription_gate.remember_login('openai', {'Authorization': 'b'})
            self.assertEqual(subscription_probe.recheck(home, now,
                                                       send=self._answer(200)),
                             [(HELPER, 'ok')])

    def test_the_probe_turn_is_minimal_and_uses_the_subscription_target(self):
        prepared = subscription_probe._prepared_probe(
            HELPER, {'Authorization': 'bearer y'})
        body = json.loads(prepared.body)
        self.assertEqual(prepared.provider, 'openai')
        self.assertTrue(prepared.path.endswith('/responses'))
        self.assertEqual(body['model'], HELPER)
        self.assertEqual(body['max_output_tokens'],
                         subscription_probe.PROBE_OUTPUT_TOKENS)
        self.assertNotIn('tools', body)
        self.assertEqual(prepared.headers.get('Authorization'), 'bearer y')

    def test_tick_honours_the_install_state(self):
        with tempfile.TemporaryDirectory() as home:
            now = time.time()
            self._blocked(home, now)
            _state(home, openai_mode='none')
            self.assertEqual(subscription_probe.tick(home, now), [])
            _state(home, subscription_probe=False)
            self.assertEqual(subscription_probe.tick(home, now), [])
            _state(home)
            self.assertEqual([slug for slug, _ in subscription_probe.tick(home, now)],
                             [HELPER])


if __name__ == '__main__':
    unittest.main()
