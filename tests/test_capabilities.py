import unittest
from ai_router.capabilities import (EXTERNAL_MODELS, REASONING_LEVELS, catalogue_patch,
    describe, input_modalities, live_levels, reasoning_levels)
from ai_router.registry import MODELS

class CapabilityTests(unittest.TestCase):
    def test_single_source_covers_registry_models(self):
        self.assertEqual(EXTERNAL_MODELS,
                         {m.slug for m in MODELS
                          if m.provider in ('openrouter', 'bedrock')})

    def test_text_only_set_matches_live_metadata(self):
        for slug in ('z-ai/glm-5.3', 'deepseek/deepseek-v4-pro-0813'):
            self.assertEqual(input_modalities(slug), ['text'])
        for slug in EXTERNAL_MODELS - {'z-ai/glm-5.3',
                                         'deepseek/deepseek-v4-pro-0813',
                                         'bedrock/openai.gpt-oss-120b'}:
            self.assertIn('image', input_modalities(slug))

    def test_reasoning_matches_live_acceptance(self):
        self.assertNotIn('max', reasoning_levels('meta/muse-spark-1.3-contributor'))
        self.assertIn('max', reasoning_levels('meta/muse-spark-1.3'))
        self.assertEqual(reasoning_levels('x-ai/grok-4.7'), ['low', 'medium', 'high', 'xhigh'])
        self.assertEqual(reasoning_levels('deepseek/deepseek-v4-pro-0813'),
                         ['low', 'high', 'max'])
        self.assertEqual(reasoning_levels('deepseek/deepseek-v4.1-flash'),
                         ['low', 'high', 'max'])
        for slug in ('xiaomi/mimo-v2.6-flash', 'xiaomi/mimo-v2.6-pro'):
            self.assertEqual(reasoning_levels(slug),
                             ['none', 'minimal', 'low', 'medium', 'high', 'xhigh'])

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


if __name__ == '__main__':
    unittest.main()
