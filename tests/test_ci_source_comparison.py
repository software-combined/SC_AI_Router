"""Source comparisons run two complete independent diagnostic acceptance paths."""
import re
import unittest

from tests.test_ci_pipeline import CHECK, DIAGNOSTIC, jobs


class SourceComparisonTests(unittest.TestCase):
    def test_two_sources_run_independently_without_release_authority(self):
        caller = CHECK.parent / 'ci-source-benchmark.yml'
        text = caller.read_text()
        self.assertIn("branches: ['cyril/ci-source-bench-*']", text)
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


if __name__ == '__main__':
    unittest.main()
