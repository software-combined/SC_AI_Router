# Plan 096: Contain mid-stream failures and bound SSE frame accumulation

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat a985197..HEAD -- ai_router/router.py ai_router/sse.py ai_router/tool_adapter.py tests/test_handler.py tests/test_tool_adapter.py`
> Read changed code and preserve current behavior before edits.
> Reconciliation 2026-09-11 (branch codex/router-plan-backlog-20260911, develop 1440645):
> Plans 090/091/093 landed since a985197. `relay` is now `router.py:301` (was `:304`;
> `sent = True` at `:360`, chunk loop `:361-367`, except at `:373`; `do_POST` ends
> with the `self.relay(...)` call at `:266`, and the Step 2 traceback pattern lives
> at `:247-252`). `sse.py` is 29 lines with `blocks` at `:4` (was `:4-16`) and no
> cap. `describe_response` (`transport.py:76-90`) returns exactly `'sse'`, so STOP 1
> does not apply. New relay/transport helpers live in `transport.py` (terminal-frame
> emission needs `json`, which pure `errors.py` must not import; `router.py` stays at
> 399/400). New tests live in `tests/test_stream_containment.py` (`test_handler.py`
> is 491/500). `test_handler.py` tail is now the Handler.timeout test (`:469-490`).

## Status and first proof

- Priority P2; effort S-M; risk LOW; confidence HIGH; category correctness; depends on none.
- Planned at `a985197`, 2026-09-10.
- First proof: a non-object SSE payload from upstream produces a logged failure and, on a Responses
  stream, a terminal `response.failed` event instead of a silent truncation; an unterminated SSE
  frame over the cap raises a bounded error rather than growing memory.

## Why this matters

1. **Escape hatch**: `relay` is called at `ai_router/router.py:269` outside `do_POST`'s try/except
   (which ends at `:254`), and its own handler catches only `(OSError, http.client.HTTPException,
   ValueError, KeyError)` (`:376`). A non-dict SSE payload (`ai_router/tool_adapter.py:345`
   `json.loads` → `:236` `event.get`) raises `AttributeError`, which escapes to
   `socketserver.handle_error` with a stderr traceback, no `router.jsonl` event, and no terminal
   event for the client — even though `sent` is already `True` at `:363`.
2. **Unbounded buffer**: `ai_router/sse.py:4-16` accumulates every line into `lines` and only flushes
   on a blank line; a stream without a frame boundary grows until EOF. The `ValueError` at `:15-16`
   arrives only after the memory is spent.

## Current state (verified at a985197)

- `ai_router/router.py:304-399` `relay`; `sent = True` at `:363`; the `for chunk in provider.adapt(...)`
  loop at `:364-372` writes and flushes per chunk; `except ... as exc` at `:376-395` logs
  `transport_error` with `error_type`; when `sent` is true nothing is written to the client.
- `router.context_error` (`:122-141`) shows the Responses terminal-event shape used elsewhere:
  `event: response.failed` + a JSON body with `{'type': 'response.failed', 'response': ...}`.
- `ai_router/sse.py:4-16`:
  ```python
  def blocks(response):
      lines = []
      for line in response:
          lines.append(line)
          if line not in (b'\n', b'\r\n'):
              continue
          ...
          yield b''.join(lines), data
          lines = []
      if lines:
          raise ValueError('Incomplete upstream SSE event')
  ```
- Consumers: `ai_router/tool_adapter.py:343` (`stream_events`) and `ai_router/agent_handoffs.py:261`.
  `snoop_response_identity` uses its own 64 KiB framer and is unaffected.

## Scope

**In scope**: `ai_router/sse.py`, `ai_router/router.py` (`relay` except-path only),
`ai_router/transport.py` (terminal-frame emission + traceback location helpers only),
`tests/test_stream_containment.py` (new; `test_handler.py` is 491/500), `tests/test_tool_adapter.py`,
`tests/test_agent_handoffs.py`.
**Out of scope**: `snoop_response_identity`, `agent_handoffs` framing, response status/header logic,
compaction, any retry or replay behavior.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -m unittest tests.test_handler tests.test_tool_adapter tests.test_agent_handoffs` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; update baseline entries for `router.py` (400) and `sse.py`-adjacent counts if changed |

## Steps

### Step 1: bound `sse.blocks` (commit 1, independent)

Add a module constant `MAX_FRAME_BYTES = 16 * 1024 * 1024` (matches the request-body ceiling;
comment why). In `blocks`, track accumulated bytes for the current frame and raise
`ValueError('upstream SSE frame exceeds %d bytes' % MAX_FRAME_BYTES)` when exceeded. The existing
`relay` `ValueError` path already handles it; consumers propagate the error mid-iteration.

**Verify**: `tests/test_tool_adapter.py` (or a small dedicated test) feeds a synthetic stream with
one line larger than the cap and asserts the `ValueError`; a legitimate multi-MB frame under the
cap still parses.

### Step 2: mid-stream error containment (commit 2)

In `relay`:
- Add `TypeError` and `AttributeError` to the except tuple (do not widen to bare `Exception`).
- In the handler, compute an error location from the traceback like `do_POST:247-253` and pass it
  to `log_event` so the event names the failing adapter frame.
- When `sent` is true **and** the response is a Responses SSE stream from a Responses provider
  (`prepared.provider in ('openrouter', 'openai-subscription')`, `metrics.get('stream') is True`,
  and the response kind recorded at `:357` says SSE — read `transport.describe_response` for the
  exact kind string), best-effort write one terminal event before closing:
  `event: response.failed\ndata: <json>\n\n` shaped like `context_error` (`:133-134`) with a
  generic message (no payload, no upstream body). Wrap the write in `try/except OSError` so a dead
  socket cannot raise from the error path. Never write this into Claude Messages streams
  (`openrouter-claude`, `anthropic-subscription`) or non-SSE bodies.
- Keep the existing `transport_error` log for every caught mid-stream error, including those already
  caught today (`ValueError`, `OSError`) when `sent` is true.

**Verify**: new `tests/test_stream_containment.py` test with a `FakeUpstream` that emits
`data: [1,2,3]\n\n` then closes (plus `tools` so the request routes through `stream_events`):
assert the response status is 200, the body ends with a `response.failed` data frame,
`log_event` was called with `transport_error`, and the process/thread survives. A second test with
`sent` false keeps today's 502 mapping.

## Done criteria

- [ ] A non-dict SSE frame produces a logged `transport_error` and a terminal frame on Responses streams.
- [ ] Claude Messages streams never receive `response.failed`; non-SSE bodies keep current behavior.
- [ ] Over-cap frames raise `ValueError`; under-cap large frames still parse.
- [ ] Full suite, compile and limit gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- The exact `describe_response` kind string for SSE is ambiguous: stop and report; do not guess the
  gate condition.
- Any existing test asserts that a mid-stream error closes with no terminal frame: stop and compare
  intents before changing the contract.
- Writing the terminal frame turns out to risk duplicating a terminal event already emitted by the
  adapter: stop and report.

## Maintenance notes

- New exception types in the adapter surface must be added to the relay tuple deliberately; the
  location log is the debugging handle.
- The cap is a safety bound, not a protocol limit; if a real frame ever approaches it, raise the
  constant rather than splitting frames.
- Reviewers: confirm the terminal frame is only written after `sent` and only for Responses SSE.
