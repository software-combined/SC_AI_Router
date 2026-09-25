"""Normalize replayed history for the subscription Responses wire.

Foreign plaintext reasoning is not a portable saved item: keeping its id
without its content asks upstream to retrieve an item it never stored.
The router's own compaction summary is not portable either: the router hands
the client an `ocx1:`-prefixed summary item, the client replays it, and the
ChatGPT backend cannot read it, refusing the turn with
`invalid_encrypted_content`. That item goes out as readable text; a native
compaction blob belongs to the backend and goes out unchanged. Only the
outbound projection changes; the client's history is never edited.

The retry repair below stays as the fallback for any blob the backend still
rejects.
"""
from . import compaction as comp
from .external_history import strip_reasoning_blobs
from .history_items import user_message_item


def normalize(payload):
    """Project reasoning and the router's own compaction summary for the wire.

    Returns the original payload on a no-op, otherwise a shallow copy; the
    client's items are never edited.
    """
    items = payload.get('input')
    if not isinstance(items, list):
        return payload
    result = []
    changed = False
    for item in items:
        if (isinstance(item, dict) and item.get('type') == 'reasoning'
                and isinstance(item.get('content'), list) and item['content']):
            changed = True
            if item.get('encrypted_content'):
                result.append({key: value for key, value in item.items() if key != 'content'})
        elif (comp.is_compaction_item(item)
                and comp.decode_summary(item.get('encrypted_content')) is not None):
            changed = True
            result.append(user_message_item(comp.compaction_text(item)))
        else:
            result.append(item)
    return {**payload, 'input': result} if changed else payload


def encrypted_field_count(item):
    """How many `encrypted_content` fields one item carries, one level deep."""
    count = 1 if 'encrypted_content' in item else 0
    blocks = item.get('content')
    if isinstance(blocks, list):
        count += sum(1 for block in blocks
                     if isinstance(block, dict) and 'encrypted_content' in block)
    return count


def removable_encrypted(item):
    """True when the retry repair owns every encrypted field on this item.

    Owned: the item-level `encrypted_content` key on a `reasoning` item,
    which goes, and on a compaction item, which becomes readable text. A
    nested content block, or the key on any other item type, is not a shape
    this repair owns, so the caller fails closed on the whole payload.
    """
    kind = item.get('type')
    return (encrypted_field_count(item) == 1
            and 'encrypted_content' in item
            and (kind == 'reasoning' or comp.is_compaction_item(item)))


def repair_input(items):
    """The retried `input` with every unreadable blob repaired, else None.

    None means nothing may change: a payload carrying an encrypted field
    this repair does not own is left alone, so the turn is not retried
    against a request the repair cannot fix.
    """
    if not isinstance(items, list):
        return None
    if any(isinstance(item, dict) and encrypted_field_count(item)
           and not removable_encrypted(item) for item in items):
        return None
    repaired = []
    for item in strip_reasoning_blobs(items):
        if (isinstance(item, dict) and comp.is_compaction_item(item)
                and 'encrypted_content' in item):
            item = user_message_item(comp.compaction_text(item))
        repaired.append(item)
    return None if repaired == items else repaired
