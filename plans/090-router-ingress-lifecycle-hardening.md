# Plan 090: Harden the router ingress lifecycle (timeouts, drain accounting, single listener)

> Implemented 2026-09-11; drift reconciled against the a985197 base in the same
> change. Two post-plan additions reshaped the code: PR #59 routes preparation
> through `ai_router/subscription_fallback.py` (its `refused()` held a second
> slot, deleted by Step 2 because the owned slot now covers the hand-off), and
> `do_POST` gained the `_owned_post` split used for the slot wrapper.
> Current anchors: `Handler.timeout` at `ai_router/router.py:78`, slot
> acquire/release at `:189-195`, `settimeout` at `:198`, relay without slot
> accounting at `:306-400`.

## Status and first proof

- Priority P1; effort S-M; risk MED; confidence HIGH; category perf/correctness; depends on none.
- Planned at `a985197`, 2026-09-10.
- First proof: a stalled client connection is dropped after the socket timeout; a request
  already reading its body survives a concurrent `/shutdown` drain; a second router
  process on the same loopback port fails to bind instead of silently sharing it.

## Why this matters

Three ingress-lifecycle defects share one file and one test surface:

1. `Handler` has no socket timeout, so a connection that never finishes its request line
   blocks a thread forever. `self.connection.settimeout(120)` runs only
   inside `do_POST` after routing, `/shutdown`, setup and `do_GET` branches.
   `ThreadingHTTPServer` has no connection cap, so threads and fds leak across a long desktop session.
2. Drain accounting counts only the relay window. `inflight` increments
   before `relay` and around the compaction branch; a request accepted by `do_POST` but still in `read_body` or `prepare` is invisible,
   so `drain_and_exit` can see `inflight == 0` and `os._exit(0)` mid-upload.
3. `self.allow_reuse_port = True` sets `SO_REUSEPORT` on the
   fallback bind, so a second router can bind the same port and the kernel splits
   connections between two processes with divergent health, state and logs.

## Current state (verified at a985197)

- `class Router(ThreadingHTTPServer)` — `daemon_threads = True; drain_deadline_s = 120`; no `timeout`.
- `class Handler(BaseHTTPRequestHandler)` — `protocol_version = 'HTTP/1.1'`; no timeout.
- `do_POST` — draining check, `/shutdown`, setup/unsupported routing, then `self.connection.settimeout(120)`, then `read_body()`.
- `drain_and_exit` calls `os._exit(0)` once `inflight == 0` or the deadline passes.
- `inflight += 1` immediately before `self.relay(...)`; `relay`'s `finally` decrements.
- Fallback bind sets `self.allow_reuse_port = True` before `super().__init__`.
- Repo conventions: tests are stdlib `unittest`, offline; `tests/test_lifecycle.py` sets `server.inflight` by hand and mocks `os._exit`-class behavior through the drain; `tests/test_handler.py` shows the raw-`HTTPConnection` pattern for protocol-level tests. Match those.

## Scope

**In scope**: `ai_router/router.py`, `ai_router/subscription_fallback.py`, `tests/test_lifecycle.py`, `tests/test_handler.py`.
**Out of scope**: provider/transport code, setup route behavior, the `fileno` launchd socket path
(first branch of `Router.__init__`), `drain_deadline_s`, any connection-cap feature, the 120 s upstream timeout in `relay`.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -m unittest tests.test_lifecycle tests.test_handler` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0 (router.py is baseline-pinned at 400; any count change requires a baseline update) |

## Steps

### Step 1: pre-request socket timeout (commit 1)

Add `timeout = 120` to `Handler` (next to `protocol_version`). Keep `self.connection.settimeout(120)`
in `_owned_post` unchanged (redundant but harmless; removing it is a follow-up decision, not this plan).
Add a handler test that builds the test server with a small class-level timeout (e.g. set
`Handler.timeout = 1` inside the test, restore in cleanup), opens a raw socket, sends a partial
request line, and asserts the connection is closed within ~2 s without a response.

**Verify**: focused tests pass; the new test fails when the timeout attribute is removed.

### Step 2: whole-request drain accounting (commit 2)

Move slot acquisition to just after the owned-path check and release
it exactly once in a `finally` that wraps everything from `self.connection.settimeout(120)` through
`self.relay(...)`. Concretely:

- Acquire under `self.server.lock` immediately before delegating to `_owned_post`.
- Wrap the remainder in `try: ... finally: with self.server.lock: self.server.inflight -= 1`.
- Delete the compaction-branch pair.
- In `relay`'s `finally`, delete only the `inflight` decrement; keep `conn.close()`
  and `self.close_connection = True`.
- Delete the second slot acquire in `subscription_fallback.refused()`: the owned slot
  now covers the twin hand-off (PR #59 drift; otherwise every helper fallback leaks +1).
  `/shutdown` and non-owned routes stay outside the slot: the drain thread must not
  wait on the very request that started it.

Extend `tests/test_lifecycle.py`: with a mocked `os._exit`, start a request whose body is not fully
sent (declare `Content-Length` larger than the bytes sent, then send the rest after a short delay),
trigger drain, and assert the process-exit path waits for that request to complete. Keep the
existing hand-set-`inflight` tests working; add a negative case asserting no double decrement
(inflight never goes negative across an error path).

**Verify**: focused tests pass; temporarily reverting the accounting makes the new test fail.

### Step 3: single-listener enforcement (commit 3)

Delete `self.allow_reuse_port = True`. `allow_reuse_address` (SO_REUSEADDR) stays on,
so normal restarts still rebind over TIME_WAIT. Add a test that constructs one `Router` and then a
second on the same port, asserting the second raises `OSError`.

**Verify**: focused tests pass; manual: `python3.14 -m ai_router` twice → second start fails with
`Address already in use`.

## Done criteria

- [ ] Handler timeout test exists and fails without the attribute.
- [ ] Drain test covers a request in `read_body`/`prepare`; no path double-decrements `inflight`.
- [ ] Second bind to the same port raises; no `allow_reuse_port` remains (`rg allow_reuse_port ai_router/` → no matches).
- [ ] Full suite, compile and source-limit gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- Any existing test or launchd/manual flow depends on two listeners or on `SO_REUSEPORT`
  (e.g. `tests/test_lifecycle.py` restart convergence): stop and report.
- The drain restructure changes error-path responses (status/body) for any existing handler test:
  stop and report — accounting must not alter responses.
- Step 3 shows production restart regression in the `fileno` path: stop; the fallback bind may
  need its own documented rationale instead of removal.

## Maintenance notes

- If a connection cap is ever added, put it in `process_request`, not in the handler.
- The slot now spans prepare, so drain waits for slow prepares too; `drain_deadline_s` still bounds it.
- Reviewers: confirm exactly-once decrement on every early `return` in the wrapped region.
