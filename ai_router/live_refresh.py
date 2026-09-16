"""Refresh derived registry fields from each provider's live metadata.

Derived (rewritten in place in models.json): modalities, context_window,
max_output_tokens, reasoning. Pinned (never touched): identity,
excluded_efforts, schema_mode, max_tools, drop_images, priority, and the
capability flags, which only probes may enable.

A refresh only rewrites rows owned by the provider whose catalogue it read
(`provider_defs.external_catalogues`); a `manual`-shape provider has no live
metadata and its rows stay untouched.
"""
import json
import sys
import urllib.request
from pathlib import Path
from . import provider_defs
from .apply_catalogue import write_guarded
from .capabilities import CANONICAL_ORDER
from .model_metadata import project_modalities, refresh_display_name
from .registry import upstream_id_for

def derive(row, live):
    """Derived fields for one registry row from its live metadata entry."""
    modalities = project_modalities(
        live.get('architecture', {}).get('input_modalities', []))
    top = live.get('top_provider') or {}
    advertised = (live.get('reasoning') or {}).get('supported_efforts')
    reasoning = list(row['reasoning'])
    if advertised:
        filtered = [lv for lv in CANONICAL_ORDER
                    if lv in advertised and lv not in row.get('excluded_efforts', [])]
        if row['default_reasoning'] in filtered:
            reasoning = filtered
    return {'modalities': modalities or list(row['modalities']),
            'context_window': live.get('context_length', row['context_window']),
            'max_output_tokens': top.get('max_completion_tokens') or row['max_output_tokens'],
            'reasoning': reasoning,
            'display_name': refresh_display_name(row, live)}


def owned_by(row, provider_id):
    """True when this row belongs to the provider whose catalogue was read."""
    return (row.get('provider') or provider_defs.DEFAULT_EXTERNAL) == provider_id


def refresh(rows, live_by_id, provider_id=provider_defs.DEFAULT_EXTERNAL):
    """Return rows with derived fields rewritten; unknown live ids ignored.

    Rows of any other provider pass through untouched, so one catalogue can
    never relabel or re-derive another provider's model.
    """
    out = []
    for row in rows:
        if not owned_by(row, provider_id):
            out.append(row)
            continue
        # The live list is keyed by the id the provider serves, which is not
        # always the id clients send (Plan 153).
        live = live_by_id.get(upstream_id_for(row))
        if live is None:
            out.append(row)
            continue
        derived = derive(row, live)
        print(json.dumps({'model': row['slug'], **derived}))
        out.append({**row, **derived})
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    provider_id = provider_defs.DEFAULT_EXTERNAL
    if argv[:1] == ['--provider']:
        if len(argv) < 2 or provider_defs.get(argv[1]) is None:
            raise SystemExit('usage: python3.14 -m ai_router.live_refresh '
                             '[--provider ID] FILE|--fetch')
        provider_id, argv = argv[1], argv[2:]
    defn = provider_defs.get(provider_id)
    if argv == ['--fetch']:
        if not defn.catalogue_url:
            raise SystemExit(f'{defn.label} has no live model catalogue')
        with urllib.request.urlopen(defn.catalogue_url, timeout=20) as response:
            live = {model['id']: model for model in json.load(response)['data']}
    elif len(argv) == 1:
        live = {model['id']: model for model in json.loads(Path(argv[0]).read_text())['data']}
    else:
        raise SystemExit('usage: python3.14 -m ai_router.live_refresh '
                         '[--provider ID] FILE|--fetch')
    path = Path(__file__).with_name('models.json')
    before = path.read_text()
    write_guarded(path, before, json.dumps(
        refresh(json.loads(before), live, provider_id), indent=2) + '\n')


if __name__ == '__main__':
    main()
