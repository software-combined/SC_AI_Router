"""The benchmark sweep must mirror the shipped rule exactly, offline.

Two accuracy defects here were found by review rather than by the paid rerun:
truncations counted without the shipped `len > 300` gate, and a hit column
that mixed dropped-unknown with valuable. These cases pin both, plus the
threshold boundary, with no provider call and no archive read.
"""
import importlib.util
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    'bench_jev_compaction', _ROOT / 'tools' / 'bench_jev_compaction.py')
bench = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bench)


def record(facts, call, label='valuable', chars=400, pid='p1'):
    return {'session': 's.jsonl', 'scores': {pid: {'facts': facts, 'call': call}},
            'labels': {pid: label}, 'pair_output_chars': {pid: chars}}


class SweepTests(unittest.TestCase):
    def row(self, records, theta=0.5):
        return bench.sweep(records)[theta]

    def test_covered_and_unneeded_drops_a_short_output_without_truncating(self):
        row = self.row([record(0.9, 0.2, chars=100)])
        self.assertEqual((row['dropped'], row['dropped_valuable'], row['truncated']),
                         (1, 1, 0))

    def test_a_truncation_needs_the_shipped_character_gate(self):
        short = self.row([record(0.9, 0.9, chars=300)])
        long = self.row([record(0.9, 0.9, chars=301)])
        self.assertEqual((short['truncated'], long['truncated']), (0, 1))
        self.assertEqual((short['truncated_valuable'], long['truncated_valuable']),
                         (0, 1))

    def test_dropped_unknown_never_lands_in_a_valuable_column(self):
        row = self.row([record(0.9, 0.2, label='unknown')])
        self.assertEqual(
            (row['dropped'], row['dropped_valuable'], row['dropped_unknown']),
            (1, 0, 1))

    def test_the_facts_threshold_is_inclusive(self):
        # At exactly the threshold the facts count as covered, so the pair
        # drops (the call is below); one step lower keeps it.
        at = self.row([record(0.5, 0.2)], theta=0.5)
        under = self.row([record(0.49, 0.2)], theta=0.5)
        self.assertEqual(at['dropped'], 1)
        self.assertEqual(under['dropped'], 0)

    def test_the_grid_separates_the_measured_maximum(self):
        # The sample's highest score is 0.83, so 0.80 and 0.85 must differ.
        surviving = {theta: bench.sweep([record(0.83, 0.2)])[theta]['dropped']
                     for theta in (0.80, 0.85)}
        self.assertEqual(surviving, {0.80: 1, 0.85: 0})


class SessionIsolationTests(unittest.TestCase):
    def test_one_unreadable_session_does_not_lose_the_run(self):
        # A per-session failure must never lose a whole (possibly paid) run:
        # the guard records the session and moves on. A field-less output is
        # refused by the module itself, so this pins the guard directly.
        def msg(role, text):
            return {'type': 'message', 'role': role,
                    'content': [{'type': 'input_text', 'text': text}]}
        items = [msg('user', 'task'), msg('assistant', 'tail')]
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / 'broken.jsonl'
            broken.write_text(''.join(
                json.dumps({'type': 'response_item', 'payload': item}) + '\n'
                for item in items))
            with mock.patch.object(bench.jev_compaction, 'summary',
                                   side_effect=TypeError('unreadable')):
                result = bench.measure(broken)
        self.assertEqual(result['session'], 'broken.jsonl')
        self.assertEqual(result['items'], len(items))
        self.assertEqual(result['error'], 'unreadable')
        # The record must survive the rest of the harness: aggregation,
        # the sweep and the spend sum all read these keys.
        self.assertEqual(bench.sweep([result])[0.5]['dropped'], 0)
        self.assertEqual(sum(r['est_cost_usd'] for r in [result]), 0.0)

    def test_a_live_run_is_capped(self):
        with self.assertRaises(SystemExit):
            bench.main(['--live', '--limit', str(bench.LIVE_LIMIT + 1)])


class SweepMirrorsTheShippedRuleTests(unittest.TestCase):
    """The sweep and the shipped rule must agree on every quadrant."""

    def _shipped(self, facts, call, chars=800):
        import os
        from ai_router import jev_compaction as jev, provider_defs
        home = Path(tempfile.mkdtemp(prefix='jev-mirror-'))
        (home / 'jev-compaction').write_text('on\n')
        items = [{'type': 'message', 'role': 'user',
                  'content': [{'type': 'input_text', 'text': 'task'}]},
                 {'type': 'function_call', 'call_id': 'a', 'name': 'tool_a',
                  'arguments': '{}'},
                 {'type': 'function_call_output', 'call_id': 'a',
                  'output': 'x' * chars}]
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
            result = jev.summary('z-ai/glm-5.3-flash', 'k', items,
                                 provider_defs.OPENROUTER, home=home, ask=asker)
        return result or ''

    def test_every_quadrant_matches(self):
        for facts, call, chars, dropped, truncated in (
                (0.95, 0.10, 800, True, False),
                (0.95, 0.95, 800, False, True),
                (0.10, 0.95, 800, False, False),
                (0.95, 0.95, 100, False, False)):
            with self.subTest(facts=facts, call=call, chars=chars):
                result = self._shipped(facts, call, chars)
                row = bench.sweep([record(facts, call, chars=chars)])[0.90]
                self.assertEqual('tool_a' not in result, dropped)
                self.assertEqual('characters removed' in result, truncated)
                self.assertEqual(row['dropped'], int(dropped))
                self.assertEqual(row['truncated'], int(truncated))


if __name__ == '__main__':
    unittest.main()
