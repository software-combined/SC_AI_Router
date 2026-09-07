"""Apply capabilities.py to OpenRouter catalogue entries with backup and guards."""
import json
import os
import sys
from pathlib import Path
from .capabilities import (OPENROUTER_MODELS, advertised_or_pinned, catalogue_patch, checked_level_entries)


def apply(catalog, live):
    """Merge pinned capabilities and live metadata; fail closed on bad defaults."""
    for model in catalog['models']:
        slug = model['slug']
        if slug not in OPENROUTER_MODELS:
            continue
        patch = catalogue_patch(slug)
        advertised = advertised_or_pinned(
            slug, (live.get(slug, {}).get('reasoning') or {}).get('supported_efforts'))
        patch['supported_reasoning_levels'] = checked_level_entries(
            slug, advertised, model['default_reasoning_level'])
        arch = (live.get(slug, {}).get('architecture') or {})
        if 'input_modalities' in arch:
            mods = arch['input_modalities']
            patch['input_modalities'] = ['text', 'image'] if 'image' in mods else ['text']
        model.update(patch)
    return catalog

def write_guarded(path, before, text):
    temp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temp.write_text(text)
    try:
        if path.read_text() != before:
            raise SystemExit('Catalog changed concurrently; no changes applied')
        backup = path.with_name(path.name + '.bak')
        backup.write_text(before)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)

if __name__ == '__main__':
    catalog_path, live_path = Path(sys.argv[1]), Path(sys.argv[2])
    before = catalog_path.read_text()
    catalog = apply(json.loads(before), {m['id']: m for m in json.loads(live_path.read_text())['data']})
    write_guarded(catalog_path, before, json.dumps(catalog, indent=2) + '\n')
    print(json.dumps({'models': [m['slug'] for m in catalog['models'] if m['slug'] in OPENROUTER_MODELS]}))
