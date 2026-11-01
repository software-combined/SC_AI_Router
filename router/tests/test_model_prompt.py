"""Effective client visibility behind the new-model prompt (Plan 135).

The prompt must list exactly the rows the current policy scope would show
after a restart: nothing outside the allowlist, nothing unverified, and a
rejected policy announces nothing at all.
"""
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from ai_router import catalogue, model_prompt, provider_defs
from ai_router.clients import models_for
from ai_router.registry import MODELS, by_slug
from tests._platform import unix_only

ALLOWED = ('z-ai/glm-5.3-flash', 'moonshotai/kimi-k3.1-pro')
EXTRA = 'openrouter/acme-test-model'


def _write_policy(home, allowed, portco='acme', department=None):
    path = Path(home) / 'model-policy.json'
    path.write_text(json.dumps({'portco': portco, 'department': department,
                                'allowed_models': list(allowed)}))
    path.chmod(0o600)
    return path


def _with_extra(*slugs):
    """Registry rows plus one synthetic visible row per slug."""
    added = tuple(replace(by_slug('z-ai/glm-5.3-flash'), slug=slug,
                          display_name='Acme: Test Model · OpenRouter')
                  for slug in (slugs or (EXTRA,)))
    return tuple(MODELS) + added


class VisibleModelsTests(unittest.TestCase):
    def test_absent_policy_lists_every_codex_visible_external_row(self):
        expected = {m.slug for m in models_for(MODELS, 'codex')
                    if provider_defs.is_external(m.provider)}
        with tempfile.TemporaryDirectory() as tmp:
            rows = model_prompt.visible_models(tmp)
        self.assertEqual({slug for slug, _ in rows}, expected)
        self.assertEqual(len(rows), len(expected))  # no duplicate slugs

    def test_allowlist_limits_the_list_to_allowed_slugs(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_policy(tmp, ALLOWED)
            rows = model_prompt.visible_models(tmp)
        self.assertEqual({slug for slug, _ in rows}, set(ALLOWED))

    def test_first_occurrence_order_matches_the_registry(self):
        external = [m.slug for m in MODELS
                    if provider_defs.is_external(m.provider) and m.listed]
        with tempfile.TemporaryDirectory() as tmp:
            rows = model_prompt.visible_models(tmp)
        self.assertEqual([slug for slug, _ in rows], external)

    def test_slug_set_matches_the_catalogue_merge_projection(self):
        # The prompt must announce exactly what the restarted client's
        # catalogue would list for the same policy, including the empty
        # set when the policy allows only subscription rows.
        for allowed in (None, ALLOWED, ('gpt-6-astra',), ()):
            with self.subTest(allowed=allowed), \
                    tempfile.TemporaryDirectory() as tmp:
                if allowed is not None:
                    _write_policy(tmp, allowed)
                merged = catalogue.merge({'models': []}, allowed=allowed)
                self.assertEqual(
                    {slug for slug, _ in model_prompt.visible_models(tmp)},
                    {m['slug'] for m in merged['models']})

    def test_rejected_policy_announces_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'model-policy.json').write_text('not json{')
            self.assertEqual(model_prompt.visible_models(tmp), [])

    def test_unlisted_row_is_never_visible(self):
        target = by_slug('moonshotai/kimi-k3.1-pro')
        rows = tuple(replace(m, listed=False) if m.slug == target.slug else m
                     for m in MODELS)
        with mock.patch.object(catalogue, 'MODELS', rows), \
                tempfile.TemporaryDirectory() as tmp:
            slugs = [slug for slug, _ in model_prompt.visible_models(tmp)]
        self.assertNotIn(target.slug, slugs)
        self.assertIn('z-ai/glm-5.3-flash', slugs)

    def test_picker_labels_come_from_the_registry_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = dict(model_prompt.visible_models(tmp))
        self.assertEqual(rows['z-ai/glm-5.3-flash'],
                         catalogue.catalog_name(by_slug('z-ai/glm-5.3-flash')))
        self.assertNotIn(' · OpenRouter', rows['z-ai/glm-5.3-flash'])

    def test_unknown_client_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                model_prompt.visible_models(tmp, client='claude')


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / 'home'
        self.home.mkdir()

    def _snapshot(self):
        return json.loads((self.home / 'model-prompt.json').read_text())

    def test_first_run_seeds_silently(self):
        self.assertEqual(model_prompt.pending(self.home), [])
        self.assertEqual(self._snapshot()['scope'], 'none')
        self.assertEqual(self._snapshot()['client'], 'codex')
        self.assertEqual(self._snapshot()['seen'],
                         [slug for slug, _ in model_prompt.visible_models(self.home)])
        self.assertEqual(model_prompt.pending(self.home), [])

    def test_added_row_is_pending_then_silent_after_acknowledge(self):
        model_prompt.pending(self.home)  # seed
        with mock.patch.object(catalogue, 'MODELS', _with_extra()):
            shown = model_prompt.pending(self.home)
            self.assertEqual(shown, [(EXTRA, 'Acme: Test Model')])
            acked = model_prompt.acknowledge(self.home)
            self.assertEqual(acked, shown)
            self.assertEqual(model_prompt.pending(self.home), [])

    def test_rejected_policy_returns_empty_and_writes_nothing(self):
        (self.home / 'model-policy.json').write_text('not json{')
        self.assertEqual(model_prompt.pending(self.home), [])
        self.assertEqual(model_prompt.acknowledge(self.home), [])
        self.assertFalse((self.home / 'model-prompt.json').exists())

    def test_scope_change_reseeds_silently(self):
        _write_policy(self.home, ALLOWED, portco='acme')
        self.assertEqual(model_prompt.pending(self.home), [])
        self.assertEqual(set(self._snapshot()['seen']), set(ALLOWED))
        _write_policy(self.home, ALLOWED, portco='other', department='sales')
        self.assertEqual(model_prompt.pending(self.home), [])
        self.assertEqual(self._snapshot()['scope'], 'other/sales')
        self.assertTrue(self._snapshot()['seen'])

    def test_unusable_snapshot_reseeds_silently(self):
        (self.home / 'model-prompt.json').write_text('{broken')
        self.assertEqual(model_prompt.pending(self.home), [])
        self.assertEqual(self._snapshot()['seen'],
                         [slug for slug, _ in model_prompt.visible_models(self.home)])

    def test_seen_never_keeps_out_of_policy_slugs(self):
        _write_policy(self.home, ALLOWED)
        model_prompt.pending(self.home)
        _write_policy(self.home, (ALLOWED[0],))
        model_prompt.acknowledge(self.home)
        self.assertEqual(self._snapshot()['seen'], [ALLOWED[0]])
        # Widening again announces the row the narrowed policy dropped.
        _write_policy(self.home, ALLOWED)
        self.assertEqual({slug for slug, _ in model_prompt.pending(self.home)},
                         set(ALLOWED) - {ALLOWED[0]})

    def test_empty_allowlist_scope_seeds_and_a_later_grant_announces(self):
        _write_policy(self.home, ())
        self.assertEqual(model_prompt.pending(self.home), [])
        self.assertEqual(self._snapshot(),
                         {'scope': 'acme/-', 'client': 'codex', 'seen': []})
        _write_policy(self.home, ALLOWED)
        self.assertEqual({slug for slug, _ in model_prompt.pending(self.home)},
                         set(ALLOWED))

    def test_missing_home_announces_nothing(self):
        missing = Path(self._tmp.name) / 'missing'
        self.assertEqual(model_prompt.pending(missing), [])
        self.assertEqual(model_prompt.acknowledge(missing), [])

    @unix_only
    def test_broken_policy_symlink_is_rejected_not_unfiltered(self):
        (self.home / 'model-policy.json').symlink_to(
            Path(self._tmp.name) / 'missing.json')
        self.assertEqual(model_prompt.visible_models(self.home), [])
        self.assertEqual(model_prompt.pending(self.home), [])
        self.assertFalse((self.home / 'model-prompt.json').exists())

    @unix_only
    def test_readable_policy_symlink_still_filters(self):
        target = _write_policy(self._tmp.name, ALLOWED)
        (self.home / 'model-policy.json').symlink_to(target)
        self.assertEqual({slug for slug, _ in model_prompt.visible_models(self.home)},
                         set(ALLOWED))


class NoticeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / 'home'
        self.home.mkdir()

    def _doc(self):
        return json.loads((self.home / 'model-prompt.json').read_text())

    def test_notice_mints_only_while_rows_are_pending(self):
        self.assertEqual(model_prompt.notice(self.home), (None, []))  # seeds
        with mock.patch.object(catalogue, 'MODELS', _with_extra()):
            nonce, rows = model_prompt.notice(self.home)
            self.assertTrue(nonce)
            self.assertEqual([slug for slug, _ in rows], [EXTRA])
            # A second trigger reuses the live nonce and never marks seen.
            again, rows2 = model_prompt.notice(self.home)
        self.assertEqual(again, nonce)
        self.assertEqual(rows2, rows)
        self.assertNotIn(EXTRA, self._doc()['seen'])

    def test_expired_notice_is_replaced_and_check_enforces_expiry(self):
        model_prompt.pending(self.home)
        ttl = model_prompt.NOTICE_TTL_S
        with mock.patch.object(catalogue, 'MODELS', _with_extra()):
            nonce, _ = model_prompt.notice(self.home, now=1000.0)
            self.assertIsNotNone(
                model_prompt.check_notice(self.home, 'codex', nonce, now=1000.0))
            self.assertIsNone(model_prompt.check_notice(
                self.home, 'codex', nonce, now=1000.0 + ttl + 1))
            replaced, _ = model_prompt.notice(self.home, now=1000.0 + ttl + 1)
        self.assertNotEqual(replaced, nonce)
        self.assertEqual(self._doc()['notice']['expires'], 1000.0 + 2 * ttl + 1)

    def test_check_notice_refuses_wrong_and_missing_nonce(self):
        model_prompt.pending(self.home)
        with mock.patch.object(catalogue, 'MODELS', _with_extra()):
            nonce, _ = model_prompt.notice(self.home)
            self.assertIsNone(model_prompt.check_notice(self.home, 'codex', 'wrong'))
            self.assertIsNone(model_prompt.check_notice(self.home, 'codex', ''))
            self.assertIsNone(model_prompt.check_notice(self.home, 'codex', None))
            self.assertIsNone(model_prompt.check_notice(self.home, 'codex', 'n\u00ff'))
            self.assertIsNotNone(model_prompt.check_notice(self.home, 'codex', nonce))

    @unix_only
    def test_notice_without_a_writable_home_returns_nothing(self):
        model_prompt.pending(self.home)  # seed so rows are pending below
        with mock.patch.object(catalogue, 'MODELS', _with_extra()):
            self.addCleanup(self.home.chmod, 0o700)
            self.home.chmod(0o500)
            self.assertEqual(model_prompt.notice(self.home), (None, []))

    def test_acknowledge_uses_the_displayed_set_and_consumes_the_notice(self):
        model_prompt.pending(self.home)
        with mock.patch.object(catalogue, 'MODELS', _with_extra()):
            nonce, _ = model_prompt.notice(self.home)
            shown = model_prompt.acknowledge(self.home, displayed=[EXTRA])
        self.assertEqual([slug for slug, _ in shown], [EXTRA])
        self.assertIn(EXTRA, self._doc()['seen'])
        self.assertNotIn('notice', self._doc())  # single use
        with mock.patch.object(catalogue, 'MODELS', _with_extra()):
            self.assertIsNone(model_prompt.check_notice(self.home, 'codex', nonce))

    def test_acknowledge_displayed_ignores_rows_that_are_not_visible(self):
        model_prompt.pending(self.home)
        with mock.patch.object(catalogue, 'MODELS', _with_extra()):
            model_prompt.notice(self.home)
            shown = model_prompt.acknowledge(
                self.home, displayed=[EXTRA, 'not/a-registry-row'])
        self.assertEqual([slug for slug, _ in shown], [EXTRA])
        self.assertNotIn('not/a-registry-row', self._doc()['seen'])

    def test_acknowledge_displayed_ignores_a_row_added_after_the_render(self):
        second = 'openrouter/acme-second-model'
        model_prompt.pending(self.home)  # seed the real rows
        with mock.patch.object(catalogue, 'MODELS', _with_extra()):
            _nonce, rows = model_prompt.notice(self.home)
        self.assertEqual([slug for slug, _ in rows], [EXTRA])
        # The second model appears between the page render and the click.
        with mock.patch.object(catalogue, 'MODELS', _with_extra(EXTRA, second)):
            shown = model_prompt.acknowledge(self.home, displayed=[EXTRA])
            acked = [s for s in self._doc()['seen'] if s.startswith('openrouter/acme')]
            still_pending = [slug for slug, _ in model_prompt.pending(self.home)]
        self.assertEqual([slug for slug, _ in shown], [EXTRA])
        self.assertEqual(acked, [EXTRA])
        self.assertEqual(still_pending, [second])


if __name__ == '__main__':
    unittest.main()
