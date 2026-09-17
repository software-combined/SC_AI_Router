"""Apply capabilities.py to external catalogue entries with backup and guards."""
import json
import sys
from pathlib import Path
from .atomic_write import replace_text
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
    if path.read_text() != before:
        raise SystemExit('Catalog changed concurrently; no changes applied')
    path.with_name(path.name + '.bak').write_text(before)
    replace_text(path, text)

if __name__ == '__main__':
    catalog_path, live_path = Path(sys.argv[1]), Path(sys.argv[2])
    before = catalog_path.read_text()
    catalog = apply(json.loads(before), {m['id']: m for m in json.loads(live_path.read_text())['data']})
    write_guarded(catalog_path, before, json.dumps(catalog, indent=2) + '\n')
    print(json.dumps({'models': [m['slug'] for m in catalog['models'] if m['slug'] in EXTERNAL_MODELS]}))
