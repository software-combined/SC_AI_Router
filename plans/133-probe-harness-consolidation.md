# Plan 133: One app-server probe harness for the three probe tools

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat b642de9..HEAD -- tools/appserver_probe.py tools/probe_codex_runtime.py tools/probe_context_budget.py tools/probe_agent_handoffs.py tests/test_probe_harness.py`
> Read changed code and preserve current behavior before edits.

> **Amendment 2026-09-12.** Plan 145 (model verification gate) runs its
> capability-claim probe legs on this plan's `AppServer` client. Keep the
> constructor, `rpc`, `turn` and `close` signatures stable so 145 can add legs
> without touching the harness. Land this plan before 145.

## Status and first proof

- Priority P3; effort M; risk MED; confidence HIGH; category tech-debt; depends on none; run before
  118/119 (they rely on paid probes).
- Planned at `b642de9`, 2026-09-11.
- Implemented 2026-09-12 on top of `72e1316`: `tools/appserver_probe.py` owns the wire plumbing and
  all three probes are thin scenario drivers over it. No live runs.
- First proof: one `AppServer` client spawns/drains/RPCs the app-server; the three probes keep their
  scenario behaviour with far less code, and the offline harness test covers the shared client.

## Why this matters

Three probes re-implement the same JSON-RPC-over-stdio harness:

- `tools/probe_codex_runtime.py:98-145` (Popen, stderr drain, stdout reader, `send`/`next_event`/`rpc`),
- `tools/probe_context_budget.py:104-201` (`Client` with the same plus `turn`/`compact`/`close`),
- `tools/probe_agent_handoffs.py:339-379` (the same inline).

Environment scrubbing diverges: `probe_context_budget.py:117-119` strips
`OPENAI_/CODEX_/CHATGPT_`, `probe_agent_handoffs.py:336-338` strips `*API_KEY/TOKEN/SECRET/AUTH*`,
and `probe_codex_runtime.py` passes the ambient env. A wire change requires three edits, and only
`probe_codex_runtime` has offline harness coverage (`tests/test_probe_harness.py`), so the other two
can regress silently.

## Scope

**In scope**: new `tools/appserver_probe.py`, the three probe scripts, `tests/test_probe_harness.py`, new `tests/test_appserver_probe.py`.
**Out of scope**: changing what the probes measure or report, paid runs, client fixtures, the
probe JSON outputs.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_probe_harness` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; probe baselines lowered |

## Steps

1. **Create `tools/appserver_probe.py`** with an `AppServer` class: spawn (command, cwd, env),
   stderr drain, stdout line reader, `send`, `next_event`, `rpc(method, params)`, `turn`, `close`,
   and a single explicit `scrub_env(env, mode)` policy where `mode` names the three existing env
   behaviours (ambient pass-through; `OPENAI_/CODEX_/CHATGPT_` strip plus synthetic key injection;
   `*API_KEY/TOKEN/SECRET/AUTH*` strip), preserving the current order of injection vs scrub for
   each probe.
   Top-level file so the release `tools/*.py` glob ships it (plan 123's inventory if it lands first).
   *Landed 2026-09-12: 245 lines; `strict_lines` and `payload`/`expect_error_code` included; `AppServer(command, cwd, env, stderr=...)` plus `send`,
   `next_event(deadline=..., timeout=...)`, `rpc(method, params, timeout=...)`,
   `turn(thread, text, timeout=..., expect_error=..., marker=...)`, `close()`, an `on_event` hook
   and `eof_detail` callable for probe-specific reporting. `scrub_env(env, mode, inject=...)`
   implements the three policies (ambient; strip `OPENAI_/CODEX_/CHATGPT_` then inject in order;
   strip `*API_KEY/TOKEN/SECRET/AUTH*` then set `CODEX_HOME`).*
2. **Migrate the three probes** to thin scenario drivers over `AppServer`. Preserve every request
   payload, event filter, output field and exit code. Where a probe intentionally differs (scrub
   mode, timeout), make it an explicit argument.
   *Landed 2026-09-12: `probe_codex_runtime.py` 389 -> 372, `probe_context_budget.py` 254 -> 215,
   `probe_agent_handoffs.py` 496 -> 486. Every request payload is unchanged; the shared `turn()`
   sends the context-budget shape by default and accepts `payload=`/`expect_error_code=` for other
   legs (plan 145's hook), while the runtime and handoffs probes keep their own `rpc` calls
   (handoffs keeps its local `ValueError` reply loop so its stdout `probe_error` field is
   unchanged). Accepted failure-path deltas: a child that exits early now raises `RuntimeError`
   immediately instead of surfacing `queue.Empty` after the global deadline; the context-budget
   probe opts into `strict_lines=True`, so a malformed stdout line fails fast instead of killing its
   reader thread; its EOF text reads `App server exited: ...` (was `Codex exited:`); and an error
   reply raises `RuntimeError` rather than `AssertionError`. Exit codes are unchanged.
   `rg 'subprocess.Popen' tools/probe_*.py` returns nothing.*
3. **Extend the offline harness test** to cover `AppServer` against the existing fake app-server:
   spawn, one RPC round trip, stderr drain, clean close, timeout path. No paid runs in tests.
   *Landed 2026-09-12: the `AppServer` coverage lives in `tests/test_appserver_probe.py` (16
   tests: spawn, RPC round trip, event hook, EOF detail, timeout, malformed-line strictness,
   kill-group teardown, all three scrub modes and the `turn/start` payload plus marker contract);
   `tests/test_probe_harness.py` keeps the probe acceptance legs (362 lines). The split keeps both
   files well under the 500-line test cap.*

**Verify**: focused test; `rg -n 'subprocess.Popen' tools/probe_*.py` shows only the shared module
(or deliberate exceptions noted); full suite green.

## Done criteria

- [x] One spawn/RPC implementation; probes keep identical behaviour and outputs (suite green; no
      `subprocess.Popen` outside the shared module; stdout fields unchanged, with the accepted
      failure-path deltas above).
- [x] Scrub policies are explicit and covered by the harness test.
- [x] Full suite, compile and limit gates pass; only in-scope files changed.
- [x] `plans/README.md` status row updated.

## STOP conditions

- A probe's event handling depends on timing/wire quirks not expressible in the shared client: stop
  for that probe, keep it local with a comment, and report.
- Any change alters probe output fields: stop; these are evidence artifacts.

## Maintenance notes

- A wire change is now a one-file fix plus probe argument updates.
- Paid probes remain owner-gated; this plan has no live runs.
- Reviewers: diff probe outputs line by line against the previous implementation.
