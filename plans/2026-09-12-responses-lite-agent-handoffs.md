# Repair Responses Lite mixed-provider agent handoffs

Implementation authorized 2026-09-12: "fix it all, commit, merge, clean up".
The scope includes this fix, the pending history fix, bounded candidate
acceptance, reviewed integration into develop and owned-worktree cleanup.
Deployment remains a separate decision; the review exception is recorded below.
Priority P1; effort M; risk MED (tool and encryption contracts).

## Ownership and preserved work

Owning task: `01a0952e-baf3-7863-b6d8-cf0ba3ae927d`, `/root`.
Worktree: `/Users/cyrilallart/Documents/Github/.worktrees/router-cross-provider-history-fix`.
Branch: `cyril/cross-provider-history-fix`; integration target: `develop`.
Base at investigation: `c177f17097d984be29d5089da5d8881c89843a3a`.
Reuse this worktree for an authorized follow-up; do not edit the primary checkout.

The separate 0.6.37 history-normalization/HTTP-400 fix is preserved in the
index, tree `2119c392ef106a4e886349289356729cfb885b85`. Its full suite passed
1,242 tests; compile and source-limit checks passed. Synthetic and bounded
live history-switch acceptance are recorded in `docs/compatibility.md`.
Its required simplification review failed before inspection on both direct
and file-brief dispatch; the other three lanes have not run. No approval,
commit, merge, deployment, or worktree cleanup has occurred. This planning
file is initially unstaged and does not change that index tree.

## Confirmed cause

The earlier fixes exist: `478f9ed` introduced plaintext collaboration aliases
and `b756a64` added parent-side steering for encrypted external handoffs.
The running router reports `0.6.36.53`; its `agent_handoffs.py` is byte-for-byte
the same as the primary checkout (SHA-256
`46e2f04ccd6bcafe7a487d5e9e0dfa0c66d9cfa67d262ddd784ca52c098b0bfd`).
This is a missing request-format branch in that fix, not evidence of a
missing deployment of those commits.

1. The installed Astra catalogue row has `use_responses_lite: true`.
   Codex CLI 0.153.4 puts its tool definitions in a developer-role
   `input` item of type `additional_tools`, and omits top-level `tools`.
2. `agent_handoffs.add_plaintext_tools` only reads `payload['tools']`.
   It therefore discovers no collaboration tools in this request format,
   advertises no `collaboration_plaintext` aliases, and returns an empty set.
3. `SubscriptionProvider.adapt` only invokes the handoff response adapter
   when that set is nonempty. Both alias restoration and encrypted-spawn
   steering are bypassed. The original encrypted native spawn executes.
4. On both failed review spawns (10:58:39 and 11:00:29 UTC), the saved call
   selected DeepSeek/max with `fork_turns: none`, omitted
   `encrypted_function_args`, and carried an opaque message. Codex's native
   executor treats only an explicit empty encryption-field list as a
   plaintext collaboration message. A file path inside the same encrypted
   argument cannot repair that transport.
5. The external-provider guard correctly rejects the unreadable assignment
   before credential lookup or upstream dispatch. Removing this guard would
   let the child act without receiving its actual assignment and constraints.

Earlier successful `create_thread` / `send_message_to_thread` delivery
(`a300989`, tool-pair follow-up and 0.6.27 acceptance) addresses standalone
`function_call_output` items. It is a different path from native
`collaboration.spawn_agent` and does not cover this failure.

## Evidence and acceptance gap

Installed clients: ChatGPT.app `26.903.71938` (build `8576`), bundled
`codex-cli 0.153.4`. Upstream repository identity rechecked with
`gh repo view openai/codex`; local source is pinned to
`rust-v0.153.4`, commit `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`.
Relevant primary-source contracts at that revision:

- `codex-rs/core/src/client.rs:929-977`: Lite inserts an `AdditionalTools`
  prefix, hashes its tool payload into the item ID, and sends no top-level tools.
- `codex-rs/protocol/src/models.rs:976-986`: `additional_tools` item shape.
- `codex-rs/core/src/tools/router.rs:44-62`: explicit
  `encrypted_function_args: []` selects `DirectPlaintextMessage`.
- `codex-rs/tools/src/tool_spec.rs:95-137`: Lite namespace serialization.

A synthetic capture used the installed binary, a temporary copy of its
actual Astra row, a loopback stub, and no live credentials or model calls.
It produced exactly:

```
use_responses_lite: true
top_level_tools: 0
additional_tools_items: 1
collaboration_namespaces: 1
collaboration_tools: followup_task, interrupt_agent, list_agents,
                     send_message, spawn_agent, wait_agent
router_plaintext_aliases: []
paid_calls: 0
```

An installed-router preparation control with identical synthetic collaboration
schemas advertises the spawn alias for classic top-level tools, but none for
Lite nested tools. The latter also leaves request bytes unchanged and disables
handoff response adaptation. No private task text or ciphertext was recorded.

The old probe builds `parent` from the external `child` template, copying
only the native model slug and live `multi_agent_version`. That template
sets `use_responses_lite: false`. Thus its Astra lifecycle evidence proves
classic Responses delivery, not the installed desktop's Lite path. The
`tool_definitions: 0` metric also counts only top-level tools and is not proof
that the real request contained no tools.

## Implementation plan

1. Extend the existing pure alias helper in `ai_router/agent_handoffs.py`
   to discover the native collaboration namespace in either classic
   top-level `tools` or a client-shaped developer `additional_tools` item.
   Reuse the same alias builder and response restoration/steering code.
   Keep aliases in the same declaration container as their native tools;
   never lift Lite tools into top-level tools or change model metadata.
   Only copy the three already-authorized handoff functions. Ignore ordinary
   text, user messages and tool results that happen to contain schema-like data.
   Reject malformed collaboration schemas, conflicting alias names, or
   duplicate/ambiguous native declarations safely before upstream dispatch.

2. Preserve every original tool schema, authority, input order and native
   encrypted handoff. Add only the existing plaintext aliases. Preserve the
   existing external-recipient steering rules and history-based child lookup.
   For a modified Lite prefix, derive a deterministic `at_` ID from the
   original identity and canonical modified tools so different visible
   payloads do not reuse a content-derived native ID. Confirm that ID format
   with the pinned client contract and live synthetic acceptance; retries
   and resumed turns must produce the same adapted ID. Do not mutate saved
   client history or decrypt, drop or relabel opaque assignments.

3. Verify that `SubscriptionProvider.prepare/adapt` receives a nonempty
   `AliasTools` result for both formats and activates the existing JSON/SSE
   restoration and steering. Re-encode only when adaptation changes the
   request; remove stale compression headers. Reuse the pending history-fix
   byte-preservation logic. Cover streamed requests even when the upstream
   Content-Type is not labelled SSE, as the existing stream flag permits.
   Do not widen changes into native service endpoints or compaction tooling.

4. Correct `tools/probe_agent_handoffs.py`: use the actual subscription
   catalogue row for live native parents and controls, instead of constructing
   them from an external row. Keep classic and Lite as explicit offline test
   variants. Report wire mode, declaration location and alias counts, with
   no payload text. Assert that the requested mode was actually exercised;
   missing native metadata in live acceptance must fail rather than silently
   selecting the external template. Keep scratch client state isolated.

5. Add focused regressions to the existing handoff helper/provider suites:
   classic versus Lite, no native authority, malformed/duplicate declarations,
   collision rejection, deterministic IDs, unchanged native schemas, byte
   preservation, zstd re-encoding, and exact call IDs/arguments through JSON
   and streamed alias restoration. Prove encrypted external spawns are
   steered on Lite, plaintext initial/follow-up/send reach the child, and
   OpenAI-to-OpenAI encrypted calls remain intact. A scripted installed-client
   test must discover aliases from the actual prepared request rather than
   inventing an alias the router did not advertise.

6. Perform bounded candidate acceptance only after implementation and paid
   probe authorization: actual Astra Lite parent -> DeepSeek/max fresh child,
   unique initial marker, `followup_task` marker, `send_message` marker, and
   native OpenAI encrypted control. Verify received/returned markers and
   actual required file reads, then restart/resume and canonical replay.
   Use an explicit call cap; no real conversation replay. Run the final
   three-lane review only after the simplification pass works on the final tree.

7. Record the corrected evidence scope in the earlier implementation record
   and `docs/compatibility.md`; update the changelog and select the next free
   patch version from current `develop`, keeping all version metadata aligned.
   Run the required unittest, compile, source-limit, lint/policy and shared
   pre-commit gates. Keep modules within their hard limits; add a small
   request-normalization leaf only if the existing helper cannot stay bounded.

## Review bootstrap and delivery

The current installed Lite path cannot run the default DeepSeek review.
The owner approved a one-time GPT-6 Astra/max exception for the four required
passes on this combined commit. This changes neither runtime routing nor
standing review policy. No unreviewed source is deployed to bootstrap review.

After verified review, commit and merge into `develop` under the existing
authorization. Publishing/deploying the fix is a separate action. After an
authorized deployment, read back the active version and repeat real desktop
Astra -> DeepSeek review delivery. Failed children with opaque saved input
need fresh children; this plan contains no history migration. Clean up only
the owned branch/worktree after verified integration.

Success means the installed desktop's actual Lite route delivers all three
assignments exactly, native encrypted control still works, opaque external
input remains blocked, and the required reviewer performs its assigned
inspection. A passed classic probe, accepted spawn, file-name acknowledgement,
or different-model review is not that evidence.

## Candidate implementation evidence

The existing helper now handles both declaration locations and preserves
the native schemas. Six new Lite regressions plus existing handoff suites
pass (34 focused tests). Installed-client offline classic and Lite probes
both pass with all markers, native encrypted control, and canonical replay.
The history switch/validation probe remains a separate verification gate.

The corrected live candidate lifecycle passed in 20 calls (cap 24) with
the installed Astra Lite row and DeepSeek/max child. Initial/follow-up/send
markers all arrived and were returned; native Sol control retained encrypted
input and returned its marker. Router restart, resume, compaction and two
subsequent recalls passed. One expected initial WebSocket 404 fallback was
recorded; there were no probe errors. The installed router was not changed.

The combined commit is intentionally coherent even if it exceeds the
default staged-line budget: both diagnosed failures cross the same provider
preparation boundary and share versioning, installed-client regression
probes and compatibility evidence. Most added lines are deterministic
regressions, probe scenarios and the requested investigation/repair record;
splitting would duplicate the blocked review/bootstrap and acceptance work.
All runtime modules remain below the 400-line hard cap. Existing soft-limit
owners remain in place (handoff helper 307, probe 492), recorded in the
source-size baseline rather than creating a second handoff implementation.

Final pre-review readback: fast-forwarded without conflict onto `ed55ced`
after develop gained loopback Host-header validation. Full offline suite:
1,252 tests passed. Compile, lint F401/F811, source limits (198 files, zero
failures), policy scans, offline model check and diff checks passed. Both
wire-mode handoff probes and the history-switch/400/transient-retry probe
passed again on that base. The two initial edge-case test failures were
fixed before review: non-list input retains its prior handling, and malformed
top-level tools retain the prior internal-error contract.

Review bootstrap: the owner explicitly approved GPT-6 Astra at max for all
four required passes for this combined commit. This is a one-time review
exception, not a change to installed model policy. The candidate changes are
staged; the required review will run before a receipt or commit is recorded.

Pass 1 (simplification) completed as a no-op on tree
`5a72e061ad647e86852fe532bc6407498921c557`: ponytail and the simplifier skill
read in full, all 28 complete staged-index files and 17 required context files
inspected. No edits or concrete bugs were reported. Requested identity was
`gpt-6-astra@max`; served model/effort were not echoed and remain `unverified`.
Diff checks passed. Subsequent pre-lane edits only correct historical review
status prose and record this result; runtime and test scope are unchanged.

Passes 2-4 (correctness, quality, adversarial) each returned ALL_CLEAR on
staged tree `734354e93396fb38d541a8576cae5167a2a35722`. Each confirmed
ponytail-first, full staged diff, all 28 complete index files and all 17
required context files. Correctness also checked the pinned Codex source.
All requested `gpt-6-astra@max` under the explicit one-time exception;
returned model and effort remain `unverified`. No findings required edits.

The owner expanded acceptance to Sonnet -> DeepSeek -> Sonnet and
Sonnet -> Astra -> Sonnet in the same parent task, retaining an existing
DeepSeek child and exercising spawn, follow-up and send across the switches.
This exposed two pre-existing failures in the same handoff path before merge:
Sonnet rejects a terminal assistant-message projection of a child reply as
unsupported prefill; external parents can select original collaboration
names on a later turn, bypassing the subscription-only plaintext steering.

One material remediation extends the existing standalone-output owner to
render readable agent messages as matched function call/result pairs, without
raising their authority or changing client history. Opaque input still fails
before credentials. An interim attempt to reuse subscription steering exposed a deterministic
client contract failure during live acceptance: response-only tool outputs
are recorded as unexpected and do not execute or request a follow-up inference
(Codex tools/router.rs:246-296, stream_events_utils.rs:293-360,433-439,
session/turn.rs:434,511-570). Correctness confirmed this HIGH finding while
the remediation review was still in progress; the interim tree was not approved.

The corrected external response adapter retains advertised handoff names and
marks their native function calls with explicit plaintext metadata when the
external upstream omitted it. The actual call, arguments and IDs are preserved,
so Codex performs normal validation and execution and can continue its turn.
Explicit nonempty or malformed encrypted metadata is rejected. This is scoped
to advertised collaboration handoffs at the external response boundary; native
subscription encryption is unchanged. Both flattened and already-native
namespace responses are covered.
Native subscriptions retain their encrypted message and call path unchanged.

Provider-level JSON/SSE regressions cover native and flattened spawn/followup/send
responses, executable call shape, arguments and call IDs, plus consecutive terminal peer messages
as matched results. Existing normalization and opaque-input tests still apply.
The source-size baseline records existing owners at providers 297, agent_handoffs 317 and tool_adapter
394 lines, below the hard cap; no new parallel adapter is introduced.

Before concluding the single remediation review, all three lanes must re-read
the corrected final staged scope;
the previous verdicts are not approval for it. Pass 1 remains the original no-op;
no post-lane simplification pass ran. Expanded live acceptance and final review
results are recorded below when complete. No installation or release is made.

Final acceptance on the corrected runtime passed: Sonnet -> DeepSeek -> Sonnet
in 13 calls and Sonnet -> Astra -> Sonnet in 16 calls, each below cap 24.
Both kept the same parent task and existing DeepSeek child, exercised
spawn/follow-up/send, and retained all three markers in actual child replies
and parent finals. All 29 requests returned HTTP 200 with matching serving
identities and no probe errors. No reminder was needed in the passing runs.
Full final suite: 1,255 tests passed; compile, lint, source-limit, policy,
classic/Lite handoff and history-switch/400/transient-retry probes passed.

Final correctness, quality and adversarial reviews each returned ALL_CLEAR
on `8c84ffeb1250f438ebc1388baf741f6d142092e0` after complete coverage of all
31 staged-index files, both remediation deltas and required context. Each
read ponytail first. Requested model/effort for every lane was
`gpt-6-astra@max`; returned identity/effort remained `unverified`. The interim
HIGH executable-call finding was accepted and resolved before final review
completion; there are no unresolved findings or accepted residual risks.
The installed review plugin changed from 0.1.4 to 0.2.0 during this work;
reviewers read the current replacement skills and retained the owner's exact
Astra/max authorization. The hook/scanner preflight passed again on 0.2.0.

The only post-review delta adds this factual review/acceptance record and the
matching compatibility evidence. It changes no runtime, tests, contracts or
required procedures, so it is mechanical and all final lane results carry
forward. Diff checks and a fresh exact-tree secret scan precede the receipt.
Combined decision: ALL_CLEAR. Publishing/deploying remains a separate action.
