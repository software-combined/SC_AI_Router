"""Opt-in compaction contracts; every asker and summary transport is offline."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ai_router import compaction as comp, decisions, jev_compaction as jev
from ai_router import provider_defs, providers, turn_budget

MODEL = 'z-ai/glm-5.3-flash'
DEFN = provider_defs.OPENROUTER


def message(text, role='assistant'):
    return {'type': 'message', 'role': role, 'content': text}


def pair(cid='a', size=800):
    return [{'type': 'function_call', 'call_id': cid, 'name': 'tool_' + cid,
             'arguments': '{ "exact": "' + cid + '" }\n'},
            {'type': 'function_call_output', 'call_id': cid,
             'output': cid * size}]


def history(*pairs):
    return ([message('original task', 'user')]
            + [item for p in (pairs or (pair(),)) for item in p]
            + [message(f'tail {n}') for n in range(6)]
            + [message('current task', 'user')])


def asker(facts=0, call=1):
    """Answers for one pair. Default is "not covered, the call matters": keep."""
    return mock.Mock(side_effect=lambda state, questions, **kw: {
        q: {'type': 'noul', 'value': facts if q.endswith('_facts') else call,
            'confidence': None, 'probabilities': None} for q in questions})


class JevCompactionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.flag = self.home / 'jev-compaction'
        self.flag.write_text('on')
        self.items = history()
        self.enterContext(mock.patch.dict(os.environ, {'ROUTER_HOME': str(self.home)}))
        self.live = self.enterContext(mock.patch.object(
            decisions, 'ask', side_effect=AssertionError('unstubbed billed call')))
        self.log = self.enterContext(mock.patch.object(jev, 'log_event'))

    def run_summary(self, ask=None, items=None):
        return jev.summary(MODEL, 'test-key', self.items if items is None else items,
                           DEFN, home=self.home, ask=ask if ask is not None else asker())

    def test_flags_and_off_never_asks(self):
        for value, expected in ((None, 'off'), ('', 'off'), ('on', 'on'),
                                ('on\n', 'on'), ('shadow', 'shadow'), ('ON', 'off'),
                                ('1', 'off'), ('off', 'off'), ('other', 'off')):
            if value is None:
                self.flag.unlink(missing_ok=True)
            else:
                self.flag.write_text(value)
            self.assertEqual(jev.state(self.home), expected)
            self.assertEqual(jev.state(), expected)
            if expected == 'off':
                self.assertIsNone(jev.summary(MODEL, 'key', self.items, DEFN))
        self.live.assert_not_called()
        with mock.patch.object(Path, 'read_text', side_effect=PermissionError):
            self.assertEqual(jev.state(self.home), 'off')
            self.assertIsNone(jev.summary(MODEL, 'key', self.items, DEFN))
        self.flag.write_bytes(b'\xff')
        self.assertEqual(jev.state(self.home), 'off')
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
                Path, 'home', return_value=self.home):
            default = self.home / '.codex' / 'mixed-model-router'
            default.mkdir(parents=True)
            (default / 'jev-compaction').write_text('shadow')
            self.assertEqual(jev.state(), 'shadow')

    def test_shadow_is_immutable_and_logs_only_metrics(self):
        before = copy.deepcopy(self.items)
        self.flag.write_text('shadow')
        ask = asker(1, 0)
        self.assertIsNone(self.run_summary(ask))
        self.assertEqual(self.items, before)
        ask.assert_called_once()
        self.assertEqual(self.log.call_args.args, ('compact_jev',))
        fields = self.log.call_args.kwargs
        self.assertEqual(fields['mode'], 'shadow')
        self.assertEqual(fields['dropped_pairs'], 1)
        self.assertEqual(fields['candidate_pairs'], 1)
        self.assertGreater(fields['request_bytes'], 0)
        for k, v in fields.items():
            self.assertTrue(k in ('mode', 'error') or isinstance(v, (int, float)))
        self.assertNotIn('test-key', json.dumps(fields))
        self.assertNotIn('tool_a', json.dumps(fields))

    def test_on_keeps_verbatim_and_preserves_order(self):
        self.items[1]['arguments'] = ' { "unicode": "\u00e9" }\n' * 200
        self.items[2]['output'] = ' \nRAW \u00e9\t\r\n' * 500
        before = copy.deepcopy(self.items)
        result = self.run_summary()
        parts = ['original task', 'tool_a', self.items[1]['arguments'],
                 self.items[2]['output'], 'tail 0', 'tail 5', 'current task']
        positions = [result.index(p) for p in parts]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(self.items, before)

    def test_drop_pair_truncate_only_output_or_keep_both(self):
        # The questions are positive: a high `facts` means the pair's facts
        # are already covered, a high `call` means the call still matters.
        # Only covered evidence may go, and only when the call stopped
        # mattering; otherwise it is kept, or kept with a shorter output.
        for facts, call, dropped, truncated in ((1, 0, True, False),
                (1, 1, False, True), (1, .69, True, False),
                (1, .90, False, True), (.90, 0, True, False),
                (0, 0, False, False), (0, 1, False, False),
                (.89, 0, False, False)):
            with self.subTest(facts=facts, call=call):
                result = self.run_summary(asker(facts, call))
                self.assertEqual('tool_a' not in result, dropped)
                self.assertEqual('characters removed' in result, truncated)
                if truncated:
                    self.assertIn('a' * 300 + '\n[500 characters removed.]', result)
                    # Never advise a re-run: the tool may not be idempotent.
                    self.assertNotIn('re-run', result)
                    self.assertNotIn('a' * 301, result)
                elif not dropped:
                    self.assertIn('a' * 800, result)
        result = self.run_summary(asker(0, 1), history(pair(size=100)))
        self.assertIn('a' * 100, result)
        self.assertNotIn('characters removed', result)

    def test_pinned_items_and_cross_boundary_pairs_are_never_questioned(self):
        first, crossing, tail = pair('first'), pair('cross'), pair('tail')
        pinned = [message('developer', 'developer'), message('system', 'system'),
                  comp.v2_compaction_item('prior evidence'),
                  {'type': 'tool_search_output', 'tools': []},
                  {'type': 'agent_message', 'author': 'peer', 'content': 'brief'}]
        items = first + pair('eligible') + pinned + [crossing[0]]
        items += [message('latest', 'user'), crossing[1]] + tail
        ask = asker()
        self.assertIsNotNone(self.run_summary(ask, items))
        sent, questions = ask.call_args.args
        self.assertEqual(set(sent['candidates']), {'p1'})
        self.assertIn('tool_eligible', sent['candidates']['p1']['call'])
        self.assertEqual(len(questions), 2)
        self.assertEqual(sent['task'], 'user: latest')
        self.assertEqual(len(sent['retained']), len(items) - 2)
        newest = history(pair('old'))[:-1] + pair('new')
        newest[0]['role'] = 'system'  # No user boundary; test just the newest-six pin.
        ask = asker()
        self.run_summary(ask, newest)
        self.assertIn('tool_old', ask.call_args.args[0]['candidates']['p1']['call'])
        self.assertEqual(len(ask.call_args.args[0]['candidates']), 1)

    def test_custom_patch_and_interleaved_pairs_keep_order(self):
        a, b = pair('a'), pair('b')
        a[0] = dict(type='custom_tool_call', call_id='a', name='custom', input='RAW\n')
        a[1]['type'] = 'custom_tool_call_output'
        b[0] = dict(type='apply_patch_call', call_id='b', status='completed',
                    operation={'type': 'update_file', 'diff': '+ exact\n'})
        b[1]['type'] = 'apply_patch_call_output'
        items = history([a[0], b[0], a[1], b[1]])
        ask = asker()
        result = self.run_summary(ask, items)
        positions = [result.index(s) for s in ('RAW\n', 'apply_patch_call', 'a' * 800, 'b' * 800)]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('+ exact', ask.call_args.args[0]['candidates']['p2']['call'])
        self.assertNotIn('custom', self.run_summary(asker(1, 0), items))

    def test_largest_sixteen_pairs_and_state_question_paths(self):
        items = history(*(pair(str(n), 100 + n) for n in range(20)))
        items.insert(1, {'type': 'reasoning', 'encrypted_content': 'SECRET-BLOB'})
        ask = asker(1, 0)
        result = self.run_summary(ask, items)
        sent, questions = ask.call_args.args
        self.assertEqual(len(sent['candidates']), 16)
        self.assertIn('tool_19', sent['candidates']['p1']['call'])
        self.assertNotIn('SECRET-BLOB', json.dumps(sent))
        self.assertIn('tool_0', result)  # Outside the selected sixteen.
        for qid, q in questions.items():
            self.assertEqual(q['type'], 'noul')
            self.assertIn('`candidates.' + qid.split('_')[0], q['instructions'])
            self.assertIn('`retained`', q['instructions'])
        for candidate in sent['candidates'].values():
            self.assertRegex(candidate['output'], r'^ok, \d+ chars \(omitted\)$')
        self.assertEqual(ask.call_args.kwargs, {'defn': DEFN, 'key': 'test-key'})

    def test_state_steps_down_and_then_thins_old_evidence(self):
        for count, cap, thinned in ((4, 2000, False), (20, 500, False),
                                    (80, 120, False), (400, 120, True)):
            items = history()
            items[3:3] = [message('x' * 4000) for _ in range(count)]
            ask = asker()
            result = self.run_summary(ask, items)
            self.assertIsNotNone(result)
            sent, questions = ask.call_args.args
            body = dict(model=DEFN.decisions_model, state=sent, questions=questions)
            self.assertLessEqual(len(json.dumps(body).encode()), 32 * 1024)
            if thinned:
                # A wide window keeps the newest evidence and says how much
                # older evidence it left out, instead of refusing outright.
                self.assertLess(len(sent['retained']), len(items) - 2)
                self.assertEqual(sent['retained_omitted'],
                                 len(items) - 2 - len(sent['retained']))
                self.assertIn('current task', sent['retained'][-1])
                self.assertLessEqual(max(map(len, sent['retained'])), 500)
                for question in questions.values():
                    self.assertIn('retained_omitted', question['instructions'])
            else:
                self.assertEqual(len(sent['retained']), len(items) - 2)
                self.assertEqual(max(map(len, sent['retained'])), cap)
                self.assertNotIn('retained_omitted', sent)

    def test_a_budget_nothing_can_fit_is_still_refused(self):
        ask = asker()
        with mock.patch.object(jev, 'MAX_BODY', 200):
            self.assertIsNone(self.run_summary(ask))
        ask.assert_not_called()
        self.assertEqual(self.log.call_args.kwargs['error'], 'request_too_large')

    def test_errors_partial_and_malformed_answers_fail_closed_once(self):
        for answer in (None, {}, {'extra': {}},
                       {'p1_facts': {'type': 'noul', 'value': 0}}):
            ask = mock.Mock(return_value=answer)
            self.assertIsNone(self.run_summary(ask))
            ask.assert_called_once()
        for value in (True, -1, 2, float('nan'), '0', None):
            self.assertIsNone(self.run_summary(asker(value)))
        for code in ('upstream_error', 'test-key tool_a'):
            ask = mock.Mock(side_effect=decisions.DecisionError(code, 'SECRET'))
            self.assertIsNone(self.run_summary(ask))
            ask.assert_called_once()
            self.assertIn(self.log.call_args.kwargs['error'], jev.ERROR_CODES)
            self.assertNotIn('SECRET', str(self.log.call_args))

    def test_unpairable_items_are_kept_and_never_asked_about(self):
        # None of these shapes leaves an eligible pair, so nothing is asked
        # and no such item can ever be dropped: it is simply not a candidate.
        for items in (history([pair()[0]]), history([pair()[1]]),
                      history(pair(), pair()), history(list(reversed(pair()))),
                      history([pair()[0] | {'arguments': None}, pair()[1]])):
            ask = asker()
            self.assertIsNone(self.run_summary(ask, items))
            ask.assert_not_called()
            self.assertEqual(self.log.call_args.kwargs['error'], 'no_candidates')

    def test_an_orphaned_output_no_longer_blocks_the_whole_compaction(self):
        # The measured real-world case: a tool output whose call is out of
        # window. The eligible pair is still judged, and the orphan is kept.
        items = history(pair('a'))
        items.insert(2, {'type': 'function_call_output', 'call_id': 'gone',
                         'output': 'ORPHAN-MUST-SURVIVE'})
        ask = asker(1, 0)
        result = self.run_summary(ask, items)
        ask.assert_called_once()
        self.assertIn('ORPHAN-MUST-SURVIVE', result)

    def test_context_window_uses_encoded_bytes(self):
        self.items[2]['output'] = '\u00e9' * 2000
        result = self.run_summary()
        window = int(len(result) / (turn_budget.BYTES_PER_TOKEN * .4)) + 1
        with mock.patch.object(jev.registry, 'by_slug', return_value=SimpleNamespace(
                context_window=window)):
            self.assertIsNone(self.run_summary())
            self.assertEqual(self.log.call_args.kwargs['error'], 'context_limit')
        with mock.patch.object(jev.registry, 'by_slug', return_value=None):
            ask = asker()
            self.assertIsNone(self.run_summary(ask))
            ask.assert_not_called()

    def test_v1_v2_round_trip_remember_and_unchanged_fallback(self):
        provider = providers.ExternalResponsesProvider(DEFN)
        payload = {'input': self.items}
        for mode in ('on', 'shadow', 'off'):
            self.flag.write_text(mode)
            expected = self.run_summary() if mode == 'on' else 'existing summary'
            with mock.patch.object(decisions, 'ask', side_effect=asker()), mock.patch.object(
                    provider, 'summarize', return_value='existing summary') as old, \
                    mock.patch.object(provider, '_require_summary_rows', return_value={}), \
                    mock.patch.object(providers, 'remember') as remember:
                v1 = provider.compact(MODEL, payload, 'key')
                self.assertEqual(v1[-1]['content'][0]['text'], comp.SUMMARY_PREFIX + '\n' + expected)
                v2 = provider.compact_trigger(MODEL, payload, 'key')
                self.assertEqual(comp.decode_summary(v2[0]['encrypted_content']), expected)
                self.assertEqual(old.call_count, 0 if mode == 'on' else 2)
                remember.assert_called_with(self.items, expected)
        self.assertIsNone(providers.compaction_call(providers.SubscriptionProvider(),
                          MODEL, '/responses/compact', payload))


if __name__ == '__main__':
    unittest.main()
