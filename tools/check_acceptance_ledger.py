"""Check the latest acceptance run and candidate-bound route evidence.

`docs/acceptance-ledger.json` holds one object per cell run (Plan 185). The
newest clients are the highest versions `docs/compatibility.md` names in the
backticked forms Codex desktop `X` and Claude Code `X`, where AGENTS.md
section 7 records both after every client upgrade. A cell is stale when its
latest pass ran on an older version of either client, and missing when it has
no run. Newer failures or conflicting tied runs supersede a pass.
Exit 1 when any P1 cell (C1-C4) is stale, failed or missing, or when either
file is unreadable or malformed; a stale or missing C5 is reported only.
"""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_router import candidate_evidence, registry

CELLS = ('C1', 'C2', 'C3', 'C4', 'C5')
P1 = CELLS[:4]
FIELDS = ('cell', 'date_aest', 'router_version', 'codex_version', 'claude_code_version',
          'rows', 'requested_effort', 'served', 'calls', 'result', 'notes')
CLIENTS = {'codex_version': 'Codex desktop', 'claude_code_version': 'Claude Code'}
VERSION = r'\d+(?:\.\d+)+'
DATE = r'\d{4}-\d\d-\d\d \d\d:\d\d AE[SD]T'


def version(text):
    return tuple(int(part) for part in text.split('.'))


def newest(page):
    """The highest backticked version of each client named on the page."""
    found = {}
    for field, label in CLIENTS.items():
        # Any whitespace between the words: the page is hard-wrapped, and a
        # missed newer version would make a stale cell look current.
        words = r'\s+'.join(map(re.escape, label.split()))
        names = re.findall(words + r'\s+`(' + VERSION + ')`', page)
        if not names:
            raise ValueError(f'the compatibility page names no {label} version')
        found[field] = max(names, key=version)
    return found


def load(text):
    """Ledger entries, each checked; ValueError names the first bad one."""
    entries = json.loads(text)
    if not isinstance(entries, list):
        raise ValueError('the ledger is not a JSON list')
    for index, entry in enumerate(entries):
        if isinstance(entry, dict) and entry.get('kind') == candidate_evidence.KIND:
            candidate_evidence.validate(entry)
            continue
        if not isinstance(entry, dict) or sorted(entry) != sorted(FIELDS):
            raise ValueError(f'entry {index} does not carry exactly the ledger fields')
        text_fields = [entry[f] for f in ('cell', 'date_aest', 'result', *CLIENTS)]
        if (not all(isinstance(value, str) for value in text_fields)
                or entry['cell'] not in CELLS or not re.fullmatch(DATE, entry['date_aest'])
                or not all(re.fullmatch(VERSION, entry[f]) for f in CLIENTS)
                or not isinstance(entry['calls'], int)):
            raise ValueError(f'entry {index} has a bad cell, date_aest, client version, calls or result')
        candidate_evidence.timestamp(entry)
    return entries


def report(entries, clients):
    """One line per cell, and the P1 cells that are stale or missing."""
    lines, failing = [], []
    for cell in CELLS:
        latest, error = candidate_evidence.latest([e for e in entries if e.get('cell') == cell])
        if error == 'conflicting':
            state = 'conflicting: latest runs disagree'
        elif latest is None:
            state = 'missing: no pass recorded'
        elif latest['result'] != 'pass':
            state = 'failed: latest run ' + latest['date_aest']
        else:
            old = any(version(latest[f]) < version(clients[f]) for f in CLIENTS)
            state = (('stale' if old else 'current') + ': latest pass ' + latest['date_aest']
                     + ' on ' + ', '.join(f'{label} {latest[f]}' for f, label in CLIENTS.items()))
        if cell in P1 and not state.startswith('current'):
            failing.append(cell)
        lines.append(f'{cell} {state}' + ('' if cell in P1 else ' (P2, reported only)'))
    return lines, failing


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', type=Path, default=ROOT / 'docs' / 'acceptance-ledger.json')
    parser.add_argument('--compatibility', type=Path, default=ROOT / 'docs' / 'compatibility.md')
    parser.add_argument('--model', help='check this candidate instead of historical Plan 185 cells')
    parser.add_argument('--client-version', action='append', default=[], metavar='CLIENT=VERSION')
    args = parser.parse_args(argv)
    try:
        entries = load(args.ledger.read_text())
        if args.model:
            row = registry.by_slug(args.model)
            if row is None:
                raise ValueError('model is not in this candidate registry')
            versions = dict(value.split('=', 1) for value in args.client_version)
            latest, error = candidate_evidence.latest(
                [e for e in entries if e.get('kind') == candidate_evidence.KIND
                 and (e['model'], e['provider']) == (row.slug, row.provider)])
            problems = [error] if error else candidate_evidence.problems(row, latest, clients=versions)
            print(args.model + ': ' + ('; '.join(problems) if problems else 'current route evidence'))
            return 1 if problems else 0
        clients = newest(args.compatibility.read_text())
    except (OSError, ValueError, TypeError) as exc:
        print(f'acceptance-ledger: unreadable or malformed input: {exc}', file=sys.stderr)
        return 1
    print('newest named clients: '
          + ', '.join(f'{label} {clients[f]}' for f, label in CLIENTS.items()))
    lines, failing = report(entries, clients)
    print('\n'.join(lines))
    print('acceptance-ledger: ' + ('stale or missing P1 cells: ' + ', '.join(failing)
                                   if failing else 'every P1 cell is current'))
    return 1 if failing else 0


if __name__ == '__main__':
    raise SystemExit(main())
