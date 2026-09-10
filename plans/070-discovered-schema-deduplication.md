# Plan 070: Keep one effective discovered schema per tool through compaction

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat 83a5023..HEAD -- codex_router/discovered.py tests/test_discovered.py tests/test_tool_adapter.py CHANGELOG.md packaging/VERSION plans/README.md`
> Read changed code and preserve current namespace/schema precedence before edits.

## Status and first proof

- DONE (source, 2026-09-10): wrapper-aware dedup implemented in `3ec24bc` (PR #54); repeated rediscovery retains one effective definition; P2; effort S; risk MED; confidence HIGH; category perf/memory.
- Planned at `83a5023`, 2026-09-10. Independent of 068/069.
- First proof: repeated compaction/rediscovery retains one effective definition
  per namespace/name, including after restart, with unchanged prepared tools.

## Current state

`discovered.py:121-134` combines fresh tool definitions with all recalled ones:

```python
defs.extend(deepcopy(item['tools']))
defs.extend(recall(items))
_MEMORY[key] = deepcopy(defs)
_write_disk(key, defs)
```

With disk writes mocked, rediscovering one tool on each of 20 compactions stores
20 definitions. `prepare_tools` at tool_adapter.py:74-88 later deduplicates:

```python
if existing is not None:
    if existing.get('parameters') is None and tool.get('parameters') is not None:
        existing['parameters'] = tool['parameters']
    continue
```

Thus this is cache/copy/disk waste, not multiplied upstream tool tokens.
tests/test_discovered.py:36-46 checks a set of names, hiding duplicates.
Follow that file's isolated-home helpers and existing restart/V1/V2 tests.

## Scope and commands

Only drift-check files plus this plan status. Do not change the cache location,
16-entry retention policy, compaction envelope, permissions, wire tool names or
credential handling. No arbitrary tool-count/byte cap or schema eviction.

| Gate | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_discovered tests.test_tool_adapter` | Baseline pass; regressions fail then pass |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | Exit 0 |
| Compile | `python3.14 -m compileall -q codex_router tools tests packaging` | Exit 0 |
| Size/diff | `python3.14 tools/check_source_limits.py` and `git diff --check` | Exit 0 |

## Steps and test plan

1. Extend tests/test_discovered.py with chained repeated rediscovery using
   existing helpers and temporary home. Assert effective definition count and
   equality of prepared tools, not just a set of names. Cover plain tools and
   the same name in two namespaces. Clear _MEMORY and assert the disk round trip
   gives the same deduplicated result. **Verify:** focused command exposes growing
   cardinality on the unfixed source without changing valid existing assertions.
2. Deduplicate before memory/disk storage by (namespace, name), in stable
   first-occurrence order. Preserve namespace wrappers and existing precedence:
   first full definition wins; a later full schema may complete an earlier stub
   lacking parameters. Do not replace first metadata wholesale. Fresh entries
   precede recalled entries today; preserve that order and copy isolation.
   Do not import tool_adapter into discovered: tool_adapter already imports it.
   Keep the small traversal local unless an existing dependency-safe helper fits.
   **Verify:** focused tests cover a fresh full schema versus recalled older
   full schema, a fresh stub versus recalled full schema, namespace collisions,
   and mutation of returned data not changing the stored definition.
3. Existing disk entries can already contain duplicates. Apply the same bounded
   normalisation on recall/insertion into memory without bulk rewriting files or
   changing the disk format. Preserve missing/unreadable-cache behavior. Avoid
   extra repeated deepcopies of each duplicate before it is discarded.
   **Verify:** seed a legacy duplicate fixture in the isolated home, recall it,
   and assert the same effective prepared-tool semantics with no lost full schema.
4. Update changelog/version and status with source evidence. **Verify:** all
   commands above pass and `git diff --name-only` contains only scoped files.

## Done, integration and stop conditions

- [ ] Effective stored/recalled count stays constant for repeated identical
  rediscovery; distinct names/namespaces and schema precedence remain correct.
- [ ] Existing restart, V1/V2, provider preparation and namespace tests pass.
- [ ] Full suite/compile/size/diff checks pass; no live cache or state was touched.
- Use one owned `codex/` worktree based on develop and reuse it. Run current
  pre-commit-review before a `fix:` commit, integrate into develop and verify
  before safe worktree cleanup. Source tests do not prove deployed memory savings.
- Stop if deduplication would drop a valid schema, change namespace/wire identity,
  add a circular import, or require a new cache format/migration. Preserve the
  full-schema completion rule; naive first-wins alone is insufficient.
- Maintenance: new schema shapes must retain the same effective identity and
  precedence tests. Do not promote this into a general cache framework.
