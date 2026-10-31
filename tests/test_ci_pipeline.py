"""Main acceptance overlaps independent checks without weakening its gate."""
import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.test_workflows import run_block

CHECK = Path(__file__).resolve().parents[1] / '.github/workflows/check.yml'
DIAGNOSTIC = CHECK.parent / 'windows-ci-benchmark.yml'


def jobs(path=CHECK):
    text = path.read_text().split('\njobs:\n', 1)[1]
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
        self.assertIn('name: Diagnostic acceptance (control)', diagnostic)
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


class PartitionExperimentTests(unittest.TestCase):
    def test_native_workers_execute_the_verified_shell_they_record(self):
        experiment = jobs(DIAGNOSTIC)
        action = (CHECK.parents[1] / 'actions/diagnostic-powershell/action.yml').read_text()
        self.assertLess(action.index('Get-FileHash'), action.index('Expand-Archive'))
        self.assertLess(action.index('Expand-Archive'), action.index('$version = & $executable'))
        self.assertIn("$version.Trim() -cne '7.6.9'", action)
        self.assertIn('CE7484804C0F0AD4DDA10C958E71ACDAF7EEBFB22505C1B480F89E0E9F1DA94D', action)
        for name in ('windows-control-native', 'windows-native'):
            with self.subTest(job=name):
                block = experiment[name]
                self.assertIn('uses: ./.github/actions/diagnostic-powershell', block)
                self.assertIn('id: pinned-shell', block)
                self.assertEqual(block.count('CI_PWSH: ${{ steps.pinned-shell.outputs.executable }}'), 2)
                self.assertIn('python tools/ci_environment.py --pwsh-executable "$env:CI_PWSH"', block)
                self.assertIn('& $env:CI_PWSH -NoProfile -NonInteractive -ExecutionPolicy Bypass -File', block)

    def test_both_arms_keep_every_platform_and_the_current_control(self):
        experiment = jobs(DIAGNOSTIC)
        self.assertEqual(experiment.keys(), jobs().keys() | {
            'windows-control-native', 'windows-native', 'windows-native-aggregate', 'candidate-test'})
        self.assertIn("|| '[\"core\"]') }}", experiment['windows-standard'])
        self.assertIn('-Suite native -EvidencePath', experiment['windows-control-native'])
        self.assertIn('suite: [native-runtime, native-shortcuts]', experiment['windows-native'])
        self.assertIn('needs: windows-native', experiment['windows-native-aggregate'])
        self.assertIn('run: test "$RESULT" = success', experiment['windows-native-aggregate'])
        common = jobs().keys() - {'test'}
        for arm, gate, native in (('control', 'test', {'windows-control-native'}),
                                  ('candidate', 'candidate-test', {'windows-native', 'windows-native-aggregate'})):
            prerequisites = re.search(r'^    needs: \[([^]]+)\]', experiment[gate], re.MULTILINE)
            self.assertEqual({name.strip() for name in prerequisites[1].split(',')}, common | native)
            self.assertIn('ARM: ' + arm, experiment[gate])
            self.assertIn('name: Diagnostic acceptance (' + arm + ')', experiment[gate])
        self.assertIn('steps: &acceptance-steps', experiment['test'])
        self.assertIn('steps: *acceptance-steps', experiment['candidate-test'])
        self.assertEqual(DIAGNOSTIC.read_text().count('if-no-files-found: error'), 8)

    @unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'diagnostic gate runs on Ubuntu')
    def test_actual_gate_rejects_every_failed_cancelled_or_unexpected_skipped_prerequisite(self):
        block = run_block('Required jobs', DIAGNOSTIC.read_text())
        for arm in ('control', 'candidate'):
            gate = 'test' if arm == 'control' else 'candidate-test'
            required = re.search(r'^    needs: \[([^]]+)\]', jobs(DIAGNOSTIC)[gate], re.MULTILINE)
            results = {name.strip(): {'result': 'success'} for name in required[1].split(',')}
            def run(values):
                return subprocess.run(['bash', '-e', '-c', block],
                                      env=dict(os.environ, ARM=arm, NEEDS=json.dumps(values)),
                                      capture_output=True, text=True, timeout=10)
            self.assertEqual(run(results).returncode, 0)
            for name, row in results.items():
                for state in ('failure', 'cancelled', 'skipped'):
                    with self.subTest(arm=arm, name=name, state=state):
                        row['result'] = state
                        self.assertNotEqual(run(results).returncode, 0)
                row['result'] = 'success'
            for name in results:
                with self.subTest(arm=arm, missing=name):
                    self.assertNotEqual(run({key: row for key, row in results.items()
                                             if key != name}).returncode, 0)


if __name__ == '__main__':
    unittest.main()
