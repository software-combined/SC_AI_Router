"""Normalize replayed history for the subscription Responses wire.

Foreign plaintext reasoning is not a portable saved item: keeping its id
without its content asks upstream to retrieve an item it never stored.
The router's own compaction summary is not portable either: the router hands
the client an `ocx1:`-prefixed summary item, the client replays it, and the
ChatGPT backend cannot read it, refusing the turn with
`invalid_encrypted_content`. That item goes out as readable text; a native
compaction blob belongs to the backend and goes out unchanged. Only the
outbound projection changes; the client's history is never edited.

Legacy custom and discovery calls regain their native item ID prefix before dispatch.
The retry repair below only handles reasoning blobs and non-empty router-owned
summaries. Native opaque compaction stays unchanged and is not retried.
"""
from . import compaction as comp
from .external_history import strip_reasoning_blobs
from .history_items import repair_call_id, user_message_item


def _owned_summary(item):
    """The non-empty router summary in one compaction item, else None."""
    return comp.decode_summary(item.get('encrypted_content'))


def normalize(payload):
    """Project reasoning, native call IDs and router compaction summaries for the wire.

    Returns the original payload on a no-op, otherwise a shallow copy; the
    client's items are never edited.
    """
    items = payload.get('input')
    if not isinstance(items, list):
        return payload
    result = []
    changed = False
    for item in items:
        repaired = repair_call_id(item)
        changed |= repaired is not item
        item = repaired
        if (isinstance(item, dict) and item.get('type') == 'reasoning'
                and isinstance(item.get('content'), list) and item['content']):
            if encrypted_field_count(item) == 0:
                changed = True
            elif removable_encrypted(item):
                changed = True
                result.append({key: value for key, value in item.items() if key != 'content'})
            else:
                result.append(item)
        elif comp.is_compaction_item(item) and removable_encrypted(item):
            changed = True
            result.append(user_message_item(comp.compaction_text(item)))
        else:
            result.append(item)
    return {**payload, 'input': result} if changed else payload


def encrypted_field_count(item):
    """How many `encrypted_content` fields one item carries at any depth."""
    count = 0
    pending = [item]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            count += 1 if 'encrypted_content' in value else 0
            pending.extend(value.values())
        if isinstance(value, list):
            pending.extend(value)
    return count


def removable_encrypted(item):
    """True when the retry repair owns every encrypted field on this item.

    Owned: the item-level `encrypted_content` key on a `reasoning` item,
    which goes, and on a compaction item carrying a non-empty router-owned
    `ocx1:` summary, which becomes readable text. A native opaque compaction
    blob, nested content block, or the key on any other item type is not a
    shape this repair owns, so the caller fails closed on the whole payload.
    """
    kind = item.get('type')
    blob = item.get('encrypted_content')
    return (encrypted_field_count(item) == 1
            and 'encrypted_content' in item
            and ((kind == 'reasoning' and isinstance(blob, str) and blob.strip())
                 or (comp.is_compaction_item(item) and _owned_summary(item) is not None)))


def repair_input(items):
    """The retried `input` with every owned blob repaired, else None.

    None means nothing may change: a payload carrying an encrypted field
    this repair does not own, including opaque native compaction, is left
    alone, so the turn is not retried against a request the repair cannot fix.
    """
    if not isinstance(items, list):
        return None
    if any(encrypted_field_count(item)
           and not (isinstance(item, dict) and removable_encrypted(item))
           for item in items):
        return None
    repaired = []
    for item in strip_reasoning_blobs(items):
        if (isinstance(item, dict) and comp.is_compaction_item(item)
                and 'encrypted_content' in item):
            item = user_message_item(comp.compaction_text(item))
        repaired.append(item)
    return None if repaired == items else repaired
