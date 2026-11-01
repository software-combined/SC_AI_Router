# Model-agnostic pre-commit review routing

Canonical authoring source: `plugins/agents/scg-subagents/skills/optimal-subagents/references/reviews.md`
in SC_AI. The review plugin bundles an unchanged release copy at
`references/reviews.md` so review-only installations remain usable.
Edit the canonical source, synchronize the copy and release both affected plugins.
Repository tests enforce equality. The installed review plugin's bundled copy
governs a running review; do not mix policy versions mid-review.

## Select each pass

The review procedure does not require a particular model, vendor, provider,
billing route or effort level. It requires a simplifier and four independent
review lanes (correctness, quality, adversarial and security) that can complete
the full staged-tree review. Security candidate verification uses the security
role's choices; it is not another configured lane.

1. Apply explicit user and project model, provider and effort requirements first.
   An exact requirement remains binding until the user changes it.
2. Otherwise read `review_models` from the machine owner's local hook
   configuration with `scg-review-state models --client <active-client>`.
   Use `codex` or `claude-code` for those clients. For each pass, use its first
   eligible `model@effort` choice. Missing preferences block dispatch; this
   skill and general task tables supply no model or effort defaults.
3. Confirm the model can use the required tools, read the complete staged files
   and context, and perform the assigned lane at the stated risk profile.
   Use relevant observed review outcomes when available. A callable model or
   public benchmark score alone does not establish review suitability.
4. Resolve the actual callable model identifier, provider route and supported
   effort before dispatch. Follow host access preferences and existing data
   constraints. Do not require a paid provider account when an eligible
   configured route is available. If effort is unsupported and no exact effort
   requirement applies, omit it and record `unavailable`. An unsupported exact
   requirement blocks the pass; never invent or silently lower an effort level.
5. Pass the resolved model and supported effort explicitly when the runtime
   permits selection. An installed adapter may resolve them from its agent
   configuration instead; record that configuration as the request. A label in
   a brief never selects the model or proves which model served the review.

The same model may run all passes in separate child contexts. Independence
comes from separate lane assignments and inspections, not different vendors.
Elevated risk changes inspection depth and required evidence; it does not
automatically change the model or bill.

## Availability and bounded fallbacks

Check effective access for the existing account, key, region and runtime.
A public catalogue entry alone does not prove access. Use a key-scoped
catalogue or matching effective snapshot when available; never read or expose
credential values. Unknown access can be established by the actual review call.
Skip known unavailable models and unsupported efforts without a paid probe.

If the selected route is unavailable, use the next configured eligible choice
within the same permissions, data constraints and authorized cost envelope.
Record the substitution. No new permission question is needed unless it changes
an explicit requirement or exceeds that authority. An exact model, provider or
effort requirement has no automatic fallback.

Permit at most two fallback dispatches per pass. A dispatched replacement
counts even if it fails before inference; a candidate skipped before dispatch
does not. Respect a useful retry delay. A shared provider failure skips its
remaining candidates; a shared runtime or handoff failure stops dispatch.
Do not change accounts, credentials, clients or data constraints to evade it.
A handoff refusal is a delivery failure, not evidence of model unavailability.
If no permitted pass can complete, preserve the work and report `❌ Block`.

Stop an active prior pass before transferring its scope. Give every replacement
the same lane, full staged scope, context, Ponytail dependency and report
contract. The parent cannot replace a lane with self-review.

## Acceptance and identity

A failed or incomplete review is not model unavailability. Make one focused
correction for concrete missing coverage or reasoning; if it remains incomplete,
use an eligible replacement within the dispatch limit. Preserve every finding
for adjudication. A valid blocking finding cannot be erased by another opinion.
A no-findings review, model age or benchmark rank alone does not justify a redo.

Record each pass's requested and returned model and effort, plus material
substitutions and failed attempts. Missing serving identity is `unverified`
and does not itself block; an observed model or effort mismatch invalidates
the pass. The hook receipt records the actually requested successful-pass
identity, never a preferred model that failed before execution.

Start each assignment with its requested model, effort (or `unavailable`),
pass and task. Use the active runtime's verified subagent tools and schema.
If `collaboration_plaintext` handoff tools are offered, use them for every
subagent assignment, message and follow-up, whatever the recipient. Otherwise
use the `collaboration` tools.
External children receive fresh readable context. Other clients need their own
verified installed adapter; this policy does not install one or authorize a
runtime switch.

Model choice never waives full staged-file coverage, lane independence,
secret scanning, required checks, adjudication, re-review or exact-tree approval.
