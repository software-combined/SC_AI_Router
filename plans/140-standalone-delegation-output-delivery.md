# Plan 140: Deliver standalone delegation outputs to OpenRouter models

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If any
> "STOP conditions" item occurs, stop and report - do not improvise. When done,
> update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat origin/develop..HEAD -- ai_router/compaction.py ai_router/providers.py tests/ config/source-limits-baseline.json`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug / compatibility
- **Planned at**: commit `d440c3a`, 2026-09-11
- **Status**: IN PROGRESS: offline proof complete 2026-09-11; commit,
  release and live acceptance pending

First proof: a request containing the captured no-call_id `create_thread`
item prepares an OpenRouter body with exactly one assistant-role plaintext
message carrying the delegation marker, and the full offline suite exits 0.

## Outcome

Nested cross-task messages (`create_thread`, `send_message_to_thread`)
injected by Codex Desktop reach tasks running on OpenRouter models instead
of being silently dropped as orphan tool fragments. Standalone
app-injected outputs (no `call_id`) are rendered as readable assistant-role
plaintext before the scrub; matched call/output pairs and the OpenAI
subscription path are unchanged.

## Current state

Codex Desktop (app-server codex-cli 0.153.4) injects cross-task messages as
a standalone Responses input item with NO `call_id`:
`{"type": "function_call_output", "name": "create_thread",
"namespace": "codex_app", "output": "<codex_delegation>..."}`.
`ai_router/compaction.py::scrub_tool_fragments` dropped any output whose
`call_id` was absent from the complete calls, so a missing `call_id`
(`None`) counted as an orphan and the item was deleted. The scrub is
called from `OpenRouterProvider.prepare` in `ai_router/providers.py`.
Result: tasks on OpenRouter models never received the delegated message;
tasks on OpenAI models did. Live probes against OpenRouter
(deepseek/deepseek-v4.1-flash): raw standalone item -> HTTP 400
`invalid_prompt`; readable assistant-role plaintext -> 200 with the marker
read.

Ownership: worktree
`/Users/cyrilallart/Documents/Github/.worktrees/router-handoff-outputs-20260911`,
branch `codex/router-handoff-outputs-20260911`, target `develop`.

## Scope and ownership

**In scope** (exact file list; nothing else was touched):

- NEW `ai_router/standalone_outputs.py` (56 lines): `materialize_outputs`
  converts standalone outputs to prefixed assistant plaintext.
- `ai_router/providers.py` (399 lines): `OpenRouterProvider.prepare` only
  calls `materialize_outputs` before the existing scrub line.
- `ai_router/compaction.py` (314 lines): the scrub drops an output only
  when it claims a string `call_id` absent from the complete calls.
- `config/source-limits-baseline.json`: synced counts for the three files
  above plus the mixed-router test growth.
- NEW `tests/test_standalone_outputs.py` (106 lines), plus one case each
  in `tests/test_compaction.py` and `tests/test_mixed_router.py`.
- NEW `tools/probe_standalone_outputs.py` (92 lines): offline PASS/FAIL
  plus capped `--live` probe.
- This plan file, the `plans/README.md` row, one `docs/compatibility.md`
  entry, one `CHANGELOG.md` bullet. No `packaging/VERSION` change, no
  commit (integration owns both).

**Out of scope**: the OpenAI subscription provider, `ai_router/claude.py`,
live paid probes (orchestrator-owned acceptance), release/version work.

## Steps

1. Run the drift check first; reconcile per the note above or STOP.
2. Add `ai_router/standalone_outputs.py` reusing `OUTPUT_TYPES` from
   `compaction.py`; keep it under 250 lines. Fail closed with a
   content-free `PreparationError` when a standalone output has no
   readable text.
3. Hook `materialize_outputs` into `OpenRouterProvider.prepare` only,
   before `scrub_tool_fragments`; keep `providers.py` under 400 lines.
4. Narrow the scrub drop condition to string `call_id`s and update the
   comment above `OUTPUT_TYPES`; keep `compaction.py` under 400 lines.
5. Add the three test slices (offline, no network); keep each test file
   under 500 lines.
6. Add `tools/probe_standalone_outputs.py` (under 400 lines); offline
   default prints PASS/FAIL only, `--live` requires `--max-calls N`.
7. Sync `config/source-limits-baseline.json` to the exact new counts.
8. Record the compatibility entry and the CHANGELOG bullet; add this plan
   and its README row; re-run the drift check so it is empty at
   integration.

## Verification commands

| Purpose | Command | Expected |
|---|---|---|
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Source limits | `python3.14 tools/check_source_limits.py` | `failures=0` |
| Focused | `python3.14 -m unittest tests.test_standalone_outputs tests.test_compaction -v` | all pass |
| Offline probe | `python3.14 tools/probe_standalone_outputs.py` | `PASS` |
| Drift at integration | `git diff --stat origin/develop..HEAD -- ai_router/compaction.py ai_router/providers.py tests/ config/source-limits-baseline.json` | empty after merge to develop |

## STOP conditions

- The captured item shape in this plan does not match the source found:
  stop and report instead of re-litigating the root cause.
- A fix requires touching files outside the scope list: stop and report.
- A test fails for a reason unrelated to this change: stop and report.
- Source limits cannot be met: stop and report instead of shipping an
  over-cap file.
- Network access, credentials, or a paid probe is needed: stop; do not
  run live probes (the orchestrator owns live acceptance).
