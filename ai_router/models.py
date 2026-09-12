"""Onboard models with one command: derive the row, probe it, write the file.

Usage: python3.14 -m ai_router.models add <slug> [--probe] [--dry-run]
           [--tier preview|verified] [--provider ID]
       python3.14 -m ai_router.models remove <slug> | check [--offline] | list
       python3.14 -m ai_router.models discover [--provider ID] [--json]

The live metadata projection belongs to the provider's definition
(`provider_defs.ProviderDef.catalogue_shape`); only the `openrouter` shape
ships today, and a `manual`-shape provider authors its rows by hand.
"""
import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from . import provider_defs
from .apply_catalogue import write_guarded
from .capabilities import CANONICAL_ORDER
from .model_metadata import project_modalities, qualify_name
from .registry import load, picker_key

MODELS_PATH = Path(__file__).with_name('models.json')
COMPAT_PATH = Path(__file__).resolve().parents[1] / 'docs' / 'compatibility.md'


def fetch_live(provider_id=provider_defs.DEFAULT_EXTERNAL):
    """Live metadata for one provider, keyed by slug; {} when it has none."""
    defn = provider_defs.get(provider_id)
    if defn is None or not defn.catalogue_url or defn.catalogue_shape == 'manual':
        return {}
    with urllib.request.urlopen(defn.catalogue_url, timeout=20) as response:
        return {model['id']: model for model in json.load(response)['data']}


def require_live_shape(provider_id):
    """The provider whose rows a live derivation can work on, else SystemExit.

    Checked before the live-list lookup so a hand-authored provider is
    refused for the reason that actually applies.
    """
    defn = provider_defs.get(provider_id)
    if defn is None or not provider_defs.is_external(provider_id):
        raise SystemExit(f'{provider_id} is not an external provider')
    if defn.catalogue_shape == 'manual' or not defn.catalogue_url:
        raise SystemExit(f'{defn.label} rows are authored by hand; '
                         f'{defn.catalogue_shape} shape has no live metadata to derive from')
    return defn


def row_key(row):
    """Picker sort key for one registry row (see registry.picker_key)."""
    return picker_key(row['vendor'], row['tier'], row['display_name'], row['slug'])


def renumbered(rows):
    """Rows in picker order with priorities renumbered from 100.

    Codex lists the picker by ascending priority, so the numbers carry the
    vendor grouping; every add or promotion re-stamps the whole set."""
    ordered = sorted(rows, key=row_key)
    return [{**row, 'priority': 100 + index} for index, row in enumerate(ordered)]


def derive_row(slug, live, provider_id=provider_defs.DEFAULT_EXTERNAL):
    """Registry row for a new slug from its live metadata entry.

    Priority is left to renumbered(), which depends on the whole set."""
    defn = require_live_shape(provider_id)
    vendor, qualified = qualify_name(slug, live)
    modalities = project_modalities(
        live.get('architecture', {}).get('input_modalities', []))
    top = live.get('top_provider') or {}
    advertised = (live.get('reasoning') or {}).get('supported_efforts') or []
    reasoning = [lv for lv in CANONICAL_ORDER if lv in advertised]
    if not advertised and (live.get('reasoning') is None
                           or live['reasoning'].get('mandatory') is False):
        reasoning = ['none']
    if not reasoning:
        raise SystemExit(f'live metadata for {slug} advertises no reasoning levels')
    default = 'low' if 'low' in reasoning else reasoning[0]
    pricing = live.get('pricing') or {}
    return {'slug': slug,
            'provider': provider_id,
            'display_name': f'{qualified} \xb7 {defn.label}',
            'vendor': vendor,
            'reasoning': reasoning,
            'default_reasoning': default,
            'modalities': modalities or ['text'],
            'excluded_efforts': [],
            'schema_mode': 'native',
            'history_mode': 'native',
            'max_tools': None,
            'drop_images': False,
            'context_window': live.get('context_length', 0),
            'max_output_tokens': top.get('max_completion_tokens') or 32768,
            'reasoning_summary': 'none',
            'apply_patch': 'none',
            'experimental_tools': [],
            'web_search': 'web_search' in pricing,
            'tier': 'preview',
            'listed': False}


def read_rows(path):
    return json.loads(Path(path).read_text())


def cmd_add(path, slug, live_by_id, tier=None, dry_run=False, probe=False,
           _probe=None, provider_id=provider_defs.DEFAULT_EXTERNAL):
    require_live_shape(provider_id)
    if live_by_id is None:
        live_by_id = fetch_live(provider_id)
    if slug not in live_by_id:
        raise SystemExit(f'{slug} is not in the live '
                         f'{provider_defs.label_for(provider_id)} list')
    before = Path(path).read_text()
    rows = json.loads(before)
    if any(row['slug'] == slug for row in rows):
        raise SystemExit(f'{slug} is already in {path}')
    live = live_by_id[slug]
    row = derive_row(slug, live, provider_id)
    if tier is not None:
        if tier not in ('preview', 'verified'):
            raise SystemExit('--tier must be preview or verified')
        row['tier'] = tier
        if tier == 'verified' and not probe:
            print(f'{slug} stays unlisted: --tier verified needs --probe to pass first')
        elif tier is not None and probe:
            print(f'{slug} stays unlisted: --tier {tier} skips the probe; '
                  'drop --tier to run it')
    promote = probe and tier is None
    if promote:
        # Preview-activate-verify-promote: the registry is file-baked, so the
        # candidate must be written before anything can route it. Verification
        # runs isolated (own router, home and catalogue); only a pass promotes.
        row['tier'] = 'preview'
        row['listed'] = False
    rows = renumbered(rows + [row])
    row = next(entry for entry in rows if entry['slug'] == slug)
    if dry_run:
        # Never writes and never bills: preview what a plain add would store.
        print(json.dumps(row, indent=2))
        return row
    if promote:
        from .candidate import legs_for, verify
        write_guarded(path, before, json.dumps(rows, indent=2) + '\n')
        # Legs come from the row we just wrote, not the import-time registry
        # (which predates this slug and would under-probe it).
        legs = legs_for(slug, row)
        try:
            passed = (_probe or (lambda s: verify(s, row=row)))(slug)
        except SystemExit as exc:
            print(f'probe refused for {slug}: {exc}')
            print(json.dumps({'added': slug, 'tier': row['tier'],
                              'listed': row['listed']}))
            return row
        if passed:
            activated = Path(path).read_text()
            promoted = renumbered(
                [{**entry, 'tier': 'verified', 'listed': True}
                 if entry.get('slug') == slug
                 else entry for entry in json.loads(activated)])
            write_guarded(path, activated, json.dumps(promoted, indent=2) + '\n')
            row = next(entry for entry in promoted if entry['slug'] == slug)
        else:
            print(f'probe failed for {slug}: row stays unlisted preview '
                  f'(legs attempted: {",".join(legs)}; the row records '
                  'preview until a probe passes)')
        _record_compat(slug, row['tier'], legs)
    else:
        write_guarded(path, before, json.dumps(rows, indent=2) + '\n')
    print(json.dumps({'added': slug, 'tier': row['tier'],
                      'listed': row['listed']}))
    return row


def _record_compat(slug, tier, legs=()):
    probed = ','.join(legs) if legs else 'base round trip'
    line = (f'| {slug} | {tier} | '
            f'{datetime.now(timezone.utc).date()} | {probed} |\n')
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


def cmd_check(path, live_by_id, provider_id=provider_defs.DEFAULT_EXTERNAL):
    """Structural checks for the whole file; the live-list check covers the
    rows owned by `provider_id` (the provider `live_by_id` came from).
    live_by_id None skips the live check (offline). Returns exit code."""
    rows = read_rows(path)
    problems = []
    valid = True
    try:
        load(json.dumps(rows))
    except SystemExit as exc:
        problems.append(str(exc))
        valid = False
    slugs = [row.get('slug') for row in rows]
    if len(set(slugs)) != len(slugs):
        problems.append('duplicate slug')
    priorities = [row.get('priority') for row in rows]
    if len(set(priorities)) != len(priorities):
        problems.append('duplicate priority')
    if valid:
        ordered = [row['priority'] for row in sorted(rows, key=row_key)]
        if ordered != sorted(ordered):
            problems.append('priorities not in picker order')
    if live_by_id is not None:
        owned = [row['slug'] for row in rows
                 if (row.get('provider') or provider_defs.DEFAULT_EXTERNAL) == provider_id]
        missing = [slug for slug in owned if slug not in live_by_id]
        if missing:
            problems.append('not in live list: ' + ', '.join(sorted(missing)))
    print(f'{path}: {len(rows)} models, {len(problems)} problems')
    for problem in problems:
        print(f'  - {problem}')
    return 1 if problems else 0


def cmd_discover(path, live_by_id, provider_id=provider_defs.DEFAULT_EXTERNAL,
                 as_json=False):
    """Read-only diff of the live catalogue against models.json.

    Never writes, never probes, needs no key for OpenRouter: `addable`
    ids are served upstream but missing locally, `registered` are in
    both, `unavailable` are registered but absent upstream, and `retired`
    are registered ids the catalogue module already drops from pickers.
    """
    from .catalogue import RETIRED_SLUGS
    defn = require_live_shape(provider_id)
    if live_by_id is None:
        live_by_id = fetch_live(provider_id)
    rows = read_rows(path)
    owned = [row for row in rows
             if (row.get('provider') or provider_defs.DEFAULT_EXTERNAL) == provider_id]
    registered = {row['slug'] for row in owned}
    live_ids = set(live_by_id)
    doc = {'provider': provider_id,
           'addable': sorted(live_ids - registered),
           'registered': sorted(registered & live_ids),
           'unavailable': sorted(registered - live_ids),
           'retired': sorted(slug for slug in registered if slug in RETIRED_SLUGS)}
    if as_json:
        print(json.dumps(doc, indent=2))
    else:
        print(f'{defn.label}: {len(doc["addable"])} addable, '
              f'{len(doc["registered"])} registered, '
              f'{len(doc["unavailable"])} unavailable, '
              f'{len(doc["retired"])} retired')
        for key in ('addable', 'registered', 'unavailable', 'retired'):
            for slug in doc[key]:
                print(f'  {key}: {slug}')
    return doc


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
    add.add_argument('--provider', default=provider_defs.DEFAULT_EXTERNAL)
    sub.add_parser('remove').add_argument('slug')
    check = sub.add_parser('check')
    check.add_argument('--offline', action='store_true')
    sub.add_parser('list')
    discover = sub.add_parser('discover')
    discover.add_argument('--provider', default=provider_defs.DEFAULT_EXTERNAL)
    discover.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    path = MODELS_PATH
    if args.command == 'add':
        cmd_add(path, args.slug, None, tier=args.tier,
                dry_run=args.dry_run, probe=args.probe,
                provider_id=args.provider)
    elif args.command == 'remove':
        cmd_remove(path, args.slug)
    elif args.command == 'check':
        if args.offline:
            return cmd_check(path, None)
        codes = []
        for defn in provider_defs.external_catalogues(shape='openrouter'):
            try:
                live = fetch_live(defn.id)
            except (OSError, ValueError):
                print(f'{defn.label} live check skipped: fetch failed')
                live = None
            codes.append(cmd_check(path, live, defn.id))
        return max(codes) if codes else cmd_check(path, None)
    elif args.command == 'list':
        cmd_list(path)
    elif args.command == 'discover':
        cmd_discover(path, None, args.provider, args.json)


if __name__ == '__main__':
    sys.exit(main())
