from pathlib import Path
import tempfile
import unittest
from codex_router.apply_catalogue import apply, write_guarded
from codex_router.capabilities import OPENROUTER_MODELS

def catalog():
    return {'models': [{'slug': slug, 'default_reasoning_level': 'low',
             'supported_reasoning_levels': []} for slug in OPENROUTER_MODELS]}

def live(levels=None, image=True):
    return {slug: {'reasoning': {'supported_efforts': levels or ['low', 'high', 'max']},
            'architecture': {'input_modalities': ['text', 'image'] if image else ['text']}}
            for slug in OPENROUTER_MODELS}

class ApplyTests(unittest.TestCase):
    def test_merge_applies_live_minus_exclusions_in_canonical_order(self):
        out = apply(catalog(), live(['max', 'minimal', 'low']))
        by_slug = {m['slug']: m for m in out['models']}
        flash = [x['effort'] for x in by_slug['z-ai/glm-5.3-flash']['supported_reasoning_levels']]
        self.assertEqual(flash, ['minimal', 'low', 'max'])
        contrib = [x['effort'] for x in by_slug['meta/muse-spark-1.3-contributor']['supported_reasoning_levels']]
        self.assertNotIn('max', contrib)

    def test_reasoning_effort_field_applies_as_declared(self):
        out = apply(catalog(), live())
        for m in out['models']:
            self.assertIsNone(m['multi_agent_reasoning_effort'])

    def test_modality_refresh_follows_live_metadata(self):
        out = apply(catalog(), live(image=False))
        by_slug = {m['slug']: m for m in out['models']}
        self.assertEqual(by_slug['moonshotai/kimi-k3']['input_modalities'], ['text'])

    def test_fallback_when_live_lacks_model(self):
        data = live()
        del data['z-ai/glm-5.3']
        out = apply(catalog(), data)
        by_slug = {m['slug']: m for m in out['models']}
        self.assertEqual([x['effort'] for x in by_slug['z-ai/glm-5.3']['supported_reasoning_levels']],
                         ['low', 'high', 'max'])

    def test_default_outside_supported_fails_closed(self):
        models = catalog()
        models['models'][0]['default_reasoning_level'] = 'ultra'
        with self.assertRaisesRegex(ValueError, 'Unsupported reasoning levels'):
            apply(models, live(['low']))

    def test_write_guarded_aborts_on_concurrent_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'mixed-models.json'
            path.write_text('{"v":2}')
            with self.assertRaises(SystemExit):
                write_guarded(path, '{"v":1}', '{"v":3}')
            self.assertEqual(path.read_text(), '{"v":2}')
            self.assertFalse((path.with_name(path.name + '.bak')).exists())

    def test_write_guarded_writes_backup_then_replaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'mixed-models.json'
            path.write_text('{"v":1}')
            write_guarded(path, '{"v":1}', '{"v":2}')
            self.assertEqual(path.read_text(), '{"v":2}')
            self.assertEqual(path.with_name(path.name + '.bak').read_text(), '{"v":1}')


if __name__ == '__main__':
    unittest.main()
