#!/usr/bin/env python3
"""Print a dated, workload-specific cost/quality frontier from public evidence."""
import argparse
import json
import math
from pathlib import Path

METRICS = ('intelligence', 'terminal', 'automation', 'briefcase', 'gdpval',
           'pdf', 'lcr', 'scicode', 'vision', 'omniscience', 'webdev')


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def candidates(data, metric, cost, input_tokens, output_tokens):
    if cost == 'aa_task' and metric != 'intelligence':
        raise ValueError('AA suite cost/task is comparable here only to the AA Intelligence Index.')
    if any(not finite(n) or n < 0 for n in (input_tokens, output_tokens)):
        raise ValueError('Token counts must be finite and nonnegative.')
    included, excluded = [], []
    for row in data['models']:
        prescribed_effort = data['prescribed_efforts'][row['id']]
        label = row['id'] + ' / ' + row['effort']
        if metric == 'webdev':
            evidence = row.get('webdev') or {}
            score = evidence.get('score')
            measured_effort = evidence.get('effort', 'unknown')
            label = row['id'] + ' / ' + measured_effort
        elif row.get('aa_eligible'):
            score = row['scores'].get(metric)
            measured_effort = row['effort']
        else:
            excluded.append(label + ': no exact AA identity')
            continue
        if measured_effort != prescribed_effort:
            excluded.append(label + ': measured effort does not match prescribed '
                            + prescribed_effort)
            continue
        if cost == 'aa_task':
            dollars = row.get('aa_task_usd')
        else:
            prices = row.get('prices_usd_per_million') or {}
            rate_in, rate_out = prices.get('input'), prices.get('output')
            dollars = ((input_tokens * rate_in + output_tokens * rate_out) / 1e6
                       if finite(rate_in) and finite(rate_out) else None)
        if not finite(score) or not finite(dollars) or dollars < 0:
            excluded.append(label + ': missing score or comparable cost')
            continue
        included.append({'model': label, 'cost_usd': dollars, 'score': score})
    return included, excluded


def frontier(rows):
    return sorted((r for r in rows if not any(
        other['cost_usd'] <= r['cost_usd'] and other['score'] >= r['score']
        and (other['cost_usd'] < r['cost_usd'] or other['score'] > r['score'])
        for other in rows)), key=lambda r: (r['cost_usd'], -r['score'], r['model']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, default=Path(__file__).resolve().parents[1]
                        / 'references/model-evidence.json')
    parser.add_argument('--metric', choices=METRICS, default='intelligence')
    parser.add_argument('--cost', choices=('aa_task', 'scenario'), default='aa_task')
    parser.add_argument('--input-tokens', type=int, default=20000)
    parser.add_argument('--output-tokens', type=int, default=5000)
    args = parser.parse_args()
    data = json.loads(args.evidence.read_text())
    try:
        rows, excluded = candidates(data, args.metric, args.cost,
                                    args.input_tokens, args.output_tokens)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps({'retrieved': data['retrieved'], 'metric': args.metric,
                      'cost_basis': args.cost, 'scenario_tokens': {
                          'uncached_input': args.input_tokens, 'billed_output': args.output_tokens}
                      if args.cost == 'scenario' else None,
                      'warning': 'Dated evidence. Scenario cost excludes caching, fees and retries; '
                      'AA cost is its benchmark bill. Neither is your cost per accepted task.',
                      'frontier': frontier(rows), 'excluded': excluded}, indent=2))


if __name__ == '__main__':
    main()
