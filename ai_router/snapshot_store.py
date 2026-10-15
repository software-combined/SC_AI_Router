"""Persisted availability snapshots (Plan 145 leaf).

One owner per provider document: the default external provider keeps
`models-availability.json`; every other provider gets
`models-availability-<provider>.json` beside it. Read, write and clear
share one shape check. Pure file handling; network and in-memory state
stay in availability.py.
"""
import json
import time
from pathlib import Path

from . import provider_defs
from .atomic_write import replace_json

SNAPSHOT_NAME = 'models-availability.json'


def path(home, provider_id=None):
    provider_id = provider_id or provider_defs.DEFAULT_EXTERNAL
    if provider_id == provider_defs.DEFAULT_EXTERNAL:
        return Path(home) / SNAPSHOT_NAME
    return Path(home) / f'models-availability-{provider_id}.json'


def read(home, provider_id=None):
    """Persisted snapshot dict, or None when absent or malformed."""
    try:
        doc = json.loads(path(home, provider_id).read_text())
    except (OSError, ValueError):
        return None
    if (not isinstance(doc, dict) or not isinstance(doc.get('key'), str)
            or not isinstance(doc.get('region'), str)
            or not isinstance(doc.get('models'), list)
            or any(not isinstance(s, str) for s in doc['models'])
            or not isinstance(doc.get('fetched_at'), (int, float))):
        return None
    try:
        ids = frozenset(doc['models'])
    except (TypeError, ValueError):
        return None
    return {'key': doc['key'], 'region': doc['region'],
            'models': ids, 'fetched_at': float(doc['fetched_at'])}


def write(home, provider_id, fingerprint, region, ids):
    """Persist one provider snapshot; False when the home is unwritable."""
    try:
        replace_json(path(home, provider_id),
                     {'key': fingerprint, 'region': region,
                      'models': sorted(ids), 'fetched_at': time.time()})
    except OSError:
        return False
    return True


def clear(home, provider_id=None):
    """Drop one provider's persisted snapshot; missing files count as cleared."""
    try:
        path(home, provider_id).unlink()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True
