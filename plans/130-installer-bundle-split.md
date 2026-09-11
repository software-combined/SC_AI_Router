# Plan 130: Give the installer real headroom with a packaging/bundle.py split

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat b642de9..HEAD -- packaging/install.py packaging/bundle.py tests/test_install.py tests/test_install_lifecycle.py tests/test_packaging.py config/source-limits-baseline.json`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P2; effort M-L; risk MED; confidence HIGH; category tech-debt; depends on 102 (its
  option-collapse lands first) and 123 (single loader/inventory).
- Planned at `b642de9`, 2026-09-11.
- First proof: `install.py` is comfortably below the 700 hard cap with unchanged installer
  behaviour, and bundle fetch/verify/install/prune live in one 3.9-safe module.

## Why this matters

`packaging/install.py` is 700/700 — the hard cap — so every installer change currently needs a
compensating deletion. Plan 102 only collapses the option-resolution and rollback blocks (roughly
20-30 lines of headroom; its own maintenance note concedes the real split is still needed). The
untapped cluster is bundle handling: `verify_sha256`, `newer`, `check_manifest`, `check_identity`,
`self_test`, `ensure_credentials`, `install_bundle`, `write_catalogue` (`:130-237`), plus release
pruning (`:542-557`). These interleave with client attachment inside a 217-line `do_install`, so the
installer's riskiest logic is also its least separable.

## Current state (verified at b642de9)

- `packaging/install.py:130-237` bundle helpers; `:313-528` `do_install`; `:542-557`
  `prune_releases`/`_release_key`; exactly 700 lines (baseline pin at
  `config/source-limits-baseline.json`).
- Tests patch `self_test`, `write_catalogue`, `fetch_feed`, `feed_serial` on `install_mod`
  (`tests/test_install.py:96-97`); `_sync_seams` mirrors `run/health/wait_version/ensure_serving`
  (`install.py:302-311`); `_patch_attrs` in tests mirrors onto `install_mod._svc`.
- Plan 102 will have landed the option collapse; plan 123 provides `service.load()` and the single
  release inventory this module must use.

## Scope

**In scope**: new `packaging/bundle.py`, `packaging/install.py`, `packaging/release.py` (inventory
entry only), `tests/test_install*.py` (seam updates only), `config/source-limits-baseline.json`.
**Out of scope**: behaviour changes, `do_install`'s attachment tail beyond moving helpers, platform
backends, `service.py` (plan 131), client config modules.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Installer suites | `python3.14 -B -m unittest tests.test_install tests.test_install_lifecycle tests.test_install_config tests.test_interpreter_resolution tests.test_platform_dispatch_order tests.test_update_channel tests.test_packaging` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; install.py baseline lowered |
| 3.9 surface | installer-surface parse test | pass; bundle.py listed |

## Steps

1. **Create `packaging/bundle.py`** (3.9 syntax, loaded via `service.load` per plan 123) owning:
   `verify_sha256`, `newer` (version comparison), `check_manifest`, `check_identity`, `self_test`,
   `ensure_credentials`, `install_bundle`, `write_catalogue`, `prune_releases`, `_release_key`.
   Pass in everything the tests patch: `run`, `self_test`, `write_catalogue`, `fetch`/`fetch_feed`,
   `verify_sha256`, `backend`, `newer`, plus `home`/`version` values. Prefer explicit parameters or
   a small frozen context over module globals so `_patch_attrs` targets remain meaningful.
2. **Rewire `install.py`**: keep thin module-level aliases for the names tests patch
   (`self_test`, `write_catalogue`, `fetch_feed`, `feed_serial`, `verify_sha256`, `newer`) that
   delegate to `bundle`, so existing patch points keep working; `do_install` calls the bundle
   functions. If a patch target must move, update the test deliberately and list every change in the
   commit message.
3. **Inventory + gates**: add `bundle.py` via plan 123's single inventory; run the size checker and
   lower the `install.py` baseline entry; keep `install.py` under the 700 cap with real headroom
   (target < 600 where achievable without churn).

**Verify**: installer suites and full suite green; `wc -l packaging/install.py`;
`python3.14 -m packaging.install --help`-equivalent smoke (or the repo's installer smoke test).

## Done criteria

- [ ] Bundle fetch/verify/install/prune/self-test logic lives in `bundle.py`; installer behaviour
      unchanged.
- [ ] Test patch points still resolve (or are updated deliberately and listed).
- [ ] `install.py` below 600 lines; baseline updated; inventory and surface lists updated.
- [ ] Full suite, compile and limit gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- A seam cannot be preserved without keeping most of the logic in `install.py`: stop and report;
  do not ship a split that only moves lines.
- Any installer test fails for a behavioural reason: stop; this plan is a move.

## Maintenance notes

- New installer features that only fetch/verify/unpack bundles belong in `bundle.py`.
- `install.py` remains the orchestration entry point (platform dispatch, clients, rollback).
- Reviewers: compare moved functions and the patch/seam wiring; behavior must be identical.
