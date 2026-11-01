"""Plan 154: the merged catalogue stays bounded as the roster grows.

`model_refresh.validate` caps a refreshed registry at 200 rows, and the
per-row instructions blob used to grow with the visible row count, so the
merged file grew with the square of it. These pin a byte and a wall-clock
budget for that worst case, and that the capped roster keeps `check` honest.
"""
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from ai_router import capabilities, catalogue, model_refresh, registry
from ai_router.model_instructions import MAX_ROSTER_IDS

ROWS = 200
# Measured with the roster cap in place: 4,929,163 bytes for 200 external rows
# plus the 8-row subscription roster. The budget sits below the 5,716,931 a
# roster-dependent merge produces, so removing the cap fails this assertion
# rather than only the count assertion below (plan 154 status row).
BYTE_BUDGET = 5600000
SECONDS_BUDGET = 10.0


def _synthetic_rows(count):
    base = json.loads(
        Path(registry.__file__).with_name('models.json').read_text())[0]
    return [{**base, 'slug': f'bench/model-{i:03d}',
             'display_name': f'Bench: Model {i:03d} \u00b7 OpenRouter',
             'priority': 100 + i} for i in range(count)]


class CatalogueScaleTests(unittest.TestCase):
    """A 200-row registry is the largest the refresh path can install."""

    def setUp(self):
        self._registry = (registry.MODELS, registry.BY_SLUG)
        self._catalogue_models = catalogue.MODELS
        self._caps = (capabilities.EXTERNAL_MODELS, capabilities.IMAGE_INPUT_MODELS,
                      capabilities.REASONING_LEVELS, capabilities.EXCLUDED_EFFORTS)
        self.addCleanup(self._restore)
        rows = registry.load(json.dumps(_synthetic_rows(ROWS)))
        registry.MODELS, registry.BY_SLUG = rows, {m.slug: m for m in rows}
        catalogue.MODELS = rows
        model_refresh.apply(rows)

    def _restore(self):
        registry.MODELS, registry.BY_SLUG = self._registry
        catalogue.MODELS = self._catalogue_models
        (capabilities.EXTERNAL_MODELS, capabilities.IMAGE_INPUT_MODELS,
         capabilities.REASONING_LEVELS, capabilities.EXCLUDED_EFFORTS) = self._caps

    def test_two_hundred_rows_stay_inside_the_budget(self):
        started = time.monotonic()
        merged = catalogue.merge({'models': []},
                                 roster=catalogue.SUBSCRIPTION_SLUGS)
        elapsed = time.monotonic() - started
        size = len(json.dumps(merged).encode())
        self.assertEqual(len(merged['models']),
                         ROWS + len(catalogue.SUBSCRIPTION_SLUGS))
        self.assertLess(size, BYTE_BUDGET, f'{size} bytes for {ROWS} rows')
        self.assertLess(elapsed, SECONDS_BUDGET, f'{elapsed:.2f}s for {ROWS} rows')

    def test_the_roster_line_is_capped_and_check_still_matches(self):
        visible = catalogue._visible_rows('codex', None)[0]
        self.assertEqual(
            catalogue.instructions_for(visible).count('`bench/model-'),
            MAX_ROSTER_IDS)
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(home), True)
        path = home / 'mixed-models.json'
        merged = catalogue.merge({'models': []},
                                 roster=catalogue.SUBSCRIPTION_SLUGS)
        path.write_text(json.dumps(merged, indent=2) + '\n')
        self.assertTrue(catalogue.check(str(path)))
        # The same file with a routed template on one subscription row must
        # fail the check rather than ship (Plan 154).
        routed = catalogue.instructions_for(visible)
        merged['models'][0]['model_messages'] = {
            'instructions_template': routed}
        path.write_text(json.dumps(merged, indent=2) + '\n')
        self.assertFalse(catalogue.check(str(path)))

    def test_subscription_rows_are_not_told_they_are_routed(self):
        merged = catalogue.merge({'models': []},
                                 roster=catalogue.SUBSCRIPTION_SLUGS)
        text = merged['models'][0]['model_messages']['instructions_template']
        self.assertIn('ChatGPT subscription', text)
        self.assertNotIn('OpenRouter', text)
        routed = catalogue.instructions_for(
            catalogue._visible_rows('codex', None)[0])
        self.assertNotIn('OpenRouter', routed)

    def test_native_tool_discovery_guidance_reaches_both_codex_routes_only(self):
        merged = catalogue.merge({'models': []}, roster=('gpt-6-astra',))
        native = next(row for row in merged['models'] if row['slug'] == 'gpt-6-astra')
        external = next(row for row in merged['models'] if row['slug'].startswith('bench/'))
        for row in (native, external):
            with self.subTest(slug=row['slug']):
                text = row['model_messages']['instructions_template']
                self.assertIn('`ALL_TOOLS` covers only exec-callable tools', text)
                self.assertIn('call offered native tools directly', text)
                self.assertIn('exact direct-call error', text)
        claude = catalogue.merge({'models': []}, client='claude', roster=('gpt-6-astra',))
        for row in claude['models']:
            self.assertNotIn('`ALL_TOOLS`', row['model_messages']['instructions_template'])

    def test_a_stale_routed_subscription_row_is_upgraded_and_refused(self):
        # A catalogue written before this change holds routed wording with the
        # roster line of that moment, and the roster moves. Both gates match
        # the wording, not one exact rendering (Plan 154).
        visible = catalogue._visible_rows('codex', None)[0]
        stale = catalogue.instructions_for(visible[:5])
        legacy = stale.replace('selected routed', 'selected OpenRouter')
        for template in (stale, legacy):
            with self.subTest(wording=template[:38]):
                stored = {**catalogue.subscription_stub('gpt-6-astra'),
                          'priority': 1,
                          'model_messages': {'instructions_template': template}}
                merged = catalogue.merge({'models': [stored]},
                                         roster=('gpt-6-astra',))
                row = next(m for m in merged['models']
                           if m['slug'] == 'gpt-6-astra')
                self.assertIn('ChatGPT subscription',
                              row['model_messages']['instructions_template'])
                row['model_messages'] = {'instructions_template': template}
                home = Path(tempfile.mkdtemp())
                self.addCleanup(shutil.rmtree, str(home), True)
                path = home / 'mixed-models.json'
                path.write_text(json.dumps(merged, indent=2) + '\n')
                self.assertFalse(catalogue.check(str(path)))


if __name__ == '__main__':
    unittest.main()
