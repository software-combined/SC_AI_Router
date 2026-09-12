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

ALLOWED = ('z-ai/glm-5.3-flash', 'moonshotai/kimi-k3')


def _write_policy(home, allowed, portco='acme', department=None):
    path = Path(home) / 'model-policy.json'
    path.write_text(json.dumps({'portco': portco, 'department': department,
                                'allowed_models': list(allowed)}))
    path.chmod(0o600)
    return path


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
        target = by_slug('moonshotai/kimi-k3')
        rows = tuple(replace(m, listed=False) if m.slug == target.slug else m
                     for m in MODELS)
        with mock.patch.object(catalogue, 'MODELS', rows), \
                tempfile.TemporaryDirectory() as tmp:
            slugs = [slug for slug, _ in model_prompt.visible_models(tmp)]
        self.assertNotIn(target.slug, slugs)
        self.assertIn('z-ai/glm-5.3-flash', slugs)

    def test_display_names_come_from_the_registry_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = dict(model_prompt.visible_models(tmp))
        self.assertEqual(rows['z-ai/glm-5.3-flash'],
                         by_slug('z-ai/glm-5.3-flash').display_name)

    def test_unknown_client_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                model_prompt.visible_models(tmp, client='claude')


if __name__ == '__main__':
    unittest.main()
