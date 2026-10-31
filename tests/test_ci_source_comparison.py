"""Source comparisons run two complete independent diagnostic acceptance paths."""
import json
import os
import re
import shutil
import subprocess
import unittest

from tests.test_ci_pipeline import CHECK, DIAGNOSTIC, jobs
from tests.test_workflows import run_block


class SourceComparisonTests(unittest.TestCase):
    def test_two_sources_run_independently_without_release_authority(self):
        caller = CHECK.parent / 'ci-source-benchmark.yml'
        text = caller.read_text()
        self.assertIn("branches: ['cyril/ci-finish-bench-*']", text)
        self.assertIn('contents: read', text)
        self.assertNotIn('secrets:', text)
        self.assertEqual(jobs(caller).keys(), {'before', 'after'})
        for arm, block in jobs(caller).items():
            self.assertNotIn('\n    needs:', '\n' + block, 'paths must not wait for each other')
            self.assertIn('uses: ./.github/workflows/windows-ci-benchmark.yml', block)
            self.assertIn('arm: ' + arm, block)
        self.assertIn('source_ref: b815fe5262168f536f06f627714112a5bfbe6ab0', jobs(caller)['before'])
        self.assertIn('source_ref: ${{ github.sha }}', jobs(caller)['after'])
        self.assertIn('name: Diagnostic acceptance (control)', jobs(DIAGNOSTIC)['test'])

    def test_each_checkout_uses_the_requested_source_and_artifacts_cannot_collide(self):
        text = DIAGNOSTIC.read_text()
        self.assertIn('workflow_call:', text)
        self.assertIn('group: windows-experiment-${{ github.ref }}-${{ inputs.arm }}', text)
        for name, block in jobs(DIAGNOSTIC).items():
            with self.subTest(job=name):
                checkouts = block.count('uses: actions/checkout@')
                self.assertEqual(checkouts, block.count('ref: ${{ inputs.source_ref || github.sha }}'))
                uploads = re.findall(r'^      - uses: actions/upload-artifact@.*?(?=^      -|\Z)',
                                     block, re.MULTILINE | re.DOTALL)
                for upload in uploads:
                    artifact = re.search(r'^          name: (.+)$', upload, re.MULTILINE)[1]
                    self.assertIn('inputs.arm', artifact)

    def test_source_mode_retains_complete_control_and_disables_only_experimental_work(self):
        pipeline = jobs(DIAGNOSTIC)
        for name in ('windows-native', 'windows-native-aggregate', 'candidate-test'):
            self.assertIn('!inputs.source_ref', pipeline[name])
        required = re.search(r'^    needs: \[([^]]+)\]', pipeline['test'], re.MULTILINE)[1]
        self.assertIn('windows-control-native', required)
        self.assertNotIn('windows-native,', required)
        self.assertIn('ARM: control', pipeline['test'])
        for name in ('installer-windows', 'windows-standard', 'desktop-menus',
                     'plugin-schedulers', 'hook-adapter'):
            with self.subTest(job=name):
                self.assertIn('*source-shell', pipeline[name])
                self.assertIn('*source-shell-check', pipeline[name])
        self.assertIn('(Get-Process -Id $PID).Path -ine $env:CI_PWSH', text := DIAGNOSTIC.read_text())
        self.assertIn("$PSVersionTable.PSVersion.ToString() -cne '7.6.9'", text)
        self.assertIn('Split-Path -Parent $env:CI_PWSH >> $env:GITHUB_PATH', text)

    def test_execution_reports_preserve_every_original_unittest_invocation(self):
        for name, block in jobs(DIAGNOSTIC).items():
            with self.subTest(job=name):
                original = re.findall(r'^        run: python -m unittest (.+)$', block, re.MULTILINE)
                recorded = re.findall(r'^        run: python tools/ci_unittest.py --workers 1 '
                                      r'--report "[^"]+" -- (.+)$', block, re.MULTILINE)
                self.assertEqual(recorded, original)
                if original:
                    self.assertIn('source-tests-*.json', block)
                    self.assertIn('always() && inputs.source_ref', block)

    def test_source_layouts_select_complete_paths_and_leave_legacy_experiments_unchanged(self):
        caller = jobs(CHECK.parent / 'ci-source-benchmark.yml')
        self.assertIn('layout: combined', caller['before'])
        self.assertIn('layout: partitioned', caller['after'])
        pipeline = jobs(DIAGNOSTIC)
        self.assertIn("layout:\n        required: true\n        type: string", DIAGNOSTIC.read_text())
        for name, layout in (('windows-control-native', 'combined'), ('test', 'combined'),
                              ('windows-native', 'partitioned'),
                              ('windows-native-aggregate', 'partitioned'), ('candidate-test', 'partitioned')):
            condition = re.search(r'^    if: (.+)$', pipeline[name], re.MULTILINE)[1]
            self.assertIn("(!inputs.source_ref || inputs.layout == '" + layout + "')", condition)
        self.assertIn("suite: ${{ fromJSON(inputs.source_ref && inputs.layout == 'partitioned' "
                      "&& '[\"core-first\",\"core-second\"]' || '[\"core\"]') }}",
                      pipeline['windows-standard'])
        self.assertIn('fail-fast: false', pipeline['windows-standard'])
        self.assertIn('suite: [native-runtime, native-shortcuts]', pipeline['windows-native'])

    @unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'layout validation runs on Ubuntu')
    def test_invalid_or_incomplete_source_layout_fails_before_verification(self):
        block = run_block('Validate comparison layout', DIAGNOSTIC.read_text())
        for source, arm, layout, accepted in (
                ('', '', '', True), ('revision', 'before', 'combined', True),
                ('revision', 'after', 'partitioned', True), ('revision', 'after', 'unknown', False),
                ('revision', 'after', '', False), ('', 'after', 'partitioned', False),
                ('revision', '', 'combined', False), ('', '', 'partitioned', False)):
            with self.subTest(source=source, arm=arm, layout=layout):
                result = subprocess.run(['bash', '-e', '-c', block], capture_output=True, text=True,
                                        env=dict(os.environ, SOURCE_REF=source, ARM=arm, LAYOUT=layout),
                                        timeout=10)
                self.assertEqual(result.returncode == 0, accepted, result.stdout + result.stderr)

    @unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'diagnostic gate runs on Ubuntu')
    def test_each_final_gate_rejects_unexpected_dependency_evidence(self):
        block = run_block('Required jobs', DIAGNOSTIC.read_text())
        for arm, gate, foreign in (('control', 'test', 'windows-native'),
                                    ('candidate', 'candidate-test', 'windows-control-native')):
            required = re.search(r'^    needs: \[([^]]+)\]', jobs(DIAGNOSTIC)[gate], re.MULTILINE)[1]
            results = {name.strip(): {'result': 'success'} for name in required.split(',')}
            results[foreign] = {'result': 'success'}
            with self.subTest(arm=arm):
                result = subprocess.run(['bash', '-e', '-c', block], capture_output=True, text=True,
                                        env=dict(os.environ, ARM=arm, NEEDS=json.dumps(results)), timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('missing or unexpected', result.stderr)


if __name__ == '__main__':
    unittest.main()
