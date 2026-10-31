"""Windows core partitions retain real unittest fixture and occurrence semantics."""
from contextlib import redirect_stderr
import io
import sys
from types import ModuleType
import unittest
from unittest import mock

from tests.test_windows_standard_suites import tool


class CorePartitionTests(unittest.TestCase):
    def setUp(self):
        self.owner = tool()
        self.flags, self.events = {}, {}
        self.modules = [ModuleType('synthetic_core_' + name) for name in ('a', 'b')]
        for module in self.modules:
            self.events[module.__name__] = []
            module.__dict__.update(unittest=unittest, flags=self.flags, events=self.events)
            exec('''
def setUpModule():
    events[__name__].append('module-up')
    if flags.get('module_skip') == __name__: raise unittest.SkipTest('module fixture skip')
def tearDownModule(): events[__name__].append('module-down')
class Cases(unittest.TestCase):
    @classmethod
    def setUpClass(cls): events[__name__].append('class-up')
    @classmethod
    def tearDownClass(cls): events[__name__].append('class-down')
    def run(self, result=None):
        if flags.get('incomplete') == __name__: return result
        return super().run(result)
    def test_case(self):
        events[__name__].append('case')
        if flags.get('failure') == __name__: self.fail('synthetic failure')
        for value in (1, 2):
            with self.subTest(value=value): self.assertGreater(value, 0)
    @unittest.skip('ordinary skip')
    def test_skip(self): pass
class Suppressed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        events[__name__].append('fixture-skip')
        raise unittest.SkipTest('class fixture skip')
    def test_case(self): raise AssertionError('skipped fixture executed a case')
''', module.__dict__)
        patched = mock.patch.dict(sys.modules, {module.__name__: module for module in self.modules})
        patched.start()
        self.addCleanup(patched.stop)
        discovery = mock.patch.object(unittest.defaultTestLoader, 'discover', side_effect=self.suite)
        self.discovery = discovery.start()
        self.addCleanup(discovery.stop)

    def suite(self, *_args, **_kwargs):
        first, second = self.modules
        return unittest.TestSuite([first.Cases('test_case'), first.Cases('test_case'),
                                   second.Cases('test_case'), second.Cases('test_skip'),
                                   second.Suppressed('test_case'), second.Suppressed('test_case')])

    def record(self, selection):
        with redirect_stderr(io.StringIO()):
            result = self.owner.run_suites(selection)[0]
        self.discovery.assert_called_with('tests', 'test*.py', '.')
        return result

    def compare(self, whole, parts):
        for report in parts:
            self.assertEqual(report['inventory'], whole['inventory'])
        for field in ('selected', 'cases', 'events', 'fixture_skipped'):
            self.assertEqual(whole[field], [row for part in parts for row in part[field]])
        self.assertEqual(whole['tests'], sum(part['tests'] for part in parts))
        self.assertEqual(whole['skipped'], sum(part['skipped'] for part in parts))

    def test_core_partitions_preserve_order_duplicates_subtests_skips_and_fixture_groups(self):
        whole = self.record('core')
        fixtures = {name: list(events) for name, events in self.events.items()}
        for events in self.events.values():
            events.clear()
        parts = [self.record(name) for name in ('core-first', 'core-second')]
        self.compare(whole, parts)
        self.assertTrue(whole['success'] and all(part['success'] for part in parts))
        self.assertEqual(self.events, fixtures)
        self.assertEqual(fixtures['synthetic_core_a'],
                         ['module-up', 'class-up', 'case', 'case', 'class-down', 'module-down'])
        self.assertEqual(fixtures['synthetic_core_b'],
                         ['module-up', 'class-up', 'case', 'class-down', 'fixture-skip', 'module-down'])
        self.assertEqual(parts[0]['selected'], whole['inventory'][:2])
        self.assertEqual(parts[1]['selected'], whole['inventory'][2:])
        self.assertEqual(len(whole['cases']), 4)
        self.assertEqual(len(whole['events']), 7)
        self.assertEqual(len(whole['fixture_skipped']), 2)

    def test_module_fixture_skips_account_for_each_suppressed_occurrence(self):
        self.flags['module_skip'] = 'synthetic_core_a'
        whole = self.record('core')
        parts = [self.record(name) for name in ('core-first', 'core-second')]
        self.compare(whole, parts)
        self.assertTrue(all(part['success'] for part in parts))
        self.assertEqual(whole['fixture_skipped'], [
            'synthetic_core_a.Cases.test_case', 'synthetic_core_a.Cases.test_case',
            'synthetic_core_b.Suppressed.test_case', 'synthetic_core_b.Suppressed.test_case'])

    def test_failure_in_either_core_partition_cannot_report_success(self):
        for index, module in enumerate(self.modules):
            with self.subTest(failed=module.__name__):
                self.flags['failure'] = module.__name__
                parts = [self.record(name) for name in ('core-first', 'core-second')]
                self.assertFalse(parts[index]['success'])
                self.assertTrue(parts[1 - index]['success'])
                self.assertIn('failed', [row['outcome'] for row in parts[index]['cases']])

    def test_unexplained_missing_execution_in_either_core_partition_cannot_pass(self):
        for index, module in enumerate(self.modules):
            with self.subTest(incomplete=module.__name__):
                self.flags['incomplete'] = module.__name__
                parts = [self.record(name) for name in ('core-first', 'core-second')]
                self.assertFalse(parts[index]['success'])
                self.assertTrue(parts[1 - index]['success'])
                self.assertLess(len(parts[index]['cases']) + len(parts[index]['fixture_skipped']),
                                len(parts[index]['selected']))


if __name__ == '__main__':
    unittest.main()
