# Plan 091: Stop the adaptation path from re-parsing and re-serializing what it did not change

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat a985197..HEAD -- ai_router/tool_adapter.py tests/test_tool_adapter.py`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P1; effort S; risk LOW; confidence HIGH; category perf; depends on none.
- Planned at `a985197`, 2026-09-10.
- First proof: an SSE turn whose frames the adapter does not modify is forwarded with the upstream
  JSON text unchanged inside the `data:` envelope, and tool-argument frames are still rewritten.

## Why this matters

Two CPU costs run in the frame-delivery path of every tool-capable OpenRouter stream:

1. `stream_events` (`ai_router/tool_adapter.py:341-349`) does `json.loads(data)` and an
   unconditional `json.dumps(event)` per frame. The parse is required (the adapter must inspect
   every event), but the dump is pure waste for frames the adapter did not modify, the common case
   for `response.output_text.delta` and unknown event types.
2. `integer_json` (`:23-31`) runs `json.loads` plus a regex substitution over every function-call
   argument string. When the text cannot contain a `.0` integer spelling, the substitution provably
   cannot change anything, so both operations are avoidable.

Magnitudes are modest (single-digit ms per MB of frames / per 200 KB of arguments) but the cost is
repeated on every turn and the fixes are small and provably behavior-preserving.

## Current state (verified at a985197)

- `ai_router/tool_adapter.py:23-31`:
  ```python
  def integer_json(text):
      try:
          json.loads(text)
      except json.JSONDecodeError:
          return text
      return re.sub(r'("(?:\\.|[^"\\])*")|(-?\d+)\.0+(?=\s*[,}\]]|\s*$)', ...)
  ```
  The numeric branch requires a literal `.0`; the string branch replaces a string with itself.
- `ai_router/tool_adapter.py:341-349`:
  ```python
  for frame, data in sse.blocks(response):
      if data and data != b'[DONE]':
          event = adapter.event(json.loads(data))
          if event is not None:
              yield b'data: ' + json.dumps(event).encode() + b'\n\n'
      else:
          yield frame
  ```
- `ToolEvents.event` (`:235-247`) mutates in place and always returns `event`; there is no change
  signal today. Suppression returns `None` (`:238-239`); `item()` updates `self.item_ids` (`:201-202`)
  and may rewrite `item` (`:203-233`); `response['output']` is always rebuilt (`:244`).
- `ai_router/agent_handoffs.py:266-271` shows the house pattern of keeping the original frame when
  the adapter did not change it.

## Scope

**In scope**: `ai_router/tool_adapter.py`, `tests/test_tool_adapter.py`.
**Out of scope**: `sse.blocks` framing, `snoop_response_identity`, `prepare_tools`,
`agent_handoffs.py`, provider call sites, any change to the SSE envelope shape.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -m unittest tests.test_tool_adapter tests.test_claude_ingress tests.test_agent_handoffs` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; `tool_adapter.py` is baseline-pinned at 349, update the baseline if the count changes |

## Steps

### Step 1: `integer_json` early return (commit 1, independent)

Add at the top of `integer_json`, after the docstring/comment:
```python
if '.0' not in text:
    return text
```
Leave the rest unchanged (the `json.loads` validity check and regex still run when `.0` appears).
Do not add the "reuse parsed envelope" idea: the double adaptation is across `.done` and
`response.completed` events with different input strings.

**Verify**: extend `test_integral_provider_numbers_do_not_break_native_integer_arguments`
(`tests/test_tool_adapter.py:29-35`) with: a malformed string without `.0` returns unchanged;
a valid JSON with `.0` inside a *string value* still returns it unchanged; `9007199254740993.0`
still trims. Focused tests pass.

### Step 2: changed-signal and unmodified-frame passthrough (commit 2)

Add `self.changed = False` to `ToolEvents.__init__`. Set it to `True` only when the serialized
content of the returned event actually changes:

- `item()`: set `self.changed = True` when `integer_json` alters the arguments string; when the
  tool maps to a `kind` other than `'identity'`; when a namespace entry adds `namespace`/`name`;
  when `agent_handoffs.restore_item` returns a different object. Re-assigning identical values
  (identity kind, unchanged arguments) must not set it.
- `event()`: reset `self.changed = False` at entry. Suppression (`return None`) keeps it `False`.
  The `response['output']` rebuild sets `changed` only if a child `item()` set it. Setting
  `notes['served_model']` alone does not count (it is not serialized into the frame).

Then in `stream_events`, replace the unconditional dump:
```python
event = adapter.event(json.loads(data))
if event is None:
    continue
if adapter.changed:
    yield b'data: ' + json.dumps(event).encode() + b'\n\n'
else:
    yield b'data: ' + data + b'\n\n'
```
This keeps today's envelope (`data: <json>\n\n`, no `event:`/`id:` lines) and forwards the upstream
JSON text verbatim for unchanged frames. Both are valid JSON for any SSE consumer; the only
difference is whitespace/key-order of unmodified frames.

**Verify**: extend `tests/test_tool_adapter.py` with (a) a synthetic SSE stream containing an
unmodified `response.output_text.delta` and asserting the emitted `data:` payload parses equal to
the upstream payload; (b) a stream whose `response.output_item.done` carries a `function_call`
with `8.0` arguments and asserting the rewritten frame still trims the integer; (c) a suppressed
`response.function_call_arguments.done` (tracked `item_id`) still yields nothing.

## Done criteria

- [ ] `rg -n "json.dumps\(event\)" ai_router/tool_adapter.py` appears only on the changed branch.
- [ ] New tests cover: unchanged frame passthrough, mutated frame rewrite, suppression, early return.
- [ ] Full suite, compile and limit gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- A test shows an unmodified event must be re-normalized (e.g. a client rejects the whitespace
  variant): stop and report, and keep the parse but drop the write-side optimization only.
- `item_ids` bookkeeping or suppression stops working in any existing test: stop; a missed change
  signal breaks tool execution, which is worse than the CPU cost.
- The change-signal cannot be made reliable for the `response.completed` path (full output rebuild):
  stop and split the plan rather than shipping a partial signal.

## Maintenance notes

- Any new mutation branch added to `ToolEvents.item`/`event` must set `self.changed`.
- `snoop_response_identity` is intentionally untouched: it already forwards before observing.
- Reviewers: scan both `item()` and `event()` for every assignment that lands in the serialized frame.
