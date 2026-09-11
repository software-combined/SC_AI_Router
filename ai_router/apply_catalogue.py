"""Apply capabilities.py to external catalogue entries with backup and guards."""
import json
import os
import sys
from pathlib import Path
from .capabilities import EXTERNAL_MODELS, catalogue_patch
from .clients.codex import capability_fields as codex_projection
from .registry import by_slug


def apply(catalog, live):
    """Merge pinned capabilities and live metadata; fail closed on bad defaults."""
    for model in catalog['models']:
        slug = model['slug']
        if slug not in EXTERNAL_MODELS:
            continue
        # One Codex projection for merge and apply alike: the same snapshot
        # yields identical capability fields on either path. Live entries
        # render through pinned exclusions and defaults, never promotions.
        model_obj = by_slug(slug)
        patch = (codex_projection(model_obj, live.get(slug),
                                    default=model.get('default_reasoning_level'))
                 if model_obj is not None else catalogue_patch(slug))
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
    print(json.dumps({'models': [m['slug'] for m in catalog['models'] if m['slug'] in EXTERNAL_MODELS]}))
