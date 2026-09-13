# Plan 162: Bound every upstream read the way request bodies are bounded

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report; do not improvise.
> When done, update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat c068368..HEAD -- ai_router/sse.py ai_router/transport.py ai_router/tool_adapter.py ai_router/agent_handoffs.py ai_router/relay.py ai_router/upstream.py ai_router/providers.py ai_router/stream_errors.py tests/test_stream_containment.py tests/fakes.py config/source-limits-baseline.json`
> If any in-scope file changed, compare the "Current state" excerpts against
> the live code before proceeding; on a mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MED
- **Depends on**: none; serialize with 164 on `ai_router/relay.py` (164 after 162). Plan 161 owns `ai_router/key_store.py`, including the `json.load(response)` at `:44`; this plan never touches that file
- **Category**: security, perf
- **Planned at**: commit `c068368` (`origin/develop`), 2026-09-13
- **Source**: `plans/2026-09-13-router-four-lane-audit.md`, finding F2

## Why this matters

Request bodies are capped at 16 MiB and `Transfer-Encoding` is refused
(`ai_router/ingress.py:128-143`). Responses are not bounded anywhere. Plan
096 added a 16 MiB SSE frame cap, but `sse.blocks` iterates `for line in
response`, which is `readline()` with no limit: a single line with no newline
is buffered whole before the cap can run. A bounded line splitter,
`sse.lines()`, already exists and is used by `stream_errors.normalize`, but
the two adapters that carry every OpenRouter tool turn and every plaintext
handoff turn still pass the raw response into `sse.blocks`. Six whole-body
reads (`response.read()` and `json.load(response)`) have no ceiling at all.
A hostile or compromised upstream, or anyone terminating TLS to one of the
three fixed hosts, can grow the router process without bound, once per
in-flight turn (32 turns on `develop`). `tools/verify_runtime_pins.py:66-71`
already caps a read for exactly this reason, so the pattern is known here.

## Current state (verified at c068368)

- `ai_router/sse.py:7-18` (`lines(chunks)`) turns byte chunks into lines and
  raises `ValueError('upstream SSE frame exceeds ...')` once the pending
  buffer passes `MAX_FRAME_BYTES`; `ai_router/sse.py:21-39` (`blocks`) does
  `for line in response:` and checks size only after each line arrives.
- `ai_router/stream_errors.py:49`: `for frame, data in sse.blocks(sse.lines(chunks)):`
  is the bounded pattern to copy.
- `ai_router/tool_adapter.py:382-384`:

```python
def stream_events(response, names, notes=None):
    adapter = ToolEvents(names, notes)
    for frame, data in sse.blocks(response):
```

- `ai_router/agent_handoffs.py:294-304`: `adapt_response` reads the whole
  body with `raw = response.read()` (`:297`) for the non-stream case and
  `for frame, data in sse.blocks(response):` (`:304`) for the stream case.
- Whole-body reads with no ceiling: `ai_router/relay.py:39` (`response.read()`
  on a native 401/403), `:50` (`raw = response.read()` on any status >= 400),
  `ai_router/upstream.py:29` (429 drain), `ai_router/providers.py:169`
  (`json.load(response)` on the non-SSE tool path), `:235` (`json.load(resp)`
  in the compaction summariser), `ai_router/agent_handoffs.py:297`.
- `ai_router/transport.py:37-39` (`passthrough`) yields `read1(65536)`
  pieces; `ai_router/transport.py:1-4` says transport "never imports router,
  claude, registry, or the installer" and it must not import `runtime`
  either (it is a leaf).
- `ai_router/runtime.py:16`: `MAX_BODY = 16 * 1024 * 1024`;
  `tests/test_stream_containment.py:34-35` already pins
  `sse.MAX_FRAME_BYTES == router_mod.MAX_BODY`.
- `ai_router/relay.py:127-128` catches `ValueError` around the whole relay and
  turns it into `transport_error` plus a terminal frame (when headers were
  already sent) or a 502; that is the containment every new bound relies on.
- Line budget: `ai_router/tool_adapter.py` is 394 lines against a 400 hard
  cap; `ai_router/agent_handoffs.py` (314), `ai_router/providers.py` (304),
  `ai_router/upstream.py` (250) are baselined above the 250 soft cap.
  `ai_router/transport.py` is 148 lines.
- Test conventions: `tests/fakes.py` provides `FakeUpstream(status, body, ...)`
  and `install_fake(test, factory)`; `tests/harness.py` provides
  `start_server`, `test_state`, `auth_file`, `post`. Read `FakeUpstream`'s
  response object before writing tests: the bound must be exercised through
  the same `read1`/iteration surface the real `http.client.HTTPResponse`
  offers.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_stream_containment tests.test_bounded_reads tests.test_handler tests.test_tool_adapter tests.test_agent_handoffs tests.test_streaming_identity tests.test_stream_context_errors tests.test_upstream_failures` | all pass |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Lint | `python3.14 -m ruff check --select F401,F811 ai_router packaging tools tests` | `All checks passed!` |
| Limits | `python3.14 tools/check_source_limits.py` | `failures=0` after re-syncing baselined counts |
| Policy scans | `python3.14 tools/check_policy_scans.py` | pass |

## Scope

**In scope**: `ai_router/transport.py`, `ai_router/sse.py` (docstring
only), `ai_router/tool_adapter.py`, `ai_router/agent_handoffs.py`,
`ai_router/relay.py`, `ai_router/upstream.py`, `ai_router/providers.py`,
`tests/test_bounded_reads.py` (create), `tests/test_stream_containment.py`
(one added case), `config/source-limits-baseline.json`, `CHANGELOG.md`,
`packaging/VERSION`, `pyproject.toml` (version).

**Out of scope**: `ai_router/stream_errors.py` (already bounded);
`ai_router/ingress.py` (request side is done); any change to what the
adapters emit; `tool_adapter.snoop_response_identity` (it streams `read1`
pieces and keeps a 64 KiB bounded copy already, `ai_router/tool_adapter.py:290-333`);
the compaction transcript budget.

## Git workflow

- Worktree based on `develop`; branch like `<you>/162-bounded-upstream-reads-20260913`.
- Suggested commits: `fix: bound adapted SSE streams by line, not by frame`
  then `fix: cap whole-body upstream reads`. Run `pre-commit-review` before
  each commit. No push or PR unless instructed.

## Steps

### Step 1: A capped reader in the transport leaf

Add to `ai_router/transport.py` (no new imports needed):

```python
MAX_UPSTREAM_BODY = 16 * 1024 * 1024   # matches runtime.MAX_BODY; pinned by a test
ERROR_BODY_LIMIT = 1024 * 1024         # an error envelope is parsed, never relayed whole


def read_capped(response, limit):
    """The whole body, or ValueError once it exceeds `limit` bytes.

    Reads in read1 pieces so a hostile upstream cannot make one call
    allocate the full body before the check runs.
    """
    chunks, total = [], 0
    while piece := response.read1(65536):
        total += len(piece)
        if total > limit:
            raise ValueError('upstream body exceeds %d bytes' % limit)
        chunks.append(piece)
    return b''.join(chunks)
```

**Verify**: `python3.14 -c "from ai_router import transport; print(transport.MAX_UPSTREAM_BODY)"` → `16777216`.

### Step 2: Route the two adapters through the bounded line splitter

- `ai_router/tool_adapter.py:384`: change `sse.blocks(response)` to
  `sse.blocks(sse.lines(passthrough(response)))` and add `passthrough` to the
  existing `from .transport import ...` line if one exists, otherwise add
  `from .transport import passthrough` beside the other relative imports.
  Check the file stays at or under 400 lines (it is 394; this adds at most
  one line).
- `ai_router/agent_handoffs.py:304`: the same change, written as
  `sse.blocks(sse.lines(transport.passthrough(response)))` after adding
  `transport` to `from . import provider_defs, sse` at `:6` (Step 3 reuses
  that module import). `agent_handoffs.py`
  must not start importing `providers` or `router`
  (`docs/architecture.md:18-21`); `transport` is a leaf and is fine.
- `ai_router/sse.py:21-22`: extend the `blocks` docstring with one line:
  "Callers pass `lines(chunks)` for an unbounded reader; iterating a raw
  response reads whole lines first."

**Verify**: `python3.14 -B -m unittest tests.test_tool_adapter tests.test_agent_handoffs tests.test_streaming_identity` → pass.

### Step 3: Cap the whole-body reads

Replace, keeping each call site's surrounding logic unchanged:

- `ai_router/relay.py:39`: `response.read()` → `transport.read_capped(response, transport.ERROR_BODY_LIMIT)`
- `ai_router/relay.py:50`: `raw = response.read()` → `raw = transport.read_capped(response, transport.ERROR_BODY_LIMIT)`
- `ai_router/upstream.py:29`: the boundary rule at `tests/test_domain_boundaries.py:70` forbids `upstream` importing `transport`, so this read moves to the caller instead of gaining a cap here; follow Step 3a.
- `ai_router/providers.py:169`: `json.load(response)` → `json.loads(transport.read_capped(response, transport.MAX_UPSTREAM_BODY))`; add `transport` to the `from . import ...` line at `ai_router/providers.py:4` (`:17` imports three names from it, not the module).
- `ai_router/providers.py:235`: `json.load(resp)` → `json.loads(transport.read_capped(resp, transport.MAX_UPSTREAM_BODY))`, keeping the surrounding `except ValueError: raise OSError('Summarizer returned invalid JSON')`; note a capped read now also raises `ValueError`, which that branch maps to the same `OSError`, and `router.py:164-165` answers `COMPACTION_UNAVAILABLE` (502): acceptable and explicit.
- `ai_router/agent_handoffs.py:297`: `raw = response.read()` → `raw = transport.read_capped(response, transport.MAX_UPSTREAM_BODY)` (the module import added in Step 2).

#### Step 3a: the `upstream` boundary rule

`tests/test_domain_boundaries.py:70` lists `transport` among the names
`ai_router/upstream.py` must never import. Do not weaken the rule. Instead
move the 429 drain read out of `upstream.upstream_retry_after`: have it stop
reading the body and let the caller drain. In `ai_router/relay.py:46-48`:

```python
        retry_after = upstream.upstream_retry_after(response, prepared, metrics)
        if retry_after is not None:
            transport.read_capped(response, transport.ERROR_BODY_LIMIT)
            return subscription_fallback.refused(handler, prepared, retry_after, metrics, started)
```

and delete the `response.read()` at `ai_router/upstream.py:29` (the function
keeps logging and returning the header). Update
`tests/test_upstream_failures.py` if it asserts the drain happened inside
`upstream_retry_after`.

**Verify**: `python3.14 -B -m unittest tests.test_upstream_failures tests.test_handler tests.test_subscription_fallback tests.test_domain_boundaries tests.test_providers tests.test_agent_handoffs` → pass (`tests.test_providers` exercises the compaction summariser path at `providers.py:235`).

### Step 4: Tests

Create `tests/test_bounded_reads.py` (docstring: fake upstream only, never
opens a network connection; reuse `tests/fakes.py` and `tests/harness.py`):

- `test_read_capped_returns_the_body_under_the_limit` and
  `test_read_capped_raises_past_the_limit` using an `io.BytesIO` (it has
  `read1`).
- `test_caps_match_the_request_ceiling`: `transport.MAX_UPSTREAM_BODY == router_mod.MAX_BODY`
  and `transport.ERROR_BODY_LIMIT < transport.MAX_UPSTREAM_BODY`.
- `test_adapted_stream_without_newlines_is_bounded`: through the server, an
  OpenRouter tool turn (a payload with one `tools` entry so
  `prepared.tool_names` is non-empty) against a `FakeUpstream` SSE response
  whose body is `b'data: ' + b'x' * (sse.MAX_FRAME_BYTES + 1)` with no
  newline; assert the client receives the terminal `response.failed` frame
  (pattern: `tests/test_stream_containment.py`, `RelayContainmentTests`) and
  that a `transport_error` event was logged. Assert also that the fake
  response was not read to the end in one call: give the fake a body larger
  than the cap and assert its read position stopped before the end (inspect
  the fake object; if `FakeUpstream` cannot report that, add a counting
  `read1` to the test's own subclass rather than editing `tests/fakes.py`).
- `test_oversized_error_body_is_a_502_not_a_relay`: `FakeUpstream(400, b'{"error": "' + b'x' * (2 * 1024 * 1024) + b'"}')`
  → the client gets 502 `UPSTREAM_FAILED` and the event log carries
  `transport_error`, no traceback.
- Extend `tests/test_stream_containment.py` with one case that
  `sse.blocks(sse.lines(iter([big_chunk])))` raises the bounded error for a
  newline-free chunk over the cap, next to `test_over_cap_frame_raises_bounded_error`.

**Verify**: focused command → all pass; then the full suite.

### Step 5: Baseline, changelog, version

Re-sync `config/source-limits-baseline.json` for every in-scope file the
limits check reports (keep every file under its hard cap; if
`tool_adapter.py` would pass 400, STOP). Add a `CHANGELOG.md` line under the
next unreleased heading and bump `packaging/VERSION` with the `pyproject.toml`
version unless already bumped on your branch.

**Verify**: limits, policy scans, lint → pass.

## Test plan

- New `tests/test_bounded_reads.py` (five cases) and one added case in
  `tests/test_stream_containment.py`, modelled on that file.
- Existing adapter, handler and containment suites pass unchanged.
- Full suite exit 0 with at least 1337 tests.

## Done criteria

- [ ] `grep -rn "sse.blocks(response)" ai_router/` returns no matches.
- [ ] `grep -nE "response\.read\(\)|json\.load\((response|resp)\)" ai_router/relay.py ai_router/upstream.py ai_router/providers.py ai_router/agent_handoffs.py ai_router/tool_adapter.py` returns no matches (`read1` calls are fine; the CLI and installer-side reads in `key_prompt.py`, `models.py`, `model_refresh.py`, `live_refresh.py`, `candidate.py` and `key_store.py` are outside this plan).
- [ ] `tests/test_domain_boundaries.py` passes with its rules unchanged.
- [ ] Full suite, compile, lint, limits and policy scans pass; only in-scope files changed.
- [ ] `plans/README.md` status row for 162 updated.

## STOP conditions

- `ai_router/tool_adapter.py` would exceed 400 lines: report; do not split
  the module inside this plan (that is a separate decision).
- `FakeUpstream`'s response object does not offer `read1`: extend the fake
  in the test module (a subclass), not in `tests/fakes.py`; if that is not
  possible, stop and report.
- A test asserts that a legitimate non-streaming completion larger than
  16 MiB is relayed: the cap matches the request ceiling by design; report
  the test and stop rather than raising the cap.
- Any verification fails twice after a reasonable fix.

## Maintenance notes

- New upstream reads use `transport.read_capped`; new SSE consumers use
  `sse.blocks(sse.lines(...))`. A reviewer should reject a bare
  `response.read()` or `json.load(response)` in `ai_router/`.
- Plan 164 edits `ai_router/relay.py` next; rebase it on this plan.
- A 429 whose body exceeds `ERROR_BODY_LIMIT` now becomes a 502 instead of
  the 503 subscription-fallback answer; no known provider sends one, and the
  relay's `ValueError` containment is the backstop.
- If a provider ever needs responses above 16 MiB, raise
  `MAX_UPSTREAM_BODY` and `runtime.MAX_BODY` together; the pin test exists
  to force that conversation.
