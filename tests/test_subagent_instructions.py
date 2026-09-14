"""Plan 151: served instructions name every visible router model."""
import json
import tempfile
import unittest
from pathlib import Path

from ai_router.catalogue import check, external_entry, merge
from ai_router.clients import models_for
from ai_router.registry import MODELS, by_slug


class SubagentInstructionTests(unittest.TestCase):
    def test_instructions_name_every_visible_router_model(self):
        template = external_entry(by_slug('z-ai/glm-5.3-flash'))[
            'model_messages']['instructions_template']
        for model in models_for(MODELS, 'codex'):
            self.assertIn(f'`{model.slug}`', template)

    def test_merge_and_check_agree_on_rendered_instructions(self):
        allowed = ('meta/muse-spark-1.3-contributor', 'z-ai/glm-5.3-flash')
        catalog = merge({'models': []}, (), 'codex', allowed)
        path = Path(tempfile.mkdtemp()) / 'catalog.json'
        path.write_text(json.dumps(catalog))
        self.assertTrue(check(str(path), 'codex', allowed))

    def test_rendered_instructions_mark_delivered_names_as_not_tools(self):
        template = external_entry(by_slug('z-ai/glm-5.3-flash'))[
            'model_messages']['instructions_template']
        self.assertIn('`delivered_message` or `delivered_app_message` are', template)

    def test_no_row_serves_the_raw_placeholder(self):
        catalog = merge({'models': []}, ('gpt-6-astra', 'gpt-5.6-luna'))
        for row in catalog['models']:
            template = row['model_messages']['instructions_template']
            self.assertNotIn('{{', template, row['slug'])
        stub = next(r for r in catalog['models'] if r['slug'] == 'gpt-6-astra')
        self.assertIn('meta/muse-spark-1.3-contributor',
                      stub['model_messages']['instructions_template'])

    def test_check_rejects_an_unrendered_placeholder(self):
        catalog = merge({'models': []}, ('gpt-6-astra',))
        row = catalog['models'][0]
        row['model_messages']['instructions_template'] += ' {{SUBAGENT_MODEL_IDS}}'
        path = Path(tempfile.mkdtemp()) / 'catalog.json'
        path.write_text(json.dumps(catalog))
        self.assertFalse(check(str(path)))

    def test_projections_narrow_every_served_row(self):
        allowed = ('meta/muse-spark-1.3-contributor', 'z-ai/glm-5.3-flash')
        for client in ('codex', 'claude'):
            with self.subTest(client=client):
                catalog = merge({'models': []}, ('gpt-6-astra',), client, allowed)
                served = '\n'.join(
                    (row.get('model_messages') or {}).get('instructions_template') or ''
                    for row in catalog['models'])
                for model in models_for(MODELS, client):
                    if model.slug not in allowed:
                        self.assertNotIn(f'`{model.slug}`', served)


if __name__ == '__main__':
    unittest.main()
