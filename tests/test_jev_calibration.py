"""The labelled calibration must score actions against known expectations."""
import importlib.util
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    'jev_calibration', _ROOT / 'tools' / 'probe_jev_calibration.py')
cal = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cal)


def record(expect, facts, call, chars=800, declined=False):
    return {'case': 'c', 'asked': not declined, 'declined': declined,
            'pairs': [] if declined else [
                {'id': 'a', 'expect': expect, 'facts': facts, 'call': call,
                 'chars': chars}]}


class CalibrationTests(unittest.TestCase):
    def row(self, records, theta=0.90):
        return cal.calibration(records)[theta]

    def test_a_covered_unneeded_pair_passes_when_it_is_droppable(self):
        row = self.row([record('drop', 0.95, 0.10)])
        self.assertEqual((row['correct'], row['missed_drops']), (1, 0))

    def test_an_uncovered_pair_is_a_missed_drop_not_a_false_one(self):
        row = self.row([record('drop', 0.10, 0.10)])
        self.assertEqual((row['correct'], row['false_drops'],
                          row['missed_drops']), (0, 0, 1))

    def test_dropping_a_pair_that_must_be_kept_is_a_false_drop(self):
        row = self.row([record('keep', 0.95, 0.10)])
        self.assertEqual((row['correct'], row['false_drops']), (0, 1))

    def test_shortening_a_pair_that_must_be_kept_is_truncation_harm(self):
        row = self.row([record('keep', 0.95, 0.95)])
        self.assertEqual((row['correct'], row['truncation_harm']), (0, 1))

    def test_a_call_whose_occurrence_matters_may_be_shortened(self):
        kept = self.row([record('keep_call', 0.95, 0.95)])
        dropped = self.row([record('keep_call', 0.95, 0.10)])
        self.assertEqual((kept['correct'], kept['false_drops']), (1, 0))
        self.assertEqual((dropped['correct'], dropped['false_drops']), (0, 1))

    def test_declined_windows_are_counted_and_never_scored(self):
        row = self.row([record('keep', 0.9, 0.9, declined=True)])
        self.assertEqual((row['declined'], row['total']), (1, 0))


class CaseSetTests(unittest.TestCase):
    def test_the_cases_carry_labels_only_for_known_ids(self):
        made = cal.cases()
        self.assertEqual(len(made), len(cal.SIZES) * 8)
        for name, items, expect in made:
            with self.subTest(case=name):
                self.assertTrue(items and isinstance(expect, dict))
                for action in expect.values():
                    self.assertIn(action, ('drop', 'keep', 'keep_call'))

    def test_a_live_run_is_capped(self):
        with self.assertRaises(SystemExit):
            cal.main(['--live', '--limit', str(cal.LIVE_LIMIT + 1)])


class ErrorRecordTests(unittest.TestCase):
    def test_a_judge_error_is_recorded_as_an_error_not_a_decline(self):
        import os
        from unittest import mock
        from ai_router import decisions
        boom = decisions.DecisionError('unreachable', 'judge down')
        with mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': 'x'}), \
                mock.patch.object(cal.decisions, 'ask', side_effect=boom):
            result = cal.run_case(cal.cases()[0], live=True)
        self.assertEqual(result['error'], 'unreachable')
        self.assertFalse(result['declined'])
        self.assertEqual(result['pairs'], [])


class ReplayTests(unittest.TestCase):
    def test_a_stored_report_replays_to_the_same_table_and_bands(self):
        import contextlib
        import io
        import json
        import tempfile
        with tempfile.TemporaryDirectory(prefix='jev-replay-cal-') as tmp:
            path = Path(tmp) / 'report.json'
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cal.main(['--records', str(path),
                                           '--limit', '4']), 0)
            stored = json.loads(path.read_text())
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cal.main(['--replay', str(path), '--json']), 0)
        replayed = json.loads(out.getvalue())
        self.assertEqual(replayed['calibration'], stored['calibration'])
        self.assertEqual(replayed['bands'], stored['bands'])
        self.assertEqual(replayed['decisions_model'], stored['decisions_model'])

    def test_a_malformed_replay_file_exits_cleanly(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix='jev-replay-cal-') as tmp:
            path = Path(tmp) / 'broken.json'
            for text in ('{', '[]', 'null', '{}'):
                with self.subTest(text=text):
                    path.write_text(text)
                    with self.assertRaises(SystemExit):
                        cal.main(['--replay', str(path)])


class MirrorTests(unittest.TestCase):
    """The table must mirror the shipped rule, not a private copy of it."""

    def _shipped(self, facts, call, chars=800):
        import os
        import tempfile
        from unittest import mock
        from ai_router import jev_compaction as jev, provider_defs
        tmp = tempfile.TemporaryDirectory(prefix='jev-mirror-cal-')
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        (home / 'jev-compaction').write_text('on\n')
        body = [{'type': 'function_call', 'call_id': 'a', 'name': 'tool_a',
                 'arguments': '{}'},
                {'type': 'function_call_output', 'call_id': 'a',
                 'output': 'x' * chars}]
        items = [{'type': 'message', 'role': 'user',
                  'content': [{'type': 'input_text', 'text': 'task'}]}] + body
        items += [{'type': 'message', 'role': 'assistant',
                   'content': [{'type': 'output_text', 'text': 'tail %d' % n}]}
                  for n in range(6)]
        items.append({'type': 'message', 'role': 'user',
                      'content': [{'type': 'input_text', 'text': 'go'}]})

        def asker(payload, questions, **kw):
            return {q: {'type': 'noul',
                        'value': facts if q.endswith('_facts') else call}
                    for q in questions}

        with mock.patch.dict(os.environ, {'ROUTER_HOME': str(home)}):
            return jev.summary('z-ai/glm-5.3-flash', 'k', items,
                               provider_defs.OPENROUTER, home=home, ask=asker) or ''

    def test_every_quadrant_matches_the_shipped_rule(self):
        for facts, call, chars, action in (
                (0.95, 0.10, 800, 'drop'), (0.95, 0.95, 800, 'truncate'),
                (0.10, 0.95, 800, 'keep'), (0.95, 0.95, 100, 'keep')):
            with self.subTest(facts=facts, call=call, chars=chars):
                result = self._shipped(facts, call, chars)
                shipped = ('drop' if 'tool_a' not in result
                           else 'truncate' if 'characters removed' in result
                           else 'keep')
                self.assertEqual(shipped, action)
                # The tool must read the same scores as that same action.
                expect = 'drop' if action == 'drop' else 'keep'
                row = cal.calibration([record(expect, facts, call, chars)])[0.90]
                if action == 'drop':
                    self.assertEqual((row['correct'], row['missed_drops']), (1, 0))
                elif action == 'truncate':
                    self.assertEqual((row['truncation_harm'], row['correct']), (1, 0))
                else:
                    self.assertEqual((row['correct'], row['false_drops']), (1, 0))


if __name__ == '__main__':
    unittest.main()
