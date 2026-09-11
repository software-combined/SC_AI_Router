"""Shared Responses event framing; callers own event interpretation."""

# Matches the request-body ceiling: a safety bound, not a protocol limit.
MAX_FRAME_BYTES = 16 * 1024 * 1024


def blocks(response):
    """Yield each original SSE frame and its joined data fields."""
    lines = []
    size = 0
    for line in response:
        size += len(line)
        if size > MAX_FRAME_BYTES:
            raise ValueError(
                'upstream SSE frame exceeds %d bytes' % MAX_FRAME_BYTES)
        lines.append(line)
        if line not in (b'\n', b'\r\n'):
            continue
        data = b'\n'.join(part[5:].lstrip().rstrip(b'\r\n')
                          for part in lines if part.startswith(b'data:')).strip()
        yield b''.join(lines), data
        lines = []
        size = 0
    if lines:
        raise ValueError('Incomplete upstream SSE event')


def replace_data(frame, data):
    """Keep comments, event IDs and event names when replacing JSON data."""
    result, replaced = [], False
    for line in frame.splitlines(keepends=True):
        if line.startswith(b'data:'):
            if not replaced:
                result.append(b'data: ' + data + b'\n')
                replaced = True
        else:
            result.append(line)
    return b''.join(result)
