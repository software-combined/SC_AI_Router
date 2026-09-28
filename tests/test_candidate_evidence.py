"""Candidate records cannot certify a different model, route, runtime or client."""
from copy import deepcopy
from dataclasses import replace
import tempfile
import unittest
from pathlib import Path

from ai_router import candidate_evidence as evidence, registry
from tests.candidate_fixtures import proof
from tools import check_acceptance_ledger


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.row = registry.MODELS[0]
        self.proof = proof(self.row)

    def test_complete_routes_pass_with_unknown_served_effort(self):
        self.assertEqual(evidence.problems(self.row, self.proof), [])
        self.assertEqual(evidence.problems(self.row, self.proof,
                         clients={'codex': '1.2.3', 'claude': '1.2.4'}),
                         ['messages: failed, stale or mismatched evidence'])
        self.proof['routes'][0]['served_models'] = []
        self.assertEqual(evidence.problems(self.row, self.proof), [])

    def test_failed_missing_duplicate_and_mismatched_routes_cannot_pass(self):
        for field, value in (('result', 'fail'), ('conformance', 'fail'), ('calls', 0),
                             ('client_version', 'unverified'),
                             ('served_models', [{'value': 'other/model', 'source': 'response.model'}]),
                             ('served_efforts', [{'value': 'max', 'source': 'response.reasoning.effort'}])):
            with self.subTest(field=field):
                changed = deepcopy(self.proof)
                changed['routes'][0][field] = value
                self.assertTrue(evidence.problems(self.row, changed))
        for routes in (self.proof['routes'][:1], [self.proof['routes'][0]] * 2):
            self.assertTrue(evidence.problems(self.row, {**self.proof, 'routes': routes}))
        self.assertTrue(evidence.problems(self.row, True))
        over_budget = deepcopy(self.proof)
        for route in over_budget['routes']:
            route['calls'] = evidence.MAX_PROBE_CALLS
        self.assertTrue(evidence.problems(self.row, over_budget))

    def test_bindings_include_capabilities_and_effective_upstream_identity(self):
        for changed in (replace(self.row, max_tools=5), replace(self.row, drop_images=not self.row.drop_images),
                        replace(self.row, upstream_id='different/model')):
            self.assertTrue(evidence.problems(changed, self.proof))
        self.assertTrue(evidence.problems(self.row, self.proof, runtime='f' * 64))
        promoted = replace(self.row, tier='verified', listed=True, priority=500)
        self.assertEqual(evidence.capability_fingerprint(promoted),
                         evidence.capability_fingerprint(self.row))

    def test_runtime_fingerprint_ignores_documents_but_catches_source_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'ai_router').mkdir()
            code = root / 'ai_router' / 'one.py'
            code.write_text('answer = 1\n')
            before = evidence.runtime_fingerprint(root)
            (root / 'notes.md').write_text('evidence\n')
            self.assertEqual(evidence.runtime_fingerprint(root), before)
            code.write_text('answer = 2\n')
            self.assertNotEqual(evidence.runtime_fingerprint(root), before)

    def test_unknown_fields_and_unproven_identity_sources_are_refused(self):
        for change in ({'transcript': 'synthetic'}, {'runtime_fingerprint': 'unknown'},
                       {'observed_at': '2026-09-28T12:00:00'}):
            self.assertTrue(evidence.problems(self.row, {**self.proof, **change}))
        self.proof['routes'][0]['served_models'][0]['source'] = 'client.marker'
        self.assertTrue(evidence.problems(self.row, self.proof))

    def test_new_records_do_not_turn_into_plan185_cell_passes(self):
        import json
        records = check_acceptance_ledger.load(json.dumps([self.proof]))
        _, failing = check_acceptance_ledger.report(records, {
            'codex_version': '26.917.62051', 'claude_code_version': '2.1.283'})
        self.assertEqual(failing, ['C1', 'C2', 'C3', 'C4'])

    def test_latest_failure_and_equal_time_conflict_replace_old_pass(self):
        newer = deepcopy(self.proof)
        newer['observed_at'] = '2099-01-02T10:00:00+10:00'
        newer['routes'][0]['result'] = 'fail'
        self.assertEqual(evidence.latest([self.proof, newer]), (newer, None))
        duplicate = deepcopy(newer)
        duplicate['routes'][0]['result'] = 'pass'
        self.assertEqual(evidence.latest([newer, duplicate]), (None, 'conflicting'))


if __name__ == '__main__':
    unittest.main()
