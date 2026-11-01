"""Discovered tool schemas keyed by compaction summary, memory plus disk.

A compacted thread replays only its summary, so per-turn rederivation loses
schemas after repeated compaction; memory alone loses them on restart. The
key is the raw summary text: V1 user messages carry it after SUMMARY_PREFIX
and V2 compaction items carry it inside the ocx1 envelope, so both legs and
every later compaction of the same thread resolve to one entry.
"""
import hashlib
import json
import os
import threading
from copy import deepcopy
from .compaction import SUMMARY_PREFIX, decode_summary
from .atomic_write import replace_text
from .state import default_home
from .tool_merge import merge_tool_defs

_MEMORY, _LOCK, _MAX = {}, threading.Lock(), 16


def _store_dir():
    return default_home() / 'discovered-tools'


def _key(summary):
    return hashlib.sha256(summary.encode()).hexdigest()


def _write_disk(key, defs):
    try:
        directory = _store_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (key + '.json')
        replace_text(path, json.dumps(defs))
        _stamp_and_prune(directory, path, _MAX)
    except OSError:
        pass  # The memory entry still serves this process.


def _stamp_after(path, latest):
    """Set path's mtime strictly past `latest`, surviving filesystem rounding.

    Windows FILETIME has 100 ns granularity and truncates the written value on
    readback, so a +1 ns bump ties with the sibling instead of ordering after
    it. Step past `latest`, confirm the stored value actually moved, and widen
    the step for any filesystem that rounds harder."""
    step = 1000
    for _ in range(20):
        target = latest + step
        os.utime(path, ns=(target, target))
        stored = path.stat().st_mtime_ns
        if stored > latest:
            return stored
        step *= 8
    return latest + step  # unreachable in practice; keep strict ordering


def _stamp_and_prune(directory, newest, limit):
    """Order by insertion, not the clock: stamp the new file past every
    sibling so rapid successive compactions still evict oldest-first."""
    try:
        entries = [(p.stat().st_mtime_ns, p) for p in directory.glob('*.json')]
    except OSError:
        return
    try:
        latest = max(ns for ns, p in entries if p != newest)
        stamped = _stamp_after(newest, latest)
        entries = [(stamped if p == newest else ns, p) for ns, p in entries]
    except (OSError, ValueError):
        pass
    entries.sort()
    if len(entries) > limit:
        for _, path in entries[:-limit]:
            try:
                path.unlink()
            except OSError:
                pass


def _read_disk(key):
    try:
        return json.loads((_store_dir() / (key + '.json')).read_text())
    except (OSError, ValueError):
        return None


def summaries_in(items):
    """Raw summary texts replayed in this input, V1 messages and V2 items."""
    found = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        if (item.get('type') in (None, 'message') and item.get('role') == 'user'):
            content = item.get('content')
            if isinstance(content, str):
                texts = [content]
            elif isinstance(content, list):
                texts = [b.get('text', '') for b in content
                         if isinstance(b, dict) and isinstance(b.get('text'), str)]
            else:
                texts = []
            for text in texts:
                if isinstance(text, str) and text.startswith(SUMMARY_PREFIX):
                    found.append(text[len(SUMMARY_PREFIX):].lstrip('\n'))
        elif item.get('type') == 'compaction':
            decoded = decode_summary(item.get('encrypted_content'))
            if decoded:
                found.append(decoded)
    return found


# Plan 129: the keying/stub/wrapper rule lives in tool_merge; the public
# name stays for callers and tests.
_dedup = merge_tool_defs


def remember(items, summary):
    """Store tool_search_output schemas under this compaction summary."""
    if not isinstance(summary, str) or not summary.strip():
        return
    defs = []
    for item in items if isinstance(items, list) else []:
        if (isinstance(item, dict) and item.get('type') == 'tool_search_output'
                and isinstance(item.get('tools'), list)):
            defs.extend(deepcopy(item['tools']))
    defs.extend(recall(items))
    defs = _dedup(defs)
    if not defs:
        return
    key = _key(summary.strip())
    with _LOCK:
        _MEMORY[key] = deepcopy(defs)
        if len(_MEMORY) > _MAX:
            _MEMORY.pop(next(iter(_MEMORY)))
    _write_disk(key, defs)


def recall(items):
    """Schemas for summaries replayed in this input, memory then disk."""
    summaries = summaries_in(items)
    if not summaries:
        return []
    found = []
    for summary in summaries:
        key = _key(summary)
        with _LOCK:
            defs = _MEMORY.get(key)
        if defs is None:
            defs = _read_disk(key)
            if defs is not None:
                with _LOCK:
                    # No eviction here: remember stays the only evictor.
                    _MEMORY.setdefault(key, deepcopy(defs))
        if defs:
            # Legacy disk entries may already hold duplicates; apply
            # the same normalisation on recall without rewriting files.
            found.extend(deepcopy(_dedup(defs)))
    return found
