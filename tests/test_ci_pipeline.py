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
        command = ('run: python tools/plugin_verification.py --base "$VERIFICATION_BASE" '
                   '--run --workers 2 --report "$RUNNER_TEMP/unit-results.json"')
        self.assertIn(command, suite)
        self.assertIn('fetch-depth: 0', suite)
        self.assertIn('github.event.pull_request.base.sha || github.event.before', suite)
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

    def test_windows_suites_use_separate_runners_and_both_reach_the_gate(self):
        pipeline = jobs()
        job = pipeline['windows-standard']
        self.assertIn('suite: [core, native]', job)
        self.assertIn('fail-fast: false', job)
        self.assertIn('-Suite ${{ matrix.suite }}', job)
        self.assertIn('runs-on: windows-latest', job)
        self.assertIn('windows-standard', pipeline['test'])

    def test_diagnostic_graph_preserves_checks_without_release_authority(self):
        diagnostic = (CHECK.parent / 'windows-ci-benchmark.yml').read_text()
        self.assertIn("branches: ['cyril/windows-ci-bench-*']", diagnostic)
        self.assertIn('name: Diagnostic acceptance', diagnostic)
        self.assertNotIn("&& 'Test'", diagnostic)
        self.assertIn('python tools/plugin_verification.py --full --run --workers 2', diagnostic)
        self.assertIn('echo "installer=true"', diagnostic)
        for name, job in jobs().items():
            self.assertIn('\n  ' + name + ':', diagnostic)
            if name not in ('changes', 'windows-standard', 'unit-suite', 'test'):
                # Unchanged native commands and full platform matrix remain present.
                for line in job.splitlines():
                    if line.lstrip().startswith(('run:', '- {target:', 'os:')):
                        self.assertIn(line, diagnostic)


if __name__ == '__main__':
    unittest.main()
