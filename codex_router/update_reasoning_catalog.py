"""Refresh OpenRouter reasoning choices without changing native OpenAI entries.

Live metadata is authoritative for levels; capabilities.py pins the
accepted exceptions (Contributor rejects max)."""
import json
import sys
import urllib.request
from pathlib import Path
from .apply_catalogue import write_guarded
from .capabilities import advertised_or_pinned, checked_level_entries

def refresh(catalog, models):
    for model in catalog['models']:
        if model['slug'] not in models or '/' not in model['slug']:
            continue
        # Live metadata is authoritative minus proven-unsupported exclusions.
        entry = advertised_or_pinned(
            model['slug'], models[model['slug']].get('reasoning', {}).get('supported_efforts'))
        try:
            model['supported_reasoning_levels'] = checked_level_entries(
                model['slug'], entry, model['default_reasoning_level'])
        except ValueError as exc:
            raise SystemExit(str(exc))
        print(json.dumps({'model': model['slug'], 'levels': [x['effort'] for x in model['supported_reasoning_levels']]}))
    return catalog

if __name__ == '__main__':
    path = Path(sys.argv[1])
    before = path.read_text()
    with urllib.request.urlopen('https://openrouter.ai/api/v1/models', timeout=20) as response:
        models = {model['id']: model for model in json.load(response)['data']}
    catalog = refresh(json.loads(before), models)
    write_guarded(path, before, json.dumps(catalog, indent=2) + '\n')
