"""Validated ChatGPT subscription catalogue data and roster composition."""
from .retired_slugs import SUBSCRIPTION as RETIRED
from .subscription_roster import replace_successors

MAX_ROWS = 256


def validate(document):
    """Return native subscription rows, or raise ValueError on bad data."""
    if not isinstance(document, dict) or not isinstance(document.get('models'), list):
        raise ValueError('subscription catalogue must contain a models list')
    rows = document['models']
    if len(rows) > MAX_ROWS:
        raise ValueError('subscription catalogue has too many models')
    seen = set()
    valid = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('subscription model must be an object')
        slug = row.get('slug')
        if not isinstance(slug, str) or not slug or slug in seen:
            raise ValueError('subscription model has an invalid or duplicate slug')
        if not isinstance(row.get('display_name'), str) or not row['display_name']:
            raise ValueError('subscription model needs a display name')
        seen.add(slug)
        valid.append(dict(row))
    return tuple(valid)


def effective_roster(configured, discovered):
    """Preserve configured choices and append newly discovered model ids."""
    out = []
    seen = set()
    for slug in list(replace_successors(configured or ())) + list(discovered or ()):
        if not isinstance(slug, str) or slug in RETIRED or slug in seen:
            continue
        seen.add(slug)
        out.append(slug)
    return tuple(out)


def managed_entry(row, existing, stub):
    """Overlay native metadata while retaining meaningful local overrides."""
    entry = {**stub, **row}
    for key, value in (existing or {}).items():
        if key not in row and (key not in stub or value != stub.get(key)):
            entry[key] = value
    return entry
