"""Plan 064 Step 1: projection and normalization contracts.

Merge and apply must agree for the same Model snapshot. The modality
equality case exposes the existing defect: merge emits full modalities
while apply reduces to text/image. Subscription rows and unrelated fields
are preserved. No upstream fetch, model file write, or candidate probe.
"""
import unittest

from ai_router import apply_catalogue, catalogue
from ai_router.registry import by_slug


def _snapshot(slug='meta/muse-spark-1.3'):
    model = by_slug(slug)
    assert model is not None
    return model


class ModelProjectionTests(unittest.TestCase):
    def test_merge_and_apply_agree_on_modalities(self):
        model = _snapshot()
        merged = catalogue.openrouter_entry(model)
        catalog = {'models': [dict(merged, slug=model.slug,
                                   default_reasoning_level=model.default_reasoning)]}
        live = {model.slug: {'architecture': {'input_modalities': list(model.modalities)},
                             'reasoning': {'supported_efforts': list(model.reasoning)}}}
        applied = apply_catalogue.apply(catalog, live)['models'][0]
        self.assertEqual(applied['input_modalities'], merged['input_modalities'])

    def test_merge_and_apply_agree_on_reasoning_levels(self):
        model = _snapshot()
        merged = catalogue.openrouter_entry(model)
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
        merged = catalogue.openrouter_entry(model)
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


if __name__ == '__main__':
    unittest.main()
