# 145: Namespaced tool alias resilience

Status: DONE: tool-alias resilience 2026-09-12 (source)

## Problem

`prepare_tools` flattens namespaced client tools to
`ns_<sha256[:12]>_<tool[:48]>`. Models re-type the 12-hex token and drop a
character: on 2026-09-12 (Codex 0.153.4, `deepseek/deepseek-v4.1-flash` via the
router) the model called `ns_ae034c2c1e8_send_message_to_thread` where the
exposed name was `ns_ae034c2cc1e8_send_message_to_thread`. The map lookup missed,
the mangled name was forwarded to the client, and the client answered
`unsupported call: <name>` with no clue about the correct name.

## Change

- `ai_router/tool_aliases.py` owns the wire-name scheme: readable
  `namespace__tool` aliases (sanitised to `[A-Za-z0-9_-]`, <= 64 chars), a
  collision/over-length fallback that keeps the readable stem and appends a
  short digest widened until the name is unique (an exhausted ladder fails the
  request rather than sharing a wire name), the repair matcher, and the
  unsupported-call annotation.
- `ToolEvents` repairs a call only when it is the plain native name of exactly
  one exposed namespaced tool, the dotted `namespace.tool` form shown in its
  description, or a fallback alias whose digest characters were re-typed. A
  call that already carries a namespace, a name the request already exposes, a
  native name the per-model ceiling withheld, an ambiguous name and an
  unrelated name are never rewritten. Repairs log `tool_call_repaired` /
  `tool_call_unresolved` once per call with `model` and `cause` only.
- A client `unsupported call: <name>` output gains one routing line naming the
  exact exposed tool (up to three) or a generic "re-read the tool list" line.
- `ai_router/upstream.py` recognises readable aliases when naming a tool in an
  upstream schema-rejection message.
- The routed base instructions state that tool names are exact and must be
  copied verbatim.

## Verification

- `python3.14 -m unittest discover -s tests -t .`
- `python3.14 -m compileall -q ai_router tools tests packaging`
- `python3.14 tools/check_source_limits.py`
- `tests/test_tool_alias_repair.py`: unit cases, a handler path test through the
  real request path with a fake upstream, and the upstream-hint case.

## Residual

- The repair leg is source-proven; a real model cannot be made to mistype
  deterministically, so live acceptance is the existing paid probe
  (`tools/probe_codex_runtime.py <model> --deferred`) after deploy, not a new
  paid test.
