# Plan 069: Forward stream bytes without waiting for model-identity inspection

> Planning only; implement only when authorised. Verify each step and record
> source, integration and live acceptance separately in this plan/index.
> Drift check: `git diff --stat 83a5023..HEAD -- codex_router/tool_adapter.py codex_router/transport.py codex_router/providers.py codex_router/router.py tests/test_streaming_identity.py tests/test_tool_adapter.py tests/test_handler.py docs/operations.md CHANGELOG.md packaging/VERSION plans/README.md`
> Reconcile Plan 068's additive metrics before editing the same stream paths.

## Status and first proof

- TODO; P1; effort M; risk MED; confidence HIGH for synthetic mechanism.
- Planned at `83a5023`, 2026-09-10. Run after 068 for live attribution; the
  deterministic regression/fix can proceed independently of paid/live access.
- First proof: first output bytes arrive before a fake upstream releases its
  remaining compressed or incomplete-line stream; every byte stays identical.
- OpenAI first-chunk≈completion logs are a lead, not proof of live compression.

## Current state

`SubscriptionProvider.adapt` at providers.py:160 always snoops successful
responses. `tool_adapter.py:243-266` chooses only by Content-Type:

```python
if 'text/event-stream' not in response.getheader('Content-Type', ''):
    raw = response.read()
    # Parse model, then yield raw.
for line in response:
    yield line
```

An offline gzip fixture had no LF in its 101 compressed bytes. The current
inspector consumed all bytes before yielding; transport.passthrough yielded
the first available 16-byte piece. Other compressed bodies may contain LF,
so the symptom varies. `transport.py:23` already uses `read1(65536)`.
Existing identity tests in tests/test_tool_adapter.py assert byte equality and
served model, but their fully buffered fake cannot prove early forwarding.

## Scope and commands

Only drift-check files and this plan status. No general decompressor, permanent
served-model cache, response-body logging, protocol rewrite or paid probes.
Keep `openai-model` response-header pinning and all auth/header isolation rules.

| Gate | Command | Expected |
|---|---|---|
| Baseline | `python3.14 -B -m unittest tests.test_tool_adapter tests.test_providers tests.test_handler` | Pass |
| Regression | `python3.14 -B -m unittest tests.test_streaming_identity` | Fails before fix; passes after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | Exit 0 |
| Compile | `python3.14 -m compileall -q codex_router tools tests packaging` | Exit 0 |
| Size/diff | `python3.14 tools/check_source_limits.py` and `git diff --check` | Exit 0 |

## Steps and tests

1. Create tests/test_streaming_identity.py with a finite piecewise RawIOBase /
   BufferedReader fixture. Record how much upstream data was consumed when
   `next(adapter)` returns; do not rely on wall-clock speed or real sockets.
   Cover gzip and zstd SSE, uncompressed partial lines/CRLF, fragmented JSON,
   invalid/oversized optional identity data and a no-body response. Assert exact
   joined byte equality and early first yield for every passthrough case.
   **Verify:** regression command fails on current compressed/partial-line cases;
   existing identity tests still characterise the old supported model extraction.
2. Use existing raw `read1` forwarding for optional identity-inspection paths.
   Bypass body inspection for any non-identity Content-Encoding. For identity
   JSON/SSE, maintain an optional bounded observer (64 KiB maximum retained
   bytes per JSON body or SSE event); overflow disables that observation, never
   forwarding. Yield bytes before optional parsing can hold the next forward.
   Malformed observation data is nonfatal. Preserve SSE multiline/CRLF support.
   **Verify:** exact bytes, bounded retained data and early yield tests pass.
3. Preserve per-response identity freshness. A valid current response header
   may provide identity only if its meaning is verified for that provider; header
   absence/ambiguity must not block bytes. Keep observed identity provenance and
   do not substitute an old server.served_models entry for a new observation.
   If compressed-body identity is unavailable, leave it unavailable and document
   that /health is last-observed state, not proof of the current served model.
   **Verify:** two responses for the same alias with different reported models
   update observations; unsupported inspection never fabricates an identity.
4. Preserve the separate mandatory tool-adaptation contract. OpenRouter builds
   fresh headers; CPython 3.14 already defaults Accept-Encoding to identity.
   Characterise this using a recording HTTPConnection with fake send/socket,
   plus existing native tool round-trip tests. Never bypass required tool
   adaptation merely because its body is encoded. If live headers prove a
   non-identity body on that route, stop for a bounded protocol decision rather
   than silently adding decompression or sending broken tools. **Verify:** the
   recording test sees identity and existing adapted-stream tests stay green.
5. Reuse 068 metrics for a later approved installed comparison on equivalent
   subscription/model/encoding workloads. Compare first read-return versus first
   forwarded data, not model generation speeds. Paid/client probes are a separate
   gate. Update docs, changelog and version. **Verify:** all table commands pass.

## Done, integration and maintenance

- [ ] Byte-preservation, early-forwarding, observer-bound and fresh-identity
  regressions pass; normal tool adaptation and auth/header tests remain green.
- [ ] Full suite/compile/size/diff checks pass; only scoped files changed.
- [ ] Source fix status does not claim deployed latency improvement.
- Use one owned `codex/` worktree from develop. Run the current pre-commit-review
  gate before commit, target develop, verify integration and safely clean up.
- Stop on source drift, a need to alter client authentication, lost mandatory
  tool adaptation, or repeated failing verification. No timing sleeps as tests.
- Future protocols must separate mandatory adaptation from optional observation;
  optional metadata is never a reason to buffer or fail a successful body.
