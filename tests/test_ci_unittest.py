"""The bounded CI runner preserves cases and cannot hide failed workers."""
import collections
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / 'tools/ci_unittest.py'


class CiUnittestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def module(self, name, body):
        (self.root / f'test_{name}.py').write_text(
            'import os, signal, subprocess, sys, time, unittest\n'
            'from pathlib import Path\n' + body, encoding='utf-8')

    def command(self, workers):
        return [sys.executable, str(RUNNER), '--workers', str(workers),
                '--report', str(self.root / 'report.json'), '--',
                'discover', '-s', str(self.root), '-t', str(self.root)]

    def run_suite(self, workers):
        return subprocess.run(self.command(workers), cwd=self.root, text=True,
                              capture_output=True, timeout=15,
                              env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})

    def report(self):
        return json.loads((self.root / 'report.json').read_text(encoding='utf-8'))

    @unittest.skipUnless(os.name == 'posix', 'two CI workers use POSIX process groups')
    def test_duplicate_cases_fixtures_skips_and_subtests_match_one_worker(self):
        self.module('a', '''
events = []
def setUpModule(): events.append('module-up')
def tearDownModule():
    assert events == ['module-up', 'class-up', 'case', 'case', 'class-down'], events
class A(unittest.TestCase):
    @classmethod
    def setUpClass(cls): events.append('class-up')
    @classmethod
    def tearDownClass(cls): events.append('class-down')
    def test_case(self): events.append('case')
def load_tests(loader, tests, pattern):
    return unittest.TestSuite([A('test_case'), A('test_case')])
''')
        self.module('b', '''
class B(unittest.TestCase):
    def test_subtests(self):
        for value in (1, 2):
            with self.subTest(value=value): self.assertGreater(value, 0)
    @unittest.skip('synthetic skip')
    def test_skip(self): pass
''')
        reports = []
        for workers in (1, 2):
            run = self.run_suite(workers)
            self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
            reports.append(self.report())
        for key in ('inventory', 'cases', 'events'):
            canonical = lambda rows: collections.Counter(json.dumps(r, sort_keys=True) for r in rows)
            self.assertEqual(canonical(reports[0][key]), canonical(reports[1][key]))
        self.assertEqual(len(reports[1]['cases']), 4)
        self.assertEqual(reports[1]['summary']['skipped'], 1)
        self.assertEqual(len(reports[1]['events']), 2)

    @unittest.skipUnless(os.name == 'posix', 'two CI workers use POSIX process groups')
    def test_failure_propagates_from_either_worker_in_either_completion_order(self):
        for failed in ('a', 'b'):
            for slow in ('a', 'b'):
                with self.subTest(failed=failed, slow=slow):
                    for name in ('a', 'b'):
                        self.module(name, f'''
class Case(unittest.TestCase):
    def test_case(self):
        time.sleep({0.2 if name == slow else 0})
        self.assertTrue({name != failed})
''')
                    run = self.run_suite(2)
                    self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
                    self.assertFalse(self.report()['complete'])
                    self.assertTrue(any(row['outcome'] == 'failed' for row in self.report()['cases']),
                                    run.stdout + run.stderr)

    @unittest.skipUnless(os.name == 'posix', 'cancellation uses POSIX process groups')
    def test_parent_cancellation_fails_even_when_children_exit_zero(self):
        heartbeat = self.root / 'heartbeat'
        (self.root / 'heartbeat.py').write_text('''
import signal, sys, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
while True:
    Path(sys.argv[1]).write_text(str(time.monotonic()))
    time.sleep(0.02)
''', encoding='utf-8')
        for name in ('a', 'b'):
            self.module(name, f'''
class Case(unittest.TestCase):
    def test_wait(self):
        signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
        if {name == 'a'}:
            subprocess.Popen([sys.executable, {str(self.root / 'heartbeat.py')!r}, {str(heartbeat)!r}])
        Path({str(self.root / (name + '.ready'))!r}).write_text('ready')
        time.sleep(30)
''')
        process = subprocess.Popen(self.command(2), cwd=self.root, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 8
            while not (heartbeat.exists() and all((self.root / (name + '.ready')).exists()
                                                  for name in ('a', 'b'))):
                self.assertIsNone(process.poll())
                self.assertLess(time.monotonic(), deadline, 'workers did not start')
                time.sleep(0.02)
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=8)
            self.assertNotEqual(process.returncode, 0, stdout + stderr)
            self.assertFalse(self.report()['complete'])
            self.assertTrue(self.report()['interrupted'])
            self.assertEqual(self.report()['exit_codes'], [0, 0])
            stopped = heartbeat.read_text()
            time.sleep(0.1)
            self.assertEqual(heartbeat.read_text(), stopped, 'grandchild survived cancellation')
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()

    def test_fixture_failure_cannot_be_a_complete_passing_report(self):
        self.module('a', '''
def setUpModule(): raise RuntimeError('synthetic fixture failure')
class Case(unittest.TestCase):
    def test_case(self): pass
''')
        run = self.run_suite(1)
        self.assertNotEqual(run.returncode, 0)
        self.assertFalse(self.report()['complete'])
        self.assertEqual(self.report()['events'][0]['outcome'], 'error')

    @unittest.skipUnless(os.name == 'posix', 'both worker modes use POSIX process groups')
    def test_successful_fixture_skips_preserve_unstarted_duplicate_occurrences(self):
        for fixture in ('module', 'class'):
            setup = ("def setUpModule(): raise unittest.SkipTest('fixture skip')\n" if fixture == 'module'
                     else '')
            class_setup = ("    @classmethod\n    def setUpClass(cls): raise unittest.SkipTest('fixture skip')\n"
                           if fixture == 'class' else '')
            self.module('a', setup + 'class Case(unittest.TestCase):\n' + class_setup + '''
    def test_case(self): pass
def load_tests(loader, tests, pattern):
    return unittest.TestSuite([Case('test_case'), Case('test_case')])
''')
            self.module('b', '''
class Case(unittest.TestCase):
    def test_pass(self): pass
''')
            for workers in (1, 2):
                with self.subTest(fixture=fixture, workers=workers):
                    run = self.run_suite(workers)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    report = self.report()
                    self.assertTrue(report['complete'])
                    self.assertEqual(len(report['cases']), 1)
                    self.assertEqual(report['fixture_skipped'], ['test_a.Case.test_case'] * 2)
                    self.assertEqual(report['events'][0]['reason'], 'fixture skip')
                    self.assertEqual(report['summary']['testsRun'], 1)
                    self.assertEqual(report['summary']['skipped'], 1)

    def test_unexplained_missing_cases_cannot_pass(self):
        self.module('a', '''
class Case(unittest.TestCase):
    def test_pass(self): pass
    def test_missing(self): pass
class CustomSuite(unittest.TestSuite):
    def run(self, result, debug=False):
        return unittest.TestSuite([Case('test_pass')]).run(result)
def load_tests(loader, tests, pattern):
    return CustomSuite([Case('test_pass'), Case('test_missing')])
''')
        run = self.run_suite(1)
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertFalse(self.report()['complete'])

    @unittest.skipUnless(os.name == 'posix', 'two CI workers use POSIX process groups')
    def test_worker_exit_zero_without_a_report_is_not_success(self):
        self.module('a', '''
class Case(unittest.TestCase):
    def test_exit(self): os._exit(0)
''')
        self.module('b', '''
class Case(unittest.TestCase):
    def test_pass(self): pass
''')
        run = self.run_suite(2)
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertFalse(self.report()['complete'])

    @unittest.skipUnless(os.name == 'posix', 'two CI workers use POSIX process groups')
    def test_custom_suite_is_preserved_in_one_worker_and_rejected_in_two(self):
        for name in ('a', 'b'):
            self.module(name, '''
class Case(unittest.TestCase):
    def test_pass(self): pass
class CustomSuite(unittest.TestSuite): pass
def load_tests(loader, tests, pattern):
    return CustomSuite([Case('test_pass')])
''')
        self.assertEqual(self.run_suite(1).returncode, 0)
        run = self.run_suite(2)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn('requires standard unittest suites', run.stdout + run.stderr)


if __name__ == '__main__':
    unittest.main()
