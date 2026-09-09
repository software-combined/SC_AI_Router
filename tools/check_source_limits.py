"""Enforce source size limits. Usage: python3.14 tools/check_source_limits.py"""
import json
import sys
from pathlib import Path

SOFT = {'codex_router': 250, 'tools': 400, 'tests': 300}
HARD = {'codex_router': 400, 'tools': 700, 'tests': 500}

def main():
    root = Path(__file__).resolve().parents[1]
    baseline = json.loads((root / 'config' / 'source-limits-baseline.json').read_text())
    checked, failures = 0, 0
    for area in SOFT:
        for path in sorted((root / area).rglob('*.py')):
            rel = path.relative_to(root).as_posix()
            count = sum(1 for _ in open(path))
            checked += 1
            if count > HARD[area]:
                print(f'HARD {rel}: {count} lines')
                failures += 1
            elif count > SOFT[area] and baseline.get(rel) != count:
                print(f'SOFT {rel}: {count} lines (not in baseline)')
                failures += 1
    print(f'source-limits: checked={checked} failures={failures}')
    return 1 if failures else 0

if __name__ == '__main__':
    sys.exit(main())
