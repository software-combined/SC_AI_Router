# Recover rejected mixed-provider handoffs

Owner: Cyril; task `01a095c4-8abc-7493-be22-eca32cc74e0f`, agent `/root`.
Authorized: plan, implement, test, commit, merge, beta tag and local deployment.
Worktree: `/Users/cyrilallart/Documents/Github/.worktrees/router-handoff-recovery-20260912`.
Branch: `cyril/handoff-recovery-20260912`; base `51ad33e`; target `develop`.
The Actions cleanup worktree belongs to another task and is not modified here.

## Outcome and cause

An encrypted handoff to an external child must be rejected before delivery,
return a real tool error to its parent, and allow a corrected plaintext call
and parent final within the same Codex turn. Cover spawn, follow-up and send.
Native encrypted handoffs and valid plaintext calls must remain unchanged.

Two real tasks ended silently after the router replaced a `function_call`
with a `function_call_output` in the upstream response stream. The change
originated in `b756a64` and remains in installed `0.6.37.54` (`6d9c5ab`).
Codex 0.153.4 records such outputs as unexpected without `needs_follow_up`.
Pinned client source: `rust-v0.153.4`,
`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`,
`core/src/stream_events_utils.rs` and `core/src/tools/handlers/mod.rs`.
The installed cost-first tool guide also omits the external plaintext route.

## Thin implementation and verification sequence

1. Add an isolated scripted-upstream probe using the installed Codex binary.
   Reject each of the three native handoff calls, require Codex to return a
   matching validation error, then emit the correct plaintext alias. Prove
   the current router fails this sequence without another user turn.
2. Replace only the existing rejection envelope in `agent_handoffs.py`.
   Preserve the native function name and call/item identities; replace
   unreadable arguments with a JSON string containing a bounded diagnostic.
   All three native handlers deserialize an object before any side effect,
   so a scalar is a deterministic, recoverable argument-validation failure.
   Codex generates the tool result and schedules the next inference itself.
   No opaque argument is decrypted, forwarded, logged or relabelled as text.
   No new tool, tool authority, router retry loop or provider call is added.
3. Add offline regressions for executable rejection shape, IDs, bounded safe
   diagnostics, classic/Lite and JSON/fragmented SSE paths. Exercise native
   encrypted and valid plaintext controls, unknown targets and replay. Run
   the real-client probe in both wire modes and a bounded live candidate
   handoff lifecycle with the installed native model metadata.
4. Correct and release the canonical SC_Agent_plugins tool guide separately:
   plaintext external spawn/send/follow-up, no inherited encrypted history,
   native encrypted messaging retained, and no repeated rejected handoffs.
   Preserve reviewer models, efforts, gates and installed hook/scanner pins.
5. Reconcile the current release workflow with protected admin-created tags.
   Use the selected tag for both bundle URLs and GitHub Release creation;
   never rely on a workflow-created secondary tag. Coordinate with the
   existing Actions cleanup instead of modifying its owned worktree.
6. Select the next unused patch version, update all version mirrors and
   changelog, run repo checks, simplification and three independent review
   lanes, commit, PR to develop, verify merge and clean up owned worktrees.
7. Verify identity/target, tag the verified develop merge as beta, wait for
   successful release and feed readback, install through the normal updater,
   read back served version and artifact identity, and repeat installed
   handoff acceptance. Keep source, release, deployment and acceptance distinct.

## Agent 57 applicability and bounds

This is a deterministic transport repair, not a new agent or delegation
authority. Existing Codex owns tools, execution, permissions, turn limits,
child concurrency and cancellation. Relevant capabilities are untrusted
input and runtime-tool error handling; the existing agent's worst-case T4
authority is not widened. The router adds zero paid calls and zero tool
effects. Probe agents have only the existing collaboration tool allowlist,
synthetic marker input/output, read-only sandbox, no shell/apps/network tools,
at most 24 live calls and a 600-second deadline; offline probes make zero
paid calls and use a 40-second deadline. Failed required evidence stops release.

Harmful replay is controlled by preserving valid calls and IDs, rejecting
before dispatch and avoiding router-level retries. Persistent idempotency,
new kill switches, write approvals and compensation are N/A for this pure
projection; revisit if the router gains execution or retry authority.
Credentials remain in existing deterministic provider boundaries. Logs and
probe output retain structural facts and synthetic markers only. No new
platform adapter is needed: native Codex contracts are verified in source and
through its installed executor. Local deployment rolls back using the existing
versioned installer lifecycle if installed acceptance fails.

## Evidence

Recorded 2026-09-12 before review:

- Unit regressions: the handoff suite (40 tests) passes, including the new
  `tests/test_handoff_recovery.py` pins for executable identity, bounded
  argument-free diagnostics, the native/plaintext controls and classic plus
  Responses Lite partial-SSE framing.
- Offline real-client probe `tools/probe_handoff_recovery.py` passes in both
  wire modes: Codex returns the argument-validation error for each native
  handoff, the parent corrects spawn, follow-up and send through
  `collaboration_plaintext`, and finishes with the required marker inside the
  same turn (`recovered_tools` all three, zero errors).
- Release workflow: the tag-integrity change (pushed tag for bundle URLs and
  `gh release create --verify-tag`) is staged here because the shared
  protected-tag ruleset admits no workflow-created secondary tag. The broader
  Actions hardening stays with the dedicated cleanup task and its worktree.
- Root cause reproduced in the live parent thread (rollout
  `01a0952f-...`, 2026-09-12): three old-envelope steers
  (`That handoff cannot be delivered readably ...`, all `send_message` to the
  externally billed `scheduler_simplifier` child) were each recorded as a
  `function_call_output` with no matching call and were followed immediately
  by `task_complete`, ending the turn silently until the user nudged it.
  The staged envelope keeps the call alive instead.

Steps 1-3 are complete; step 4 (plugin tool guide) and the remaining Actions
hardening stay with their owning tasks. Steps 6-7 continue in this worktree.

