"""Windows suite selection preserves discovery and rejects incomplete evidence."""
import collections
from contextlib import redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def tool():
    spec = importlib.util.spec_from_file_location('windows_suites', ROOT / 'tools/windows_standard.py')
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    return owner


class SuiteSelectionTests(unittest.TestCase):
    def test_default_and_split_preserve_commands_and_execution_outcomes(self):
        owner = tool()
        calls = []
        def program(args, worker):
            calls.append(args)
            self.assertIsNone(worker)
            native = 'tests.test_windows_native_lifecycle' in args
            ids = ['native.case'] if native else ['core.case', 'core.case']
            report = dict(complete=True, inventory=ids, selected=ids,
                          cases=[dict(id=name, outcome='passed') for name in ids], events=[],
                          fixture_skipped=[], summary=dict(testsRun=len(ids), skipped=0))
            return mock.Mock(report=lambda: report)
        with mock.patch.object(owner, 'Program', side_effect=program):
            combined = owner.run_suites()
            commands = list(calls)
            calls.clear()
            split = owner.run_suites('core') + owner.run_suites('native')
        self.assertEqual([row['suite'] for row in combined], ['core', 'native'])
        self.assertEqual([{k: v for k, v in row.items() if k != 'elapsed_s'} for row in combined],
                         [{k: v for k, v in row.items() if k != 'elapsed_s'} for row in split])
        self.assertEqual(commands, calls)
        self.assertIn('discover', commands[0])
        self.assertEqual(commands[1][-4:], [
            'tests.test_windows_native_lifecycle', 'tests.test_windows_acl_native',
            'tests.test_windows_task_cohort', 'tests.test_windows_shortcut_recovery'])

    def test_real_recording_preserves_duplicate_cases_skips_and_failures(self):
        owner = tool()
        class Cases(unittest.TestCase):
            def test_pass(self):
                with self.subTest(path='/synthetic/profile'):
                    self.assertTrue(True)
            @unittest.skip('synthetic skip')
            def test_skip(self): pass
            def test_fail(self): self.fail('synthetic failure')
        suite = lambda: unittest.TestSuite([Cases('test_pass'), Cases('test_pass'), Cases('test_skip')])
        with redirect_stderr(io.StringIO()), \
                mock.patch.object(unittest.defaultTestLoader, 'discover', side_effect=lambda *_a, **_k: suite()):
            report = owner.run_suites('core')[0]
        self.assertTrue(report['success'])
        self.assertEqual(report['tests'], 3)
        self.assertEqual(report['skipped'], 1)
        self.assertNotIn('/synthetic/profile', json.dumps(report))
        self.assertEqual(len(report['events']), 2)
        self.assertEqual(collections.Counter(report['inventory']),
                         collections.Counter(row['id'] for row in report['cases']))
        for mode in ('core', 'native'):
            with self.subTest(mode=mode), redirect_stderr(io.StringIO()), \
                    mock.patch.object(unittest.defaultTestLoader, 'discover',
                                      return_value=unittest.TestSuite([Cases('test_fail')])), \
                    mock.patch.object(unittest.defaultTestLoader, 'loadTestsFromNames',
                                      return_value=unittest.TestSuite([Cases('test_fail')])):
                self.assertFalse(owner.run_suites(mode)[0]['success'])

    def test_invalid_selection_is_rejected_before_discovery(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/windows_standard.py'),
                                 '--sid', 'synthetic', '--suite', 'unknown'],
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('invalid choice', result.stderr)


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell is required to execute the report validator')
class ReportValidationTests(unittest.TestCase):
    def validate(self, report, suite='all', exit_code=0):
        # Extract and execute the actual function without launching a Windows account.
        command = '''
param($Script, $Report, $Suite, $Code)
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Script, [ref]$null, [ref]$null)
$function = $ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Assert-StandardReport'}, $false)
if (-not $function) { throw 'Report validator is missing' }
. ([scriptblock]::Create($function.Extent.Text))
Assert-StandardReport -Path $Report -Suite $Suite -Sid 'synthetic-sid' -ExitCode $Code | Out-Null
'''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'validate.ps1').write_text(command)
            path = root / 'report.json'
            if report is not None:
                path.write_text(report if isinstance(report, str) else json.dumps(report))
            return subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File',
                                   str(root / 'validate.ps1'), str(ROOT / 'tools/run_windows_standard.ps1'),
                                   str(path), suite, str(exit_code)],
                                  capture_output=True, text=True, timeout=15)

    @staticmethod
    def report(names=('core', 'native')):
        return dict(sid='synthetic-sid', elevated=False, status=0,
                    suites=[dict(suite=name, tests=2, skipped=0, success=True) for name in names])

    def test_valid_all_core_and_native_reports(self):
        for mode, names in (('all', ('core', 'native')), ('core', ('core',)), ('native', ('native',))):
            with self.subTest(mode=mode):
                result = self.validate(self.report(names), mode)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_malformed_wrong_identity_and_wrong_suites_fail(self):
        invalid = [None, '{', self.report(('core',)), self.report(('core', 'core')),
                   self.report(('native', 'core')), self.report(('core', 'unknown'))]
        for key, value in (('sid', 'foreign-sid'), ('elevated', True), ('status', 1)):
            report = self.report()
            report[key] = value
            invalid.append(report)
        for report in invalid:
            with self.subTest(report=report):
                self.assertNotEqual(self.validate(report).returncode, 0)

    def test_failed_empty_skipped_native_and_nonzero_process_cannot_pass(self):
        for key, value in (('success', False), ('success', 'true'), ('tests', 0), ('skipped', 1)):
            report = self.report(('native',))
            report['suites'][0][key] = value
            with self.subTest(key=key, value=value):
                self.assertNotEqual(self.validate(report, 'native').returncode, 0)
        self.assertNotEqual(self.validate(self.report(), exit_code=1).returncode, 0)
