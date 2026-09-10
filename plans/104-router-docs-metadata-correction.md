# Plan 104: Correct stale version metadata, architecture notes, and README claims

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat a985197..HEAD -- pyproject.toml packaging/VERSION docs/architecture.md README.md tests/test_packaging.py`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P3; effort S; risk LOW; confidence HIGH; category docs; depends on none (README edits
  coordinate with Plan 117 Stage 5; see below).
- Planned at `a985197`, 2026-09-10.
- First proof: a test asserts `pyproject.toml`'s version equals `packaging/VERSION`; the architecture
  notes and the two README claims match current behavior.

## Why this matters

Four documents are actively wrong in ways a reader can act on:

1. `pyproject.toml:3` says `version = "0.6.9"` while `packaging/VERSION` is `0.6.14`; nothing reads
   or checks it (`packaging/release.py:74` reads only `packaging/VERSION`).
2. `docs/architecture.md:53-54` says `install.py` still dispatches `darwin` vs `linux` inline with a
   `systemd_manager()` flag and points at Plan 056 to extract `packaging/platforms/`. Reality:
   `install.py:112-118` delegates through `_platforms.select`, `packaging/platforms/` exists, and
   Plan 056 is completed and removed (`plans/README.md` removal log). Line `:55-56` (service.py launchd half) is still accurate
   and should be retargeted at Plan 103.
3. `README.md:201-202` says a 503 with `Retry-After` means the router is draining. Upstream 429s are
   also mapped to a retryable 503 (`ai_router/router.py:321-323`,
   `ai_router/errors.py:247-248` `UPSTREAM_RATE_LIMITED`) with a different body code from
   `SERVER_DRAINING` (`errors.py:243-244`).
4. `README.md:172-173` says the Claude listing "will apply the mirror rule ... when it lands". The
   listing is live at `GET /v1/models` (`ai_router/router.py:155-156`, `ai_router/claude.py:66-78`)
   and deliberately includes every OpenRouter registry row; the mirror rule applies to catalogue
   merging (`ai_router/clients/__init__.py:10-23`), not to this listing.

Plan 117 Stage 5 owns README corrections; fix these two claims here and record that in the 117 row
so the two workstreams never edit `README.md` concurrently.

## Current state (verified at a985197; line refs refreshed at 12c834b)

- `pyproject.toml:3` `version = "0.6.9"`; `packaging/VERSION` = `0.6.14`.
- `docs/architecture.md:53-56`:
  > - `packaging/install.py` still dispatches `darwin` vs `linux` inline with a
  >   `systemd_manager()` two-valued flag (Plan 056 extracts `packaging/platforms/`).
  > - `packaging/service.py` mixes launchd/plist/feed/state helpers (Plan 056
  >   re-homes the launchd half with the darwin backend).
- `README.md:172-173` and `:201-202` as quoted above.
- `tests/test_packaging.py:111,152` holds the version checks; add the parity check beside them.

## Scope

**In scope**: `pyproject.toml`, `docs/architecture.md`, `README.md` (the two passages only),
`tests/test_packaging.py`, `plans/README.md` (status row only).
**Out of scope**: `packaging/VERSION`, the release workflow, any other README section, the pinned
runtime-file list test (`test_readme_runtime_list_matches_files`), Plan 117's other stages.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -m unittest tests.test_release tests.test_packaging` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |

## Steps

### Step 1: version parity (commit 1)

Set `pyproject.toml` version to `0.6.14` (match `packaging/VERSION` exactly; strip any build
suffix logic the same way `release.yml` does). Add a parity test beside the existing version checks in `tests/test_packaging.py` asserting
`tomllib`-parsed `pyproject.toml` version equals `packaging/VERSION` text (repo uses Python 3.14,
`tomllib` is stdlib).

### Step 2: architecture notes (commit 1)

In `docs/architecture.md`: delete the install.py bullet; rewrite the service.py bullet to say the
launchd half is being extracted by Plan 103 (and that `health`/`wait_version`/`ensure_serving` stay
cross-platform). Keep the "do not entrench" framing.

### Step 3: README corrections (commit 2)

Replace the two passages with wording that matches behavior:

- Drain/429: "A 503 with `Retry-After` means the request was not served — either the router is
  draining (`SERVER_DRAINING`) or an upstream 429 was mapped to a retryable answer
  (`UPSTREAM_RATE_LIMITED`); the JSON body names the code. Retry after the delay."
- Claude listing: "The Claude listing is live at `GET /v1/models` and includes every OpenRouter
  registry row (bare `anthropic/...` ids and `claude/<slug>` aliases); the mirror rule that hides
  OpenRouter-billed rows from the Codex picker is a catalogue-merge rule and does not filter this
  listing."

Do not touch the pinned runtime-file list. Record in `plans/README.md`'s 117 row that these two
README claims were corrected here.

## Done criteria

- [ ] `pyproject.toml` version equals `packaging/VERSION`; new test fails on a mismatch.
- [ ] Architecture notes match the code (no `systemd_manager`, no live Plan-056 pointer).
- [ ] Both README claims are behavior-accurate; 117 row notes the correction.
- [ ] Full suite and compile gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- `pyproject.toml` version is intentionally unrelated to the release version (documented anywhere):
  stop and report before changing it.
- The README passages have already been rewritten by Plan 117 work in the same tree: stop; do not
  run both workstreams on the file.

## Maintenance notes

- The parity test makes `pyproject.toml` a checked duplicate; if the field is ever declared
  vestigial, remove both the field and the test.
- Reviewers: confirm the README edits preserve the surrounding lines (the file is pinned elsewhere
  for runtime-file names).
