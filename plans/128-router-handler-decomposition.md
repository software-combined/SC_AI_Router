# Plan 128: Decompose router.py into ingress and relay collaborators

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat b642de9..HEAD -- ai_router/router.py ai_router/ingress.py ai_router/relay.py tests/test_handler.py tests/test_lifecycle.py tests/test_router_response.py`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P3; effort M-L; risk MED; confidence HIGH; category tech-debt; depends on
  090, 091, 093, 096 (all edit this file; do not start before they land and are merged).
- Planned at `b642de9`, 2026-09-11.
- Implemented 2026-09-12 on top of `e8ede6b`; `router.py` is 388 -> 204 lines over `ingress.py`
  (121) and `relay.py` (125); no test behaviour changed (the only test edit is the packaging
  `FILES` list gaining the two new modules) and the suite is green.
- First proof: `router.py` is a thin HTTP handler over two collaborators, below the 400 hard cap,
  with every existing handler/lifecycle test unchanged and green.

## Why this matters

`ai_router/router.py` was 400/400 at planning (388 at execution) — at or near the hard cap — and
mixed six concerns: authentication and DNS-rebinding, error shaping, GET routes, POST
orchestration, dead-key diagnosis, body read/decompress, and the relay loop, plus the module-level
`_payload_has_image`. Four queued plans (090, 091, 093, 096) already contended for it. Any further
change paid a full read of a cap-sized handler, and the drain/inflight accounting introduced by 090
was entangled with relay mechanics. *Reconciled 2026-09-12: the ingress concerns live in
`ingress.py`, the relay loop in `relay.py`, and the handler is 204 lines.*

## Current state (verified at b642de9; reconciled 2026-09-12)

- `router.py` at planning: `Router` (drain/inflight), `Handler` auth/GET, `do_POST`,
  dead-key + `read_body`, `relay`. After the split: `Router` and `do_POST`/`_owned_post` stay;
  `send_json`/`error`/`authorized_path`/`context_error`/`do_get`/`read_body` live in `ingress.py`;
  the relay loop lives in `relay.py`; `Handler` keeps thin wrappers for every public name tests use.
- Tests: `tests/test_handler.py`, `tests/test_lifecycle.py` (drain/accounting),
  `tests/test_router_response.py`, `tests/test_safe_diagnostics.py` (drives `Handler.error` on an
  uninitialised instance), `tests/test_ingress_guards.py` (patches `router.MAX_BODY`),
  `tests/test_stream_containment.py` (patches `router.log_event` through the relay path).

## Scope

**In scope**: `ai_router/router.py`, new `ai_router/ingress.py`, new `ai_router/relay.py`, focused
tests for any moved seam, plus the release inventory entries a new runtime module needs
(`tests/test_packaging.py` `FILES` and the README runtime list), and the ownership map the split
makes stale (`docs/architecture.md` domain row and rule 2).
**Out of scope**: behaviour change of any kind (statuses, bodies, headers, accounting), the protocol
dispatch table, provider/transport code, `_payload_has_image`'s semantics (plan 125 owns its
primitive form).

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_handler tests.test_lifecycle tests.test_router_response tests.test_latency_metrics` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; baseline updated; router.py below 400 |

## Steps

1. **Relay collaborator (commit 1).** Move `relay` mechanics (`:304-399`, including the terminal
   mid-stream handling plan 096 adds) into `ai_router/relay.py` as a function/class taking
   `(handler, provider, prepared, metrics, started)` or an equivalent narrow interface. Keep
   `transport.post_with_phases` calls, header relay, failure description, and the single inflight
   decrement exactly once (090 owns the accounting location — preserve its single-decrement rule).
   `router.Handler.relay` becomes a two-line delegation.
   *Landed 2026-09-12: `relay.relay(handler, provider, prepared, metrics, started,
   has_image=False, *, log_event)` holds the moved loop verbatim; the `log_event` seam is
   keyword-only because `tests/test_stream_containment.py` patches `router.log_event` and the
   wrapper must pass the patched object. `NATIVE_SERVICE_PATHS` comes from its owner
   (`providers.py`).*
2. **Ingress collaborator (commit 2).** Move auth/rebinding (`:106-120`), `read_body` (`:289-302`),
   and the GET-route helpers into `ai_router/ingress.py`; `Handler` keeps thin wrappers so the
   public method names used by tests stay valid (`authorized_path`, `read_body`, `send_json`,
   `error`). `_payload_has_image` moves to its post-125 home (do not re-create it here).
   *Landed 2026-09-12: `ingress.py` owns `send_json`, `error`, `authorized_path`,
   `context_error`, `do_get` and `read_body`; `Handler` keeps the wrappers, so
   `tests/test_safe_diagnostics.py` still drives `Handler.error` on an uninitialised instance and
   `tests/test_ingress_guards.py` still bounds the read through `router.MAX_BODY` (the wrapper
   passes it, so the patch point stays live). `VERSION` is imported from `runtime.py`;
   `_payload_has_image` stays in `router.py` because `tests/test_handler.py` imports it there.*
3. **Trim + verify.** After both moves `router.py` must sit below 300 lines; run the focused and
   full suites; update the baseline entry.
   *Landed 2026-09-12: 204 lines; baseline `ai_router/router.py` 388 -> 204; `ingress.py` 121 and
   `relay.py` 125 are under the 250 soft limit, so no new baseline entries. The packaging gate
   required both new modules in `tests/test_packaging.py` `FILES` and the README runtime list.*

**Verify**: `wc -l ai_router/router.py` < 300; focused tests green; `rg -n 'def relay' ai_router/`
shows the delegation.

## Done criteria

- [x] `relay.py` and `ingress.py` own their concerns; `router.py` is 204 lines (< 300).
- [x] No status/body/header/accounting change; no test behaviour changed and the suite is green
      (1052 tests; the only test edit is the packaging `FILES` list).
- [x] Full suite, compile and limit gates pass; only in-scope files changed.
- [x] `plans/README.md` status row updated.

## STOP conditions

- A move changes the call order between auth, setup, body read and draining: stop; the ordering is
  a security and accounting contract.
- The single inflight decrement cannot be preserved cleanly: stop and report before proceeding.
- Plan 090/091/093/096 is not yet merged: do not start.

## Maintenance notes

- New ingress validation goes in `ingress.py`; new relay/failure behaviour in `relay.py`; the
  Handler stays a router.
- Reviewers: compare against the pre-split file line by line; this is a move, not a rewrite.
