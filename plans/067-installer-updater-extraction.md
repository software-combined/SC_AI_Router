# Plan 067: Extract scheduled-update orchestration before installer growth

> Planning only. Source baseline `96db57f`, 2026-09-09. This names the updater
> split previously referenced by Plan 056 without its own executable plan.
> Reuse an already integrated equivalent; do not create a second updater.

Priority P1; effort S/M; risk MEDIUM. No feature change. Execute before 056
changes the installer. Coordinate the single writer with any current updater
or token-budget work; inspect worktrees and current source first.

## First proof

The existing `--check-update` CLI and stable `update_launch.py` still perform
the same update, deferral, parking and rollback behavior from an extracted
release bundle. `packaging/install.py` falls below 600 lines (baseline 699)
without increasing its hard limit. The new helper stays below 400 lines.

## Canonical source and current behavior

Repository: `/Users/cyrilallart/Documents/Github/SC_Codex_openRouter_adapter`.
Runtime Python 3.14+, stdlib only; installer bootstrap retains its current
older-Python compatibility. Use an owned worktree targeting `develop`.

Read `packaging/install.py:514-620`, `service.py`, `update_launch.py`,
`release.py`, `tests/test_install.py`, `tests/test_install_lifecycle.py`,
`tests/test_launchd.py`, `tests/test_update_launcher.py` if present, and
`tests/test_release.py`. Discover actual test names before choosing commands.

Current `do_check_update` starts with `_sync_seams()`, resolves an explicit or
channel feed, sleeps bounded jitter, reads/saves ETag, retries transport errors,
checks serial, skips old/parked versions, verifies and extracts a candidate,
then launches its installer with a 900-second timeout. Only explicit
`args.feed` is passed to the child; a channel-resolved URL must not become a
persistent pin. `_park` counts failures and stops repeated attempts, including
GitHub's no-ETag path. Success is recorded only after the current pointer matches
the requested version. A deferred install is not failure or successful update.

The stable updater launcher resolves the active release's `install.py` and
invokes `--check-update`; retain that external contract. This plan does not
change scheduled jobs, idle/drain, feed origins, release triggers or serials.

## Scope

Only `packaging/install.py`, new `packaging/updater.py`, necessary explicit
bundle-list entries, adjacent updater/lifecycle/bundle tests, source-limit
metadata if mechanically required, and plan status. A behavior-neutral move
does not need a product version bump unless required by the effective release
rules; any actual user-visible behavior change does and belongs separately.

Use the installer's file-based import pattern, avoiding `import packaging.x`.
Keep one small wrapper at the existing `do_check_update` entrypoint so callers
and injected `_fetch`, `_read_feed`, `_sleep` seams remain valid. Pass explicit
dependencies or a narrow existing helper module; do not import the entrypoint
back into the helper, copy its globals wholesale, or create a service framework.

## Steps and checks

1. Reconcile current worktree ownership and run
   `git diff --stat 96db57f..HEAD -- packaging tests`. If an equivalent split
   has landed, verify it and close this plan without moving code again.
2. Characterize any uncovered meaningful branch before moving it: ETag 304,
   no-ETag parked version, transport retry versus HTTP failure, explicit feed
   one-shot behavior, child timeout/nonzero exit, busy deferral and success
   only after activation. Reuse existing tests; do not duplicate them for counts.
   Gate: focused tests pass and a deliberately broken branch fails its test.
3. Move the update function and only its owned helpers into `updater.py`.
   Preserve execution order and return/exception behavior. Keep shared failure
   state helpers where both normal installation and update need them. Stage a
   coherent source/test/bundle slice under the commit limit.
   Gate: existing updater/installer tests pass without weakened assertions;
   no circular import; installer is below 600 lines.
4. Add `updater.py` to `release.bundle_files` and existing bundle assertions.
   Extract a real bundle; run its installer `--help` without checkout imports,
   then exercise its update path against synthetic feeds and fake services.
   Gate: the extracted copy imports its own helper; omitting that helper makes
   the smoke fail. Preserve determinism and all required resources.
5. Run required tests/checks and current pre-commit review. Integrate into
   `develop`, verify the integrated tree, then let 056 rebase and proceed.
   Deployment or live updater execution is not needed to qualify this source
   extraction; production acceptance belongs to 050/054/058.

```sh
python3.14 -m unittest tests.test_install tests.test_install_lifecycle tests.test_release tests.test_packaging
python3.14 -m unittest discover -s tests -t .
python3.14 -m compileall -q codex_router tools tests packaging
python3.14 tools/check_source_limits.py
git diff --check
```

## STOP conditions

Stop on another writer owning these paths, changed updater contracts, a failed
existing test, a missing extracted helper, or any need to alter update/rollback
semantics to make the move pass. Do not raise source limits, bypass review,
rewrite `service.py`, or activate the live updater. After safe integration,
clean the owned worktree or reuse it for the authorised next stage.
