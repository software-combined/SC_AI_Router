"""Subscription picker gate: state, verdicts, login memory, picker rows.

Protects the contract that a refused ChatGPT subscription slug leaves the
Codex picker while its OpenRouter twins stay, that only the allowlisted
evidence moves the gate, that a malformed or hostile document can never
block a row, and that the login the recheck needs stays in memory.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from ai_router import catalogue, subscription_gate
from ai_router.subscription_roster import SUBSCRIPTION_SLUGS

HELPER = 'gpt-5.6-luna'
TWIN = 'openai/gpt-5.6-luna'
PERCENT = 'x-codex-primary-used-percent'


def _state(home, **extra):
    """Router state beside the picker file: every roster slug is a row."""
    doc = {'port': 0, 'token': 'test-token',
           'openai_models': list(SUBSCRIPTION_SLUGS)}
    doc.update(extra)
    Path(home, 'mixed-router-state.json').write_text(json.dumps(doc))


def _rows(home):
    doc = json.loads(Path(home, 'mixed-models.json').read_text())
    return {row['slug'] for row in doc['models']}


class GateStateTests(unittest.TestCase):
    def test_refusal_blocks_and_clear_releases_the_slug(self):
        with tempfile.TemporaryDirectory() as home:
            now = time.time()
            self.assertTrue(subscription_gate.record(
                home, HELPER, ('block', 'refusal', now + 60), now))
            self.assertEqual(subscription_gate.blocked(home), {HELPER})
            self.assertEqual(subscription_gate.blocked(home, now + 61), set())
            self.assertTrue(subscription_gate.record(
                home, HELPER, subscription_gate.CLEAR, now))
            self.assertFalse(subscription_gate.record(
                home, HELPER, subscription_gate.CLEAR, now))

    def test_foreign_slugs_and_malformed_documents_never_block(self):
        with tempfile.TemporaryDirectory() as home:
            document = subscription_gate.path(home)
            document.write_text('not json')
            self.assertEqual(subscription_gate.read(home), {})
            self.assertEqual(subscription_gate.blocked(home), set())
            document.write_text(json.dumps({
                'z-ai/glm-5.3': {'source': 'refusal', 'since': 1, 'until': None},
                HELPER: {'source': 'nonsense'},
                'gpt-5.5': ['wrong shape'],
                'gpt-5.4-mini': {'source': 'headers', 'since': 'soon'}}))
            # A well-formed entry for a slug the gate does not own is kept;
            # only the roster decides what the gate may hide.
            self.assertEqual(list(subscription_gate.read(home)), ['z-ai/glm-5.3'])
            self.assertEqual(subscription_gate.blocked(home), set())
            document.write_text(json.dumps([1, 2]))
            self.assertEqual(subscription_gate.blocked(home), set())

    def test_a_busy_session_does_not_rewrite_the_gate_every_turn(self):
        with tempfile.TemporaryDirectory() as home:
            now = time.time()
            self.assertTrue(subscription_gate.record(
                home, HELPER, ('block', 'refusal', now + 3600), now))
            # Same source, comfortably in the future: nothing worth a write.
            self.assertFalse(subscription_gate.record(
                home, HELPER, ('block', 'refusal', now + 3660), now + 60))
            # Well spent: the refreshed expiry lands.
            late = now + 3600
            self.assertTrue(subscription_gate.record(
                home, HELPER, ('block', 'refusal', late + 3600), late))

    def test_a_new_source_always_lands(self):
        with tempfile.TemporaryDirectory() as home:
            now = time.time()
            subscription_gate.record(
                home, HELPER, ('block', 'refusal', now + 3600), now)
            self.assertTrue(subscription_gate.record(
                home, HELPER, ('block', 'auth', now + 3600), now + 1))
            self.assertEqual(subscription_gate.read(home)[HELPER]['source'], 'auth')

    def test_an_unwritable_home_never_raises(self):
        with tempfile.TemporaryDirectory() as home:
            with mock.patch.object(subscription_gate, 'replace_json',
                                   side_effect=OSError('read only')):
                self.assertFalse(subscription_gate.record(
                    home, HELPER, ('block', 'refusal', time.time() + 60),
                    time.time()))
            self.assertEqual(subscription_gate.blocked(home), set())


class VerdictTests(unittest.TestCase):
    def test_status_decides_when_no_usage_header_is_present(self):
        now = time.time()
        self.assertEqual(subscription_gate.verdict(429, {}, now)[0:2],
                         ('block', 'refusal'))
        for status in (401, 403):
            with self.subTest(status=status):
                self.assertEqual(subscription_gate.verdict(status, {}, now)[0:2],
                                 ('block', 'auth'))
        self.assertEqual(subscription_gate.verdict(200, {}, now),
                         subscription_gate.CLEAR)
        for status in (400, 404, 500, 502):
            with self.subTest(status=status):
                self.assertIsNone(subscription_gate.verdict(status, {}, now))

    def test_a_spent_window_blocks_until_its_reported_reset(self):
        now = time.time()
        headers = {'x-codex-primary-used-percent': '100',
                   'x-codex-primary-resets-in-seconds': '1800',
                   'x-codex-secondary-used-percent': '42.5'}
        kind, source, until = subscription_gate.verdict(200, headers, now)
        self.assertEqual((kind, source), ('block', 'headers'))
        self.assertAlmostEqual(until, now + 1800, delta=1)
        self.assertEqual(subscription_gate.verdict(429, headers, now)[2], until)

    def test_headroom_and_junk_values_clear_or_ignore(self):
        now = time.time()
        headroom = {'x-codex-primary-used-percent': '99.9',
                    'x-codex-secondary-used-percent': '0'}
        self.assertEqual(subscription_gate.verdict(200, headroom, now),
                         subscription_gate.CLEAR)
        self.assertEqual(subscription_gate.verdict(429, headroom, now)[0:2],
                         ('block', 'refusal'))
        for junk in ('nonsense', '-1', '', None):
            with self.subTest(junk=junk):
                self.assertEqual(subscription_gate.verdict(200, {PERCENT: junk}, now),
                                 subscription_gate.CLEAR)
        self.assertEqual(subscription_gate.verdict(500, {PERCENT: '150%'}, now)[0:2],
                         ('block', 'headers'))

    def test_a_spent_window_is_capped_or_bounded_by_a_refusal(self):
        now = time.time()
        spent = 'x-codex-secondary-used-percent'
        headers = {spent: '100', 'x-codex-secondary-resets-in-seconds': '99999999'}
        self.assertEqual(subscription_gate.verdict(200, headers, now),
                         ('block', 'headers', now + subscription_gate.RESET_CAP_S))
        huge = {'x-codex-secondary-used-percent': '100',
                'x-codex-secondary-resets-in-seconds': '99999999999'}
        self.assertEqual(subscription_gate.verdict(200, huge, now),
                         ('block', 'headers', now + subscription_gate.REFUSAL_TTL_S))
        self.assertEqual(subscription_gate.verdict(
            200, {spent: '100'}, now),
            ('block', 'headers', now + subscription_gate.REFUSAL_TTL_S))


class LoginMemoryTests(unittest.TestCase):
    def setUp(self):
        subscription_gate.forget_login()
        self.addCleanup(subscription_gate.forget_login)

    def test_only_the_subscription_login_is_kept_and_hop_headers_drop(self):
        subscription_gate.remember_login('openrouter', {'Authorization': 'bearer x'})
        self.assertIsNone(subscription_gate.login())
        subscription_gate.remember_login(
            'openai', {'Authorization': 'bearer y', 'Host': 'loopback',
                       'Cookie': 'session=1', 'chatgpt-account-id': 'acct'})
        self.assertEqual(subscription_gate.login(),
                         {'Authorization': 'bearer y',
                          'chatgpt-account-id': 'acct'})
        subscription_gate.login()['Authorization'] = 'mutated'
        self.assertEqual(subscription_gate.login()['Authorization'], 'bearer y')

    def test_the_login_lives_only_while_a_slug_is_blocked(self):
        with tempfile.TemporaryDirectory() as home:
            now = time.time()
            subscription_gate.record(
                home, HELPER, ('block', 'refusal', now + 60), now)
            subscription_gate.remember_login('openai', {'Authorization': 'bearer y'})
            self.assertIsNotNone(subscription_gate.login())
            subscription_gate.record(home, HELPER, subscription_gate.CLEAR, now)
            self.assertIsNone(subscription_gate.login())


class PickerRowTests(unittest.TestCase):
    def test_a_blocked_row_leaves_the_picker_and_comes_back(self):
        with tempfile.TemporaryDirectory() as home:
            _state(home)
            picker = Path(home) / 'mixed-models.json'
            catalogue.merge_file(picker)
            rows = _rows(home)
            self.assertIn(HELPER, rows)
            # The twin waits for the subscription row to be refused.
            self.assertNotIn(TWIN, rows)
            now = time.time()
            subscription_gate.record(
                home, HELPER, ('block', 'refusal', now + 3600), now)
            catalogue.merge_file(picker)
            rows = _rows(home)
            self.assertNotIn(HELPER, rows)
            self.assertIn(TWIN, rows)
            self.assertIn('gpt-5.3-codex-spark', rows)
            # The verification path agrees with the merge it checks.
            self.assertTrue(catalogue.check(picker))
            subscription_gate.record(home, HELPER, subscription_gate.CLEAR, now)
            catalogue.merge_file(picker)
            rows = _rows(home)
            self.assertIn(HELPER, rows)
            self.assertNotIn(TWIN, rows)
            self.assertTrue(catalogue.check(picker))

    def test_the_merge_hides_only_the_blocked_roster_rows(self):
        merged = catalogue.merge({'models': []}, roster=(HELPER,),
                                 blocked=frozenset({HELPER}))
        slugs = {row['slug'] for row in merged['models']}
        self.assertNotIn(HELPER, slugs)
        self.assertIn(TWIN, slugs)
        merged = catalogue.merge({'models': []}, roster=(HELPER,))
        self.assertIn(HELPER, {row['slug'] for row in merged['models']})

    def test_a_carried_row_outside_the_roster_is_never_dropped(self):
        # Only a roster row can be restored, so only a roster row is gated:
        # dropping a row the roster no longer names loses it for good.
        with tempfile.TemporaryDirectory() as home:
            picker = Path(home) / 'mixed-models.json'
            picker.write_text(json.dumps({'models': [
                catalogue.subscription_stub(HELPER),
                catalogue.subscription_stub('gpt-5.5')]}))
            _state(home, openai_models=[HELPER])
            now = time.time()
            subscription_gate.record(
                home, 'gpt-5.5', ('block', 'refusal', now + 3600), now)
            catalogue.merge_file(picker)
            self.assertIn('gpt-5.5', _rows(home))
            self.assertIn(HELPER, _rows(home))
            subscription_gate.record(home, 'gpt-5.5', subscription_gate.CLEAR, now)
            catalogue.merge_file(picker)
            self.assertIn('gpt-5.5', _rows(home))

    def test_an_expired_block_restores_the_row_at_the_next_merge(self):
        with tempfile.TemporaryDirectory() as home:
            _state(home)
            picker = Path(home) / 'mixed-models.json'
            catalogue.merge_file(picker)
            now = time.time()
            subscription_gate.record(
                home, HELPER, ('block', 'refusal', now + 60), now)
            catalogue.merge_file(picker)
            self.assertNotIn(HELPER, _rows(home))
            with mock.patch.object(subscription_gate.time, 'time',
                                   return_value=now + 61):
                catalogue.merge_file(picker)
            self.assertIn(HELPER, _rows(home))


if __name__ == '__main__':
    unittest.main()
