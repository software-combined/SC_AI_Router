"""Derived-field refresh from live OpenRouter metadata (Plan 044)."""
import unittest
from codex_router.live_refresh import derive, refresh


def _row(**over):
    base = {'slug': 'm/x', 'default_reasoning': 'low',
            'reasoning': ['low', 'high', 'max'], 'excluded_efforts': ['max'],
            'modalities': ['text'], 'context_window': 1, 'max_output_tokens': 7}
    base.update(over)
    return base


def _live(**over):
    base = {'architecture': {'input_modalities': ['text', 'image', 'video', 'file', 'audio']},
            'context_length': 100, 'top_provider': {'max_completion_tokens': 50},
            'reasoning': {'supported_efforts': ['low', 'high']}}
    base.update(over)
    return base


class LiveRefreshTests(unittest.TestCase):
    def test_modalities_keep_codex_vocabulary_only(self):
        derived = derive(_row(), _live())
        self.assertEqual(derived['modalities'], ['text', 'image', 'audio'])

    def test_excluded_efforts_removed_in_canonical_order(self):
        derived = derive(_row(), _live(reasoning={'supported_efforts':
            ['max', 'high', 'low', 'minimal']}))
        self.assertEqual(derived['reasoning'], ['minimal', 'low', 'high'])

    def test_unknown_live_ids_ignored_and_missing_models_untouched(self):
        row = _row()
        out = refresh([row], {'zzz/unknown': _live()})
        self.assertEqual(out, [row])

    def test_missing_top_provider_falls_back_to_pinned(self):
        live = _live()
        del live['top_provider']
        derived = derive(_row(), live)
        self.assertEqual(derived['max_output_tokens'], 7)
        self.assertEqual(derived['context_window'], 100)

    def test_default_guard_keeps_pinned_reasoning(self):
        derived = derive(_row(), _live(reasoning={'supported_efforts': ['high']}))
        self.assertEqual(derived['reasoning'], ['low', 'high', 'max'])

    def test_alias_target_name_folds_into_display_name(self):
        live = _live(alias_target={'name': 'SpaceXAI: Grok 4.6', 'slug': 'x-ai/grok-4.6'})
        derived = derive(_row(display_name='Grok Latest \xb7 OpenRouter'), live)
        self.assertEqual(derived['display_name'], 'SpaceXAI: Grok 4.6 \xb7 OpenRouter')

    def test_display_name_untouched_without_alias(self):
        derived = derive(_row(display_name='Grok Latest \xb7 OpenRouter'), _live())
        self.assertEqual(derived['display_name'], 'Grok Latest \xb7 OpenRouter')

    def test_pinned_identity_fields_untouched(self):
        row = _row(slug='m/x', excluded_efforts=['max'])
        out = refresh([row], {'m/x': _live()})
        self.assertEqual(out[0]['slug'], 'm/x')
        self.assertEqual(out[0]['excluded_efforts'], ['max'])
        self.assertEqual(out[0]['default_reasoning'], 'low')


if __name__ == '__main__':
    unittest.main()
