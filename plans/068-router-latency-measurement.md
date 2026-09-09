# Plan 068: Separate router overhead from upstream waiting

> Planning only. Execute after an implementation instruction. Read this entire
> plan, verify each step, and update the plan/index with the actual evidence gate.
> Drift check: `git diff --stat 83a5023..HEAD -- codex_router/router.py codex_router/transport.py codex_router/tool_adapter.py codex_router/providers.py codex_router/runtime.py tests/test_latency_metrics.py tests/test_safe_diagnostics.py docs/operations.md CHANGELOG.md packaging/VERSION plans/README.md`
> Reconcile changed symbols against the excerpts; stop on a changed contract.

## Status and first proof

- TODO; P1; effort S-M; risk MED; confidence HIGH; category perf/diagnostics.
- Planned at `83a5023`, 2026-09-10. No prerequisite implementation.
- First proof: deterministic fake-clock tests separate read/prepare/connect/send/
  headers/forwarding intervals, while preserving response bytes and safe logs.
- This enables later measurement; it does not itself prove reduced latency.

## Current state

`router.py:176-178` reads the entire body before preparation. `:234-243` builds
metrics after preparation, and `:260-315` connects and adapts the response:

```python
'local_prepare_ms': round((time.monotonic() - started) * 1000, 1)
conn = http.client.HTTPSConnection(prepared.host, timeout=120)
conn.request('POST', prepared.path, body=prepared.body, headers=prepared.headers)
response = conn.getresponse()
```

`upstream_headers_ms` and `first_chunk_ms` are cumulative from request start.
The first chunk is measured after provider adaptation. Read-only installed
0.6.10.25 data showed OpenRouter prepare median 19.1 ms versus first chunk
3663.9 ms (515 completions); this cannot attribute the remaining time.
Follow metadata-only `runtime.log_event` and the canary tests in
`tests/test_safe_diagnostics.py`. Plan 060's no-content rule already applies.

## Scope and commands

Only files in the drift check, plus this plan's status. No credential reads in
tests, raw payload capture, new logging dependency, timing-driven retry, timeout
change, service restart, or paid benchmark. Keep existing metric fields for
compatibility; add precise fields rather than silently redefining old ones.

| Gate | Command | Expected |
|---|---|---|
| Baseline | `python3.14 -B -m unittest tests.test_handler tests.test_providers tests.test_safe_diagnostics` | Pass |
| New metrics | `python3.14 -B -m unittest tests.test_latency_metrics tests.test_safe_diagnostics` | Pass after implementation |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | Exit 0 |
| Compile | `python3.14 -m compileall -q codex_router tools tests packaging` | Exit 0 |
| Source limits | `python3.14 tools/check_source_limits.py` | Zero failures |
| Diff | `git diff --check` | Exit 0 |

## Steps

1. Create `tests/test_latency_metrics.py`. Drive the handler with fake upstream
   and clocks, following tests/fakes.py and the unbound-handler canary pattern.
   Require body read versus decode/prepare, connect, request send, header wait,
   first returned upstream body data, and first successful downstream write to
   have distinct documented meanings. Include one failed connect, upstream read
   reset, and downstream write reset. No sockets or real time sleeps are needed.
   **Verify:** new tests fail because the fields/classification are absent;
   the baseline command remains green.
2. Add monotonic boundaries in the existing handler/transport paths. Explicit
   `conn.connect()` separates connection establishment from request upload; keep
   it inside existing exception cleanup. Include HTTPS object setup in a named
   setup/connect interval. Do not claim separate DNS/TCP/TLS times without
   measuring them. Add a generated request correlation id and runtime version.
   Keep phase state local to each request. Record durations on failure too.
   **Verify:** metrics tests assert exact fake durations and unchanged byte/status
   outputs, including non-streaming and subscription/OpenRouter routes.
3. Categorise response type as sse/json/other and encoding as
   identity/gzip/deflate/br/zstd/other, using fixed values only. Do not log arbitrary
   header strings. Record first upstream *read-return* separately from first
   forwarded data; whole-body/line reads must never be labelled network TTFB.
   Observe useful text/tool events only where already parsed; omit unavailable
   values on opaque/compressed paths instead of adding another parser.
   Classify client disconnect only when the failed operation is downstream write.
   **Verify:** synthetic private markers in headers, exception text, messages and
   tool arguments never appear in logs; both upstream/downstream reset cases pass.
4. Document field definitions and an aggregate-only comparison recipe in
   docs/operations.md. Group by version/provider/model/stream/encoding and include
   failed/aborted counts, sample size and time window. Use per-request ratios,
   never ratios of unrelated percentiles. Live collection uses approved existing
   logs; paid direct-versus-router tests require separate explicit authority.
   Update changelog/version for the runtime change. **Verify:** all table gates.

## Done, integration and stop conditions

- [ ] New timing and content-canary tests pass; old metric semantics remain.
- [ ] Full suite, compile, size and diff gates pass; only scoped files changed.
- [ ] Report source evidence separately from installed/live measurements.
- Use one owned `codex/` worktree based on develop; reuse it, never edit primary.
  Run the current installed pre-commit-review gate before a `feat:` or `fix:`
  commit; target develop and verify integration before safe worktree cleanup.
- Stop if precise measurement needs invasive socket wrappers or platform-specific
  internals; deliver the useful coarse intervals with explicit unavailable fields.
  Stop if privacy requires logging arbitrary upstream/user content, or if a
  timing change alters request dispatch, retries, cancellation or billing.
- Maintenance: preserve these field meanings through future transport changes;
  a metric that times a buffering adapter cannot stand in for provider TTFB.
