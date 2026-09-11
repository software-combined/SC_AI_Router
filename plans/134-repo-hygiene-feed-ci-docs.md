# Plan 134: Repository hygiene: feed_verify placement, CI single owner, docs index and shim owner

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat b642de9..HEAD -- ai_router/feed_verify.py packaging/feed_verify.py packaging/feed.py packaging/release.py tests/test_feed_verify.py tests/test_install.py tests/test_packaging.py .github/ docs/ README.md codex_router/`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P3; effort M; risk MED; confidence HIGH; category tech-debt/docs; depends on 101 (CI edit order) and 122; coordinates 106 (land the feed_verify move before its feed work, or rebase onto it).
- Planned at `b642de9`, 2026-09-11.
- First proof: the feed verifier lives with its only consumers; CI pins and policy scans have one
  owner; docs are discoverable; the compatibility shim has a named owner and removal condition.

## Why this matters

Three unrelated pieces of repository hygiene, each with a concrete cost:

1. **`ai_router/feed_verify.py` is packaging/build tooling in the runtime tree.** No `ai_router`
   module imports it; its consumers are `packaging/feed.py:14-18` (cross-tree file load) and
   `packaging/release.py:15`. It ships in the runtime bundle only because the release glob covers
   `ai_router/**/*.py`, and it is pinned separately in `tests/test_packaging.py`. The runtime tree
   carries a module no runtime code uses; packaging loads across the tree boundary.
2. **CI has no single owner for pins and policy checks.** The same two pinned actions repeat in
   `.github/workflows/check.yml:27-28`, `release.yml:22-23`, `refresh.yml:24-25` with no composite
   action; the request-cap and secrets greps are inline shell (`check.yml:44,48`), cannot be run
   locally, and the secrets include list omits `*.yml`, `*.sh`, `*.ps1`.
3. **Docs and shim ownership.** `docs/kiro-compatibility.md:13-14` points reopeners at "Plan 065
   step 3" — Plan 065 was completed and removed (`plans/README.md` removal log), so the pointer is
   unrecoverable except via git. `docs/PROVENANCE.md` and `docs/architecture.md` have zero inbound
   links from `README.md`'s Links section. `codex_router/__init__.py:1-4` says "Removal needs its
   own plan" and no live plan owns it. `packaging/release.py:26` bundles every `tools/*.py` by glob,
   so a repo-only helper silently ships; no architecture/AGENTS rule says where `tools/` vs
   `packaging/` scripts belong.

## Scope

**In scope**: the files in the drift check; `.github/workflows/` and a new `.github/actions/`
composite; new `tools/check_policy_scans.py`; `docs/` text; `AGENTS.md` or `docs/architecture.md`
for the tools/ rule.
**Out of scope**: changing the check/release job split (deliberate), the paid probe workflow,
removing `codex_router/` (needs the external-consumer search and owner decision), test suites.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_feed_verify tests.test_packaging tests.test_release` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; baseline if counts change |
| Surface | 3.9 parse test | pass; updated lists |

## Steps

1. **Move the verifier (commit 1).** `git mv ai_router/feed_verify.py packaging/feed_verify.py`;
   update `packaging/feed.py` and `packaging/release.py` to load it as a sibling; update the release
   inventory, the 3.9 surface list, the deploy list and `tests/test_packaging.py` pins; update the
   imports in `tests/test_feed_verify.py:10` and `tests/test_install.py:18` (used at `:413`/`:416`)
   to the new location. Keep the
   file's contents unchanged. Coordinate with 106: land before its feed work or rebase onto it.
2. **CI single owner (commit 2).** Add `.github/actions/setup/action.yml` owning only setup-python (pinned once). `actions/checkout`
   must remain the first step of each workflow: a same-repo local action cannot run before checkout.
   Use the composite after checkout in all three workflows; add `tools/check_policy_scans.py` implementing
   the request-cap and secret greps with an include list covering `*.py,*.md,*.json,*.toml,*.yml,*.sh,*.ps1`,
   and call it from `check.yml` (after 101 adds the ruff step). Keep the existing pinned-action
   conventions.
3. **Docs and shim ownership (commit 3).** Add a short docs index (extend README Links or add
   `docs/README.md`) covering operations, architecture, adding-a-model, compatibility, PROVENANCE,
   kiro; fix the kiro reopen pointer to state the condition instead of a removed plan number;
   add a deprecation note + named owner/removal condition for `codex_router/` (in the shim docstring
   and `plans/README.md`), and a one-line rule in `docs/architecture.md` (or `AGENTS.md §2a`)
   defining what belongs in `tools/` vs `packaging/` given the bundle glob.

**Verify**: focused tests; `rg -n 'feed_verify' ai_router/` → no matches; workflow YAML parses
(the composite action is valid); docs links resolve.

## Done criteria

- [ ] Verifier moved with all lists updated; no ai_router reference remains.
- [ ] One composite setup action; policy scans runnable locally and from CI with widened coverage.
- [ ] Docs index in place; kiro pointer resolvable; shim owner recorded; tools/ rule documented.
- [ ] Full suite, compile, limit and surface gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- Moving the verifier breaks release closure or the 3.9 parse gate: stop; revert the move and report.
- Workflow changes cannot be validated without network/CI: keep them minimal, validate YAML locally,
  and record the CI-side verification as pending in the completion report.
- The shim has live external consumers you can identify: do not remove it; the deprecation note is
  the deliverable.

## Maintenance notes

- New packaging-only support modules live under `packaging/`; runtime leaves only if runtime code
  imports them.
- CI pins change in one place; policy scans change in one script.
- Reviewers: confirm no behavior change in release closure and that docs edits are factual.
