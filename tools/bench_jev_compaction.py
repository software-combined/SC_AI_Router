"""Replay archived Codex sessions through the shipped Jev compaction.

Read-only over the archive. Offline by default: the asker returns fixed
answers so the mechanics (windows, pairs, labels, budgets, rendering) can be
measured without a single provider call. `--live` forwards every batch to the
real endpoint and bills the router's OpenRouter key; keep the batch count
small and the spend inside the goal cap.

    python3.14 tools/bench_jev_compaction.py --limit 20            # offline
    python3.14 tools/bench_jev_compaction.py --limit 5 --live      # billed

The labels are heuristics, not ground truth: `redundant` means an identical
call plus identical output appears elsewhere in the same window, `valuable`
means the output carries a failure, test, or mutation marker. Everything else
is `unknown`. The report says so, and the sweep is read against them.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_router import compaction, decisions, jev_compaction, provider_defs  # noqa: E402

ARCHIVE = Path.home() / '.codex' / 'archived_sessions'
ITEM_TYPES = (frozenset(compaction.CALL_TYPES) | frozenset(compaction.OUTPUT_TYPES)
              | {'message', 'reasoning', 'agent_message', 'tool_search_output'})
WINDOW_ITEMS = 160
THRESHOLDS = (0.50, 0.60, 0.70, 0.80, 0.85, 0.90, 0.95, 0.99)
# A live run bills the router's key; the goal caps total spend well below
# this, and a larger batch is always a mistake rather than an experiment.
LIVE_LIMIT = 200
MUTATION = re.compile(
    r'\b(apply_patch|git (commit|push|merge)|npm i|pip install|rm -|mv |mkdir)\b')
VALUABLE = re.compile(
    r'(FAILED|Traceback|AssertionError|ERROR|error:|Exception|'
    r'passed|OK \(|refus|denied|conflict)', re.I)


def key():
    """The router's own credential order; never printed."""
    env = os.environ.get('OPENROUTER_API_KEY', '').strip()
    if env:
        return env
    path = Path.home() / '.codex' / 'mixed-model-router' / 'openrouter.key'
    if path.exists():
        return path.read_text().strip()
    return json.loads((Path.home() / '.local/share/opencode/auth.json')
                      .read_text())['openrouter']['key']


def load_items(path):
    """Responses-shaped items from one archived rollout, in order."""
    items = []
    for line in path.read_text(errors='replace').splitlines():
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        payload = doc.get('payload') if doc.get('type') == 'response_item' else None
        if isinstance(payload, dict) and payload.get('type') in ITEM_TYPES:
            items.append(payload)
    return items


def window(items, limit=WINDOW_ITEMS):
    """The tail Codex would carry into a compaction."""
    return items[-limit:] if len(items) > limit else items


def _fingerprint(items, pair):
    """(arguments text, output text) for a pair, for duplicate detection."""
    call, output = pair
    args = items[call].get('arguments', items[call].get('input'))
    return json.dumps(args, sort_keys=True), jev_compaction._output(items[output])


def label_pairs(items, pairs):
    """Heuristic labels: redundant, valuable, or unknown. Never ground truth."""
    seen = {}
    for pair in pairs:
        seen.setdefault(_fingerprint(items, pair), []).append(pair)
    labels = {}
    for pair in pairs:
        call, output = pair
        args = json.dumps(items[call].get('arguments', items[call].get('input')))
        if len(seen[_fingerprint(items, pair)]) > 1:
            labels[pair] = 'redundant'
        elif MUTATION.search(args) or VALUABLE.search(jev_compaction._output(items[output])):
            labels[pair] = 'valuable'
        else:
            labels[pair] = 'unknown'
    return labels


def _stub(payload, questions, defn=None, key=None):
    """Offline asker: nothing is covered, so nothing is dropped or shortened."""
    return {qid: {'type': 'noul',
                  'value': 1.0 if qid.endswith('_call') else 0.0}
            for qid in questions}


def measure(path, live=False, timeout=5.0, window_items=WINDOW_ITEMS):
    """One session through the shipped module; the raw scores are captured."""
    items = window(load_items(path), window_items)
    if not items:
        return None
    capture = {}

    def asker(payload, questions, defn=None, key=None):
        capture['payload'] = payload
        capture['questions'] = questions
        answers = (decisions.ask(payload, questions, defn=defn, key=key, timeout=timeout)
                   if live else _stub(payload, questions))
        capture['answers'] = answers
        return answers

    # A throwaway home: the archive stays read-only, the live router home
    # never gains a flag file, and nothing is left behind in /tmp.
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='jev-bench-') as tmp:
        home = Path(tmp)
        (home / 'jev-compaction').write_text('on\n')
        try:
            result = jev_compaction.summary('deepseek/deepseek-v4.1-flash',
                                            key() if live else 'x', items,
                                            provider_defs.OPENROUTER, home=home,
                                            ask=asker)
        except (TypeError, ValueError, KeyError):
            # One malformed archived session must not lose the whole run.
            return {'session': path.name, 'items': len(items),
                    'error': 'unreadable', 'candidate_pairs': 0,
                    'state_bytes': 0, 'rendered_bytes': 0, 'elapsed_ms': 0.0,
                    'asked': 0, 'scores': {}, 'labels': {},
                    'pair_output_chars': {}, 'calls': 0, 'outputs': 0,
                    'unmatched_calls': 0, 'unmatched_outputs': 0,
                    'code': 'seed_error', 'est_cost_usd': 0.0}
    elapsed = round((time.monotonic() - started) * 1000, 1)
    questions = capture.get('questions') or {}
    scores = {}
    for qid, answer in (capture.get('answers') or {}).items():
        name, _, which = qid.partition('_')
        scores.setdefault(name, {})[which] = answer['value']
    try:
        pairs, _last_user = jev_compaction._pairs(items)
        code = 'ok'
    except decisions.DecisionError as exc:
        pairs = []
        code = exc.code
    calls = [i for i, item in enumerate(items)
             if item.get('type') in compaction.CALL_TYPES | {'tool_search_call'}]
    outputs = [i for i, item in enumerate(items)
               if item.get('type') in compaction.OUTPUT_TYPES | {'tool_search_output'}]
    call_ids = {items[i].get('call_id') for i in calls if items[i].get('call_id')}
    out_ids = {items[i].get('call_id') for i in outputs if items[i].get('call_id')}
    counts = {
        'code': code,
        'calls': len(calls),
        'outputs': len(outputs),
        'unmatched_calls': len(call_ids - out_ids),
        'unmatched_outputs': len(out_ids - call_ids),
    }
    labels = label_pairs(items, pairs)
    state_bytes = len(json.dumps(capture.get('payload') or {}))
    return {
        'session': path.name,
        'items': len(items),
        'candidate_pairs': len(pairs),
        'state_bytes': state_bytes,
        'rendered_bytes': len(result.encode()) if result else 0,
        'elapsed_ms': elapsed,
        'asked': len(questions),
        'scores': scores,
        **counts,
        'labels': {f'p{i + 1}': labels.get(pair, '?') for i, pair in enumerate(pairs)},
        # Characters, not bytes: the shipped rule compares len(text) > 300.
        'pair_output_chars': {f'p{i + 1}': len(jev_compaction._output(items[pair[1]]))
                              for i, pair in enumerate(pairs)},
        'est_cost_usd': (round(state_bytes / 4 * 0.042 / 1_000_000, 8)
                         if live else 0.0),
    }


def sweep(records):
    """Drop, keep and truncate outcomes per threshold, read against labels.

    A truncation counts only when the shipped rule would actually shorten the
    output (over 300 characters), and the hit columns stay separate so a
    dropped unknown pair is never reported as a marker hit.
    """
    table = {}
    for theta in THRESHOLDS:
        row = {'dropped': 0, 'truncated': 0, 'missed_redundant': 0,
               'dropped_valuable': 0, 'dropped_unknown': 0,
               'truncated_valuable': 0, 'examples': []}
        examples = []
        for record in records:
            for pid, scores in record['scores'].items():
                label = record['labels'].get(pid, '?')
                facts, call = scores.get('facts'), scores.get('call')
                if facts is None or call is None:
                    continue
                if facts >= theta and call < theta:
                    row['dropped'] += 1
                    if label == 'valuable':
                        row['dropped_valuable'] += 1
                        examples.append((record['session'][-12:], pid, label))
                    elif label == 'unknown':
                        row['dropped_unknown'] += 1
                        examples.append((record['session'][-12:], pid, label))
                elif facts >= theta and record['pair_output_chars'].get(pid, 0) > 300:
                    row['truncated'] += 1
                    if label == 'valuable':
                        row['truncated_valuable'] += 1
                        examples.append((record['session'][-12:], pid,
                                         'trunc-' + label))
                elif label == 'redundant':
                    row['missed_redundant'] += 1
        row['examples'] = examples[:3]
        table[theta] = row
    return table


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=10,
                        help='how many archived sessions to replay')
    parser.add_argument('--window', type=int, default=WINDOW_ITEMS,
                        help='tail items to replay as one compaction input')
    parser.add_argument('--live', action='store_true',
                        help='send each batch to the endpoint (billed)')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--records', help='write the full JSON report to this path')
    args = parser.parse_args(argv)
    if args.live and args.limit > LIVE_LIMIT:
        raise SystemExit(f'--live is capped at {LIVE_LIMIT} sessions per run')
    sessions = sorted(ARCHIVE.glob('*.jsonl'), key=lambda p: p.stat().st_size,
                      reverse=True)[:args.limit]
    records = [r for r in (measure(path, live=args.live, window_items=args.window)
                           for path in sessions) if r]
    report = {'live': args.live, 'sessions': len(records), 'records': records,
              'sweep': sweep(records),
              'spend_usd': round(sum(r['est_cost_usd'] for r in records), 6)}
    if args.records:
        Path(args.records).write_text(json.dumps(report, indent=1))
    if args.json:
        print(json.dumps(report, indent=1))
        return 0
    for record in records:
        print(f"{record['session'][-24:]} items={record['items']:4d} "
              f"pairs={record['candidate_pairs']:3d} state={record['state_bytes']:6d}B "
              f"rendered={record['rendered_bytes']:6d}B asked={record['asked']:3d} "
              f"{record['elapsed_ms']:8.1f}ms")
    print('\nthreshold  dropped  truncated  missed_redundant  '
          'drop_val  drop_unk  trunc_val')
    for theta, row in report['sweep'].items():
        print(f'{theta:9.2f}  {row["dropped"]:7d}  {row["truncated"]:9d}  '
              f'{row["missed_redundant"]:16d}  {row["dropped_valuable"]:8d}  '
              f'{row["dropped_unknown"]:8d}  {row["truncated_valuable"]:9d}')
    print(f'\nspend (estimated): ${report["spend_usd"]:.6f}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
