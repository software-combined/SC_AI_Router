"""Offline checks for the bounded Claude Code multi-read probe gate."""
import importlib.util
import argparse
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools' / 'probe_claude_code.py'
spec = importlib.util.spec_from_file_location('probe_claude_code', SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def _read(path):
    return {'type': 'tool_use', 'id': 'toolu_' + Path(path).stem.replace('-', '_'),
            'name': 'Read',
            'input': {'file_path': path}}


def _result(path):
    return {'type': 'tool_result',
            'tool_use_id': 'toolu_' + Path(path).stem.replace('-', '_')}


def _raw_result(tool_use_id):
    return {'type': 'tool_result', 'tool_use_id': tool_use_id}


def _stream(events):
    return probe._stream_report('\n'.join(json.dumps(event) for event in events))


class MultiReadGateTest(unittest.TestCase):
    def test_candidate_uses_the_shared_attempt_guard_and_probe_output_cap(self):
        with patch('ai_router.candidate.IsolatedRouter') as scope:
            self.assertIs(probe._candidate_home('synthetic/model'), scope.return_value)
        scope.assert_called_once_with('synthetic/model', bounded=True, max_output=2048)

    def test_sequential_reads_pass(self):
        report = _stream([
            {'type': 'assistant', 'message': {'model': 'deepseek/deepseek-v4.1-flash',
                                             'content': [_read('probe-1.txt')]}},
            {'type': 'user', 'message': {'content': [
                _result('probe-1.txt')]}},
            {'type': 'assistant', 'message': {'model': 'deepseek/deepseek-v4.1-flash',
                                             'content': [_read('probe-2.txt')]}},
            {'type': 'user', 'message': {'content': [
                _result('probe-2.txt')]}},
            {'type': 'result', 'result': 'MARKER-1 MARKER-2', 'is_error': False},
        ])
        self.assertTrue(report['sequential_reads'])
        self.assertTrue(report['tool_result_ids_match'])
        self.assertTrue(probe._accepted(
            2, ['MARKER-1', 'MARKER-2'], report,
            'deepseek/deepseek-v4.1-flash'))

    def test_reversed_reads_fail_the_order_gate(self):
        report = _stream([
            {'type': 'assistant', 'message': {'model': 'deepseek/deepseek-v4.1-flash',
                                             'content': [_read('probe-2.txt')]}},
            {'type': 'user', 'message': {'content': [
                _result('probe-2.txt')]}},
            {'type': 'assistant', 'message': {'model': 'deepseek/deepseek-v4.1-flash',
                                             'content': [_read('probe-1.txt')]}},
            {'type': 'user', 'message': {'content': [
                _result('probe-1.txt')]}},
            {'type': 'result', 'result': 'MARKER-1 MARKER-2', 'is_error': False},
        ])
        self.assertTrue(report['sequential_reads'])
        self.assertFalse(probe._accepted(
            2, ['MARKER-1', 'MARKER-2'], report,
            'deepseek/deepseek-v4.1-flash'))

    def test_parallel_reads_fail(self):
        report = _stream([
            {'type': 'assistant', 'message': {'content': [
                _read('probe-1.txt'), _read('probe-2.txt')]}},
            {'type': 'user', 'message': {'content': [
                _result('probe-1.txt'), _result('probe-2.txt')]}},
            {'type': 'result', 'result': 'MARKER-1 MARKER-2', 'is_error': False},
        ])
        self.assertFalse(report['sequential_reads'])
        self.assertFalse(probe._accepted(
            2, ['MARKER-1', 'MARKER-2'], report,
            'deepseek/deepseek-v4.1-flash'))

    def test_error_result_fails_even_with_both_markers(self):
        report = _stream([
            {'type': 'assistant', 'message': {'content': [_read('probe-1.txt')]}},
            {'type': 'user', 'message': {'content': [
                _result('probe-1.txt')]}},
            {'type': 'assistant', 'message': {'content': [_read('probe-2.txt')]}},
            {'type': 'user', 'message': {'content': [
                _result('probe-2.txt')]}},
            {'type': 'result', 'result': 'MARKER-1 MARKER-2',
             'is_error': True, 'subtype': 'error_during_execution'},
        ])
        self.assertTrue(report['sequential_reads'])
        self.assertFalse(probe._accepted(
            2, ['MARKER-1', 'MARKER-2'], report,
            'deepseek/deepseek-v4.1-flash'))

    def test_extra_reads_fail_the_call_cap(self):
        report = _stream([
            {'type': 'assistant', 'message': {'content': [_read('probe-1.txt')]}},
            {'type': 'user', 'message': {'content': [
                _result('probe-1.txt')]}},
            {'type': 'assistant', 'message': {'content': [_read('probe-2.txt')]}},
            {'type': 'user', 'message': {'content': [
                _result('probe-2.txt')]}},
            {'type': 'result', 'result': 'MARKER-1 MARKER-2', 'is_error': False},
        ])
        report.update(read_calls=3, tool_calls=3,
                      read_paths=['probe-1.txt', 'probe-2.txt', 'probe-1.txt'])
        self.assertFalse(probe._accepted(
            2, ['MARKER-1', 'MARKER-2'], report,
            'deepseek/deepseek-v4.1-flash'))

    def test_served_model_mismatch_fails_and_is_labelled(self):
        report = _stream([
            {'type': 'assistant', 'message': {'model': 'other/model',
                                             'content': [_read('probe-1.txt')]}},
            {'type': 'user', 'message': {'content': [
                _result('probe-1.txt')]}},
            {'type': 'assistant', 'message': {'model': 'other/model',
                                             'content': [_read('probe-2.txt')]}},
            {'type': 'user', 'message': {'content': [
                _result('probe-2.txt')]}},
            {'type': 'result', 'result': 'MARKER-1 MARKER-2', 'is_error': False},
        ])
        self.assertEqual(probe._identity('deepseek/deepseek-v4.1-flash', report),
                         'mismatched')
        self.assertFalse(probe._accepted(
            2, ['MARKER-1', 'MARKER-2'], report,
            'deepseek/deepseek-v4.1-flash'))

    def test_mismatched_duplicate_missing_or_swapped_result_ids_fail(self):
        cases = (
            ('mismatched', ['wrong-one', 'wrong-two']),
            ('duplicate', ['toolu_probe_1', 'toolu_probe_1']),
            ('missing', ['toolu_probe_1']),
            ('swapped', ['toolu_probe_2', 'toolu_probe_1']),
        )
        for label, result_ids in cases:
            with self.subTest(label=label):
                events = [
                    {'type': 'assistant', 'message': {'content': [
                        _read('probe-1.txt')]}},
                    {'type': 'user', 'message': {'content': [
                        _raw_result(result_ids[0])]}},
                    {'type': 'assistant', 'message': {'content': [
                        _read('probe-2.txt')]}},
                ]
                if len(result_ids) == 2:
                    events.append({'type': 'user', 'message': {
                        'content': [_raw_result(result_ids[1])]}})
                events.append({'type': 'result', 'result': 'MARKER-1 MARKER-2',
                               'is_error': False})
                report = _stream(events)
                self.assertFalse(report['tool_result_ids_match'])
                self.assertFalse(probe._accepted(
                    2, ['MARKER-1', 'MARKER-2'], report,
                    'deepseek/deepseek-v4.1-flash'))

    def test_truthful_id_resolves_to_served_upstream_identity(self):
        slug = 'deepseek/deepseek-v4.1-flash'
        alias = slug
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'current').write_text('1')
            release = home / 'releases' / '1' / 'ai_router'
            release.mkdir(parents=True)
            (release / 'models.json').write_text(json.dumps([
                {'slug': slug, 'upstream_id': 'deepseek/served'}]))
            expected = probe._expected_model(home, alias)
        self.assertEqual(expected, 'deepseek/served')
        report = {'result': 'MARKER', 'served': [expected]}
        self.assertEqual(probe._identity(expected, report), 'matched')
        self.assertTrue(probe._accepted(1, ['MARKER'], report, expected))

    def test_candidate_alias_uses_its_explicit_source_registry(self):
        slug = 'z-ai/glm-5.3-flash'
        alias = slug
        rows = [{'slug': slug, 'upstream_id': 'synthetic/served'}]
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            expected = probe._expected_model(home, alias, rows)
            self.assertEqual(expected, 'synthetic/served')
            self.assertEqual(probe._expected_model(home, alias), alias)
            args = SimpleNamespace(models=[alias], max_rows=1, deferred=True,
                max_legs=2, read_count=1, effort='low', max_budget_usd=None, json=True)
            with patch.object(probe, 'probe', return_value={'pass': True}) as client:
                probe._legs(args, home, rows)
            self.assertEqual(client.call_args.kwargs['expected_model'], expected)

    def test_budget_must_be_finite_and_positive(self):
        for value in ('nan', 'inf', '-inf', '0', '-1'):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    probe._positive_budget(value)
        self.assertEqual(probe._positive_budget('0.10'), 0.10)

    def test_budgeted_multi_leg_runs_are_rejected(self):
        args = SimpleNamespace(
            models=['model-a', 'model-b'], max_rows=2, deferred=False,
            max_legs=2, read_count=2, effort='max', max_budget_usd=1.0,
            json=True)
        with patch.object(probe, 'probe') as fake:
            with self.assertRaises(SystemExit) as raised:
                probe._legs(args, Path('/tmp'))
        self.assertEqual(raised.exception.code, 2)
        fake.assert_not_called()


class DeferredGateTests(unittest.TestCase):
    def report(self, results=('search-id', 'stub-id'), error=False):
        content = lambda name, identifier: {'type': 'tool_use', 'id': identifier,
                                            'name': name, 'input': {}}
        events = [
            {'type': 'assistant', 'message': {'model': 'fake/model', 'content': [
                content('ToolSearch', 'search-id')]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': results[0]}]}},
            {'type': 'assistant', 'message': {'model': 'fake/model', 'content': [
                content(probe.STUB_TOOL, 'stub-id')]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': results[1], 'is_error': error}]}},
            {'type': 'result', 'result': 'MARKER', 'is_error': False},
        ]
        return _stream(events)

    def test_marker_echo_without_search_or_tool_use_cannot_pass(self):
        self.assertFalse(probe._accepted(1, ['MARKER'],
            {'result': 'MARKER', 'is_error': False}, 'fake/model', deferred=True))

    def test_search_then_released_tool_with_paired_results_passes(self):
        self.assertTrue(probe._accepted(1, ['MARKER'], self.report(),
                                      'fake/model', deferred=True))

    def test_wrong_result_ids_or_tool_errors_fail_even_with_the_marker(self):
        for report in (self.report(results=('search-id', 'search-id')),
                       self.report(error=True)):
            self.assertFalse(probe._accepted(1, ['MARKER'], report,
                                           'fake/model', deferred=True))


if __name__ == '__main__':
    unittest.main()
