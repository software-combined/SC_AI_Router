"""Refresh derived registry fields from live OpenRouter metadata.

Derived (rewritten in place in models.json): modalities, context_window,
max_output_tokens, reasoning. Pinned (never touched): identity,
excluded_efforts, schema_mode, max_tools, drop_images, priority, and the
capability flags, which only probes may enable.
"""
import json
import sys
import urllib.request
from pathlib import Path
from .apply_catalogue import write_guarded
from .capabilities import CANONICAL_ORDER
from .model_metadata import project_modalities, refresh_display_name

MODELS_URL = 'https://openrouter.ai/api/v1/models'


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


def refresh(rows, live_by_id):
    """Return rows with derived fields rewritten; unknown live ids ignored."""
    out = []
    for row in rows:
        live = live_by_id.get(row['slug'])
        if live is None:
            out.append(row)
            continue
        derived = derive(row, live)
        print(json.dumps({'model': row['slug'], **derived}))
        out.append({**row, **derived})
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ['--fetch']:
        with urllib.request.urlopen(MODELS_URL, timeout=20) as response:
            live = {model['id']: model for model in json.load(response)['data']}
    elif len(argv) == 1:
        live = {model['id']: model for model in json.loads(Path(argv[0]).read_text())['data']}
    else:
        raise SystemExit('usage: python3.14 -m codex_router.live_refresh FILE|--fetch')
    path = Path(__file__).with_name('models.json')
    before = path.read_text()
    write_guarded(path, before, json.dumps(refresh(json.loads(before), live), indent=2) + '\n')


if __name__ == '__main__':
    main()
