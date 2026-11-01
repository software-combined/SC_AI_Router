"""Receipt-proven JSON edits without rewriting unrelated settings or formatting.

The standard decoder validates the whole document, including duplicate keys.
Token positions are used only after validation to edit one owned object.
Python 3.9-safe; no file writes or client-specific policy live here.
"""
import json


class Conflict(ValueError):
    """A redacted ownership classification, never a setting value."""


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Conflict('duplicate_keys')
        result[key] = value
    return result


def _constant(value):
    raise Conflict('invalid_json')


def document(text):
    try:
        result = json.loads(text, object_pairs_hook=_unique, parse_constant=_constant)
    except json.JSONDecodeError:
        raise Conflict('invalid_json') from None
    if not isinstance(result, dict):
        raise Conflict('unsupported_structure')
    return result


def snapshot(text, keys):
    """A complete prior-values record; malformed receipts never mean absent."""
    if not isinstance(text, str):
        raise Conflict('damaged_receipt')
    try:
        previous = document(text)
    except Conflict:
        raise Conflict('damaged_receipt') from None
    if any(key not in previous for key in keys):
        raise Conflict('damaged_receipt')
    return previous


def _space(text, index):
    while index < len(text) and text[index] in ' \r\n\t':
        index += 1
    return index


def _members(text, start):
    """Key and value spans in an already validated JSON object."""
    decoder, members = json.JSONDecoder(), []
    index = _space(text, start + 1)
    while text[index] != '}':
        first = index
        key, index = decoder.raw_decode(text, index)
        value_start = _space(text, _space(text, index) + 1)
        _, value_end = decoder.raw_decode(text, value_start)
        members.append((key, first, value_start, value_end))
        index = _space(text, value_end)
        if text[index] == ',':
            index = _space(text, index + 1)
    return members, index


def _scope(text, scope):
    doc, start = document(text), _space(text, 0)
    for key in scope:
        if not isinstance(doc, dict):
            raise Conflict('unsupported_structure')
        if key not in doc:
            return None, None
        row = next(row for row in _members(text, start)[0] if row[0] == key)
        doc, start = doc[key], row[2]
    return doc, start


def _deletions(members, removals):
    edits, index = [], 0
    while index < len(members):
        if index not in removals:
            index += 1
            continue
        first = index
        while index + 1 in removals:
            index += 1
        last = index
        begin, end = members[first][1], members[last][3]
        if last + 1 < len(members):
            end = members[last + 1][1]
        elif first:
            begin = members[first - 1][3]
        edits.append((begin, end, ''))
        index += 1
    return edits


def _edit(text, edits):
    for begin, end, replacement in sorted(edits, reverse=True):
        text = text[:begin] + replacement + text[end:]
    document(text)
    return text


def remove_item(text, scope, entry):
    """Remove one receipt-proven callback, preserving every other array item."""
    values, start = _scope(text, scope)
    if start is None:
        return text
    if not isinstance(values, list):
        raise Conflict('unsupported_structure')
    matches = [index for index, value in enumerate(values) if value == entry]
    if len(matches) > 1:
        raise Conflict('ambiguous_callback')
    if not matches:
        return text
    decoder, members, index = json.JSONDecoder(), [], _space(text, start + 1)
    for item in range(len(values)):
        _, end = decoder.raw_decode(text, index)
        members.append((item, index, index, end))
        index = _space(text, end)
        if text[index] == ',':
            index = _space(text, index + 1)
    return _edit(text, _deletions(members, set(matches)))


def restore(text, scope, written, previous):
    """Restore proven keys or accept an already completed restore on retry.

    None in the receipt means the key was absent. A user-written null is
    distinct from that absence and is never removed as if owned.
    """
    doc, start = _scope(text, scope)
    if not isinstance(written, dict) or not written or any(key not in previous for key in written):
        raise Conflict('damaged_receipt')
    if start is None:
        if all(previous[name] is None for name in written):
            return text
        raise Conflict('connection_changed')
    if not isinstance(doc, dict):
        raise Conflict('unsupported_structure')
    members, _ = _members(text, start)
    removals, edits = set(), []
    for key, expected in written.items():
        old = previous[key]
        if (key not in doc and old is None) or (old is not None and doc.get(key) == old):
            continue
        if key not in doc or doc[key] != expected:
            raise Conflict('connection_changed')
        index = next(index for index, row in enumerate(members) if row[0] == key)
        if old is None:
            removals.add(index)
        else:
            row = members[index]
            edits.append((row[2], row[3], json.dumps(old, ensure_ascii=False)))
    # Delete each consecutive run with one adjacent comma, keeping all bytes
    # belonging to surviving members, including their key spelling and values.
    return _edit(text, edits + _deletions(members, removals))
