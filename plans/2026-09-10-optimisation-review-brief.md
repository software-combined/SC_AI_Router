# Router optimisation audit: independent review brief

User requests an Opus 5 review at high reasoning, then implementation plans.
This is review/planning only; no runtime changes, installs, deployments,
client mutations or inference probes. The parent owns all writes.

Repository: `/Users/cyrilallart/Documents/Github/SC_Codex_openRouter_adapter`.
Frozen source: `83a5023195336297c58e9f3ddacd0d48e0171b05` on develop.
Planning worktree: `/Users/cyrilallart/Documents/Github/.worktrees/router-optimisation-plans-20260910`.
Branch: `codex/router-optimisation-plans-20260910`; owner: task
`01a0868b-1747-7d81-819c-131d933ecf81`, parent agent `/root`; target: develop.

Reviewer: read this complete brief first, acknowledge its exact assignment,
then review source read-only. Do not write files, alter Git, access credentials
or private logs, make network requests, or recursively delegate.
Read `/Users/cyrilallart/.codex/skills/improve/references/audit-playbook.md`,
sections Performance, Correctness / Bugs, Test Coverage and Finding format.

Audit findings to challenge, not assume correct:

1. `tool_adapter.snoop_response_identity` iterates raw upstream responses by
   newline for SSE without handling Content-Encoding. An offline gzip SSE
   fixture (1,844 plain bytes, 101 compressed bytes with no LF), delivered in
   16-byte pieces through BufferedReader, consumed all 101 bytes before the
   inspector's first yield; `transport.passthrough` yielded after 16 bytes.
   Non-SSE identity inspection also uses a whole-body read. Prefer incremental
   byte forwarding, bounded supported inspection and an encoding-aware bypass.
2. Handler metrics combine upload/decompression/preparation, connection setup,
   upstream wait and adaptation. First chunk is not first useful text/tool.
   Add content-safe phase/encoding measurements before claiming savings.
3. Every relay and compaction creates/closes a fresh HTTPSConnection. Small
   bounded reuse might avoid TCP/TLS setup on sequential tool turns, but benefit
   and safe reuse contracts are not measured. Do not blindly replay paid POSTs.
4. While blocked waiting for upstream data, client disconnect is not detected
   until a later downstream write. Earlier cancellation could release resources;
   provider cancellation/billing effectiveness is unproven.
5. discovered.remember concatenates fresh definitions and recalled definitions
   without deduplication. With disk writes mocked, 20 compactions each
   rediscovering the same tool stored 20 definitions. prepare_tools emits one
   final wire definition, so this is cache/copy waste, not multiplied tool tokens.

Read-only timing evidence gathered by the parent from existing installed logs:
release 0.6.10.25, last start 2026-09-09T13:50:40.975Z; snapshot ended around
2026-09-09T14:23:23Z. 515 completed OpenRouter /responses requests: local_prepare
median/p95 19.1/57.9 ms; headers 3663.3/7169.7 ms; first chunk
3663.9/7170.0 ms; total 6141.8/37578.2 ms. 38 OpenAI subscription responses:
local_prepare 3.2/5.4 ms; headers 1564.8/2640.9 ms; first chunk
11348.0/29477.3 ms; total 11348.2/29477.6 ms. All these rows say stream=true.
OpenAI first-chunk/total proximity is a lead, not proof of compressed SSE.
Logs do not record response encoding/type or true upstream-first-byte time.
No direct-versus-router benchmark was run; successful-request sample only.

Installed 0.6.10.25 tool_adapter.py matches develop; router/providers differ
primarily by the recent protocol/transport extraction. No installed edits.
Synthetic provider.prepare with 100 namespaced tools: ~267 KB median 0.73 ms,
~1 MB median 2.1 ms across 30 runs. Fake key, no network. New HTTPSConnection
object construction without connect: median 3.46 ms; not handshake timing.
65 existing focused tests passed: tests.test_tool_adapter, test_discovered,
test_context_budget and test_providers. No code changes from this audit.

Read relevant source yourself, and inspect existing plans/README.md for overlap.
Return: accept/reject/refine per finding; any high-confidence material omitted
issue; sensible plan grouping/order; exact file/line evidence; effort/risk.
Scope is latency and resource efficiency, not a general architecture rewrite.
Stop after one bounded pass. Report requested/served identity honestly;
do not infer your identity from the task wording.
