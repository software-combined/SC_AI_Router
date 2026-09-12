# Plan 137: Validate the Host header on loopback ingress

> **Executor instructions**: Follow this plan step by step. If any "STOP
> conditions" item occurs, stop and report. When done, update this plan's status
> row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 08aff1e..HEAD -- ai_router/router.py tests/test_ingress_guards.py config/source-limits-baseline.json`
> Compare the "Current state" excerpts before proceeding.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none; plan 090 landed at `02e8e6e` and left the headroom this
  plan needs (`ai_router/router.py` is 395 lines)
- **Category**: security
- **Planned at**: commit `08aff1e`, 2026-09-11

First proof: a request whose `Host` is not `127.0.0.1` or `localhost` is
rejected with 403 before any routing, while the normal client paths
(`127.0.0.1:<port>`, `localhost:<port>`, a bare `127.0.0.1`, and a Host-less
HTTP/1.0 request) keep working.

## Why this matters

DNS rebinding is the standard way a web page reaches a loopback service. Today
the only browser-facing gate is the `Origin` check, and GETs that browsers send
without an `Origin` header (image loads, top-level navigation) skip it. The
path token still returns 403, and the rebinding response is not readable
cross-origin, so this is defence in depth rather than a live break - but the
check is two lines at the single ingress choke point and it keeps any future
GET surface from inheriting the gap. See
`plans/2026-09-11-router-external-security-audit.md`, finding 4.

## Current state

- `ai_router/router.py:99-113` - `authorized_path()`; its first check rejects
  any non-setup request carrying an `Origin` header, and no code anywhere in
  `ai_router/` inspects `Host` (`rg -n "Host" ai_router/` shows only unrelated
  transport constants).
- Headroom: `ai_router/router.py` is 395 lines (baseline value 395); the three
  added guard lines stay under the 400 hard cap, so sync the baseline entry to
  the new count when you make the edit.
- `ai_router/setup.py:54-55` - `same_origin(origin, port)` treats a missing
  Origin as same-origin; that stays as-is (the token and nonce still gate
  setup).
- `ai_router/transport.py:10` - `host` is in `HOP_HEADERS`, so the upstream
  `Host` is always regenerated; nothing in the relay depends on the inbound
  value.
- Verified at planning: no caller in `ai_router/`, `packaging/`, `tools/`,
  `tests/` or `docs/` uses `localhost` or `[::1]` in a loopback URL; every
  generated URL is `http://127.0.0.1:<port>/...`.
- Conventions: ingress guard tests live in `tests/test_ingress_guards.py`
  (Plan 092, 89 lines; helpers `_auth_file`, `_start_server`, `_test_state`
  are imported there).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Headroom check | `wc -l ai_router/router.py` | 395 before the edit |
| Focused tests | `python3.14 -m unittest tests.test_ingress_guards -v` | all pass |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Source limits | `python3.14 tools/check_source_limits.py` | exit 0 |

## Scope

**In scope**: `ai_router/router.py`, `tests/test_ingress_guards.py`,
`config/source-limits-baseline.json` (router.py baseline sync only).
**Out of scope**: the `Origin`/setup logic, `same_origin`, provider or
transport code, IPv6 support, and any port-matching rule for Host.

## Git workflow

- One writable worktree per session, branch based on `develop`, integrated back
  to `develop`.
- Commit subject: `fix: validate the Host header on loopback ingress`.
- Run the shared `pre-commit-review` skill before committing.

## STOP recorded 2026-09-11

Step 1's headroom check failed: `ai_router/router.py` is 398 lines after Plans 096 and 136
landed, so the three-line guard would land at 401, over the 400 hard cap. Per this plan's
first STOP condition the work is handed to Plan 128's router split; re-execute this plan
after 128 lands.

## Steps

### Step 1: confirm headroom

Run `wc -l ai_router/router.py`. The guard adds three lines. If the result is
above 397, STOP and report: this plan must wait for plan 128's split instead of
shipping an over-cap file, and the baseline entry must be synced either way.

### Step 2: add the guard

At the top of `authorized_path()` (currently `ai_router/router.py:100`), before
the Origin check, insert:

```python
        name = (self.headers.get('Host') or '').split(':', 1)[0].strip().lower()
        if name and name not in ('127.0.0.1', 'localhost'):
            return None, False
```

Notes for the implementer:
- A missing `Host` stays allowed (HTTP/1.0 clients), and `localhost` is kept
  for manual convenience. This check is defence in depth only: a raw client
  that omits `Host` skips it, but browser-driven rebinding always sends a
  `Host`, and the path token still returns 403 for any request that would
  otherwise get through. Do not describe the guard as the primary control.
- The port is intentionally not compared: the socket is loopback-only, so
  `127.0.0.1:<anything>` cannot reach another host.
- Do not add an IPv6 literal branch; the bind is IPv4-only and nothing in the
  repo uses one (see Current state).

**Verify**: `python3.14 -m unittest tests.test_ingress_guards -v` -> all
existing tests pass; `wc -l ai_router/router.py` -> 400 or fewer; sync the
`ai_router/router.py` value in `config/source-limits-baseline.json` to the new
count and rerun `python3.14 tools/check_source_limits.py` -> exit 0.

### Step 3: pin the behaviour with tests

Extend `IngressGuardTests` in `tests/test_ingress_guards.py`:

- Host `evil.example` with a valid path token on `GET /test-token/health` ->
  403 (use `headers={'Host': 'evil.example'}` on the `http.client` request).
- Host `localhost:<port>` with the valid token -> 200.
- Host `127.0.0.1` (no port) with the valid token -> 200.
- A raw HTTP/1.0 `GET /test-token/health` with no Host header -> 200 (use the
  raw-socket pattern added by plan 136 if it has landed; otherwise open a
  socket and read the status line).

Keep `tests/test_ingress_guards.py` under the 300 soft cap; it starts at 89
lines, so the four cases fit without a baseline change.

**Verify**: focused tests pass, including the four new cases; temporarily
removing the Step 2 guard makes the rebinding case fail - restore it.

### Step 4: full gates

Run the full suite, compile and limits commands from the table. Then confirm the
caller audit still holds:

`rg -n "http://(localhost|\[::1\])" ai_router packaging tools tests docs`

**Verify**: no hits; all gates exit 0.

## Test plan

- New: rebinding Host rejected; localhost and short-form loopback Hosts
  accepted; Host-less HTTP/1.0 request accepted.
- Existing: full `LoopbackBoundaryTests` set pins token, Origin and missing-token
  behaviour.
- Structural pattern: `tests/test_ingress_guards.py:1-30`.

## Done criteria

- [x] Rebound `Host` values get 403 before routing.
- [x] `127.0.0.1`, `localhost` and Host-less requests behave as before.
- [x] `ai_router/router.py` is at or below 400 lines; limits gate exits 0.
- [x] Full suite and compile gate exit 0; router.py baseline synced.
- [x] `plans/README.md` status row updated.

## Landed notes, 2026-09-12

- The guard landed where plan 128 left the choke point: the first check in
  `ai_router/ingress.py::authorized_path`, so both GET and POST pass it before
  any routing and before the Origin exemption. It keys on the Host name only:
  a missing Host stays allowed (HTTP/1.0), `localhost` is kept for manual
  convenience, every other name is refused, and no IPv6 branch was added.
- `ai_router/router.py` is untouched, so its baseline entry needs no sync
  (the Step 1 STOP was resolved by plan 128's split; the guard is in the
  142-line `ingress.py`, under the runtime soft cap, and the tests file stays
  under 300 lines).
- `tests/test_ingress_guards.py` pins the four plan cases plus a suffix
  attack (`127.0.0.1.evil.example`) and case-insensitive `LOCALHOST`; removing
  the guard fails four of them.
- Rejected in review: a duplicate or malformed `Host` authority
  (`Host: 127.0.0.1` plus `Host: evil.example`, `Host: :1234`,
  `Host: 127.0.0.1:8080:junk`) still passes, because the guard reads the
  first value and the plan deliberately compares the name only. That is
  pre-existing acceptance rather than a regression, and a raw client that can
  craft a second `Host` can already omit `Host` altogether, which the plan
  keeps allowed. The path token remains the primary control; tightening the
  authority belongs to plan 146 if the owner wants it.
- The ordering claim is now pinned: a foreign Host carrying a loopback
  `Origin` is refused before the Origin exemption.

## STOP conditions

- `router.py` has less than three lines of headroom before the edit: STOP; hand this
  plan to 128's split instead.
- Any real caller or test uses a different Host form (for example an IPv6
  literal): STOP and report rather than widening the allowlist.
- Any existing subscription or health test fails after the guard: STOP and
  report the exact failing case.

## Maintenance notes

- When plan 128 moves `authorized_path` into `ai_router/ingress.py`, keep this
  guard first in the moved function.
- New ingress surfaces must route through `authorized_path` so this check
  applies; do not add per-route Host logic.
