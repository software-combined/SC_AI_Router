"""Estimate billable context for the OpenRouter pre-flight refusal.

Counts serialized input plus tools plus instructions at ~4 chars/token:
the three shapes the upstream provider bills. Image blocks are
excluded, matching the client counter, which carries no image charge;
text-only turns strip images before dispatch in any case.
"""
import json


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
        total = len(json.dumps([_without_images(i) for i in items])) // 4
        if isinstance(payload.get('tools'), list):
            total += len(json.dumps(payload['tools'])) // 4
        if isinstance(payload.get('instructions'), str):
            total += len(payload['instructions']) // 4
        return total
    except (ValueError, TypeError):
        return 0
