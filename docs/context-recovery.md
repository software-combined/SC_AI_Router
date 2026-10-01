# Context-reset brief recovery

## Root cause and evidence

The 2026-09-13 investigation of task `01a08bbd-7a0a-7d42-834d-190cda2bb16f`
found that the statements "The subagent message channel is dropping briefs"
and "The subagent spawn channel is unreliable here" misdiagnosed a later
context reset as a delivery failure.

The correctness, quality and adversarial children received user-role briefs,
acknowledged them and inspected the specified staged tree. They subsequently
called `new_context` with empty arguments. The saved `compacted` records had
an empty summary and replacement histories containing only initial setup:
no assignment or review progress. They then asked what to work on. The parent
retried delivery with `send_input` and later created separate tasks, incurring
duplicate work without addressing the reset.

Concrete reset timestamps (UTC on 2026-09-12): correctness 14:42:50,
adversarial 14:43:18, quality 14:47:46. The later `create_thread` claim was at
14:56:15, following those same failed reviews. Private briefs and transcripts
are not copied into this repository.

Verified client source: `openai/codex` tag `rust-v0.153.4`,
`codex-rs/core/src/session/mod.rs::start_new_context_window` rebuilds initial
context and stores `message: String::new()`. Its `new_context_window` tool
explicitly says it does not summarize history. The shipped router prompt
incorrectly described all context transitions as automatic compaction with
a summary. Existing client guidance required history recovery, but the
children did not perform it before ending their turns.

During this work the owner upgraded to desktop `26.908.40834` (build 8881),
bundled CLI `0.154.0-alpha.6.2`. Matching source tag
`rust-v0.154.0-alpha.6.2` (`a1bc283c327568149d7a29d5fbd304cc471a981a`)
retains the same unsummarized reset behavior. The current model defaults can
disable token-budget rollover; explicitly enabled and existing sessions still
need the recovery path. The separate PATH CLI is `0.153.1` and is not the
desktop acceptance target.

The earlier handoff fixes remain distinct: readable handoff schemas handle
external brief delivery, and 0.6.38 makes invalid encrypted handoffs recover within the
parent turn. Neither addresses a child forgetting an already-delivered brief.
An accepted spawn or brief acknowledgement does not prove task completion.

The two later standalone review tasks (`01a0961e-8680-7623-819b-95fed605eb99`
and `01a0961e-8fe8-7033-ba36-30701d1ef060`) stopped for a different reason.
Both were still reviewing after their resets. At 15:12:14 UTC the parent
explicitly called `close_agent` for each, immediately followed by their
`turn_aborted` events with reason `interrupted`. The preceding user message
requested non-GPT review models, and the parent announced replacement with
GLM/DeepSeek. These stops were deliberate cancellation, not lost delivery or
an app-upgrade crash. The recovery guidance must respect that cancellation.

## Fix plan and ownership

1. Correct the canonical shipped instructions to distinguish summarized
   compaction from unsummarized rollover, require a checkpoint before an
   explicit reset, and require assignment/progress recovery afterwards.
   Catalogue upgrades migrate only the exact legacy router paragraph in
   retained subscription templates, preserving custom/native instructions and
   model-specific metadata. Without this migration, existing installations
   would retain the misleading pre-reset paragraph despite a newer bundle.
2. Add a pure request projection at the shared Responses-provider boundary.
   Only a developer-role `context_window` block with a valid previous-window
   UUID triggers the fixed recovery note. No user/tool text can trigger it,
   and no assignment text is copied into developer instructions. Both native
   and external routes receive it; ordinary requests and native service or
   compaction requests keep their existing behavior and credential boundaries.
3. Cover real client behavior: deliver a synthetic assignment, execute the
   actual `new_context` tool, assert the assignment is absent, retrieve it via
   a local read-only history tool, and require its exact answer in the same
   turn. Scripted mode proves wiring; live mode proves the selected model
   follows recovery guidance, with at most six provider calls per invocation.
4. Run repository tests/static gates, the simplification and three independent
   review lanes, commit, integrate into `develop`, and publish `v0.6.40-beta`.
   Re-read the beta feed and released manifest. Run the post-upgrade Codex and
   Claude Code compatibility legs before publication.

Worktree owner: task `01a09617-e3b4-70b1-b979-8e76dbdae437`, branch
`cyril/context-recovery-20260913`, initially based on `e226a755`, updated to
`origin/develop` at `f596209` before final review. The intervening 0.6.39
release-authority changes are preserved.
Other tasks' active worktrees and agents are outside this fix's write scope.

## Acceptance and limits

Run `python3.14 tools/probe_context_recovery.py` for the native scripted leg;
add `--model deepseek/deepseek-v4.1-flash` for external serialization. Live
acceptance adds `--live --max-live-calls 4`. The probe starts a disposable
client and loopback candidate router, carries only synthetic task data, and
removes its temporary history/auth copy on exit. Its history tool serves only
the synthetic task's matching previous window. It never reads another task.

`tests/test_context_recovery.py` failed against the pre-fix provider paths and
passes with the fix. It protects both routes, compressed native requests,
credential isolation, no-op paths, untrusted lookalikes and idempotence.

This is a router-side recovery instruction fix, not a change to Codex's
storage algorithm or a guarantee that every model always follows instructions.
Actual history remains owned by Codex. An inaccessible checkpoint/history is
reported as a recovery blocker; the router does not fabricate the assignment,
create replacement top-level tasks, or keep a transcript cache. A genuine
empty initial handoff is a separate failure and is not masked by this note.
