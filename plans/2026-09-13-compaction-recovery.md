# Compaction recovery: investigation and delivery plan 161

Owner: task `01a09791-cf38-7222-bfdf-42fc1b15264a`; base `779c2972ac9a0196bf36cffbb7a0e56573490d19`.
Target: `develop`, router 0.6.43 beta. The user authorized investigation,
implementation, commit, merge, beta tag, forced owner-Mac update, then a new
task continuing **Full plan path**. This is a source-stage record; publication,
installation and live acceptance are verified separately after integration.
PR #107 landed during review at `c068368e3f7ed4e6d70aa381c063996af4a857e8`.
Both fixes were preserved; the combined offline probe passed all nine legs.

## Verified cause

Task `01a08bbd-7a0a-7d42-834d-190cda2bb16f` stopped on 2026-09-12
at 19:21:50 UTC (13 September 05:21:50 Sydney). Its 950,351-token scope
exceeded the 943,718 compaction threshold. The first summary hit the router's
4,000-token output cap; the router returned 409 at 19:21:33. Subsequent
summaries succeeded (6,204 and 7,901 characters), but the router returned
HTTP 200 JSON at 19:21:40 and 19:21:49. Codex V2 expected an SSE compaction
item and `response.completed`, so retries ended with
`stream closed before response.completed`. The 409 is the router's response,
not evidence of the upstream summarizer's HTTP status.

Evidence: thread-scoped `~/.codex/logs_2.sqlite`, the original task rollout,
and `~/.codex/mixed-model-router/logs/router.jsonl` lines 2739-2742.
No transcripts, credentials or token-bearing URLs are copied into this report.
Official Codex source matched bundled CLI 0.154.0-alpha.6.2 at tag
`rust-v0.154.0-alpha.6.2`, commit `b5bffd3ec4db487e7e3dec59663875b0ef7b72ca`:
`compact_remote_v2_attempt.rs:70-85`, `compact_remote_v2.rs:371-571`, and
`codex-api/src/sse/responses.rs:357-363,483-506,596-600` under `codex-rs/`.
The annotated tag object `a1bc283c...` is distinct from that commit.

## Reviewed implementation plan

1. Emit one compaction item and terminal completion for streaming V2;
   preserve V1/non-streaming JSON and subscription forwarding. Serialize
   before headers and contain disconnected writes so no second reply starts.
2. Retry only HTTP 200 structured output-limit truncation, once at 8,000
   output tokens after the initial 4,000, clamped to the model ceiling.
   Keep the same model/history and lowest supported effort; share the
   120-second deadline. Reject empty, malformed, failed and nonterminal
   results; never remember partial output. Log attempt/budget/outcome only.
3. Extract summary validation into a pure leaf to respect the existing
   400-line module limit, include it in deployment files, and add regressions.
   Exercise both protocol modes in the offline real-client probe: threshold,
   explicit context-error recovery, plus V2 truncation followed by success.
4. Run full tests, compilation, source/policy checks and the required
   simplifier, secret scan and three independent reviews. Commit and PR to
   `develop`; verify CI/integration before tagging `v0.6.43-beta`.
5. Verify tag workflow/feed/manifest, run the installed updater, read back
   manifest commit and healthy running version, and run the probe from the
   installed release directory. Then perform one capped live compaction with
   synthetic surrounding turns and verify the summary marker on resumption.
   Only then create the requested continuation task; preserve the original.

## Verification and practical limits

The original V2-disabled probe passed despite the bug. Enabling V2 without
source edits reproduced the exact failure; a two-event wire substitution
made threshold and context-error scenarios pass. The corrected probe passed
all five V1/V2 scenarios against the bundled binary, including two summary
attempts only for truncation. Compatibility baseline details are in
`docs/compatibility.md`; source/probe proof is not deployed acceptance.

The existing summary captures the newest 24,000 characters; Codex separately
retains bounded user/developer/system context. This fix does not promise
lossless older tool history. Across three possible client requests, the
router permits at most six summary attempts and 36,000 requested output
tokens, not a billing or account-wide cap. No model/policy/key changes occur.
Rollback uses the prior installed 0.6.40.56 bundle, which retains this defect.
Stop on failed required checks or unverifiable deployment identity/target;
retain work and report that exact gate. Clean the task worktree only after
verified integration and preservation of all deliverables.
