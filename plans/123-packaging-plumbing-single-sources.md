# Plan 123: One 3.9 loader, one release inventory, one subscription roster

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat b642de9..HEAD -- packaging/install.py packaging/service.py packaging/release.py packaging/diagnostics.py packaging/updater.py packaging/feed.py packaging/platforms/ tests/test_packaging.py ai_router/subscription_roster.py ai_router/catalogue.py`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P2; effort M; risk MED; confidence HIGH; category tech-debt; depends on none.
- Run BEFORE plan 094 (its Step 2 would otherwise add a 20th loader copy) and before/with plan 100
  (same shared-leaf pattern).
- Planned at `b642de9`, 2026-09-11.
- First proof: one `spec_from_file_location` pattern loads packaging modules; the release bundle
  and 3.9 surface lists derive from one inventory; the eight subscription rows exist once.

## Why this matters

Three mechanical duplications make every packaging change more expensive than it should be:

1. **Loader copies.** `spec_from_file_location` blocks: `install.py` 7, `diagnostics.py` 3,
   `service.py` 2, and one each in `updater.py`, `update_launch.py`, `router_launch.py`,
   `release.py`, `platforms/windows.py`, `platforms/linux.py`, `platforms/__init__.py`, `feed.py`
   (~19 total). Module-name strings drift (`router_feed_verify`, `router_winacl`, …), and
   `install.py` — pinned at the 700 hard cap — pays the most lines for it.
2. **Release inventory in three places.** `packaging/release.py` builds the bundle, while
   `tests/test_packaging.py` hand-lists the expected bundle and the 3.9 surface files. Every new
   module needs all three (plans 094 and 100 both warn about it), and a missed entry either fails
   the release test or ships an incomplete bundle.
3. **Subscription roster duplicated.** `packaging/service.py:54` `DEFAULT_OPENAI_MODELS` (8 slugs)
   and `ai_router/catalogue.py` `SUBSCRIPTION_REASONING` (`:80`) / `SUBSCRIPTION_DISPLAY_NAMES`
   (`:91`) carry the same eight slugs; `tests/test_install_state.py:28-40` checks only the service
   copy. Plan 100 deliberately defers this ("fold when the roster next changes").

## Current state (verified at b642de9)

- `rg -c spec_from_file_location packaging/*.py packaging/platforms/*.py` → install.py 7,
  diagnostics.py 3, service.py 2, others 1 each.
- `packaging/release.py:20-45` bundle construction; `tests/test_packaging.py:9-48` explicit expected
  bundle; `:123-135` explicit 3.9 surface list.
- `packaging/service.py:54` roster list; `ai_router/catalogue.py:80-100` reasoning/display tables
  keyed by slug strings.
- Plan 100 creates `ai_router/retired_slugs.py` as the 3.9-safe leaf precedent.
  Packaging loads such leaves with `spec_from_file_location` (`packaging/service.py:36-43`) or an
  explicit `sys.path.insert` (`packaging/install.py:22`), never a bare package import from a module
  the installed launchers spec-load.

## Scope

**In scope**: `packaging/service.py` (add `load()`), migrate the loader copies that run after
service is available; `packaging/release.py` + `tests/test_packaging.py` (single inventory);
new `ai_router/subscription_roster.py`, `packaging/service.py` roster spec-load,
`ai_router/catalogue.py` tables, `tests/test_install_state.py`, `tests/test_catalogue.py`
(coupling assertion); `config/source-limits-baseline.json` counts.
**Out of scope**: `platforms/__init__.py`'s bootstrap loader (it must work before service exists),
the two standalone launch scripts' own loading, `packaging/feed.py` internals, behavior changes of
any kind, the retired-slug leaf (plan 100).

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_packaging tests.test_install_state tests.test_catalogue tests.test_install_lifecycle` | pass |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; baseline updated where counts changed |
| 3.9 surface | the installer-surface parse test | pass |

## Steps

1. **Add `load(name, filename)` to `packaging/service.py`** (3.9 syntax): the existing
   `spec_from_file_location` + `module_from_spec` + `exec_module` sequence, returning the module.
   Then migrate the loader blocks that execute after `service` is importable — at minimum
   `install.py` (7), `diagnostics.py` (3), `updater.py`, and any module loaded through service.
   Keep `platforms/__init__.py`'s helper for the pre-service bootstrap and the two launch scripts
   self-contained (they run without service). Record every deliberate exception in the commit
   message; the bootstrap loader that makes `service.load()` reachable stays in install.py, so
   expect exactly one remaining `spec_from_file_location` there. Update plan 094's Step 2 wording to use this helper (a one-line note in that file is
   allowed in this plan's scope).
2. **Single release inventory.** In `packaging/release.py`, expose the bundle as a module-level
   function/constant (e.g. `bundle_files()`), and have `tests/test_packaging.py` derive its
   expected-bundle and deploy assertions from it (loading release.py the way the test already loads
   packaging modules). Keep the 3.9 parse surface as an explicit list (packaging modules plus the
   3.9-executed `tools/` and runtime leaves) and add new modules to it as they appear: deriving it
   from the bundle would parse 3.14-only runtime modules and fail the gate. Keep the explicit
   `ai_router` import-closure assertion the installer needs — the test must still fail if a
   required file disappears.
3. **Roster leaf.** Create `ai_router/subscription_roster.py` (3.9-safe, plain tuple of the eight
   slugs, no annotations that break 3.9). Load it in `packaging/service.py` the way service already
   loads `launchd.py`/`feed.py` (`spec_from_file_location`, `service.py:36-43`; a module-level
   package import would break the installed launchers, which spec-load service before any
   `sys.path` insert) and import it normally in `ai_router/catalogue.py` to key the reasoning/display tables (keep the tables' content
   identical). Add a coupling test asserting the roster, the service list, and the catalogue tables
   cover the same slugs. Add the new module to the release bundle and the explicit 3.9 surface list.
   Add a test that spec-loads `service.py` from a home-style layout and asserts the roster is
   reachable.
4. **Baseline**: run the size checker and update `config/source-limits-baseline.json` for every
   file whose count changed (install.py should shrink; service.py may grow slightly).

**Verify**: focused tests pass; `rg -c spec_from_file_location packaging/install.py` → 1 (the service bootstrap); the
surface parse test passes; full suite green.

## Done criteria

- [ ] One loader function in `service.py`; install.py loader blocks gone; exceptions documented.
- [ ] `tests/test_packaging.py` derives its bundle/deploy lists from the release inventory; the 3.9 parse surface stays an explicit list.
- [ ] One roster leaf; all three copies removed; coupling test exists.
- [ ] Full suite, compile, limits and surface gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- A loader cannot move without changing import timing (module loaded before service): stop for that
  file only, keep it local, and record the exception.
- Deriving the test lists from release.py would make the test unable to detect a missing required
  file: keep an explicit required-files assertion and proceed.
- The roster leaf cannot be imported by packaging under the 3.9 surface gate: stop and report.

## Maintenance notes

- New packaging modules: add to the release inventory; extend the explicit 3.9 surface list only when the installer surface test must parse them.
- New subscription rows: edit the roster leaf and the display/reasoning tables together; the
  coupling test enforces it.
- Reviewers: confirm no module-load timing changed and the surface list still parses under 3.9.
