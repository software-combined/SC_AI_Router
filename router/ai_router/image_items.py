"""Image-block helpers for the Responses input shape.

An input_image block counts and detects the same wherever it nests in
message content or tool output.
"""
IMAGE_NOTE = ('ERROR: Cannot read image (this model does not support '
               'image input). Inform the user.')
# Last-resort trim note. Never the capability note above: the model can read
# this image, the router is just not carrying it any further.
IMAGE_TRIM_NOTE = ("[earlier image omitted: this thread's carried history "
                   'outgrew the router request limit; re-read the file if it '
                   'matters]')
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


def image_payload_bytes(value):
    """Carried bytes inside input_image blocks, however deep they nest."""
    if is_image(value):
        return sum(len(v) for key, v in value.items()
                   if key in ('url', 'image_url', 'data') and isinstance(v, str))
    if isinstance(value, dict):
        return sum(image_payload_bytes(v) for v in value.values())
    if isinstance(value, list):
        return sum(image_payload_bytes(v) for v in value)
    return 0


def image_blocks(value):
    """(container, key) for each input_image block, in traversal order."""
    if isinstance(value, dict):
        for key, item in value.items():
            if is_image(item):
                yield value, key
            else:
                yield from image_blocks(item)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if is_image(item):
                yield value, index
            else:
                yield from image_blocks(item)


def has_images(items):
    return count_images(items) > 0


def _walk(value):
    if is_image(value):
        return {'type': 'input_text', 'text': IMAGE_NOTE}
    if isinstance(value, list):
        if count_images(value) == 0:
            return value
        return [_walk(v) for v in value]
    if isinstance(value, dict):
        if count_images(value) == 0:
            return value
        return {k: _walk(v) for k, v in value.items()}
    return value


def note_images(items):
    if not isinstance(items, list):
        return items
    if count_images(items) == 0:
        return items
    return _walk(items)
