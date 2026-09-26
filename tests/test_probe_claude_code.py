"""Offline checks for the bounded Claude Code multi-read probe gate."""
import importlib.util
import argparse
import json
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
    return {'type': 'tool_use', 'name': 'Read',
            'input': {'file_path': path}}


def _stream(events):
    return probe._stream_report('\n'.join(json.dumps(event) for event in events))


class MultiReadGateTest(unittest.TestCase):
    def test_sequential_reads_pass(self):
        report = _stream([
            {'type': 'assistant', 'message': {'model': 'deepseek/deepseek-v4.1-flash',
                                             'content': [_read('probe-1.txt')]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'one'}]}},
            {'type': 'assistant', 'message': {'model': 'deepseek/deepseek-v4.1-flash',
                                             'content': [_read('probe-2.txt')]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'two'}]}},
            {'type': 'result', 'result': 'MARKER-1 MARKER-2', 'is_error': False},
        ])
        self.assertTrue(report['sequential_reads'])
        self.assertTrue(probe._accepted(
            2, ['MARKER-1', 'MARKER-2'], report))

    def test_parallel_reads_fail(self):
        report = _stream([
            {'type': 'assistant', 'message': {'content': [
                _read('probe-1.txt'), _read('probe-2.txt')]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'one'},
                {'type': 'tool_result', 'tool_use_id': 'two'}]}},
            {'type': 'result', 'result': 'MARKER-1 MARKER-2', 'is_error': False},
        ])
        self.assertFalse(report['sequential_reads'])
        self.assertFalse(probe._accepted(
            2, ['MARKER-1', 'MARKER-2'], report))

    def test_error_result_fails_even_with_both_markers(self):
        report = _stream([
            {'type': 'assistant', 'message': {'content': [_read('probe-1.txt')]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'one'}]}},
            {'type': 'assistant', 'message': {'content': [_read('probe-2.txt')]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'two'}]}},
            {'type': 'result', 'result': 'MARKER-1 MARKER-2',
             'is_error': True, 'subtype': 'error_during_execution'},
        ])
        self.assertTrue(report['sequential_reads'])
        self.assertFalse(probe._accepted(
            2, ['MARKER-1', 'MARKER-2'], report))

    def test_extra_reads_fail_the_call_cap(self):
        report = _stream([
            {'type': 'assistant', 'message': {'content': [_read('probe-1.txt')]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'one'}]}},
            {'type': 'assistant', 'message': {'content': [_read('probe-2.txt')]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'two'}]}},
            {'type': 'result', 'result': 'MARKER-1 MARKER-2', 'is_error': False},
        ])
        report.update(read_calls=3, tool_calls=3,
                      read_paths=['probe-1.txt', 'probe-2.txt', 'probe-1.txt'])
        self.assertFalse(probe._accepted(
            2, ['MARKER-1', 'MARKER-2'], report))

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


if __name__ == '__main__':
    unittest.main()
