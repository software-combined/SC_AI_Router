"""Turn-size accounting for routed turns: what a carried body weighs.

Sizes only. Nothing here reads or logs message or tool content; the one
value taken from an image is the byte length of its payload.
"""
import json

from .image_items import count_images, image_payload_bytes

# Named in the refusal line, in the order a search-heavy thread grows them.
CLASSES = ('tool_search_output', 'function_call_output', 'reasoning', 'message')


def class_stats(items):
    """Flat count and json bytes per class, plus carried image weight."""
    stats = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        kind = item.get('type')
        count, size = stats.get(kind, (0, 0))
        stats[kind] = (count + 1,
                       size + len(json.dumps(item, separators=(',', ':'))))
    flat = {}
    for name in CLASSES:
        flat[name], flat[name + '_bytes'] = stats.get(name, (0, 0))
    flat['images'] = count_images(items)
    flat['image_bytes'] = image_payload_bytes(items)
    return flat
