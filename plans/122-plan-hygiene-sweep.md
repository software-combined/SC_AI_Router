# Plan 122: Sweep the live backlog clean of pre-rename paths, placeholders and stale counts

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat b642de9..HEAD -- plans/`
> Read changed text and preserve intent before edits.

## Status and first proof

- Priority P1; effort S; risk LOW; confidence HIGH; category docs; depends on none.
- Run BEFORE executing plans 094, 101, 102, 103 (it fixes their citations).
- Planned at `b642de9`, 2026-09-11.
- First proof: every live plan's drift-check command is runnable as written, and no live plan
  points at `codex_router/`, `<ROUTER_ROOT>`, `feed_token.py`, or stale line counts.

## Why this matters

The package rename (old Plan 074) and the backlog renumbering/cleanup (commit `b642de9`) fixed the
docs but not the plans. Verified at `b642de9`:

- 12 live plans still name the pre-rename package in edit targets/commands: `plans/099:61`,
  `109:51`, `111:52`, `113:22-23`, `115:22`, `116:64-65`, `118:73`, `119:8,54,62` (and any others
  `rg` finds).
- 5 live plans carry the literal placeholder `<ROUTER_ROOT>` in the mandatory-first drift check:
  `plans/099:17`, `109:9`, `110:29`, `111:9`, `118:19` — the command cannot run.
- `plans/110:71,92` expects `dist/codex-model-router-<VERSION>.tar.gz`, but `packaging/release.py:103`
  writes `ai-router-<version>.tar.gz`; `plans/110:63` uses the retired repo slug.
- Deleted/stale source facts: plans 094 and 101 cite `packaging/feed_token.py` (deleted in `099ca9f`,
  now `packaging/feed.py`); plan 094 says `codex_config.py` is 152 lines (actual 156); plan 102 says
  `install.py` is 697 (actual 700, the hard cap); plan 103 says `service.py` is 680 (actual 671).

An executor following a plan with an unrunnable drift check or a nonexistent path either stalls or
improvises; this sweep is the cheapest way to prevent that across the whole backlog.

## Current state (verified at b642de9)

- `rg -l 'codex_router/' plans/0*.md plans/1*.md` → 12 files; 107, 112, 113, 115, 116, 117
  and 119 also name `codex_router/` paths inside edit targets or commands.
- `rg -l '<ROUTER_ROOT>' plans/*.md` → 099, 109, 110, 111, 118.
- Scanning after this sweep also returns plans 122 and 134; those mentions are
  intentional (this sweep's rule text and the compatibility-shim discussion).
- `wc -l packaging/install.py` → 700; `packaging/service.py` → 671; `packaging/codex_config.py` → 156.
- `packaging/release.py:103` names the bundle `ai-router-<version>.tar.gz`; `release.py:18` and
  `feed.py:22` use repository `SC_OpenRouter_adapter`.

## Scope

**In scope**: numbered live plans `plans/090-121` (text only).
**Out of scope**: dated reports (`plans/2026-*`), `parked/`, `rejected-muse-retry/`, source code,
`plans/README.md` (update only if a row's wording depends on a fixed value). Do NOT rewrite
mentions that discuss the `codex_router/` compatibility shim itself (its deprecation/removal is
plan 134) — only repo paths and runnable commands.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Stale scan | `rg -n 'codex_router[./]|<ROUTER_ROOT>|feed_token\.py' plans/0*.md plans/1*.md` | only intentional/historical hits remain (dot-form module run commands are renamed too, not just `codex_router/`) |
| Counts | `rg -n '697| 680 lines|152' plans/094*.md plans/102*.md plans/103*.md` | no stale counts |
| Diff | `git diff --check` | exit 0 |

## Steps

1. Replace `codex_router/` with `ai_router/` everywhere a plan names a repo path, module run
   command, or test target. Leave any sentence about the compatibility shim/alias package intact.
2. Replace `<ROUTER_ROOT>` in the five drift checks with a runnable form, e.g.
   ``git diff --stat b642de9..HEAD -- $(git rev-parse --show-toplevel)/<paths>`` or drop the root
   token and keep the path list. Keep the check's intent (detect drift in in-scope files).
3. In plan 110: artifact name → `ai-router-<version>.tar.gz`; repo slug → `SC_OpenRouter_adapter`.
4. Refresh stale facts: plan 094 and 101 `feed_token.py` → `feed.py` (drop the file-specific
   import bullet in 101 if it no longer applies — `feed.py`'s urllib imports are used); plan 094
   `152` → `156`; plan 102 `697`/`below 697` → `700`/`below 700` (it is now exactly at the cap);
   plan 103 `680` → `671`. Also correct plan 100 (same stale citation): `packaging/service.py:39-41` is not a `sys.path` precedent — service.py has no `sys.path` insert; point at `packaging/install.py:22` or the loader block (then `service.py:36-43`; since plan 123 it is `service.load()` at `service.py:38-50`). Plan 100's Step 2 anchor (its "after the existing `from ai_router import feed_verify` line" instruction) must be repointed to the spec-load pattern as well, plan 100:25's claim that `service.py:39-41` imports `feed_verify` is stale (the loader is at `:36-43`), and plan 094's `(service.py:25-28)` loader reference becomes `service.py:36-43`.
5. Sanity re-read of each touched plan's drift check: run it against the current tree; it must
   exit 0 without changing anything.

**Verify**: the scans above; `git diff --check`; `python3.14 tools/check_source_limits.py` (no
source changed) — all exit 0. Hits inside plans 122 and 134 are intentional (this rule and the shim discussion); do not "fix" them.

## Done criteria

- [ ] No live plan contains `codex_router/`, `<ROUTER_ROOT>`, or `feed_token.py` outside an
      intentional shim discussion.
- [ ] Plans 094/101/102/103 cite current counts and paths.
- [ ] Every touched drift check runs cleanly on the current tree.
- [ ] Only `plans/` text changed; dated reports untouched.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- A `codex_router/` mention is part of a deliberate historical instruction (e.g. the shim's own
  removal) — leave it and note why in the completion report.
- A plan's drift check intentionally points at a path that does not exist yet (forward-looking
  step), e.g. a file the plan will create — rewrite the check to target the files that exist, and
  note it.

## Maintenance notes

- New plans must use `ai_router/` paths and runnable drift checks from day one; the executor rule
  in `plans/README.md` is the contract.
- Dated reports keep old names and numbers deliberately; do not sweep them.
