"""Onboard models with one command: derive the row, probe it, write the file.

Usage: python3.14 -m codex_router.models add <slug> [--probe] [--dry-run]
           [--tier preview|verified]
       python3.14 -m codex_router.models remove <slug> | check [--offline] | list
"""
import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from .apply_catalogue import write_guarded
from .capabilities import CANONICAL_ORDER
from .live_refresh import CODEX_MODALITIES
from .registry import load

MODELS_URL = 'https://openrouter.ai/api/v1/models'
MODELS_PATH = Path(__file__).with_name('models.json')
COMPAT_PATH = Path(__file__).resolve().parents[1] / 'docs' / 'compatibility.md'


def fetch_live():
    with urllib.request.urlopen(MODELS_URL, timeout=20) as response:
        return {model['id']: model for model in json.load(response)['data']}


def derive_row(slug, live, rows):
    """Registry row for a new slug from its live metadata entry."""
    name = live.get('name', slug)
    vendor, sep, short = name.partition(':')
    if not sep:
        vendor, short = '', name
    modalities = [m for m in CODEX_MODALITIES
                  if m in live.get('architecture', {}).get('input_modalities', [])]
    top = live.get('top_provider') or {}
    advertised = (live.get('reasoning') or {}).get('supported_efforts') or []
    reasoning = [lv for lv in CANONICAL_ORDER if lv in advertised]
    if not reasoning:
        raise SystemExit(f'live metadata for {slug} advertises no reasoning levels')
    default = 'low' if 'low' in reasoning else reasoning[0]
    priorities = [row['priority'] for row in rows if isinstance(row.get('priority'), int)]
    pricing = live.get('pricing') or {}
    return {'slug': slug,
            'provider': 'openrouter',
            'display_name': f'{short.strip()} \xb7 OpenRouter',
            'vendor': vendor.strip(),
            'reasoning': reasoning,
            'default_reasoning': default,
            'modalities': modalities or ['text'],
            'excluded_efforts': [],
            'schema_mode': 'native',
            'max_tools': None,
            'context_window': live.get('context_length', 0),
            'priority': max([100] + priorities) + 1,
            'max_output_tokens': top.get('max_completion_tokens') or 32768,
            'reasoning_summary': 'none',
            'apply_patch': 'none',
            'experimental_tools': [],
            'web_search': 'web_search' in pricing,
            'tier': 'preview'}


def probe_round_trip(slug):
    """Base tool round trip through the installed router. True on pass."""
    from .runtime import ROUTER_HOME
    state = ROUTER_HOME / 'mixed-router-state.json'
    cmd = [sys.executable, str(Path(__file__).resolve().parents[1]
                               / 'tools' / 'probe_codex_runtime.py'), slug]
    if state.exists():
        cmd += ['--router-state', str(state)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=150)
    except (OSError, subprocess.SubprocessError):
        return False
    return '"desktop_runtime_tool_round_trip": "passed"' in (proc.stdout or '')


def read_rows(path):
    return json.loads(Path(path).read_text())


def cmd_add(path, slug, live_by_id, tier=None, dry_run=False, probe=False,
           _probe=probe_round_trip):
    if live_by_id is None:
        live_by_id = fetch_live()
    if slug not in live_by_id:
        raise SystemExit(f'{slug} is not in the live OpenRouter list')
    before = Path(path).read_text()
    rows = json.loads(before)
    if any(row['slug'] == slug for row in rows):
        raise SystemExit(f'{slug} is already in {path}')
    live = live_by_id[slug]
    row = derive_row(slug, live, rows)
    if tier is not None:
        if tier not in ('preview', 'verified'):
            raise SystemExit('--tier must be preview or verified')
        row['tier'] = tier
    elif probe:
        row['tier'] = 'verified' if _probe(slug) else 'preview'
    if dry_run:
        print(json.dumps(row, indent=2))
        return row
    if probe:
        _record_compat(slug, row['tier'])
    write_guarded(path, before, json.dumps(rows + [row], indent=2) + '\n')
    print(json.dumps({'added': slug, 'tier': row['tier']}))
    return row


def _record_compat(slug, tier):
    line = (f'| {slug} | {tier} | '
            f'{datetime.now(timezone.utc).date()} | base round trip |\n')
    if not COMPAT_PATH.exists():
        COMPAT_PATH.write_text('# Compatibility matrix\n\n'
                               '| model | tier | date | probes |\n'
                               '|---|---|---|---|\n')
    with open(COMPAT_PATH, 'a') as stream:
        stream.write(line)


def cmd_remove(path, slug):
    before = Path(path).read_text()
    rows = json.loads(before)
    kept = [row for row in rows if row['slug'] != slug]
    if len(kept) == len(rows):
        raise SystemExit(f'{slug} is not in {path}')
    write_guarded(path, before, json.dumps(kept, indent=2) + '\n')
    print(json.dumps({'removed': slug}))


def cmd_check(path, live_by_id):
    """live_by_id None skips the live-list check (offline). Returns exit code."""
    rows = read_rows(path)
    problems = []
    try:
        load(json.dumps(rows))
    except SystemExit as exc:
        problems.append(str(exc))
    slugs = [row.get('slug') for row in rows]
    if len(set(slugs)) != len(slugs):
        problems.append('duplicate slug')
    priorities = [row.get('priority') for row in rows]
    if len(set(priorities)) != len(priorities):
        problems.append('duplicate priority')
    if live_by_id is not None:
        missing = [slug for slug in slugs if slug not in live_by_id]
        if missing:
            problems.append('not in live list: ' + ', '.join(sorted(missing)))
    print(f'{path}: {len(rows)} models, {len(problems)} problems')
    for problem in problems:
        print(f'  - {problem}')
    return 1 if problems else 0


def cmd_list(path):
    for row in read_rows(path):
        print(f"{row['slug']}  tier={row.get('tier')}  "
              f"modalities={','.join(row.get('modalities', []))}  "
              f"reasoning={','.join(row.get('reasoning', []))}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog='models')
    sub = parser.add_subparsers(dest='command', required=True)
    add = sub.add_parser('add')
    add.add_argument('slug')
    add.add_argument('--probe', action='store_true')
    add.add_argument('--dry-run', action='store_true')
    add.add_argument('--tier', default=None)
    sub.add_parser('remove').add_argument('slug')
    check = sub.add_parser('check')
    check.add_argument('--offline', action='store_true')
    sub.add_parser('list')
    args = parser.parse_args(argv)
    path = MODELS_PATH
    if args.command == 'add':
        cmd_add(path, args.slug, None, tier=args.tier,
                dry_run=args.dry_run, probe=args.probe)
    elif args.command == 'remove':
        cmd_remove(path, args.slug)
    elif args.command == 'check':
        live = None
        if not args.offline:
            try:
                live = fetch_live()
            except (OSError, ValueError):
                print('live check skipped: fetch failed')
        return cmd_check(path, live)
    elif args.command == 'list':
        cmd_list(path)


if __name__ == '__main__':
    sys.exit(main())
