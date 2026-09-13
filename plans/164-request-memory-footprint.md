# Plan 164: Release request buffers before the relay and name the upstream timeout

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report; do not improvise.
> When done, update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat c068368..HEAD -- ai_router/router.py ai_router/relay.py ai_router/transport.py ai_router/providers.py ai_router/subscription_fallback.py tests/test_handler.py tests/test_latency_metrics.py tests/test_subscription_fallback.py config/source-limits-baseline.json`
> If any in-scope file changed, compare the "Current state" excerpts against
> the live code before proceeding; on a mismatch, STOP. Land 162 and 163
> first: all three edit `ai_router/relay.py` or `ai_router/router.py`.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 162 (relay), 163 (router lock section)
- **Category**: perf
- **Planned at**: commit `c068368` (`origin/develop`), 2026-09-13
- **Source**: `plans/2026-09-13-router-four-lane-audit.md`, finding F4

## Why this matters

`Handler._owned_post` reads the body, parses it, prepares the upstream
request and then calls `self.relay(...)` from inside its own frame. The raw
bytes (`raw`), the parsed graph (`payload`) and the serialised wire copy
(`prepared.body`) therefore all stay reachable for the whole streaming relay,
which lasts seconds to minutes. The scalability lane measured, in memory on
this Mac, about three times the body size resident per in-flight turn: a
15 MiB body peaked near 47 MiB and held about 32 MiB for the stream. With
Codex spawning parallel sub-agents, eight turns at the 16 MiB ceiling are
roughly 375 MiB of data that is dead the moment `prepare()` returns. Two of
the three copies can be released with a frame change and no behaviour change
on ordinary turns; the third (`prepared.body`) is still read after the
response arrives by the refusal cache and the rejection fingerprint, so it
stays. The frame change frees nothing on subscription helper turns:
`subscription_fallback.Plan` pins the parsed payload and the raw body for the
twin redispatch (`ai_router/subscription_fallback.py:59-64`, attached at
`:103-104`), so those turns keep both copies for the whole relay and the
resident figure will not fall there. Separately, the 120-second timeout is a
bare literal in six places: four upstream-side literals that become
`UPSTREAM_TIMEOUT_S` and two client-socket literals that become
`CLIENT_TIMEOUT_S` in Step 2, and the metrics field `timeout_s` must match
the real connection timeout for the latency telemetry to be honest.

## Current state (verified at c068368)

- `ai_router/router.py:136-212` (`_owned_post`): `raw, payload, size = self.read_body()` at `:140`; `has_image = _payload_has_image(payload)` at `:143`; `prepared = subscription_fallback.prepare(provider, model, path, payload, raw, dict(self.headers), self.server)` at `:167-168`; the method ends with `self.relay(provider, prepared, metrics, started, has_image)` at `:212`, so `raw` and `payload` are live locals during the relay.
- `ai_router/router.py:130-134` (`do_POST`): `return self._owned_post(path, via_path, started)` inside the `try/finally` that releases the in-flight slot.
- `ai_router/providers.py:157-160`: `ExternalResponsesProvider.prepare` returns `Prepared(..., json.dumps(payload).encode(), tool_names, self.name)`; `ai_router/transport.py:27-28`: `Prepared.__slots__` holds `body`.
- `ai_router/relay.py:20-29`: `upstream.recall_refusal(prepared.provider, ..., prepared.body)` before the request; `:80-87`: `upstream.remember_refusal(..., prepared.body, ...)` and `upstream.rejection_fingerprint(prepared.body)` after a 4xx. `prepared.body` must therefore survive the request.
- `ai_router/subscription_fallback.py:56-72`: `Plan` keeps its own `payload` and `raw_body` references for the twin redispatch; it does not read `prepared.body`.
- Timeout literals: `ai_router/relay.py:30` (`HTTPSConnection(prepared.host, timeout=120)`), `:74` and `:143` (`'timeout_s': 120`), `ai_router/providers.py:228` (summariser connection), `ai_router/router.py:71` (`timeout = 120`, the client socket) and `:138` (`self.connection.settimeout(120)`).
- `_payload_has_image` (`ai_router/router.py:60-66`) walks the whole parsed input on every POST; its only consumer is the Grok timeout hint in `ai_router/upstream.py:241-243`. Measured cost is under one millisecond on a 4 MiB body, and plan 163 contains its recursion hazard, so this plan keeps the walk and records that decision.
- Tests that touch this path: `tests/test_handler.py` (imports `Handler` by name at `:20`, not the module), `tests/test_latency_metrics.py` (asserts the per-phase fields), `tests/test_subscription_fallback.py` (calls `handler.relay` from inside `refused`). The `timeout_s` value is asserted in `tests/test_upstream_failures.py:14-17` (the message must name 120); `tests/test_safe_diagnostics.py:48` and `tests/test_tool_alias_repair.py:303` pass the field into `describe_failure`. The latency suite does not read it.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_handler tests.test_latency_metrics tests.test_upstream_failures tests.test_subscription_fallback tests.test_stream_containment tests.test_ingress_guards tests.test_mixed_router` | all pass |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Lint | `python3.14 -m ruff check --select F401,F811 ai_router packaging tools tests` | pass |
| Limits | `python3.14 tools/check_source_limits.py` | `failures=0` |
| Policy scans | `python3.14 tools/check_policy_scans.py` | pass |

## Scope

**In scope**: `ai_router/router.py`, `ai_router/relay.py` (timeout constant
only), `ai_router/transport.py` (one constant), `ai_router/providers.py`
(one literal), `tests/test_handler.py` (one structural test),
`config/source-limits-baseline.json`, `CHANGELOG.md`, `packaging/VERSION`,
`pyproject.toml` (version).

**Out of scope**: clearing `prepared.body` (read after the response);
`ai_router/subscription_fallback.py`; the image walk itself; any change to
metrics field names (`tests/test_latency_metrics.py` pins them); connection
pooling or any change to the upstream connection lifecycle.

## Git workflow

- Worktree based on `develop`, after 162 and 163 are integrated; branch like
  `<you>/164-request-footprint-20260913`.
- Suggested commits: `refactor: relay after the request frame has released its buffers`
  and `refactor: name the upstream timeout once`. Run `pre-commit-review`.
  No push or PR unless instructed.

## Steps

### Step 1: Prepare in one frame, relay in another

Change `_owned_post` to return what the relay needs instead of calling it.
The error branches already `return self.error(...)`, whose value is `None`;
make the success path return a tuple and have `do_POST` relay when it gets
one:

```python
    def do_POST(self):
        ...
        try:
            ready = self._owned_post(path, via_path, started)
            if ready is not None:
                self.relay(*ready)
        finally:
            with self.server.lock:
                self.server.inflight -= 1
```

and at the end of `_owned_post` (`:212`) replace
`self.relay(provider, prepared, metrics, started, has_image)` with
`return provider, prepared, metrics, started, has_image`. Every `return
self.error(...)` and `return self.send_json(...)` above it keeps returning
`None`, so nothing else changes. `raw` and `payload` now go out of scope
before the relay starts. Keep the lock section exactly as plan 163 left it.

**Verify**: `python3.14 -B -m unittest tests.test_handler tests.test_subscription_fallback tests.test_latency_metrics` → pass.

### Step 2: One name for the upstream timeout

In `ai_router/transport.py` add `UPSTREAM_TIMEOUT_S = 120` with a one-line
comment ("operation timeout on the upstream socket, not a turn deadline";
see the 2026-09-10 optimisation audit's adjudication). Use it at
`ai_router/relay.py:30`, `:74`, `:143` and `ai_router/providers.py:228`.
`ai_router/relay.py:15` imports the module, so `transport.UPSTREAM_TIMEOUT_S`
reads there; `ai_router/providers.py:17` imports names only
(`from .transport import HOP_HEADERS, Prepared, passthrough`), so add
`UPSTREAM_TIMEOUT_S` to that list and use the bare name rather than
`transport.UPSTREAM_TIMEOUT_S`, which is unbound in that module. In
`ai_router/router.py`, add `CLIENT_TIMEOUT_S = 120` beside `MAX_INFLIGHT`
with a comment that it bounds the client socket (idle pre-auth reads and
blocked writes) and use it at `:71` and `:138`. Do not unify the two names:
they bound different sockets for different reasons.

**Verify**: `grep -nE "timeout=120|timeout_s': 120|timeout = 120|settimeout\(120\)" ai_router/relay.py ai_router/providers.py ai_router/router.py` → no matches; focused tests pass (`tests/test_upstream_failures.py` still sees `timeout_s == 120` in the timeout message). Name the three files rather than scanning `ai_router/`: `ai_router/candidate.py:71` has an unrelated `subprocess` `timeout=120` that stays.

### Step 3: Pin the frame contract with a test

In `tests/test_handler.py` add:

```python
    def test_relay_runs_after_the_request_frame_returns(self):
        # The raw body and parsed payload are locals of _owned_post; calling
        # relay from do_POST lets them die before the stream starts.
        source = inspect.getsource(Handler._owned_post)
        self.assertNotIn('self.relay(', source)
        self.assertIn('self.relay(*ready)', inspect.getsource(Handler.do_POST))
```

(`Handler` is already imported at `tests/test_handler.py:20`; add `inspect`
to that module's imports). This is a structural pin,
not a behaviour test; the behaviour is covered by the existing handler and
fallback suites.

**Verify**: `python3.14 -B -m unittest tests.test_handler` → pass.

### Step 4: Record the image-walk decision, baseline, changelog

- In `ai_router/router.py:60-66`, extend the `_payload_has_image` comment:
  "Kept eager: under 1 ms on a 4 MiB body; RecursionError is contained by
  the handler (plan 163)."
- Re-sync `config/source-limits-baseline.json` if a count changed; add a
  `CHANGELOG.md` line ("the router no longer holds the request body and its
  parsed form for the duration of a streamed turn") and bump
  `packaging/VERSION` with the `pyproject.toml` version unless already
  bumped on your branch.

**Verify**: limits, policy scans, lint, full suite → pass.

## Test plan

- New: the structural pin in Step 3.
- Existing: handler, fallback, latency-metrics and containment suites pass
  unchanged (they exercise every return path of `_owned_post`).
- Optional, not a unit test: run `tools/probe_context_budget.py` or a local
  `tracemalloc` snapshot before and after against a 15 MiB synthetic body
  and record the resident figure in the plan's status row.

## Done criteria

- [ ] `grep -n "self.relay(" ai_router/router.py` shows exactly one call, in `do_POST`.
- [ ] `grep -nE "timeout=120|timeout_s': 120|timeout = 120|settimeout\(120\)" ai_router/relay.py ai_router/providers.py ai_router/router.py` returns no matches.
- [ ] Full suite, compile, lint, limits and policy scans pass; only in-scope files changed.
- [ ] `plans/README.md` status row for 164 updated.

## STOP conditions

- A test patches `Handler._owned_post` to intercept the relay call, or
  asserts that `_owned_post` returns `None` on success: report before
  changing the contract.
- `subscription_fallback.refused` stops receiving a handler whose `relay`
  method works mid-stream (it must; do not move `relay` off the handler).
- Any verification fails twice after a reasonable fix.

## Maintenance notes

- `prepared.body` stays alive on purpose for the refusal cache and the
  rejection fingerprint (`ai_router/relay.py:80-87`); if those ever move to
  a precomputed digest, `prepared.body` can be dropped after
  `transport.post_with_phases` returns and the resident figure falls again.
- New per-request state belongs in `metrics` or `Prepared`, not in
  `_owned_post` locals captured by a closure.
