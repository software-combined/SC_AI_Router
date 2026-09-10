# Router optimisation audit and Opus review adjudication

Planning only, 2026-09-10. Source: develop `83a5023`. No runtime fixes,
configuration changes or deployments are authorised by these plans.
The [review brief](2026-09-10-optimisation-review-brief.md) records the original
scope, measurements and worktree ownership. The [Opus review](2026-09-10-opus-optimisation-review.md)
records the independent report and delivery limitations.

## Evidence and limits

Opus request and returned response both identify `anthropic/claude-opus-5`
with reasoning `high`; the successful response status was `completed`.
The reviewer inspected selected source excerpts through a direct plaintext
OpenRouter API call after native subagent dispatch rejected encrypted briefs.
It did not inspect live logs or the complete backlog. The parent checked its
claims against full local source and existing plans before writing Plans 068-072.

Installed-release log snapshot: 0.6.10.25, start 2026-09-09T13:50:40.975Z,
snapshot ending around 14:23:23Z. Completed /responses requests only:

| Provider | n | Prepare median/p95 ms | Headers median/p95 ms | First chunk median/p95 ms | Total median/p95 ms |
|---|---:|---:|---:|---:|---:|
| OpenRouter | 515 | 19.1 / 57.9 | 3663.3 / 7169.7 | 3663.9 / 7170.0 | 6141.8 / 37578.2 |
| OpenAI subscription | 38 | 3.2 / 5.4 | 1564.8 / 2640.9 | 11348.0 / 29477.3 | 11348.2 / 29477.6 |

All rows report stream=true. These are not controlled direct-versus-router
comparisons, do not include failed requests, and do not isolate network/provider
latency. First adapted chunk is not first useful token. Current prepare timing
includes body upload/read and decompression. Different providers/models are
different workloads; do not compare their latency as a router-effect estimate.

The installed tool_adapter matches the audited source; router/providers have
the same relevant relay behavior before the recent transport extraction.
Synthetic offline checks reproduced compressed-SSE buffering and duplicate
cached schemas. Synthetic 100-tool preparation took median 0.73 ms at ~267 KB
and 2.1 ms at ~1 MB. These microbenchmarks exclude network and live contention.
65 focused tests passed during audit. Full unittest discovery subsequently
exited 0; existing socket ResourceWarnings were emitted. Compile and source-size
checks passed (93 checked, zero failures). No implementation tests were added.

## Adjudication

| Reviewer conclusion | Parent decision and reason | Owner |
|---|---|---|
| Add phase/encoding metrics first | Accept; use exact read-return semantics, not an unsupported claim of wire-level TTFB. Include failed requests and write-side classification. | 068 |
| Compressed SSE can buffer in identity snoop | Accept mechanism, retain unverified live cause. Compressed bytes can contain LF, so buffering is variable, not inevitably the whole response. | 069 |
| Header-first identity, then permanent served-model cache | Accept only validated per-response header as optional evidence. Reject cross-request identity caching: aliases/provider routing can change and /health records observations. Header stripping does not prove upstream supplies that header. | 069 |
| Whole JSON read is unavoidable | Refine: parsing needs complete JSON, forwarding does not. Bound optional observation; never withhold bytes merely to learn identity. No claim of faster usable JSON before completion. | 069 |
| Adapted streams need compression handling | Refine: CPython 3.14 HTTPConnection.putrequest already sends Accept-Encoding: identity when none supplied; OpenRouter constructs fresh headers. Preserve/test that existing contract. No general decoder for hypothetical upstream noncompliance. | 069 |
| Reject immediate connection pooling | Accept measurement gate; reject unmeasured handshake estimates and fixed claimed savings. Both normal inference and synchronous compaction can block user progress. | 071 |
| Measure before active cancellation | Accept. Correct review's missing-timeout claim: relay and summarizer already use HTTPSConnection(timeout=120). It is an operation timeout, not a total-turn deadline. | 072 |
| Classify BrokenPipe/ConnectionReset as client disconnect | Refine: only classify by the failing downstream write phase; upstream resets use the same exception classes. | 068/072 |
| Deduplicate remembered definitions; add arbitrary count/byte cap | Accept dedup; reject arbitrary eviction of required schemas. Preserve namespace identity and existing full-schema/stub precedence. | 070 |
| Malformed Content-Length omission | Not an optimisation finding; enclosing handler already maps ValueError. No new plan. | None |

## Execution and overlap

Start 068 for evidence, then 069 for streaming. 070 is independent and can be
implemented by a separate writer if authorised. 071 and 072 are bounded
investigations after 068/069; neither authorises production pooling/cancellation.
They may close with a measured no-go decision instead of runtime code.

Reuse existing Plan 060 content-safety rules and the integrated Plan 062
transport/protocol boundaries. Preserve Plan 045 drain behavior. Do not replay
those plans or widen this into Plan 066's separate encrypted-brief problem.
No new general cache, async rewrite, request cap, provider fallback or automatic
paid-POST replay is proposed. Release/live/billing acceptance remain separate.
