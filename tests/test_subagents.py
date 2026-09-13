import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins/scg-subagents'
SKILL = PLUGIN / 'skills/cost-first-subagents'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


pareto = module('pareto', SKILL / 'scripts/pareto.py')


class SubagentsTest(unittest.TestCase):
    def test_frontier_keeps_tradeoffs_and_ties_but_removes_dominated(self):
        rows = [{'model': name, 'cost_usd': cost, 'score': score} for name, cost, score in
                [('cheap', 1, 10), ('better', 2, 20), ('dominated', 3, 15),
                 ('tie', 2, 20), ('ceiling', 5, 25), ('same-cost-worse', 2, 10)]]
        self.assertEqual([r['model'] for r in pareto.frontier(rows)],
                         ['cheap', 'better', 'tie', 'ceiling'])

    def test_missing_and_proxy_scores_do_not_enter_aa_frontier(self):
        data = json.loads((SKILL / 'references/model-evidence.json').read_text())
        rows, excluded = pareto.candidates(data, 'intelligence', 'aa_task', 20000, 5000)
        self.assertFalse(any('contributor' in r['model'] or 'qwen' in r['model'] for r in rows))
        self.assertTrue(any('contributor' in r for r in excluded))
        self.assertFalse(any('muse' in r['model'] and 'xhigh' in r['model'] for r in rows))
        rows, excluded = pareto.candidates(data, 'webdev', 'scenario', 20000, 5000)
        self.assertFalse(any('qwen/qwen3.8-max-0902' in r['model'] for r in rows))
        self.assertTrue(any('qwen' in r and 'effort' in r for r in excluded))
        self.assertFalse(any(r['model'].startswith('gpt-5.5') for r in rows))
        with self.assertRaises(ValueError):
            pareto.candidates(data, 'webdev', 'aa_task', 20000, 5000)
        with self.assertRaises(ValueError):
            pareto.candidates(data, 'terminal', 'scenario', -1, 5000)

    def test_scenario_uses_route_price_and_preserves_real_zero_score(self):
        row = {'id': 'test', 'effort': 'max', 'aa_eligible': True,
               'scores': {'terminal': 0}, 'prices_usd_per_million': {'input': 2, 'output': 10}}
        rows, excluded = pareto.candidates({'models': [row], 'prescribed_efforts': {'test': 'max'}},
                                          'terminal', 'scenario', 20000, 5000)
        self.assertAlmostEqual(rows[0]['cost_usd'], 0.09)
        self.assertEqual(rows[0]['score'], 0)
        self.assertEqual(excluded, [])

    def test_every_model_has_one_prescribed_effort_in_evidence_and_catalogue(self):
        data = json.loads((SKILL / 'references/model-evidence.json').read_text())
        self.assertEqual(set(data['prescribed_efforts']), {r['id'] for r in data['models']})
        catalogue = (SKILL / 'references/catalogue.md').read_text()
        for model, effort in data['prescribed_efforts'].items():
            self.assertEqual(catalogue.count(f'| `{model}` | `{effort}` |'), 1)
        self.assertEqual(data['prescribed_efforts']['meta/muse-spark-1.3'], 'max')
        self.assertEqual(data['prescribed_efforts']['meta/muse-spark-1.3-contributor'], 'xhigh')

if __name__ == '__main__':
    unittest.main()
