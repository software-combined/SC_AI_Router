# Plan 128: Decompose router.py into ingress and relay collaborators

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat b642de9..HEAD -- ai_router/router.py ai_router/ingress.py ai_router/relay.py tests/test_handler.py tests/test_lifecycle.py tests/test_router_response.py`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P3; effort M-L; risk MED; confidence HIGH; category tech-debt; depends on
  090, 091, 093, 096 (all edit this file; do not start before they land and are merged).
- Planned at `b642de9`, 2026-09-11.
- First proof: `router.py` is a thin HTTP handler over two collaborators, below the 400 hard cap,
  with every existing handler/lifecycle test unchanged and green.

## Why this matters

`ai_router/router.py` is exactly 400/400 — the hard cap — and mixes six concerns: authentication and
DNS-rebinding (`:106-120`), error shaping (`:95-104`, `:122-141`), GET routes (`:143-162`), POST
orchestration (`:170-269`), dead-key diagnosis (`:271-287`), body read/decompress (`:289-302`), and
the relay loop (`:304-399`), plus the module-level `_payload_has_image` (`:61-74`). Four queued plans
(090, 091, 093, 096) already contend for it. After they land, any further change pays a full read of
a cap-sized handler, and the drain/inflight accounting introduced by 090 is entangled with relay
mechanics.

## Current state (verified at b642de9)

- `router.py:21-59` `Router` (drain/inflight); `:77-162` `Handler` auth/GET; `:170-269` `do_POST`;
  `:271-302` dead-key + `read_body`; `:304-399` `relay`.
- Tests: `tests/test_handler.py` (33 tests), `tests/test_lifecycle.py` (drain/accounting),
  `tests/test_router_response.py`, `tests/test_streaming_identity.py` (tool file).

## Scope

**In scope**: `ai_router/router.py`, new `ai_router/ingress.py`, new `ai_router/relay.py`, focused
tests for any moved seam.
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
2. **Ingress collaborator (commit 2).** Move auth/rebinding (`:106-120`), `read_body` (`:289-302`),
   and the GET-route helpers into `ai_router/ingress.py`; `Handler` keeps thin wrappers so the
   public method names used by tests stay valid (`authorized_path`, `read_body`, `send_json`,
   `error`). `_payload_has_image` moves to its post-125 home (do not re-create it here).
3. **Trim + verify.** After both moves `router.py` must sit below 300 lines; run the focused and
   full suites; update the baseline entry.

**Verify**: `wc -l ai_router/router.py` < 300; focused tests green; `rg -n 'def relay' ai_router/`
shows the delegation.

## Done criteria

- [ ] `relay.py` and `ingress.py` own their concerns; `router.py` < 300 lines.
- [ ] No status/body/header/accounting change; all existing tests untouched and green.
- [ ] Full suite, compile and limit gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- A move changes the call order between auth, setup, body read and draining: stop; the ordering is
  a security and accounting contract.
- The single inflight decrement cannot be preserved cleanly: stop and report before proceeding.
- Plan 090/091/093/096 is not yet merged: do not start.

## Maintenance notes

- New ingress validation goes in `ingress.py`; new relay/failure behaviour in `relay.py`; the
  Handler stays a router.
- Reviewers: compare against the pre-split file line by line; this is a move, not a rewrite.
