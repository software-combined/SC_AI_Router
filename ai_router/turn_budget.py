"""Turn-size accounting for routed turns: what a carried body weighs, and
the last-resort trims that keep an oversized one inside the transport budget.

Sizes only. Nothing here reads or logs message or tool content; the one
value taken from an image is the byte length of its payload.
"""
import itertools
import json

from .events import log_event
from .image_items import (IMAGE_TOKEN_ALLOWANCE, IMAGE_TRIM_NOTE, count_images,
                          image_blocks, image_payload_bytes, is_image)

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
    tool call/output pairing survives. Returns (payload, stats): a trimmed
    copy and what was replaced, or the caller's payload and an empty mapping
    when nothing reducible was found - the caller then keeps today's refusal.
    Only the items and containers on a trimmed path are copied; the caller's
    history is never edited. `size` is the caller's body length when it
    already has one.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get('input'), list):
        return payload, {}
    if (body_size(payload) if size is None else size) <= budget:
        return payload, {}
    stats = {'dropped_bytes': 0, 'images': 0, 'outputs': 0}
    items = payload['input']
    for name, trim in (('images', _trim_images), ('outputs', _trim_outputs)):
        items, dropped, count = trim(items)
        stats['dropped_bytes'] += dropped
        stats[name] += count
        if body_size({**payload, 'input': items}) <= budget:
            break
    if not stats['images'] and not stats['outputs']:
        return payload, {}
    return {**payload, 'input': items}, stats


def body_size(payload):
    """Json byte weight of the body this payload becomes, as the gate measures
    it: the same encoder the adapter sends, separators included."""
    return len(json.dumps(payload).encode())


def _trim_images(items):
    """Note every image past the newest kept set; returns (items, bytes, count)."""
    weights = [image_payload_bytes(container[key]) for container, key in image_blocks(items)]
    kept, remaining, drop = 0, IMAGE_KEEP_BYTES, set()
    for ordinal in reversed(range(len(weights))):
        if kept < IMAGE_KEEP and weights[ordinal] <= remaining:
            kept, remaining = kept + 1, remaining - weights[ordinal]
        else:
            drop.add(ordinal)
    if not drop:
        return items, 0, 0
    ordinals = itertools.count()

    def note(block):
        return {'type': 'input_text', 'text': IMAGE_TRIM_NOTE} if next(ordinals) in drop else block
    return (_replace_images(items, note), sum(weights[ordinal] for ordinal in drop),
            len(drop))


def _replace_images(value, replace):
    """`value` with each image block, in `image_blocks` order, passed through
    `replace`; only the containers on a replaced block's path are copied."""
    if not isinstance(value, (dict, list)):
        return value
    copied = None
    for key, child in value.items() if isinstance(value, dict) else enumerate(value):
        new = replace(child) if is_image(child) else _replace_images(child, replace)
        if new is not child:
            if copied is None:
                copied = dict(value) if isinstance(value, dict) else list(value)
            copied[key] = new
    return value if copied is None else copied


def _trim_outputs(items):
    """Truncate long old tool outputs to head plus tail; (items, bytes, count)."""
    outputs = [index for index, item in enumerate(items)
               if isinstance(item, dict) and isinstance(item.get('output'), str)
               and item.get('type') in ('function_call_output', 'custom_tool_call_output')]
    trimmed, dropped, count = list(items), 0, 0
    for index in outputs[:-OUTPUT_KEEP]:
        text = items[index]['output']
        if len(text) <= OUTPUT_TRIM_MIN:
            continue
        output = text[:OUTPUT_HEAD] + OUTPUT_TRIM_NOTE + text[-OUTPUT_TAIL:]
        trimmed[index] = {**items[index], 'output': output}
        dropped += len(text) - len(output)
        count += 1
    return (trimmed if count else items), dropped, count
