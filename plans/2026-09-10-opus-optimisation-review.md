# Opus 5 independent optimisation review

Requested: `anthropic/claude-opus-5`, reasoning `high`.
Returned model: `anthropic/claude-opus-5`.
Returned reasoning: `{"effort": "high"}`.
Source: develop `83a5023`, 2026-09-10.
Delivery: direct OpenRouter Responses API, bounded plaintext source packet.
Native subagent dispatch was rejected for encrypted instructions. An initial API
call confirmed the requested model/effort but exhausted 10,000 output tokens in
reasoning; this report comes from the completed bounded retry.
The API reviewer saw the audit brief and selected source excerpts, not live logs
or the entire repository/backlog. The parent independently checks the findings.

## Reviewer note

The brief requests an "Opus 5" reviewer. I cannot verify what model this API call was routed to; I only see the served side. No tools/filesystem were available, so this review is based solely on the source excerpts above. Line references are to those excerpts.

## Finding 1 — SSE identity snoop ignores Content-Encoding: **ACCEPT (refine scope)**

Real. `tool_adapter.py:245` branches on Content-Type only; `:256` does `for line in response`, and `http.client` never decompresses. On a gzip/br/zstd SSE body, `readline()` blocks until it finds an LF byte or EOF, so a compressed stream is buffered whole before the first yield. `transport.passthrough` (`transport.py:23-25`) has no such problem. The circumstantial log evidence is stronger than the brief credits: OpenAI subscription rows show first chunk ≈ total (11348.0/11348.2, 29477.3/29477.6) while OpenRouter shows first chunk ≈ headers (3663.9 vs 3663.3). That pattern is exactly "subscription path buffers, OpenRouter path streams", and `SubscriptionProvider.prepare` (`providers.py:157`) forwards client headers unchanged — including whatever `Accept-Encoding` Codex sends — so upstream compression is permitted only on that path.

Refinements:
- Reject the non-SSE sub-claim as material. A whole-body `read()` at `:246` is unavoidable to parse `model`, and a partial JSON body is useless to the client. Bounding it is fine; it is not a latency win.
- The cheapest fix is not a decompressor. `transport.py:35` deliberately strips upstream `openai-model`, which implies upstream sends it. Prefer: (a) take `served_model` from the response header when present and use `passthrough` outright; (b) skip snooping entirely when `server.served_models` (`router.py:316-318`) already holds a mapping for the requested slug; (c) only then fall back to bounded body inspection, bypassing to `passthrough` whenever `Content-Encoding` is non-identity. That removes per-stream body inspection on the hot path rather than making it faster.
- Confirm with one captured subscription response header set (Content-Type + Content-Encoding) before building any decode path. The 16-byte fixture proves the mechanism, not that production is compressed.

## Finding 2 — conflated metrics: **ACCEPT (do first)**

`local_prepare_ms` (`router.py:239`) spans from `started` and therefore includes `rfile.read(size)` (`:249`) — i.e. client upload time — plus zstd decode, provider selection and prepare. `upstream_headers_ms` (`:303`) also spans from `started`, so it embeds prepare, DNS, TCP and TLS. `first_chunk_ms` (`:310-311`) is the first *adapted* chunk; for the subscription path that is the first snoop yield, which finding 1 says may be the whole body. No savings claim is verifiable without splitting these. Add: `upload_read_ms`, `connect_ms` (explicit `conn.connect()`), `upstream_ttfb_ms` (first raw read inside `adapt`/`passthrough`), and response `content_type`/`content_encoding`. All are additive log fields, no behaviour change.

## Finding 3 — connection reuse: **REJECT for the relay path (refine to gated experiment)**

Fresh connections at `router.py:261` and `providers.py:298`, closed in `finally`. But the arithmetic is unfavourable: a TLS 1.3 handshake to these hosts is tens of milliseconds against an OpenRouter headers median of 3663 ms — under ~3%, and invisible against 6142 ms total. The 3.46 ms object-construction figure measures nothing relevant, as the brief concedes. Against that, pooling in a threaded handler adds per-host locking, stale-socket detection, and the unacceptable failure mode the brief already names: a `CannotSendRequest`/reset on a reused socket must never be resolved by replaying a paid POST. Keep this rejected unless the `connect_ms` field from plan 1 shows connect+TLS exceeding ~10% of `upstream_headers_ms`. `summarize` (`providers.py:298`) is a plausible narrow exception (own connection, own retry semantics), but compaction is already off the interactive path.

## Finding 4 — late client-disconnect detection: **REFINE (defer, measure first)**

Correct as stated but mostly derivative. On a genuinely streaming response, the next `self.wfile.write`/`flush` (`:312-313`) raises within one chunk, so the exposure window is small; it is large only when the adapter buffers — i.e. the finding 1 bug. Fixing incremental forwarding shrinks this by itself. Also note `self.connection.settimeout(120)` (`:176`) governs the client socket only; a stalled upstream can hold an `inflight` slot for the full 120 s with no idle-read timeout, which is the bigger resource-retention issue in the same area. Drop the provider cancellation/billing claim entirely — unprovable from here. Immediate cheap step: in the `except` at `:319`, distinguish `BrokenPipeError`/`ConnectionResetError` and log `client_disconnected` so the frequency is known before adding `select()`-based abort logic (which risks aborting live requests on any readable-but-not-EOF client socket).

## Finding 5 — `discovered.remember` duplication: **ACCEPT (low severity, trivial fix)**

Confirmed: `discovered.py:125` extends with fresh `tool_search_output` schemas, then `:126` extends with `recall(items)`, which returns deepcopies of everything stored under replayed summaries. Chained compactions therefore accumulate one copy per turn, with a full deepcopy on store (`:131`) and another in `_write_disk`. The brief's token conclusion is right: `prepare_tools` dedupes via `declared.setdefault` (`tool_adapter.py:75, 78-88`), so the wire carries one definition. Fix: dedupe by `(namespace, name)` keeping first occurrence — fresh definitions are appended first, so first-wins preserves the newest schema — plus a cap on stored count/bytes. `tests/test_discovered.py` has no growth assertion; add one (N×`remember` of the same tool ⇒ stored length stable).

## Material omissions

1. **The adapting path shares the encoding bug and fails worse.** `stream_events` (`tool_adapter.py:284-290`) iterates lines identically; on a compressed body `json.loads` raises `ValueError`, caught at `router.py:319` *after* `sent = True`, so the client receives a 200 with a truncated stream and no error. Same for `ValueError('Incomplete upstream SSE event')` (`:296-297`). Here bypass is impossible — you must either pin `Accept-Encoding: identity` upstream on the adapting path or decompress. Any plan for finding 1 must state which.
2. **`served_model` is re-derived every subscription stream** to populate a map that is effectively constant per slug (`router.py:316-318`). Caching it is the highest value/lowest risk item in this audit.
3. **Minor, verify:** `int(self.headers.get('Content-Length','-1'))` (`:246`) raises `ValueError`, not `InvalidSize`, on a malformed header; the enclosing handler is not shown.

## Suggested plan order

1. **Phase + encoding instrumentation** (S, low risk) — unblocks 1, 3, 4.
2. **`remember` dedup + test** (XS, low risk) — independent, land now.
3. **Subscription identity fast path**: header-first, cached, encoding-aware bypass, bounded fallback (M, medium risk) — gated on plan 1 data.
4. **Encoding safety for `stream_events`** + error-after-headers behaviour (S–M, medium risk).
5. **Deferred**: disconnect logging now, `select()` abort later; connection reuse only if plan 1 justifies it (M, higher risk).
