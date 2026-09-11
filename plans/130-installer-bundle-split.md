# Plan 130: Give the installer real headroom with a packaging/bundle.py split

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat b642de9..HEAD -- packaging/install.py packaging/bundle.py tests/test_install.py tests/test_install_lifecycle.py tests/test_packaging.py config/source-limits-baseline.json`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P2; effort M-L; risk MED; confidence HIGH; category tech-debt; depends on 102 (its
  option-collapse lands first) and 123 (single loader/inventory).
- Planned at `b642de9`, 2026-09-11.
- Implemented 2026-09-12 on top of `72a848b`: `packaging/install.py` 697 -> 587 lines and the new
  `packaging/bundle.py` (225 lines) owns bundle verify/install/prune plus rollback activation;
  both sit under their caps with real headroom.
- First proof: `install.py` is comfortably below the 700 hard cap with unchanged installer
  behaviour, and bundle verify/install/prune live in one 3.9-safe module.

## Why this matters

`packaging/install.py` was 700/700 at planning (697 at execution) — the hard cap — so every
installer change needed a compensating deletion. The untapped cluster was bundle handling:
`verify_sha256`, `newer`, `check_manifest`, `check_identity`, `self_test`, `ensure_credentials`,
`install_bundle`, `write_catalogue`, plus release pruning and rollback activation. These
interleaved with client attachment inside `do_install`, so the installer's riskiest logic was also
its least separable. *Reconciled 2026-09-12: the cluster lives in `packaging/bundle.py`, loaded via
`service.load`; `install.py` keeps thin module-level seams for the names tests patch.*

## Current state (verified at b642de9; reconciled 2026-09-12)

- `packaging/install.py` at planning held the bundle helpers, `do_install` and
  `prune_releases`/`_release_key` in 700 lines (697 at execution; baseline-pinned). After the split:
  587 lines, with `packaging/bundle.py` (225) owning the moved logic.
- Tests patch the `_SEAMS` names (`run`, `health`, `wait_version`, `self_test`, `write_catalogue`,
  `fetch_feed`, `feed_serial`) on `install_mod` and mirror onto `install_mod._svc`;
  `install._sync_seams` forwards `run`, `safe_extract`, `install_launcher` and `swap_current` into
  `_bundle.bind_seams(...)`, while `self_test`, `write_catalogue` and `provider_keys` travel as
  explicit wrapper arguments.
- Plan 123 provides `service.load()` and the single release inventory; `bundle.py` is in
  `packaging/release.py` `PACKAGING_FILES`, in `tests/test_packaging.py` `REQUIRED_PACKAGING`, and
  in the 3.9 installer-surface grammar list.

## Scope

**In scope**: new `packaging/bundle.py`, `packaging/install.py`, `packaging/release.py` (inventory
entry only), `tests/test_packaging.py` (inventory and 3.9-surface lists), `config/source-limits-baseline.json`.
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
   *Landed 2026-09-12: `bundle.py` owns the named helpers plus `provider_keys`, `_clear_current`,
   `prune_releases` and rollback activation (`do_rollback`). Seams are explicit parameters with
   `bind_seams(...)` globals as fallback; `install.py` re-exports the non-seam names as aliases and
   keeps wrappers where a seam must be passed (`self_test`, `write_catalogue`, `install_bundle`,
   `ensure_credentials`, `do_rollback`).*
2. **Rewire `install.py`**: keep thin module-level aliases for the names tests patch
   (`self_test`, `write_catalogue`, `fetch_feed`, `feed_serial`, `verify_sha256`, `newer`) that
   delegate to `bundle`, so existing patch points keep working; `do_install` calls the bundle
   functions. If a patch target must move, update the test deliberately and list every change in the
   commit message.
   *Landed 2026-09-12: every `_SEAMS` name still resolves on `install_mod` and call sites read the
   patched values; no test assertion changed (only the packaging `FILES`/surface lists gained
   `packaging/bundle.py`).*
3. **Inventory + gates**: add `bundle.py` via plan 123's single inventory; run the size checker and
   lower the `install.py` baseline entry; keep `install.py` under the 700 cap with real headroom
   (target < 600 where achievable without churn).
   *Landed 2026-09-12: `packaging/release.py` `PACKAGING_FILES` and the `REQUIRED_PACKAGING`/3.9
   surface lists in `tests/test_packaging.py` list `bundle.py`; baseline `packaging/install.py`
   697 -> 587 (bundle.py 225 stays under the 400 soft limit, so no entry).*

**Verify**: installer suites and full suite green; `wc -l packaging/install.py`;
`python3.14 -m packaging.install --help`-equivalent smoke (or the repo's installer smoke test).

## Done criteria

- [x] Bundle fetch/verify/install/prune/self-test logic lives in `bundle.py` (plus rollback
      activation); installer behaviour unchanged (1052-test suite green).
- [x] Test patch points still resolve (no test assertion changed).
- [x] `install.py` below 600 lines (587); baseline updated; inventory and surface lists updated.
- [x] Full suite, compile and limit gates pass; only in-scope files changed.
- [x] `plans/README.md` status row updated.

## STOP conditions

- A seam cannot be preserved without keeping most of the logic in `install.py`: stop and report;
  do not ship a split that only moves lines.
- Any installer test fails for a behavioural reason: stop; this plan is a move.

## Maintenance notes

- New installer features that only fetch/verify/unpack bundles belong in `bundle.py`.
- `install.py` remains the orchestration entry point (platform dispatch, clients, rollback).
- Reviewers: compare moved functions and the patch/seam wiring; behavior must be identical.
