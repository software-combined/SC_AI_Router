"""Validated ChatGPT subscription catalogue data and roster composition."""
from .retired_slugs import SUBSCRIPTION as RETIRED
from .subscription_roster import replace_successors

MAX_ROWS = 256


def _valid_levels(value):
    if not isinstance(value, list) or not value:
        return False
    efforts = []
    for level in value:
        if not isinstance(level, dict):
            return False
        effort = level.get('effort')
        description = level.get('description', '')
        if not isinstance(effort, str) or not effort or effort in efforts:
            return False
        if not isinstance(description, str):
            return False
        efforts.append(effort)
    return True


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
        item = dict(row)
        if 'hidden' in item:
            if not isinstance(item['hidden'], bool):
                raise ValueError('subscription model hidden flag must be boolean')
            item['visibility'] = 'hidden' if item['hidden'] else item.get('visibility', 'list')
            del item['hidden']
        if item.get('visibility', 'list') not in ('list', 'hidden'):
            raise ValueError('subscription model has invalid visibility')
        levels = item.get('supported_reasoning_levels')
        if levels is not None and not _valid_levels(levels):
            raise ValueError('subscription model has invalid reasoning levels')
        default = item.get('default_reasoning_level')
        if default is not None and (not isinstance(default, str) or not default):
            raise ValueError('subscription model has invalid default reasoning level')
        if (levels is None) != (default is None):
            raise ValueError('subscription model needs complete reasoning metadata')
        if levels is not None and default is not None and default not in [
                level['effort'] for level in levels]:
            raise ValueError('subscription model default effort is not supported')
        modalities = item.get('input_modalities')
        if modalities is not None and (
                not isinstance(modalities, list)
                or any(not isinstance(value, str) or not value for value in modalities)):
            raise ValueError('subscription model has invalid input modalities')
        if 'priority' in item and (
                isinstance(item['priority'], bool)
                or not isinstance(item['priority'], (int, float))):
            raise ValueError('subscription model has invalid priority')
        for key in ('context_window', 'max_context_window'):
            if key in item and (
                    isinstance(item[key], bool)
                    or not isinstance(item[key], int) or item[key] <= 0):
                raise ValueError(f'subscription model has invalid {key}')
        messages = item.get('model_messages')
        if messages is not None and not isinstance(messages, dict):
            raise ValueError('subscription model has invalid model messages')
        if isinstance(messages, dict) and 'instructions_template' in messages \
                and not isinstance(messages['instructions_template'], str):
            raise ValueError('subscription model has invalid instructions')
        if item.get('upgrade') is not None and not isinstance(item['upgrade'], str):
            raise ValueError('subscription model has invalid upgrade id')
        seen.add(slug)
        valid.append(item)
    return tuple(valid)


def preferred_roster(configured):
    """Migrated, valid configured ids in their saved order."""
    return tuple(dict.fromkeys(
        slug for slug in replace_successors(configured or ())
        if isinstance(slug, str) and slug not in RETIRED))


def effective_roster(configured, discovered=None):
    """Compose live membership from configured preferences and discovered ids.

    With no discovery result the configured list is the static bootstrap
    roster. A live discovery result is authoritative: configured ids only
    provide ordering among models the server currently advertises.
    """
    preferred = preferred_roster(configured)
    if discovered is None:
        return preferred
    available = tuple(dict.fromkeys(
        slug for slug in discovered
        if isinstance(slug, str) and slug not in RETIRED))
    wanted = set(available)
    return tuple(dict.fromkeys(
        [slug for slug in preferred if slug in wanted] + list(available)))


def managed_entry(row, existing, stub):
    """Overlay native metadata while retaining meaningful local overrides."""
    entry = {**stub, **row}
    for key, value in (existing or {}).items():
        if key not in row and (key not in stub or value != stub.get(key)):
            entry[key] = value
    return entry
