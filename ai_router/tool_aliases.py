"""Readable wire names for namespaced client tools, with repair on re-type.

Models re-type high-entropy hash prefixes and drop characters, so expose
namespaced tools under readable ``namespace__tool`` aliases and repair a
damaged alias back to the exact exposed name before dispatch. A disambiguated
fallback (the readable stem plus a short digest) covers collisions and
over-length names, and a name the request already exposes is never rewritten.
"""
import hashlib
import re

from .standalone_outputs import DELIVERED_NAMES

# Provider function-name ceiling; the disambiguated fallback also fits it.
LIMIT = 64

PREFIX = 'unsupported call: '
HINT = 'No tool with that exact name is exposed this turn.'
HINT_DELIVERED = ('That name marks a message delivered to you, not a tool. '
                  'Reply in your answer or with the collaboration tools.')
EDITS = 2  # a re-typed alias is repaired within this many edits


class ToolNames(dict):
    """Wire-name map plus the names the repairer must never touch.

    ``reserved`` holds every name this request already exposes: top-level
    client tools and every wire name assigned before the tool ceiling drops
    some. A call to one of those is exact, so it is neither repaired nor
    counted as unresolved.

    ``dropped`` holds the native names of namespaced tools the client sent but
    this turn did not expose, so a surviving same-named sibling can never be
    substituted for one of them.
    """

    def __init__(self):
        super().__init__()
        self.reserved = set()
        self.dropped = set()


def _clean(value):
    return re.sub(r'[^A-Za-z0-9_-]', '_', value)


def fallback(namespace, name, width=12):
    """Disambiguated fallback: the readable stem plus a short digest.

    Sanitised, always within ``LIMIT``, and never a bare hash: the model can
    still read the tool it is calling when the name had to be shortened.
    """
    suffix = '_' + hashlib.sha256((namespace + '\0' + name).encode()).hexdigest()[:width]
    stem = _clean(namespace) + '__' + _clean(name)
    return stem[:LIMIT - len(suffix)] + suffix


def readable(namespace, name):
    """Readable alias, or None when longer than the provider ceiling."""
    candidate = _clean(namespace) + '__' + _clean(name)
    return candidate if len(candidate) <= LIMIT else None


def wire_names(pairs, taken):
    """Map ordered (namespace, name) pairs to one wire name each.

    Two-pass and order-independent: a readable candidate is used only when
    it fits, is produced by exactly one pair, and is not already taken.
    Every colliding or oversized pair falls back to a disambiguated name
    (all colliding sources, not just the later one).
    """
    counts = {}
    for pair in pairs:
        candidate = readable(*pair)
        if candidate is None or candidate in taken:
            continue
        counts[candidate] = counts.get(candidate, 0) + 1
    taken = set(taken)
    mapping = {}
    for pair in pairs:
        candidate = readable(*pair)
        if (candidate is not None and counts.get(candidate) == 1
                and candidate not in taken):
            mapping[pair] = candidate
        else:
            alias = fallback(*pair)
            for width in (16, 20, 24, 32, 48):
                if alias not in taken:
                    break
                alias = fallback(*pair, width)
            if alias in taken:
                # Never share a wire name: a duplicate would silently
                # re-target every call to whichever tool registered last.
                raise ValueError(
                    f'tool {pair[0]}.{pair[1]} has no unique wire name; trim the tool set')
            mapping[pair] = alias
        taken.add(mapping[pair])
    return mapping


def bind(entries):
    """Wire-name map for one request's (tool, namespace) entries."""
    entries = list(entries)
    pairs = [(ns, tool['name']) for tool, ns in entries if ns and 'name' in tool]
    top = {tool['name'] for tool, ns in entries if not ns and 'name' in tool}
    mapping = ToolNames()
    mapping.reserved |= top
    mapping.update(wire_names(pairs, top))
    mapping.reserved |= set(mapping.values())
    return mapping


def reserved(names):
    """Names this request already exposes; never repair sources or targets."""
    return getattr(names, 'reserved', ())


def dropped(names):
    """Native names the client sent but this turn did not expose."""
    return getattr(names, 'dropped', ())


def _renamed(entry):
    return (isinstance(entry, dict) and entry.get('kind') is not None
            and 'namespace' in entry and 'name' in entry)


def _near(called, wire, limit=EDITS):
    """True when called is within `limit` edits of wire (bounded distance)."""
    if abs(len(called) - len(wire)) > limit:
        return False
    previous = list(range(len(wire) + 1))
    for i, left in enumerate(called, 1):
        current = [i]
        for j, right in enumerate(wire, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (left != right)))
        if min(current) > limit:
            return False
        previous = current
    return previous[-1] <= limit


def _hex(value):
    return all(character in '0123456789abcdef' for character in value)


def _digest_damage(called, wire, namespace, native, limit=EDITS):
    """True when called is wire with a slipped disambiguating digest.

    Only a wire the fallback branch minted for this pair counts, and only the
    router's own digest widths, so a readable sibling name whose last segment
    merely looks like a digest can never be rewritten onto another tool.
    """
    if wire == readable(namespace, native):
        return False
    stem, _, digest = wire.rpartition('_')
    if len(digest) not in _DIGEST_WIDTHS or not _hex(digest):
        return False
    prefix = stem + '_'
    if not called.startswith(prefix):
        return False
    tail = called[len(prefix):]
    return (bool(tail) and _hex(tail) and abs(len(tail) - len(digest)) <= limit
            and _near(tail, digest, limit))


_DIGEST_WIDTHS = (12, 16, 20, 24, 32, 48)  # router-minted digest widths


def _hex_tail(called):
    """True when called ends in a digest-width hex segment.

    A readable alias whose last segment looks like a disambiguating digest
    names a real (possibly now absent) tool, not a typo: repairing it onto
    a one-character-different survivor would misroute, so the near-miss
    class leaves it to the client.
    """
    tail = called.rpartition('_')[2]
    return len(tail) in _DIGEST_WIDTHS and _hex(tail)


def _repair_class(called, wire, namespace, native):
    """The repair class for one wire candidate, or None."""
    if called == native:
        return 'exact'
    if called == namespace + '.' + native:
        return 'dotted'
    if _digest_damage(called, wire, namespace, native):
        return 'digest'
    if (wire == readable(namespace, native)
            and _near(called, wire)
            and not _hex_tail(called)):
        return 'near'
    return None


def candidates(names, called):
    """Ordered exposed wire names the caller could have meant.

    Only router-renamed namespaced tools are eligible, never a name this
    request already exposes, and never a native name the client sent but this
    turn did not expose. Repairs stay as wide as the shapes the router mints:
    the plain native name, the dotted description form, a fallback alias
    with damaged digest characters, or a readable alias within two edits
    (an ambiguous near miss is never guessed). Anything else is left to the
    client.
    """
    if (not isinstance(called, str) or not called or called in reserved(names)
            or called in dropped(names)):
        return []
    if called in DELIVERED_NAMES:
        return []
    classes = {'exact': [], 'dotted': [], 'digest': [], 'near': []}
    for key, entry in names.items():
        if len(key) != 2 or key[0] is not None or not _renamed(entry):
            continue
        wire, native = key[1], entry['name']
        shape = _repair_class(called, wire, entry['namespace'], native)
        if shape:
            classes[shape].append(wire)
    return sum(classes.values(), [])


def repair(names, called):
    """The single matching wire name, else None; ambiguity never guesses."""
    matches = candidates(names, called)
    return matches[0] if len(matches) == 1 else None


def repair_item(item, names, notes, logged):
    """Repair one unknown function call in place; True when it changed.

    An already exposed name is exact, so it passes through silently;
    everything else is repaired or counted once per call.
    """
    called = item.get('name')
    if isinstance(called, str) and called in reserved(names):
        return False
    wire = repair(names, called)
    key = item.get('id') or item.get('call_id') or called
    if key not in logged:
        logged.add(key)
        from .runtime import log_event
        model = notes.get('model') if isinstance(notes, dict) else None
        cause = 'unknown'
        if isinstance(called, str) and called in DELIVERED_NAMES:
            cause = 'delivered'
        if wire is not None:
            entry = names[(None, wire)]
            shape = _repair_class(called, wire, entry['namespace'], entry['name'])
            cause = 'native' if shape == 'exact' else shape
        log_event('tool_call_repaired' if wire is not None else 'tool_call_unresolved',
                  model=model, cause=cause)
    if wire is None:
        return False
    item['name'] = wire
    item.pop('namespace', None)
    return True


def annotate(output, names):
    """Append one routing line to a client unsupported-call output.

    The client's own text is never edited, and an existing hint is left
    alone, so a re-prepared payload cannot stack lines.
    """
    if (not isinstance(output, str) or not output.startswith(PREFIX)
            or HINT in output or HINT_DELIVERED in output):
        return output
    called = output[len(PREFIX):].split('\n', 1)[0].strip()
    if (None, called) in names or called in reserved(names):
        return output
    if called in DELIVERED_NAMES:
        return output + '\n' + HINT_DELIVERED
    options = candidates(names, called)[:3]
    if options:
        return output + '\n' + HINT + ' Use the exact exposed name: ' + ', '.join(options)
    return output + '\n' + HINT + ' Re-read the tool list and copy an exact name.'
