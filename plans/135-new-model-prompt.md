# Plan 135: New-model prompt — offer a one-click Codex restart only when new models appear

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat 4584a1e..HEAD -- ai_router/model_prompt.py ai_router/router.py ai_router/setup.py packaging/updater.py tests/ docs/operations.md`
> Read changed code and preserve current behavior before edits.

> **Amendment 2026-09-12.** The Step 0 spike has run; its result is recorded in
> `plans/2026-09-12-external-router-review.md`: Codex reads `model_catalog_json`
> once at startup and does **not** pick up a rewritten catalogue, verified
> against `codex-cli 0.153.4`. The prompt and restart work stands, with two
> changes:
> 1. Stage 2 (steps 1-7 below) is sequenced **after plan 145**. Its visibility
>    function must treat a `listed: false` row as absent, so an unverified model
>    never triggers a restart prompt.
> 2. The trigger stays model-set based and remains silent for a version bump.
> Do not repeat the spike.

## Status and first proof

- Priority P2; effort M; risk MED; confidence MED-HIGH; category direction/dx; depends on 128
  (router.py is at the 400 hard cap), 127 (setup pages) and 131 (state/writer rules); hooks into 099
  (refresh wiring); coordinates 106 (updater/feed).
- Planned at `4584a1e`, 2026-09-11.
- First proof: the prompt appears only when the current policy scope gains model rows; it lists
  exactly those new models (nothing outside the allowlist); Later silences it until the next
  addition; no click ever restarts Codex implicitly.

## Why this matters

A router update or a model-data refresh can add models, but if Codex only reads its catalogue at
startup (`model_catalog_json`, `packaging/codex_config.py:21`), the new rows do not show until the
user restarts Codex — today with no signal at all.

The signal should be about the *model set*, not the version:

- If an update adds no visible model, stay silent (no popup for a version bump).
- If models appear for this scope, list them and offer **Restart Codex** / **Later**.
- The list must be resolved per user/group scope, at view time, because visibility is policy-driven.
  Today the scope is the portco/department allowlist (`ai_router/model_policy.py:21-65`); per-user
  and per-group policies will extend the same resolution, so nothing here may hard-code the scope
  or a global list.

## Current state (verified at b642de9/4584a1e)

- Visibility is policy-driven but **the on-disk catalogue is not filtered**: the installer merges
  without `--allowed` (`packaging/install.py:232-237`; `catalogue.py:293-305` takes `allowed` only
  from argv), the runtime loads the policy once into `state['allowed_models']` at startup
  (`ai_router/runtime.py:64-68`) and gates routing from it (`providers.select`,
  `claude.select`), and `claude.models_listing()` (`claude.py:66-78`) is policy-blind. Any
  projection this plan shows must therefore intersect `model_policy.load(home)`'s `allowed`
  itself — never read the on-disk catalogue as if it were filtered.
- `model_policy.load(home)` returns `(portco, department, allowed)` and fails closed: absent file
  → `(None, None, None)` = unfiltered; unreadable/invalid/wrong-permissions → `(None, None, ())` =
  empty OpenRouter set (`model_policy.py:34-56`).
- The updater runs the installer for each new version (`packaging/updater.py:131-154`) and ends
  with the version check, failure clear, `update.log` append and `installed <version>`
  (`:155-166`). It is Python 3.9 (`updater.py:1-4`) and must never import the 3.14 runtime
  (`docs/architecture.md:47-49`); the sanctioned cross-boundary pattern is a subprocess with the
  router interpreter (`install.py:234`).
- The setup key window is the trust/UI pattern to reuse: `setup_pending` nonce (`setup.py:29`),
  `open_key_window` with an injectable opener (`:257-290`), `serve` GET/POST (`:352`),
  `_atomic_replace` (`:302`). `router.py` exempts `/setup/` from the Origin rejection and routes
  it; its 2026-09-12 count is 204 lines against the 400 hard cap
  (`config/source-limits-baseline.json`), so plan 128's headroom is already in hand and the
  route edit is not cap-blocked.
- No notification or client-restart code exists (`rg 'osascript|notify-send' ai_router packaging`
  → none).

## Scope

**In scope**: new `ai_router/model_prompt.py`, new `tests/test_model_prompt.py`,
`ai_router/router.py` (one exempted prefix + two route lines, only after 128), `packaging/updater.py`
(call the pending check after install), tests, `docs/operations.md`.
**Out of scope**: automatic restarts, CLI/headless restart, Windows toast infrastructure, changing
update cadence or feed handling, the Claude-side prompt (same mechanism can add `client='claude'`
later; it must compose `claude_alias` with `allowed`), per-user policy itself (identity family),
`packaging/install.py` beyond forwarding the `_announce` test seam through its existing
`do_check_update` wrapper (700 cap; the pass-through moved the file from 628 to 629 lines and the
source-limit baseline with it).

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_model_prompt tests.test_setup tests.test_update_channel tests.test_catalogue tests.test_handler` | pass after implementation (`tests/test_model_prompt.py` is new in commit 1) |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; baselines updated if counts change |

## Steps

0. **Client-behaviour spike first (no source).** Verify whether Codex re-reads the catalogue
   without a restart (plan 099 Step 3 assumes it sees new models on the next `/models` request).
   Use the installed client read-only: change nothing; observe catalogue reads. If confirmed that no
   restart is needed, STOP and report — the prompt then reduces to (at most) a notification, and
   this plan must be re-scoped by the owner before any page/restart work.
1. **One effective-visibility function (commit 1).** In `ai_router/model_prompt.py`,
   `visible_models(home, client='codex') -> list[(slug, display_name)]`:
   resolve `allowed` via `model_policy.load(home)` and apply it explicitly — for Codex, the same
   projection routing uses (`catalogue.merge(base, roster, client='codex', allowed=allowed)` or its
   pure equivalent); for the deferred Claude variant, `claude_alias` rows intersected with
   `allowed` (never the policy-blind `models_listing` output as-is). Fail closed: an invalid policy
   yields the empty OpenRouter set exactly like routing.
2. **Snapshot in its own file (commit 2).** Store `model-prompt.json` in the router home —
   **not** in `mixed-router-state.json` (that document already has unsynchronized writers and a
   single-use setup nonce that a second read-modify-write could resurrect). Contents:
   `{'scope': '<portco>/<department|->', 'client': 'codex', 'seen': [slugs]}`. Rules:
   - an **absent** policy (`None`) is a valid unfiltered scope (`scope='none'`) and seeds and
     acknowledges normally; a **rejected/invalid** policy (`()`) yields empty `pending` and mutates
     nothing;
   - first run (no snapshot) seeds `seen = visible_models(home)` silently — never announces the
     catalogue;
   - `pending(home) = visible_models(home) - seen`, first-occurrence order;
   - acknowledge sets `seen = seen ∪ pending` (the displayed set), never the live visible set;
   - a scope change re-seeds silently for the new scope;
   - the snapshot (`model-prompt.json`) is written through the shared atomic writer (131) or
     `setup._atomic_replace` until 131 lands; an unreadable/invalid snapshot is treated as absent
     (silent re-seed), never as permanently rejected;
   - the seen list never includes models outside the resolved allowlist.
3. **Page + route (commit 3).** `model_prompt.py` serves a GET page listing the pending models
   (cap the visible list, e.g. 12 names plus "and N more") with **Restart Codex** and **Later**,
   and a POST action for a single-use nonce (mint on first pending notification, TTL ~48 h). Exempt
   its prefix from the Origin rejection like `/setup/` and route GET/POST beside the setup routes.
   Both actions acknowledge; `restart` additionally runs the platform restart. Expired/missing
   nonce or no pending models renders the plain "nothing to do" page — never a restart. Router.py
   is at the 400 hard cap: land this only after 128, or keep the edit net-zero.
4. **Trigger points (commit 4), best-effort and never runtime-importing in packaging.** The
   updater is 3.9 and must not import `ai_router`; query the running router's pending endpoint over
   loopback (stdlib `urllib`, path token from state, never logged) or via a router-interpreter
   subprocess, with a bounded wait for the new version on `/health`.
   - `packaging/updater.py`: only **after** `:166` (version check, failure clear and update log
     already done); wrap in `except Exception` (not `OSError`) so a notification/browser/subprocess
     failure cannot skip the log or change the exit code.
   - `ai_router/model_refresh.apply` (when 099 wires it): call the check inside a guarded wrapper;
     it must never escape `apply` or kill the refresh daemon thread.
   - Policy changes alone do not prompt in this version: the running router caches its allowlist at
     startup and the client catalogue is not rebuilt, so a policy-only trigger would announce
     models the router still rejects. Revisit with the per-user policy owner.
5. **Notification (commit 4).** One command per platform: macOS
   `osascript -e 'display notification "New models: <names>< +N more>. Restart Codex to use them." with title "Router update"'`;
   Linux `notify-send` when present; Windows log only. Names come from `pending()`; cap ~3 in the
   notification, full list on the page. No URLs, tokens or credentials in the text. Failures are
   ignored at the boundary.
6. **Platform restart action (commit 5).** Injected runner (fake in tests): macOS
   `osascript -e 'quit app "Codex"'` then `open -a Codex` (verify the app name; unsupported if
   ambiguous); Windows only if a deterministic command exists; Linux unsupported. Never kill by
   process pattern; never run without the POST click.
7. **Tests + docs (same commits).** New `tests/test_model_prompt.py` (commit 1) plus additions to
   existing modules as needed: pending diff with additions only (removals and version-only updates
   silent); allowlist filtering (a model outside the policy never shows); rejected-policy read
   mutates nothing; scope change re-seeds silently; first-run seeding; acknowledge = union;
   nonce mint/consume/expiry; routes via the existing patterns (`tests/test_setup.py`,
   `tests/test_handler.py`); restart commands via the fake runner; updater trigger is best-effort
   and runs after the update log. One paragraph in `docs/operations.md`.

**Verify**: focused tests; `rg -n 'osascript|notify-send' ai_router/ packaging/` shows only the
planned call sites; full suite green.

## Done criteria

- [ ] Step 0 spike recorded; if no restart is needed, the plan is re-scoped by the owner.
- [ ] Prompt appears only when `visible_models(home)` gains rows; otherwise silent.
- [ ] The page lists exactly the added rows for the current scope; nothing outside the allowlist;
      snapshot seeds/acknowledges only from a successfully resolved policy.
- [ ] Scope resolution is dynamic per call (`model_policy.load`), never cached globally; a future
      per-user/group scope only changes the key, not the logic.
- [ ] Later/Restart acknowledge; restart runs only on the nonce-authenticated POST click.
- [ ] Updater/refresh triggers are best-effort (`except Exception`), never import runtime code from
      3.9 packaging, and never alter their primary result or log.
- [ ] Full suite, compile and limit gates pass; `install.py` gains only the `_announce` pass-through
      (700 cap); router edits land only after 128.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- The spike shows Codex re-reads the catalogue without a restart: stop and report before building
  the page or the restart action.
- The effective visible set cannot be resolved without duplicating routing logic: stop and extract
  the single resolver first (with plan 125/121's allowlist work) rather than growing a second
  filter.
- Per-user/per-group policy lands mid-implementation and changes the scope contract: stop and
  re-scope the snapshot key with that owner.
- Codex cannot be identified/quit cleanly on a platform: degrade to notification + manual
  instructions there; never broaden to pattern kills.
- Any pressure to prompt for removals, for version-only updates, on policy changes alone, or to
  restart automatically: stop; owner decision.

## Maintenance notes

- Removals are silent by design; a "models retired" notice is a separate ask.
- The snapshot is per scope+client; when per-user policy lands, move it to the per-user state store
  rather than widening a global key.
- 099's refresh wiring must call `model_prompt.pending` after `apply()` inside the guarded wrapper;
  note it in the 099 row at integration.
- Reviewers: confirm no token/nonce/URL reaches logs or notifications, that a rejected policy
  mutates nothing, and that every prompt step failing leaves update and refresh outcomes unchanged.

## Landed notes, 2026-09-12

- Steps 1-2 landed as `0844c5d` (effective visibility) and `f4bfef4` (snapshot,
  pending, acknowledge). The snapshot is `model-prompt.json` with
  `{'scope', 'client', 'seen'}`; a present-but-unresolvable policy is rejected
  through the `scope == 'none' and allowed == ()` sentinel, so a valid policy
  that allows no models still seeds its own scope and a later grant announces.
- Steps 3 and 6 land together: a page whose Restart button did nothing would be
  a defect, so the route, the note and the macOS restart action ship in one
  commit. The HTML, the HTTP handler and the restart action live in
  `ai_router/model_prompt_page.py`, so `ai_router/model_prompt.py` stays the
  visibility/snapshot owner (canonical setup keeps its handler in `setup.py`
  and only the HTML in `setup_page.py`; this page keeps its three related
  pieces together).
- The single-use link is `notice: {'nonce', 'expires'}` inside the same
  snapshot document, TTL 48 h, reused while live and dropped by the
  acknowledge write a click performs. `check_notice` is read-only, so a GET
  never consumes the link, and a POST with nothing pending neither restarts
  nor consumes it.
- The page carries the displayed slugs in hidden `m` fields and passes them to
  `acknowledge`, so a row that appears between render and click is not marked
  seen unseen.
- Restart is macOS only: `osascript` quits the app by bundle id
  (`com.openai.codex`, the identity `packaging/notice.py` already uses for
  its update dialog) and `open -b` relaunches it, behind an injected runner;
  other platforms report that a manual restart is needed. Nothing runs
  without the nonce-authenticated POST click. A quit that errors reports
  failure rather than letting `open` activate the still-running app.
- Deviation from step 3's wording: an unknown or expired nonce renders a
  404 "Link expired" page rather than the 200 nothing-to-do page; it carries
  no actions and never restarts, matching the setup route's 404 contract.
- Steps 4-5 land with the updater trigger. The bare `/<token>/model-prompt`
  path is the loopback check the 3.9 updater calls: it mints or reuses the
  notice and answers JSON `{'pending': [{'slug', 'name'}], 'url'}`. The URL
  carries the token and nonce, so the updater opens it and never prints it.
  A browser Origin is refused on that path (only the nonce page is
  origin-exempt).
- `packaging/updater.py` calls `_announce_new_models(state)` after the
  update log and ETag write, behind one `except Exception`, so no desktop
  or loopback failure can change the update result or exit code. macOS
  notifies through `osascript` and opens the page through `open`; Linux uses
  `notify-send`/`xdg-open` only when present; Windows logs the offer. Names
  cap at three plus "+N more". `do_check_update(..., _announce=...)` is the
  test seam.
- `packaging/notice.py` keeps owning the version-level "restart the client"
  dialog, including its Windows and Linux paths; this prompt is the
  model-set-level offer, so it adds a banner plus the browser page instead of
  a second dialog. Windows therefore logs the offer (no banner backend) and
  the page is macOS/Linux only.
- Step 4's refresh half is deferred with plan 099: `model_refresh.start()`
  still has no caller, so the guarded `apply()` hook lands with that wiring,
  and the 099 row now names it.
- Review-round guards: the announce returns early unless the state says
  Codex is attached (`clients`/`client`, so a Claude-only or service-only
  install is never told to restart Codex) and unless `ROUTER_NO_NOTICE` is
  unset; the loopback fetch bypasses proxy handling so the path token never
  travels to `http_proxy`, caps the reply before parsing, and only opens a
  page URL whose suffix is nonce-shaped, so a traversal or foreign host is
  ignored. The first landing after this feature ships only seeds the
  snapshot; that delay is recorded in the CHANGELOG and the operations page.
- Noted for 099: call the prompt check only when the refresh actually
  changed the catalogue (a repeat call re-offers the same unacknowledged
  models), and remember the mint is a read-modify-write that needs the same
  single-caller discipline as the updater.
- Installer follow-up (adversarial round 2): `state['clients']` is written
  only when `--clients` is passed, so it can go stale against `client`
  (`--clients both` then `--client none` leaves `clients: 'both'`; a
  `--clients claude` install re-run with no flags keeps `clients: 'claude'`
  after re-attaching Codex). The gate reads the recorded value, so the first
  sequence can still offer a restart on a service-only install and the
  second suppresses a real Codex install; `packaging/notice.py`'s dialog
  reads the same record. Fixing the recording belongs with the installer,
  not this plan.
