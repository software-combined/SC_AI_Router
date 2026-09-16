"""Plan 064 Step 1: projection and normalization contracts.

Merge and apply must agree for the same Model snapshot. The modality
equality case exposes the existing defect: merge emits full modalities
while apply reduces to text/image. Subscription rows and unrelated fields
are preserved. No upstream fetch, model file write, or candidate probe.
"""
import unittest

from ai_router import apply_catalogue, catalogue, claude, clients, registry
from ai_router.registry import by_slug


def _snapshot(slug='meta/muse-spark-1.3'):
    model = by_slug(slug)
    assert model is not None
    return model


class ModelProjectionTests(unittest.TestCase):
    def test_merge_and_apply_agree_on_modalities(self):
        model = _snapshot()
        merged = catalogue.external_entry(model)
        catalog = {'models': [dict(merged, slug=model.slug,
                                   default_reasoning_level=model.default_reasoning)]}
        live = {model.slug: {'architecture': {'input_modalities': list(model.modalities)},
                             'reasoning': {'supported_efforts': list(model.reasoning)}}}
        applied = apply_catalogue.apply(catalog, live)['models'][0]
        self.assertEqual(applied['input_modalities'], merged['input_modalities'])

    def test_merge_and_apply_agree_on_reasoning_levels(self):
        model = _snapshot()
        merged = catalogue.external_entry(model)
        catalog = {'models': [dict(merged, slug=model.slug,
                                   default_reasoning_level=model.default_reasoning)]}
        live = {model.slug: {'architecture': {'input_modalities': list(model.modalities)},
                             'reasoning': {'supported_efforts': list(model.reasoning)}}}
        applied = apply_catalogue.apply(catalog, live)['models'][0]
        self.assertEqual(
            [e['effort'] for e in applied['supported_reasoning_levels']],
            [e['effort'] for e in merged['supported_reasoning_levels']])

    def test_subscription_rows_and_unrelated_fields_preserved(self):
        model = _snapshot()
        merged = catalogue.external_entry(model)
        before = dict(merged, slug=model.slug,
                      default_reasoning_level=model.default_reasoning,
                      custom_note='keep me')
        catalog = {'models': [dict(before),
                              {'slug': 'gpt-6-astra', 'display_name': 'Astra',
                               'custom_note': 'native'}]}
        live = {model.slug: {'architecture': {'input_modalities': list(model.modalities)},
                             'reasoning': {'supported_efforts': list(model.reasoning)}}}
        out = apply_catalogue.apply(catalog, live)['models']
        native = next(m for m in out if m['slug'] == 'gpt-6-astra')
        self.assertEqual(native['custom_note'], 'native')
        routed = next(m for m in out if m['slug'] == model.slug)
        self.assertEqual(routed['custom_note'], 'keep me')


class ClientSurfaceTests(unittest.TestCase):
    def test_the_claude_picker_and_the_messages_listing_differ(self):
        # Two surfaces answer "what does Claude Code see" and they differ by
        # design: the picker hides externally billed Anthropic rows so a
        # Claude Code user sees one row per model instead of the same model on
        # two billing routes, while GET /v1/models lists them so that user can
        # still choose an externally billed Claude model -- the listing's own
        # key filter, not the client rule, is what narrows it.
        picker = clients.models_for(registry.MODELS, 'claude')
        listing = claude.models_listing()['data']
        hidden = [m for m in registry.MODELS
                  if m.listed and not clients.visible_for(m, 'claude')]
        self.assertTrue(hidden, 'the two surfaces agree, so this test proves nothing')
        self.assertEqual(len(listing), len(picker) + len(hidden))
        listed_ids = {row['id'] for row in listing}
        picker_slugs = {m.slug for m in picker}
        for model in hidden:
            with self.subTest(slug=model.slug):
                self.assertNotIn(model.slug, picker_slugs)
                self.assertIn(claude.claude_alias(model.slug), listed_ids)


if __name__ == '__main__':
    unittest.main()
