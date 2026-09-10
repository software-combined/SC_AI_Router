# Plan 076: Harden the router ingress lifecycle (timeouts, drain accounting, single listener)

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat a985197..HEAD -- ai_router/router.py tests/test_lifecycle.py tests/test_handler.py`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P1; effort S-M; risk MED; confidence HIGH; category perf/correctness; depends on none.
- Planned at `a985197`, 2026-09-10.
- First proof: a stalled client connection is dropped after the socket timeout; a request
  already reading its body survives a concurrent `/shutdown` drain; a second router
  process on the same loopback port fails to bind instead of silently sharing it.

## Why this matters

Three ingress-lifecycle defects share one file and one test surface:

1. `Handler` has no socket timeout, so a connection that never finishes its request line
   blocks a thread forever. `self.connection.settimeout(120)` runs only at
   `ai_router/router.py:188`, deep inside `do_POST` after routing, `/shutdown`, setup and
   `do_GET` branches. `ThreadingHTTPServer` has no connection cap, so threads and fds leak
   across a long desktop session.
2. Drain accounting counts only the relay window. `inflight` increments at
   `ai_router/router.py:267-269` (relay) and `:209-219` (compaction); a request accepted at
   `:176` but still in `read_body` (`:190`) or `prepare` (`:221`) is invisible, so
   `drain_and_exit` (`:50-59`) can see `inflight == 0` and `os._exit(0)` mid-upload.
3. `self.allow_reuse_port = True` (`ai_router/router.py:34-36`) sets `SO_REUSEPORT` on the
   fallback bind, so a second router can bind the same port and the kernel splits
   connections between two processes with divergent health, state and logs.

## Current state (verified at a985197)

- `ai_router/router.py:21-23` — `class Router(ThreadingHTTPServer): daemon_threads = True; drain_deadline_s = 120`; no `timeout`.
- `ai_router/router.py:77-78` — `class Handler(BaseHTTPRequestHandler): protocol_version = 'HTTP/1.1'`; no timeout.
- `ai_router/router.py:176-190` — draining check, `/shutdown`, setup/unsupported routing, then `self.connection.settimeout(120)`, then `read_body()`.
- `ai_router/router.py:50-59` — `drain_and_exit` calls `os._exit(0)` once `inflight == 0` or the deadline passes.
- `ai_router/router.py:267-269` — `inflight += 1` immediately before `self.relay(...)`; `relay`'s `finally` (`:396-399`) decrements.
- `ai_router/router.py:34-36` — fallback bind sets `self.allow_reuse_port = True` before `super().__init__`.
- Repo conventions: tests are stdlib `unittest`, offline; `tests/test_lifecycle.py:173-187` sets `server.inflight` by hand and mocks `os._exit`-class behavior through the drain; `tests/test_handler.py:123-142` shows the raw-`HTTPConnection` pattern for protocol-level tests. Match those.

## Scope

**In scope**: `ai_router/router.py`, `tests/test_lifecycle.py`, `tests/test_handler.py`.
**Out of scope**: provider/transport code, setup route behavior, the `fileno` launchd socket path
(`router.py:25-42` first branch), `drain_deadline_s`, any connection-cap feature, the 120 s
upstream timeout in `relay` (`:305`).

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
at `:188` unchanged (redundant but harmless; removing it is a follow-up decision, not this plan).
Add a handler test that builds the test server with a small class-level timeout (e.g. set
`Handler.timeout = 1` inside the test, restore in cleanup), opens a raw socket, sends a partial
request line, and asserts the connection is closed within ~2 s without a response.

**Verify**: focused tests pass; the new test fails when the timeout attribute is removed.

### Step 2: whole-request drain accounting (commit 2)

Move slot acquisition to just after the owned-path check (`ai_router/router.py:184-187`) and release
it exactly once in a `finally` that wraps everything from `self.connection.settimeout(120)` through
`self.relay(...)`. Concretely:

- Acquire under `self.server.lock` immediately before `settimeout`.
- Wrap the remainder in `try: ... finally: with self.server.lock: self.server.inflight -= 1`.
- Delete the compaction-branch pair at `:209-219`.
- In `relay`'s `finally` (`:396-399`), delete only the `inflight` decrement; keep `conn.close()`
  and `self.close_connection = True`.
- `/shutdown` (`:178-183`) and non-owned routes stay outside the slot: the drain thread must not
  wait on the very request that started it.

Extend `tests/test_lifecycle.py`: with a mocked `os._exit`, start a request whose body is not fully
sent (declare `Content-Length` larger than the bytes sent, then send the rest after a short delay),
trigger drain, and assert the process-exit path waits for that request to complete. Keep the
existing hand-set-`inflight` tests working; add a negative case asserting no double decrement
(inflight never goes negative across an error path).

**Verify**: focused tests pass; temporarily reverting the accounting makes the new test fail.

### Step 3: single-listener enforcement (commit 3)

Delete `self.allow_reuse_port = True` at `:35`. `allow_reuse_address` (SO_REUSEADDR) stays on,
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
