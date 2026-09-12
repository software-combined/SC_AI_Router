# Plan 066 implementation record

Owner: Cyril; executor: this task `/root`. Worktree:
`/Users/cyrilallart/Documents/Github/.worktrees/router-optimisation-plans-20260910`,
branch `codex/router-optimisation-plans-20260910`, target `develop`.
Reconciled from `83a5023` to `ca8ac8d`; the earlier staged optimisation plans
remain intact. A temporary owned Git stash retains their pre-reconcile copy
until final reconciliation. No other worktree is adopted.

## Agent 57 change analysis

- Goal: deliver complete mixed-provider assignments while preserving native
  encrypted collaboration. Reuse Codex execution, approval, sandbox, child
  limits and message delivery; the router only adapts representation.
- Trigger/systems: existing Responses requests and collaboration calls;
  ChatGPT subscription and OpenRouter retain separate credentials and hosts.
- Context: canonical runtime source is this repository. Client contract is
  Codex `0.153.4`, upstream `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`.
  Probe inputs are synthetic; no workspace/user documents enter probes.
- Contract: copy only already-exposed spawn/message/follow-up tools; retain
  their schemas and results. Explicit plaintext aliases restore native names
  and `encrypted_function_args: []`. Ciphertext is never relabeled or logged.
- Risk tier: T4 host compatibility; no new execution authority. Applicable
  capabilities: untrusted input, runtime tools, existing broad autonomy.
  Native Codex remains the deterministic executor and limit/permission owner.
- Probe budget: at most 24 live requests per invocation
  (--max-live-calls 1..24), 120 seconds per network operation and 600
  seconds total; cap zero permits no live calls.
  Scripted probes never contact providers. No deployment in this stage.
- Replay: retain native call IDs and names, no extra executor, automatic tool
  retry, registry or provenance store. Verify follow-up and resumed history.
- Error path: content-free protocol failure on opaque input, unknown aliases
  or incompatible encoding; the client receives the failure, never a guessed
  assignment. Existing failed opaque children require a fresh assignment.
- Tool contract: aliases share the native tool purpose, parameters, outputs,
  side effects, identity, permissions, timeouts and call limits. Allowed only
  when that native tool was already offered in the current request. No new
  shell/file/network tools or client SDK dependency. There is no Codex-specific
  Agent 57 adapter; repository and versioned client contracts own this binding.
- N/A: new write approval, idempotency store, leases and rollback ledger because
  no new acting tool or writer is introduced; reevaluate if the router starts
  executing tools or managing children. No new model or data-retrieval agent;
  reevaluate caps/context policy if the router begins invoking such agents.
- Coexistence is owner-selected: encrypted originals plus plaintext aliases.
  Reevaluate aliases when Codex supports recipient-aware native negotiation.
- Rollback: withdraw this source release; no client/catalogue migration or
  persistent alias state. Deployment requires its own verified target gate.

## Evidence

- Evidence correction, 2026-09-12: the Astra parent in these probes was
  constructed from the external-model template and therefore had
  `use_responses_lite: false`. The successes below cover classic Responses;
  they do not establish native desktop Lite delivery. The current follow-up
  adds Lite declarations and requires the installed subscription row in live
  probes. See `2026-09-12-responses-lite-agent-handoffs.md`.

- Isolated scripted probe: exit 0. All three plaintext markers delivered,
  alias emitted, canonical replay true, no errors.
- Astra v2 parent with scripted children (installed router, Codex 0.153.4,
  2026-09-10, 11 parent calls, low effort): exit 0. All three plaintext
  markers reached the Muse child as input_text-only blocks; the native
  gpt-5.6-sol child kept input_text plus encrypted_content; alias emitted;
  canonical replay true; no probe errors. One expected WebSocket 404
  fallback in tool_failures.
- Luna v1 parent with scripted children (same setup, 12-13 parent calls):
  exit 1 without the steer, fail-closed as designed. Luna used the alias
  for early turns then emitted a native encrypted followup/send_message;
  downstream child turns carried encrypted_content and were rejected.
  Real native shapes observed: task_name is bare ('synth_agent') while
  targets are author-prefixed paths ('/root/synth_agent'); history echoes
  restored alias calls with encrypted_function_args [] but native encrypted
  calls omit the field.
- Luna v1 fix (this worktree): adapt-time steer replaces a provably
  undeliverable encrypted handoff with a targeted error output naming the
  exact alias call. Fires for encrypted spawns naming an OpenRouter model
  and encrypted followup/send_message to a child whose spawn names an
  OpenRouter model (exact task match, else unique path suffix; ambiguous
  suffixes pass through to the downstream guards). Final Luna lifecycle
  through candidate code (2026-09-10, 15 live calls, low effort): exit 0.
  All three markers delivered to and returned by the real Muse child;
  native control intact; one steer fired and Luna complied with the alias;
  alias emitted; canonical replay true; no errors.
- Focused suites: 36 tests pass (agent handoffs, handoff providers,
  containment). Full suite: 645 tests pass (2026-09-10, final source).
- Final-source Astra lifecycle through candidate code (2026-09-10, 20 live
  calls, low effort): exit 0. All three markers delivered to and returned
  by the real Muse child; native child kept encrypted content and returned
  its control marker; alias emitted; canonical replay true; router restart,
  resume, compaction and two recall turns all true; no errors. One expected
  WebSocket 404 fallback in tool_failures.
- Reverse-provider run, GLM 5.3 Flash parent with live children through
  candidate code (2026-09-10, 22 live calls): exit 1, fail-closed as
  designed. The first two markers reached the Muse child as plaintext and
  were returned; the third turn re-encrypted, so later child turns carried
  encrypted_content and were rejected (6 opaque-content rejections).
  Same parent-choice pattern as Luna v1, on a different provider. OpenRouter
  parents need their own plan if pursued; Plan 066 covers the Astra v2
  parent route.
- No deployment or installed-router change.
