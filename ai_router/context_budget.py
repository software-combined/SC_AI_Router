"""Estimate billable context for the OpenRouter pre-flight refusal.

Counts serialized input plus tools plus instructions at ~4 chars/token:
the three shapes the upstream provider bills. Image blocks are excluded
from the character count and billed through a flat per-block allowance,
so base64 payloads in replayed history never read as text tokens. The
client counter carries no image charge of its own.
"""
import json

from .image_items import IMAGE_TOKEN_ALLOWANCE, count_images, strip_images


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


def estimate(payload):
    """~tokens in input + tools + instructions; 0 on malformed payload."""
    if not isinstance(payload, dict):
        return 0
    try:
        items = payload.get('input', [])
        if not isinstance(items, list):
            items = []
        total = count_images(items) * IMAGE_TOKEN_ALLOWANCE
        total += _dumped_len(strip_images(items, False)) // 4
        if isinstance(payload.get('tools'), list):
            total += _dumped_len(payload['tools']) // 4
        if isinstance(payload.get('instructions'), str):
            total += len(payload['instructions']) // 4
        return total
    except (ValueError, TypeError):
        return 0
