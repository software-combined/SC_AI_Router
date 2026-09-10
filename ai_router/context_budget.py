"""Estimate billable context for the OpenRouter pre-flight refusal.

Counts serialized input plus tools plus instructions at ~4 chars/token:
the three shapes the upstream provider bills. Image blocks are
excluded, matching the client counter, which carries no image charge;
text-only turns strip images before dispatch in any case.
"""
import json


class _Counter:
    """File-like sink that counts serialized chars without keeping the string."""

    __slots__ = ('size',)
    def __init__(self):
        self.size = 0
    def write(self, chunk):
        self.size += len(chunk)


def _dumped_len(obj):
    """Length of the JSON serialization without materializing the string."""
    counter = _Counter()
    json.dump(obj, counter)
    return counter.size


def _without_images(item):
    if (isinstance(item, dict) and isinstance(item.get('content'), list)
            and any(isinstance(b, dict) and b.get('type') == 'input_image'
                    for b in item['content'])):
        item = {**item, 'content': [b for b in item['content']
                if not (isinstance(b, dict) and b.get('type') == 'input_image')]}
    return item


def estimate(payload):
    """~tokens in input + tools + instructions; 0 on malformed payload."""
    if not isinstance(payload, dict):
        return 0
    try:
        items = payload.get('input', [])
        if not isinstance(items, list):
            items = []
        total = _dumped_len([_without_images(i) for i in items]) // 4
        if isinstance(payload.get('tools'), list):
            total += _dumped_len(payload['tools']) // 4
        if isinstance(payload.get('instructions'), str):
            total += len(payload['instructions']) // 4
        return total
    except (ValueError, TypeError):
        return 0
