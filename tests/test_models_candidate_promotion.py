"""Promotion requires both route proofs against the still-current candidate."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_router import models
from tests.candidate_fixtures import proof
from tests.test_models_cmd import LIVE


class PromotionTests(unittest.TestCase):
    def test_incomplete_failed_stale_and_scalar_proof_stay_preview(self):
        for defect in ('missing_route', 'failed_route', 'stale_runtime', 'scalar'):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as folder:
                path, ledger = Path(folder) / 'models.json', Path(folder) / 'ledger.json'
                path.write_text('[]\n')
                historical = '{"historical": "preserve formatting"}'
                ledger.write_text('[\n' + historical + '\n]\n')

                def verify(slug):
                    record = proof(json.loads(path.read_text())[0])
                    if defect == 'missing_route': record['routes'].pop()
                    if defect == 'failed_route': record['routes'][1]['result'] = 'fail'
                    if defect == 'stale_runtime': record['runtime_fingerprint'] = 'f' * 64
                    return True if defect == 'scalar' else record

                with patch.object(models, 'EVIDENCE_PATH', ledger), contextlib.redirect_stdout(io.StringIO()):
                    models.cmd_add(path, 'qwen/qwen4-coder', LIVE, probe=True, _probe=verify)
                self.assertEqual((json.loads(path.read_text())[0]['tier'],
                                  json.loads(path.read_text())[0]['listed']), ('preview', False))
                self.assertIn(historical, ledger.read_text())
                self.assertEqual(len(json.loads(ledger.read_text())), 1 if defect == 'scalar' else 2)

    def test_concurrent_capability_edit_is_preserved_and_not_promoted(self):
        with tempfile.TemporaryDirectory() as folder:
            path, ledger = Path(folder) / 'models.json', Path(folder) / 'ledger.json'
            path.write_text('[]\n')

            def verify(slug):
                rows = json.loads(path.read_text())
                record = proof(rows[0])
                rows[0]['context_window'] += 1
                path.write_text(json.dumps(rows))
                return record

            with patch.object(models, 'EVIDENCE_PATH', ledger), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(SystemExit, 'Candidate changed'):
                    models.cmd_add(path, 'qwen/qwen4-coder', LIVE, probe=True, _probe=verify)
            row = json.loads(path.read_text())[0]
            self.assertEqual(row['context_window'], LIVE[row['slug']]['context_length'] + 1)
            self.assertEqual((row['tier'], row['listed']), ('preview', False))


if __name__ == '__main__':
    unittest.main()
