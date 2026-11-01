"""External history stages for the items only OpenAI can read (Plan 183).

A compaction item replays as visible text and a reasoning item loses its
OpenAI-owned blob, so an external upstream never gets a blob it cannot read.
The subscription retry repair reuses `strip_reasoning_blobs` for a blob the
backend rejected. This projection reads the compaction codec; compaction
never imports it back.
"""
from .compaction import compaction_text, is_compaction_item
from .history_items import reasoning_text, user_message_item


def rewrite_input(items):
    """Replace compaction items with visible text; never drop history silently."""
    if not isinstance(items, list):
        return items
    rewritten = []
    for item in items:
        if is_compaction_item(item):
            rewritten.append(user_message_item(compaction_text(item)))
        else:
            rewritten.append(item)
    return rewritten


def strip_reasoning_blobs(items, *, drop_tail=False):
    """Strip blobs; external retries also omit an unfinished reasoning suffix."""
    if not isinstance(items, list):
        return items
    out = []
    for item in items:
        if (isinstance(item, dict) and item.get('type') == 'reasoning'
                and 'encrypted_content' in item):
            item = {k: v for k, v in item.items() if k != 'encrypted_content'}
            if not reasoning_text(item):
                continue
        out.append(item)
    # Codex saves interrupted reasoning before retrying. External providers
    # treat a reasoning-only tail as assistant prefill and reject the retry.
    if drop_tail:
        while out and isinstance(out[-1], dict) and out[-1].get('type') == 'reasoning':
            out.pop()
    return out
