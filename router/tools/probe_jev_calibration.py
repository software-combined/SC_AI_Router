"""Labelled calibration for the Jev compaction rule.

Every case is a small window whose correct action is known by construction,
so the sweep can report *false drops* rather than marker hits: a drop of a
pair that still carries a needed fact is a false drop, a shortening that
loses a fact past character 300 is truncation harm, and keeping a pair whose
facts are already retained elsewhere is missed savings.

Offline by default (the asker returns keep-everything answers and bills
nothing). `--live` sends one request per case through the shipped module.

    python3.14 tools/probe_jev_calibration.py                 # offline
    python3.14 tools/probe_jev_calibration.py --live --json    # billed
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_router import decisions, jev_compaction, provider_defs  # noqa: E402

LIVE_LIMIT = 200
THRESHOLDS = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85,
              0.90, 0.95, 0.99)
SIZES = (120, 290, 700)


def key():
    """The router's own credential order; never printed."""
    if os.environ.get('OPENROUTER_API_KEY', '').strip():
        return os.environ['OPENROUTER_API_KEY'].strip()
    path = Path.home() / '.codex' / 'mixed-model-router' / 'openrouter.key'
    if path.exists():
        return path.read_text().strip()
    return json.loads((Path.home() / '.local/share/opencode/auth.json')
                      .read_text())['openrouter']['key']


def _msg(role, text):
    return {'type': 'message', 'role': role,
            'content': [{'type': 'input_text', 'text': text}]}


def _pair(cid, args, output):
    return [{'type': 'function_call', 'call_id': cid, 'name': 'exec_command',
             'arguments': json.dumps({'cmd': args})},
            {'type': 'function_call_output', 'call_id': cid, 'output': output}]


def _window(task, body):
    """One window: a task, the body items, six tail messages, a final task."""
    items = [_msg('user', task)] + list(body)
    items += [_msg('assistant', f'progress note {n}') for n in range(6)]
    items.append(_msg('user', 'continue with the plan'))
    return items


def cases():
    """(name, items, expected action per candidate pair) by construction."""
    made = []
    for size in SIZES:
        filler = 'x' * size
        tail_fact = 'x' * max(0, size - 40) + ' VERDICT: the migration failed'
        made += [
            # The retained read carries the same fact: dropping is correct.
            ('retained_duplicate_%d' % size,
             _window('Summarise tests',
                     [_msg('assistant', 'earlier read of tests: ' + filler)]
                     + _pair('a', 'ls tests', 'test_feed.py ' + filler)),
             {'a': 'drop'}),
            # A unique fact lives only in this pair: nothing may be dropped.
            ('unique_fact_%d' % size,
             _window('Fix the failing test',
                     _pair('a', 'unittest tests.test_feed',
                           'FAILED test_serial_replay_guard ' + filler)),
             {'a': 'keep'}),
            # Two equal-length outputs that contradict each other: the judge
            # never sees bodies, so dropping either is unsafe.
            ('equal_length_contradiction_%d' % size,
             _window('Decide whether the deploy is safe',
                     _pair('a', 'check deploy', 'deploy is SAFE ' + filler)
                     + _pair('b', 'check deploy again',
                             'deploy is UNSAFE ' + filler)),
             {'a': 'keep', 'b': 'keep'}),
            # In the long output the verdict sits past character 300, so
            # shortening loses it; the shorter sizes stay under the cut.
            ('verdict_after_300_%d' % size,
             _window('Confirm the migration result',
                     _pair('a', 'run migration', tail_fact)),
             {'a': 'keep'}),
            # Knowing the call happened is itself the fact: keep the call.
            ('occurrence_matters_%d' % size,
             _window('Confirm the payment was sent',
                     _pair('a', 'send invoice', 'sent, id 4211 ' + filler)),
             {'a': 'keep_call'}),
            # A mutation receipt nothing else repeats.
            ('mutation_receipt_%d' % size,
             _window('Track the patch that landed',
                     _pair('a', 'apply_patch feed.py',
                           'patched feed.py, 12 insertions ' + filler)),
             {'a': 'keep'}),
            # Superseded by a later identical read that stays retained.
            ('superseded_%d' % size,
             _window('Re-check the directory listing',
                     _pair('a', 'ls tests', 'test_feed.py ' + filler)
                     + [_msg('assistant', 'later read of tests: test_feed.py '
                             + filler)]),
             {'a': 'drop'}),
            # Nothing eligible at all: the rule must decline.
            ('no_candidates_%d' % size,
             _window('Just a note', [_msg('assistant', 'nothing to run '
                                          + filler)]),
             {}),
        ]
    return made


def _offline(payload, questions, defn=None, key=None):
    """Nothing is covered, so the shipped rule keeps everything."""
    return {qid: {'type': 'noul',
                  'value': 1.0 if qid.endswith('_call') else 0.0}
            for qid in questions}


def run_case(case, live=False):
    """Per-pair scores the shipped rule would act on, plus the expectation."""
    name, items, expect = case
    capture = {}

    def asker(payload, questions, defn=None, key=None):
        capture['payload_bytes'] = len(json.dumps(payload, allow_nan=False).encode())
        try:
            capture['answers'] = (
                decisions.ask(payload, questions, defn=defn, key=key, timeout=5.0)
                if live else _offline(payload, questions))
        except decisions.DecisionError as exc:
            # A refused or unreachable judge is not a decline: keep the code,
            # or an outage would read as "nothing to do" in the report.
            capture['error'] = exc.code
            raise
        return capture['answers']

    with tempfile.TemporaryDirectory(prefix='jev-cal-') as tmp:
        home = Path(tmp)
        (home / 'jev-compaction').write_text('on\n')
        try:
            jev_compaction.summary('z-ai/glm-5.3-flash', key() if live else 'x',
                                   items, provider_defs.OPENROUTER, home=home,
                                   ask=asker)
            pairs, _last = jev_compaction._pairs(items)
        except (TypeError, ValueError, KeyError, decisions.DecisionError):
            pairs = []
    answers = capture.get('answers') or {}
    rows = []
    for n, (a, b) in enumerate(pairs, 1):
        facts = answers.get(f'p{n}_facts', {}).get('value')
        call = answers.get(f'p{n}_call', {}).get('value')
        if facts is None or call is None:
            continue
        rows.append({'id': items[a].get('call_id'),
                     'expect': expect.get(items[a].get('call_id'), 'keep'),
                     'facts': facts, 'call': call,
                     'chars': len(jev_compaction._output(items[b]))})
    error = capture.get('error')
    return {'case': name, 'asked': bool(answers), 'error': error, 'pairs': rows,
            'declined': not pairs and error is None,
            'est_cost_usd': (round(capture.get('payload_bytes', 0) / 4
                                   * 0.042 / 1_000_000, 8) if live else 0.0)}


def calibration(records):
    """Correct, false-drop, truncation-harm and missed-savings per threshold."""
    table = {}
    for theta in THRESHOLDS:
        scores = {'correct': 0, 'false_drops': 0, 'truncation_harm': 0,
                  'missed_drops': 0, 'declined': 0, 'total': 0}
        for record in records:
            if record['declined']:
                scores['declined'] += 1
            for row in record['pairs']:
                scores['total'] += 1
                covered = row['facts'] >= theta
                matters = row['call'] >= theta
                if covered and not matters:
                    action = 'drop'
                elif covered and row['chars'] > 300:
                    action = 'truncate'
                else:
                    action = 'keep'
                want = row['expect']
                if want == 'drop':
                    scores['correct'] += action == 'drop'
                    scores['missed_drops'] += action != 'drop'
                elif want == 'keep_call':
                    scores['correct'] += action != 'drop'
                    scores['false_drops'] += action == 'drop'
                else:
                    scores['correct'] += action == 'keep'
                    scores['false_drops'] += action == 'drop'
                    scores['truncation_harm'] += action == 'truncate'
        table[theta] = scores
    return table


def bands(records):
    """Score range per expectation class, so a replay re-derives the report."""
    out = {}
    for record in records:
        for row in record['pairs']:
            for kind, key in (('facts', 'facts'), ('call', 'call')):
                bucket = out.setdefault((row['expect'], kind), [])
                bucket.append(row[key])
    return {f'{expect}.{kind}': (round(min(vals), 2), round(max(vals), 2))
            for (expect, kind), vals in sorted(out.items())}


def replay(stored):
    """The report recomputed from a stored run, without another call."""
    return {'live': stored.get('live'), 'cases': len(stored['records']),
            'judged_pairs': sum(len(r['pairs']) for r in stored['records']),
            'declined': sum(1 for r in stored['records'] if r['declined']),
            'errors': [r['case'] for r in stored['records'] if r.get('error')],
            'decisions_model': stored.get('decisions_model', 'unknown'),
            'calibration': calibration(stored['records']),
            'bands': bands(stored['records']), 'records': stored['records']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true',
                        help='send one request per case (billed)')
    parser.add_argument('--limit', type=int, default=len(SIZES) * 8)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--records', help='write the JSON report here')
    parser.add_argument('--replay', help='recompute the table from a stored report')
    args = parser.parse_args(argv)
    if args.replay:
        try:
            stored = json.loads(Path(args.replay).read_text())
            if not isinstance(stored, dict):
                raise SystemExit(f'cannot replay {args.replay}: not a report object')
            report = replay(stored)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise SystemExit(f'cannot replay {args.replay}: {exc}') from None
        print(json.dumps(report, indent=1) if args.json else
              json.dumps({'bands': report['bands'],
                          'rung_0.90': report['calibration'][0.90]}, indent=1))
        return 0
    if args.live and args.limit > LIVE_LIMIT:
        raise SystemExit(f'--live is capped at {LIVE_LIMIT} cases per run')
    if args.live:
        try:
            key()
        except OSError as exc:  # a keyless run must fail cleanly, not crash
            raise SystemExit(f'no OpenRouter key available: {exc}') from None
    records = [r for r in (run_case(c, live=args.live)
                           for c in cases()[:args.limit]) if r]
    report = {'live': args.live, 'cases': len(records),
              'judged_pairs': sum(len(r['pairs']) for r in records),
              'declined': sum(1 for r in records if r['declined']),
              'errors': [r['case'] for r in records if r.get('error')],
              'decisions_model': provider_defs.OPENROUTER.decisions_model,
              'spend_usd': round(sum(r['est_cost_usd'] for r in records), 6),
              'calibration': calibration(records), 'bands': bands(records),
              'records': records}
    if args.records:
        Path(args.records).write_text(json.dumps(report, indent=1))
    if args.json:
        print(json.dumps(report, indent=1))
        return 0
    print(f"cases={report['cases']} pairs={report['judged_pairs']} "
          f"declined={report['declined']}")
    print('\ntheta  correct  false_drops  truncation_harm  missed_drops')
    for theta, row in report['calibration'].items():
        print(f'{theta:5.2f}  {row["correct"]:7d}  {row["false_drops"]:11d}  '
              f'{row["truncation_harm"]:15d}  {row["missed_drops"]:12d}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
