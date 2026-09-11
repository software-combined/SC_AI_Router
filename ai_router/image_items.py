"""Own image-block handling for the Responses input shape.

The estimator, the text-only stripper and the modality check share these
walkers so they cannot drift apart: an input_image block counts, strips
and detects the same wherever it nests in message content or tool output.
"""
IMAGE_NOTE = '[image omitted: this model runs text-only]'
# Flat per-block allowance approximating provider image billing (observed
# ~1.3k tokens for one detail: high screenshot); base64 payload length
# must never reach the token estimate.
IMAGE_TOKEN_ALLOWANCE = 1600


def is_image(block):
    return isinstance(block, dict) and block.get('type') == 'input_image'


def count_images(value):
    if is_image(value):
        return 1
    if isinstance(value, dict):
        return sum(count_images(v) for v in value.values())
    if isinstance(value, list):
        return sum(count_images(v) for v in value)
    return 0


def has_images(items):
    return count_images(items) > 0


_DROP = object()


def _walk(value, note):
    if is_image(value):
        return {'type': 'input_text', 'text': IMAGE_NOTE} if note else _DROP
    if isinstance(value, list):
        if count_images(value) == 0:
            return value
        return [r for r in (_walk(v, note) for v in value) if r is not _DROP]
    if isinstance(value, dict):
        if count_images(value) == 0:
            return value
        return {k: r for k, v in value.items()
                for r in (_walk(v, note),) if r is not _DROP}
    return value


def strip_images(items, keep_images):
    if keep_images or not isinstance(items, list):
        return items
    if count_images(items) == 0:
        return items
    return _walk(items, False)


def note_images(items):
    if not isinstance(items, list):
        return items
    if count_images(items) == 0:
        return items
    return _walk(items, True)
