import unittest
from ai_router.capabilities import (EXTERNAL_MODELS, REASONING_LEVELS, catalogue_patch,
    check_images, describe, input_modalities, live_levels, reasoning_levels)
from ai_router.registry import MODELS

class CapabilityTests(unittest.TestCase):
    def test_single_source_covers_registry_models(self):
        self.assertEqual(EXTERNAL_MODELS,
                         {m.slug for m in MODELS if m.provider == 'openrouter'})

    def test_text_only_set_matches_live_metadata(self):
        for slug in ('z-ai/glm-5.3', 'deepseek/deepseek-v4-pro-0813'):
            self.assertEqual(input_modalities(slug), ['text'])
        for slug in EXTERNAL_MODELS - {'z-ai/glm-5.3',
                                         'deepseek/deepseek-v4-pro-0813'}:
            self.assertIn('image', input_modalities(slug))

    def test_reasoning_matches_live_acceptance(self):
        self.assertNotIn('max', reasoning_levels('meta/muse-spark-1.3-contributor'))
        self.assertIn('max', reasoning_levels('meta/muse-spark-1.3'))
        self.assertEqual(reasoning_levels('x-ai/grok-4.6'), ['low', 'medium', 'high', 'xhigh'])
        self.assertEqual(reasoning_levels('deepseek/deepseek-v4-pro-0813'),
                         ['low', 'high', 'max'])
        self.assertEqual(reasoning_levels('deepseek/deepseek-v4.1-flash'),
                         ['low', 'high', 'max'])

    def test_trial_values_proven_for_subagents_and_switching(self):
        patch = catalogue_patch('z-ai/glm-5.3')
        self.assertEqual(patch['multi_agent_version'], 'v1')
        self.assertIsNone(patch['comp_hash'])
        self.assertFalse(patch['node_repl_disabled'])


class InvariantTests(unittest.TestCase):
    def test_every_model_resolves_in_every_map(self):
        for slug in EXTERNAL_MODELS:
            self.assertIn(slug, REASONING_LEVELS)
            self.assertTrue(reasoning_levels(slug))
            patch = catalogue_patch(slug)
            self.assertEqual(patch['input_modalities'], input_modalities(slug))

    def test_live_minus_exclusions(self):
        self.assertNotIn('max', live_levels('meta/muse-spark-1.3-contributor',
            ['minimal', 'low', 'medium', 'high', 'xhigh', 'max']))
        self.assertIn('max', live_levels('meta/muse-spark-1.3',
            ['minimal', 'low', 'medium', 'high', 'xhigh', 'max']))

    def test_shared_descriptions(self):
        self.assertEqual(describe('max'), 'Maximum reasoning')
        self.assertEqual(describe('low'), 'Low reasoning')

    def test_unknown_model_fails_closed(self):
        with self.assertRaises(KeyError):
            catalogue_patch('unknown/model')


class ImageDetectionTests(unittest.TestCase):
    def test_historical_image_passes_on_a_text_only_row(self):
        slug = next(slug for slug in EXTERNAL_MODELS
                    if 'image' not in input_modalities(slug))
        items = [{'type': 'message', 'role': 'user',
                  'content': [{'type': 'input_image',
                               'image_url': 'data:image/png;base64,AAA'}]},
                 {'type': 'message', 'role': 'user', 'content': 'next turn'}]
        check_images(slug, items)

    def test_trailing_developer_item_does_not_hide_the_current_message(self):
        slug = next(slug for slug in EXTERNAL_MODELS
                    if 'image' not in input_modalities(slug))
        items = [{'type': 'message', 'role': 'user',
                  'content': [{'type': 'input_image',
                               'image_url': 'data:image/png;base64,AAA'}]},
                 {'type': 'message', 'role': 'developer',
                  'content': 'context note'}]
        with self.assertRaisesRegex(ValueError, 'does not accept image input'):
            check_images(slug, items)

    def test_current_message_image_still_refused(self):
        slug = next(slug for slug in EXTERNAL_MODELS
                    if 'image' not in input_modalities(slug))
        with self.assertRaisesRegex(ValueError, 'does not accept image input'):
            check_images(slug, [{'type': 'message', 'role': 'user',
                                 'content': [{'type': 'input_image',
                                              'image_url': 'data:image/png;base64,AAA'}]}])

    def test_tool_output_after_last_user_message_does_not_raise(self):
        slug = next(slug for slug in EXTERNAL_MODELS
                    if 'image' not in input_modalities(slug))
        items = [{'type': 'message', 'role': 'user', 'content': 'plain text'},
                 {'type': 'function_call_output', 'call_id': 'c1',
                  'output': [{'type': 'input_image',
                              'image_url': 'data:image/png;base64,AAA'}]}]
        check_images(slug, items)

if __name__ == '__main__':
    unittest.main()
