# Plan 097: Take the global lock off the discovered-recall disk path

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat a985197..HEAD -- ai_router/discovered.py tests/test_discovered.py`
> Read changed code and preserve current behavior before edits.
> Reconciliation 2026-09-11 (branch codex/router-plan-backlog-20260911, 122/123/090-096 and 136
> landed): drift check is empty for both in-scope files. `remember` still stores
> `deepcopy(defs)` under `_LOCK` and is the only evictor (`discovered.py:197-201`); `_read_disk`
> still returns `None` on any error (`:85-89`); `_dedup` is still read-only over its input
> (`:127-180`). The only stale ref is the `tool_adapter.py:75` call-site line, now `:77`
> (`prepare_tools` moved from `:67` to `:69`); reconciled above. STOP conditions do not apply:
> no in-place `_MEMORY` mutation outside `remember`, and FIFO eviction order is untouched.

## Status and first proof

- Priority P2; effort S; risk LOW; confidence HIGH; category perf; depends on none.
- Planned at `a985197`, 2026-09-10.
- First proof: recall returns the same definitions as today while concurrent requests no longer
  serialize on disk reads or deep-copies; repeated recall of an evicted key still re-reads disk.

## Why this matters

`discovered.recall` (`ai_router/discovered.py:204-219`) holds the single module lock `_LOCK` across
the entire call: the input scan (`summaries_in`), `_read_disk`, the `_MEMORY` deep-copy and
`deepcopy(_dedup(defs))`. It is called on every OpenRouter request (`ai_router/tool_adapter.py:77`
via `prepare_tools`; `:75` at plan time). With more than 16 active summaries (or a cold start), concurrent routed
requests queue behind one request's disk I/O and copies; a cache miss re-reads disk on every
request because misses are not cached. `remember` only replaces `_MEMORY` values under the lock and
never mutates stored entries, so the lock is needed only for the memory-map read/insert.

## Current state (verified at a985197)

- `ai_router/discovered.py:17` — `_MEMORY, _LOCK, _MAX = {}, threading.Lock(), 16`.
- `ai_router/discovered.py:204-219`:
  ```python
  def recall(items):
      found = []
      with _LOCK:
          for summary in summaries_in(items):
              key = _key(summary)
              defs = _MEMORY.get(key)
              if defs is None:
                  defs = _read_disk(key)
                  if defs is not None:
                      _MEMORY[key] = deepcopy(defs)
              if defs:
                  found.extend(deepcopy(_dedup(defs)))
      return found
  ```
- `remember` (`:183-201`) stores `deepcopy(defs)` under `_LOCK` and evicts FIFO above `_MAX`; it
  never mutates an existing entry in place.
- `_read_disk` (`:85-89`) returns `None` on any error; `_dedup` (`:127-180`) is read-only over its input.

## Scope

**In scope**: `ai_router/discovered.py`, `tests/test_discovered.py`.
**Out of scope**: cache location, 16-entry retention, disk format, `remember` semantics,
`_stamp_and_prune`, `prepare_tools` dedup, any new eviction policy.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_discovered tests.test_tool_adapter tests.test_providers` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; update baseline only if `discovered.py` crosses the soft limit |

## Steps

### Step 1: narrow the lock (commit 1)

Restructure `recall` so only `_MEMORY` access happens under `_LOCK`:

```python
def recall(items):
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
                    _MEMORY.setdefault(key, deepcopy(defs))
        if defs:
            found.extend(deepcopy(_dedup(defs)))
    return found
```

Keep the current semantics exactly: no eviction on recall-insert (today `remember` is the only
evictor), disk values are deep-copied into memory, and every returned definition is a deep copy so
callers cannot mutate the cache. Concurrent duplicate disk reads are harmless. Do not change
`remember`.

### Step 2: tests (same commit)

Keep the existing `tests/test_discovered.py` coverage green (restart, V1/V2, dedup, pruning).
Add one regression test that fails if recall mutates cache state: recall a key, mutate the returned
definitions, recall again, assert unchanged; and one test that an evicted key still resolves from
disk (simulating `_MAX` overflow as the existing tests do).

**Verify**: focused modules pass; the mutation test fails if `deepcopy` is dropped from the return path.

## Done criteria

- [x] `_read_disk`, `_dedup` and deep copies run outside `_LOCK`.
- [x] Returned data is still copy-isolated; disk round-trip behavior unchanged.
- [x] Existing restart/dedup/prune tests pass.
- [x] Full suite, compile and limit gates pass; only in-scope files changed.
- [x] `plans/README.md` status row updated.

Implemented 2026-09-11 (branch codex/router-plan-backlog-20260911): `recall` scans input and
returns before touching the lock, takes `_MEMORY.get` and the recall-insert `setdefault`
(each under `_LOCK`, no eviction on insert), and runs `_read_disk`/`_dedup`/deep-copies
outside the lock. Semantics kept exactly: `remember` untouched and still the only evictor,
disk values deep-copied into memory, every returned definition a deep copy. Regression tests:
`test_mutating_disk_backed_recall_leaves_store_intact` (disk-path copy isolation) and
`test_evicted_key_still_resolves_from_disk` (memory-evicted key re-reads disk). Negative
checks: both mutation tests fail with the copies dropped (2 failures on the no-copy variant);
the eviction test passes on old code, as expected for unchanged semantics.

## STOP conditions

- A test demonstrates that `_MEMORY` entries are mutated in place somewhere outside `remember`:
  stop and report; the lock scope analysis is then wrong.
- The change alters the FIFO eviction order observed by tests: stop.

## Maintenance notes

- If recall ever starts evicting, the eviction must move under the lock with `remember`'s policy.
- The module lock still serializes `remember` writes; that path is rare (compaction) and untouched.
- Reviewers: confirm every `_MEMORY` access is inside `_LOCK` after the change.
