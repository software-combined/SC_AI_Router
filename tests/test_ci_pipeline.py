"""Main acceptance overlaps independent checks without weakening its gate."""
import re
import unittest
from pathlib import Path

CHECK = Path(__file__).resolve().parents[1] / '.github/workflows/check.yml'


def jobs():
    text = CHECK.read_text().split('\njobs:\n', 1)[1]
    return dict(re.findall(r'^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)',
                           text, re.MULTILINE | re.DOTALL))


class AcceptancePipelineTests(unittest.TestCase):
    def test_full_suite_can_start_before_native_checks_finish(self):
        pipeline = jobs()
        suite = pipeline['unit-suite']
        self.assertNotIn('\n    needs:', '\n' + suite, 'offline tests are independent')
        command = ('run: python tools/ci_unittest.py --workers 2 '
                   '--report "$RUNNER_TEMP/unit-results.json" -- discover -s tests -t .')
        self.assertIn(command, suite)
        self.assertIn("SCG_RUN_INSTALLER_TESTS: '1'", suite)
        self.assertEqual(sum(command in job for job in pipeline.values()), 1)

    def test_required_gate_waits_for_every_acceptance_job(self):
        pipeline = jobs()
        needs = re.search(r'^    needs: \[([^]]+)\]', pipeline['test'], re.MULTILINE)
        self.assertIsNotNone(needs)
        self.assertEqual({name.strip() for name in needs[1].split(',')},
                         pipeline.keys() - {'test'})
        self.assertIn('unit-suite', needs[1])
        self.assertIn("contains(needs.*.result, 'failure') || "
                      "contains(needs.*.result, 'cancelled')", pipeline['test'])


if __name__ == '__main__':
    unittest.main()
