"""Enforce source size limits.

Usage: python3.14 tools/check_source_limits.py [--root REPO]

Each baseline entry is a ceiling for one file over its soft cap (Plan 166):
the file may shrink freely and may not grow past the recorded count. An
entry for a missing file, an unknown area, or a file back under its soft
cap fails the check instead of drifting silently past it (Plan 156).
"""
import argparse
import json
import sys
from pathlib import Path

# packaging/ holds entrypoints (installer, service helpers), so it takes the
# entrypoint budget from AGENTS.md rather than the module one.
SOFT = {'ai_router': 250, 'tools': 400, 'tests': 300, 'packaging': 400}
HARD = {'ai_router': 400, 'tools': 700, 'tests': 500, 'packaging': 700}


def problems(root):
    """(checked, failures) for one repository root."""
    baseline = json.loads((root / 'config' / 'source-limits-baseline.json').read_text())
    checked, failures, over_soft = 0, [], set()
    for area in SOFT:
        for path in sorted((root / area).rglob('*.py')):
            rel = path.relative_to(root).as_posix()
            count = sum(1 for _ in open(path))
            checked += 1
            if count <= SOFT[area]:
                continue
            over_soft.add(rel)
            recorded = baseline.get(rel)
            if count > HARD[area]:
                failures.append(f'HARD {rel}: {count} lines')
            elif recorded is None:
                failures.append(f'SOFT {rel}: {count} lines (not in baseline)')
            elif isinstance(recorded, bool) or not isinstance(recorded, int):
                failures.append(f'BASELINE {rel}: ceiling is not an integer')
            elif count > recorded:
                failures.append(f'SOFT {rel}: {count} lines (baseline ceiling {recorded})')
    for rel in sorted(set(baseline) - over_soft):
        if not (root / rel).is_file():
            failures.append(f'BASELINE {rel}: no such file')
        elif rel.split('/', 1)[0] not in SOFT:
            failures.append(f'BASELINE {rel}: unknown area')
        else:
            failures.append(f'BASELINE {rel}: no longer over the soft cap')
    return checked, failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]),
                        help='repository root to check')
    args = parser.parse_args(argv)
    checked, failures = problems(Path(args.root).resolve())
    for failure in failures:
        print(failure)
    print(f'source-limits: checked={checked} failures={len(failures)}')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
