# Plan 131: Decompose service/state ownership and finish the atomic-writer family

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat b642de9..HEAD -- packaging/service.py packaging/feed.py packaging/updater.py packaging/install.py packaging/diagnostics.py packaging/atomic_write.py packaging/claude_config.py packaging/claude_desktop_config.py ai_router/state.py ai_router/atomic_write.py ai_router/winacl.py ai_router/credentials.py ai_router/runtime.py ai_router/setup.py ai_router/catalogue.py ai_router/discovered.py ai_router/model_refresh.py tests/`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P2; effort L; risk MED; confidence HIGH; category tech-debt; depends on 094, 095, 100,
  103, 123; coordinate with 106 (feed) and 099 (cache writers).
- Planned at `b642de9`, 2026-09-11.
- First proof: each state file has one reader contract and one writer contract; `service.py` owns
  service/lock/health only; `--preflight` shares the installer's service instance.

## Why this matters

After plan 103 moves the launchd half out, `packaging/service.py` still mixes four owners:
update-failure state (`:469-506`, consumed only by `updater.py`), feed serial and fetch
(`:87-118`, `:288-306`, `:638-671`, overlapping `feed.py` with a different retry policy), and health
(`:262-285`). Separately, the persistence story is incomplete:

- `packaging/feed.py:46-60` rewrites `feed-token` and `feed-token.previous` with `O_TRUNC`;
  `ai_router/discovered.py:37` and `ai_router/catalogue.py:305` write with truncate/`write_text`;
  `ai_router/model_refresh.py:89,138` write cache/etag. Plans 094/095 route only
  `service._write_state`/`ensure_state` and `codex_config`/receipts; 094 explicitly excludes
  `claude_config.write_settings`/`claude_desktop_config.write_json`, which remain a second
  deterministic-tmp recipe.
- State reads are duplicated at ~10 sites with three strictness levels: full validation in
  `ai_router/runtime.py:36-69`, partial in `packaging/service.py:475-481,609-620`, unchecked
  `json.loads` in `install.py`, `updater.py:127`, `diagnostics.py:129`,
  `platforms/windows.py:398-399`, `catalogue.py:230`, `setup.py:276-282`, probes.
- `packaging/diagnostics.py:24-28` loads a private `service` module object; `install._sync_seams`
  binds only some helpers, so patched feed helpers never reach `--preflight`.
- Key privacy is defined twice: `diagnostics.py:50-66` re-implements `credentials.py:33-41`.

## Scope

**In scope**: the files in the drift check, including `ai_router/setup.py` (key-claim write only, after 127); focused tests; `config/source-limits-baseline.json`.
**Out of scope**: installer orchestration (130), platform backends (132), bootstrap scripts, any
behaviour/format change to state documents, the receipt writer (095 owns it), retired slugs (100).

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Installer/platform | `python3.14 -B -m unittest tests.test_install tests.test_install_lifecycle tests.test_install_state tests.test_update_channel tests.test_feed_serial tests.test_feed_migration tests.test_safe_diagnostics tests.test_setup tests.test_catalogue tests.test_discovered tests.test_model_refresh` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; baselines updated |

## Steps

1. **One writer contract.** Promote the atomic-write helper to a shared, 3.9-safe leaf
   (`ai_router/atomic_write.py`, or keep `packaging/atomic_write.py` as a thin re-export if 094's
   tests pin it) with `replace_text` and `replace_json(path, doc, stale_tmp='refuse'|'reuse')`.
   Route: the two Claude writers (preserving their stale-tmp refusal), `feed.py`'s token pair
   (two files, explicit order — keep the current/previous recovery semantics), `catalogue.py:305`,
   `discovered.py:37`, `model_refresh.py:89,138`. Every sink keeps its current permissions, JSON
   shape and failure tolerance (e.g. `discovered` swallows `OSError` and `model_refresh` degrades —
   a literal route that turns a degraded cache write into a request failure is a defect). Also
   route `ai_router/setup.py`'s key-claim write (`:84-88`, the `O_TRUNC` open) through the helper;
   it lands after the setup split in 127. Any packaging-side import of a runtime leaf must work in
   the installed launcher context (spec loading or an explicit release-root `sys.path` insert); add
   a test that spec-loads the module from a home-style layout.
2. **One read contract.** Add a 3.9-safe `ai_router/state.py` with `read(path) -> dict|None`,
   `required_keys`, and `migrate(doc)`; `runtime.py` keeps its credential/policy checks but reads
   through it; route `service._read_failures`/`ensure_state`, `install.py` loads, `updater.py`,
   `diagnostics.py`, `platforms/windows.py`, `catalogue.py`, `setup.py`. Preserve each site's
   current tolerance (fail-closed at startup, tolerant elsewhere) explicitly.
3. **Service decomposition.** Move feed serial/fetch helpers into `feed.py` (service re-exports so
   patched names still resolve); move update-failure state into `updater.py` (or a small
   `update_state.py`). Verify whether `service.fetch`'s missing previous-token retry is deliberate
   before merging it with `feed.live_feed`; if deliberate, keep two documented paths.
4. **Diagnostics + key privacy.** Bind the service module in `install._sync_seams` (as
   `updater.bind(svc=...)` does) and drop diagnostics' private load once 123 lands; add
   `owner_only(path)` to `ai_router/winacl.py` and use it from `credentials.py` and
   `diagnostics._key_private`.
5. **Baseline + inventory**: update counts and the release inventory for any new module.

**Verify**: focused suite after each step; full suite at the end; `rg -n 'O_TRUNC' packaging/ ai_router/` shows only the writer leaf; `rg -n '_key_private' ai_router packaging` shows one owner.

## Done criteria

- [ ] One writer leaf and one state-read contract; all listed sinks routed.
- [ ] `service.py` owns service/lock/health + re-exports only; feed and update state moved.
- [ ] `--preflight` uses the installer's service instance; key privacy has one owner.
- [ ] Full suite, compile and limit gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- A state document's tolerance differs per site in a way that is load-bearing (startup fail-closed
  vs updater tolerant): stop and encode the difference explicitly rather than unifying silently.
- The two-file feed-token update cannot be expressed by the helper without changing recovery
  semantics: keep it separate, document why, and proceed.
- 094/095/100/103/123 are not merged: do not start.

## Maintenance notes

- New state files use `state.read`/`atomic_write.replace_json`; no ad-hoc `open(..., 'w')`.
- `feed.py` is the feed-channel owner; service keeps a thin alias layer for installer patches only.
- Reviewers: check permissions (0600), temp naming, and that no reader became stricter or looser.
