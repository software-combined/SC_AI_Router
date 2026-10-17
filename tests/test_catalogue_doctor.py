"""The doctor checks the installed projection, including its visibility gates."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ai_router import availability, catalogue, snapshot_store
from tests._platform import requires_posix_perms
from tests.install_fixtures import install_mod

ROOT = Path(__file__).resolve().parents[1]


class CatalogueDoctorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.key = 'synthetic-catalogue-check-key'
        self.models = [m for m in catalogue._visible_rows('codex', None)[0]
                       if m.provider == 'openrouter']
        self.visible = self.models[0].slug
        (self.home / 'mixed-router-state.json').write_text(json.dumps({
            'openai_mode': 'subscription', 'openai_models': ['gpt-6-sol'],
            'openrouter_region': 'global'}))
        snapshot_store.write(self.home, 'openrouter',
                             availability.key_fingerprint(self.key), 'global',
                             {self.visible})
        catalogue.merge_file(self.home / 'mixed-models.json',
                             available={self.visible})

    def check(self):
        operator = install_mod._operator
        with (mock.patch.object(operator._svc, 'current_release_dir', return_value=ROOT),
              mock.patch.object(operator, 'run', subprocess.run),
              mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': self.key})):
            return operator._catalogue_row(self.home, sys.executable)

    def test_key_filtered_catalogue_is_healthy_and_check_writes_nothing(self):
        before = {p.name: p.read_bytes() for p in self.home.iterdir() if p.is_file()}
        row = self.check()
        self.assertEqual(row['status'], 'OK', row)
        self.assertIsNone(row['fix'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.home.iterdir()
                                  if p.is_file()})

    @requires_posix_perms
    def test_local_policy_and_key_filter_use_the_same_projection(self):
        visible = self.models[1].slug
        snapshot_store.write(self.home, 'openrouter',
                             availability.key_fingerprint(self.key), 'global',
                             {self.visible, visible})
        policy = self.home / 'model-policy.json'
        policy.write_text(json.dumps({'portco': 'fixture', 'allowed_models': [visible]}))
        policy.chmod(0o600)
        catalogue.merge_file(self.home / 'mixed-models.json',
                             allowed=[visible], available={self.visible, visible})
        self.assertEqual(self.check()['status'], 'OK')

    def test_real_catalogue_corruption_still_warns(self):
        path = self.home / 'mixed-models.json'
        doc = json.loads(path.read_text())
        row = next(r for r in doc['models'] if r['slug'] == self.visible)
        row['context_window'] = -1
        path.write_text(json.dumps(doc))
        result = self.check()
        self.assertEqual(result['status'], 'WARN')
        self.assertIn('context_window', result['detail'])
        self.assertTrue(result['fix'])

    def test_empty_key_availability_does_not_restore_hidden_models(self):
        snapshot_store.write(self.home, 'openrouter',
                             availability.key_fingerprint(self.key), 'global', set())
        catalogue.merge_file(self.home / 'mixed-models.json', available=set())
        self.assertEqual(self.check()['status'], 'OK')


if __name__ == '__main__':
    unittest.main()
