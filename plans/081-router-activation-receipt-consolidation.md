# Plan 081: One writer for the activation receipt

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat a985197..HEAD -- packaging/codex_config.py packaging/claude_config.py packaging/claude_desktop_config.py tests/test_client_activation.py tests/test_claude_config.py tests/test_claude_desktop_config.py`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P2; effort M; risk MED; confidence HIGH; category tech-debt; depends on plans/080-router-atomic-write-consolidation.md.
- Planned at `a985197`, 2026-09-10.
- First proof: a source-level invariant shows `activation.json` is written in exactly one module,
  and Claude attach/detach round-trips keep a prior Codex entry and the original pre-attach snapshot.

## Why this matters

`codex_config.py:88-156` owns the receipt contract (`RECEIPT_VERSION`, `read_receipt`,
`write_receipt`, `drop_client`), and both Claude adapters already receive it as the `receipts`
argument (`install.py:486`, `install.py:530`). Yet both Claude adapters reimplement the
read-modify-write and version forcing:

- `claude_config.py:127-147` builds `clients['claude']` and writes the file itself, with an inline
  `{}` fallback for the snapshot and no `previous_sha256`/`global_instructions`/`openai_mode` keys.
- `claude_desktop_config.py:180-199` does the same with its own `_snapshot()` helper and includes
  the `deploymentMode` field.

The copies have already drifted, and any schema change (new field, atomic write, version bump) must
be made in three places or a client silently loses restore information. (`previous_sha256` is
written by the Codex path but read nowhere repo-wide; keep or drop it explicitly, do not make it
part of the new shared contract.)

## Current state (verified at a985197; line refs refreshed at 12c834b)

- `packaging/codex_config.py:113-129` `write_receipt` merges `clients[client] = {...}` and writes
  the file; `:137-156` `drop_client` writes or unlinks.
- `packaging/claude_config.py:139-147`: builds `{'config_path', 'inserted_block', 'claude_mode'}`,
  sets `receipt['version']`, writes the file, chmods 0600.
- `packaging/claude_desktop_config.py:189-199`: same shape plus `deploymentMode` in the snapshot;
  `_snapshot(text)` at `:142-148`.
- Re-attach snapshot semantics: `claude_config.py:130-138` and
  `claude_desktop_config.py:183-188` must preserve the original pre-attach values when the effective
  values did not change (tested by `tests/test_claude_desktop_config.py::test_reattach_keeps_original_snapshot`).
- Plan 080 adds `packaging/atomic_write.py`; route the receipt writes through it here.

## Scope

**In scope**: `packaging/codex_config.py`, `packaging/claude_config.py`,
`packaging/claude_desktop_config.py`, `tests/test_client_activation.py`,
`tests/test_claude_config.py`, `tests/test_claude_desktop_config.py`.
**Out of scope**: receipt version number, rename of the `receipts` parameter, detach semantics for
hand-managed settings, `previous_sha256` semantics for Codex, any change to what `inserted_block`
contains.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -m unittest tests.test_client_activation tests.test_claude_config tests.test_claude_desktop_config tests.test_install` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; update baseline if counts change |

## Steps

### Step 1: extend `codex_config` with the single entry writer (commit 1)

Add:
```python
def write_client_receipt(home, client, entry):
    """Record one client attachment; other attachments are preserved."""
```
It reads the receipt, **always ensures `doc['version'] = RECEIPT_VERSION` before writing** (a
fresh Claude-only home must not produce a versionless file that `read_receipt` rejects as
never-attached), sets `doc.setdefault('clients', {})[client] = entry`, writes via
`atomic_write.replace_text`, chmods 0600, and returns nothing. Refactor `write_receipt` to build the
Codex entry and delegate to it (keep the `previous_sha256` key for Codex). Add
`parse_snapshot(text)` returning `{}` for non-object JSON, replacing the two private helpers.

### Step 2: switch both Claude adapters (commit 2)

In `claude_config.attach` and `claude_desktop_config.attach`, build only their per-client entry
(preserving `claude_mode`, the `deploymentMode` snapshot field for desktop, and the existing
re-attach snapshot logic) and call `receipts.write_client_receipt(home, 'claude', entry)` /
`receipts.write_client_receipt(home, CLIENT_KEY, entry)`. Delete their local write/version/chmod
code and the local `_snapshot`. `detach` keeps reading via `receipts.read_receipt` and calls
`receipts.drop_client` where it already does.

**Verify**: existing reattach test stays green; add a behavioral test that attaching Claude preserves
a pre-existing `codex` entry byte-for-byte (except formatting), and a fresh-home test (empty tmp
home → attach → `read_receipt` returns `version == RECEIPT_VERSION` with the claude entry present).

### Step 3: source invariant test (same commit)

Add to `tests/test_packaging.py` (or `tests/test_client_activation.py`): among `packaging/*.py`,
the literal `activation.json` appears only in `codex_config.py`. This fails closed if a fourth
writer appears.

## Done criteria

- [ ] `rg -l "activation.json" packaging/` → only `codex_config.py`.
- [ ] No `write_receipt`-style read-modify-write remains in the two Claude adapters.
- [ ] `test_reattach_keeps_original_snapshot` and the attach/detach suites pass unchanged.
- [ ] A fresh-home Claude attach (no prior receipt) reads back via `read_receipt` with `version == RECEIPT_VERSION` and the claude entry present.
- [ ] Receipt writes go through the plan-080 atomic helper.
- [ ] Full suite, compile and limit gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- The reattach snapshot test fails and cannot be preserved through the shared writer: stop; the
  restore contract outranks consolidation.
- `previous_sha256` turns out to be read by a tool outside `packaging/`: stop and report before
  deciding its fate.
- Any adapter needs behavior the shared writer cannot express without a client-specific branch:
  stop and report rather than adding conditionals to the shared function.

## Maintenance notes

- New fields belong to the entry dict built by each adapter; the writer stays dumb.
- If a fourth client arrives, it adds an entry builder only.
- Reviewers: verify the receipt file still ends with a newline and mode 0600 everywhere.
