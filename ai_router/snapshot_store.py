"""Persisted availability snapshots (Plan 145 leaf).

One owner for the `models-availability.json` document: read, write and
clear. Validation lives here so every reader shares one shape check.
Pure file handling; network and in-memory state stay in availability.py.
"""
import json
import time
from pathlib import Path

from .atomic_write import replace_json

SNAPSHOT_NAME = 'models-availability.json'


def path(home):
    return Path(home) / SNAPSHOT_NAME


def read(home):
    """Persisted snapshot dict, or None when absent or malformed."""
    try:
        doc = json.loads(path(home).read_text())
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


def write(home, fingerprint, region, ids):
    """Persist one snapshot; False when the home is unwritable."""
    try:
        replace_json(path(home),
                     {'key': fingerprint, 'region': region,
                      'models': sorted(ids), 'fetched_at': time.time()})
    except OSError:
        return False
    return True


def clear(home):
    """Drop the persisted snapshot; missing files count as cleared."""
    try:
        path(home).unlink()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True
