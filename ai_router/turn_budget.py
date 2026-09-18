"""Turn-size accounting for routed turns: what a carried body weighs, and
the last-resort trims that keep an oversized one inside the transport budget.

Sizes only. Nothing here reads or logs message or tool content; the one
value taken from an image is the byte length of its payload.
"""
import json

from .events import log_event
from .image_items import (IMAGE_TOKEN_ALLOWANCE, IMAGE_TRIM_NOTE, count_images,
                          image_blocks, image_payload_bytes)

# Named in the refusal line, in the order a search-heavy thread grows them.
CLASSES = ('tool_search_output', 'function_call_output', 'reasoning', 'message')

# Matches runtime.MAX_BODY: the prepared body the ingress gate refuses above.
BODY_BUDGET = 16 * 1024 * 1024  # pinned by a test
# Trims keep the newest of each kind and note the rest: images first, because
# their bytes are cheap to re-read and expensive to carry.
IMAGE_KEEP = 4
IMAGE_KEEP_BYTES = 4 * 1024 * 1024
OUTPUT_KEEP = 2
OUTPUT_TRIM_MIN = 32 * 1024
OUTPUT_HEAD = 16 * 1024
OUTPUT_TAIL = 2 * 1024
OUTPUT_TRIM_NOTE = ('\n[... earlier tool output truncated to fit the router '
                    'request limit; re-run the tool if it matters ...]\n')
# Live 2026-09-11: a 4,324,328-byte turn billed 750,806 input tokens, so four
# characters per token under-counts a carried Codex thread; the image
# allowance mirrors the client's own flat discount for base64 payloads.
BYTES_PER_TOKEN = 5.8


def carried_tokens(payload, decoded_bytes):
    """Input tokens this thread's own history weighs.

    The client compacts on provider-reported usage, and the router's slim is
    invisible upstream, so a byte-heavy thread has to say what it carries or
    it never compacts (2026-09-16: 67 MB carried, about 1 MB billed).
    Image bytes ride the flat allowance; the caller clamps to its own window.
    """
    if not isinstance(payload, dict):
        return 0
    items = payload.get('input')
    images = image_payload_bytes(items)
    return int(max(decoded_bytes - images, 0) / BYTES_PER_TOKEN
               + count_images(items) * IMAGE_TOKEN_ALLOWANCE)


def report_usage(usage, notes):
    """Raise a routed frame's reported input tokens to what the thread carries.

    Returns True when the frame changed. The provider's own number is never
    lowered, its detail fields are left alone, and a turn without a carried
    figure (subscription passthrough, the helper twin) stays untouched.
    """
    carried = (notes or {}).get('context_tokens')
    reported = usage.get('input_tokens') if isinstance(usage, dict) else None
    if (not carried or isinstance(reported, bool) or not isinstance(reported, int)
            or carried <= reported):
        return False
    usage['input_tokens'] = carried
    output = usage.get('output_tokens')
    if isinstance(output, int) and not isinstance(output, bool):
        usage['total_tokens'] = carried + output
    log_event('usage_reported', model=(notes or {}).get('model'),
              reported=reported, carried=carried)
    return True


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


def fit(payload, budget, size=None):
    """Replace the oldest reducible weight until the body fits `budget`.

    Images go first, then long tool outputs; structure is never touched, so
    tool call/output pairing survives. Returns what was replaced, or an empty
    mapping when nothing reducible was found - the caller then keeps today's
    refusal. `size` is the caller's body length when it already has one.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get('input'), list):
        return {}
    if (body_size(payload) if size is None else size) <= budget:
        return {}
    stats = {'dropped_bytes': 0, 'images': 0, 'outputs': 0}
    for name, trim in (('images', _trim_images), ('outputs', _trim_outputs)):
        dropped, count = trim(payload)
        stats['dropped_bytes'] += dropped
        stats[name] += count
        if body_size(payload) <= budget:
            break
    if not stats['images'] and not stats['outputs']:
        return {}
    return stats


def body_size(payload):
    """Json byte weight of the body this payload becomes, as the gate measures
    it: the same encoder the adapter sends, separators included."""
    return len(json.dumps(payload).encode())


def _trim_images(payload):
    """Note every image past the newest kept set; returns (bytes, count)."""
    kept, remaining, dropped, count = 0, IMAGE_KEEP_BYTES, 0, 0
    for container, key in reversed(list(image_blocks(payload.get('input')))):
        weight = image_payload_bytes(container[key])
        if kept < IMAGE_KEEP and weight <= remaining:
            kept, remaining = kept + 1, remaining - weight
            continue
        container[key] = {'type': 'input_text', 'text': IMAGE_TRIM_NOTE}
        dropped, count = dropped + weight, count + 1
    return dropped, count


def _trim_outputs(payload):
    """Truncate long old tool outputs to head plus tail; (bytes, count)."""
    outputs = []
    for item in payload['input']:
        if (isinstance(item, dict) and isinstance(item.get('output'), str)
                and item.get('type') in ('function_call_output', 'custom_tool_call_output')):
            outputs.append(item)
    dropped = count = 0
    for item in outputs[:-OUTPUT_KEEP]:
        text = item['output']
        if len(text) <= OUTPUT_TRIM_MIN:
            continue
        item['output'] = text[:OUTPUT_HEAD] + OUTPUT_TRIM_NOTE + text[-OUTPUT_TAIL:]
        dropped += len(text) - len(item['output'])
        count += 1
    return dropped, count
