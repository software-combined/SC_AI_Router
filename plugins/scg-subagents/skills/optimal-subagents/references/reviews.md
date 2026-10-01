# Cost-first pre-commit model routing

Canonical authoring source: `plugins/scg-subagents/skills/optimal-subagents/references/reviews.md`
in SC_AI_Router. The review plugin bundles an unchanged release copy at
`references/reviews.md` so existing review-only installations remain usable.
Edit the canonical source, synchronize the copy and release both affected plugins.
Repository tests enforce equality. For a running review, the installed review
plugin's bundled copy is its effective release policy; do not mix policy versions
mid-review. General model evidence and refresh methodology live in the
optimal-subagents skill.

## Defaults and authorized availability fallbacks

Every pass prefers GPT-6.1 Sol through OpenRouter at `high`. The ordered
fallbacks below are enabled by default, including when the preferred model is
named in a brief. Use them automatically unless the current user explicitly
forbids substitution or an applicable instruction requires an exact route.
Astra is excluded from automatic reviewer routing.

These alternatives are lane-specific choices, not a claim of general parity
with Sol. Public benchmarks do not measure review defect recall. Qualification
uses known defects and clean controls; a missed material defect or false blocking
finding excludes that model from the affected lane. Use the prescribed effort,
never a cheaper effort variant.

For future routing changes, compare a small sanitized set of known regression
diffs and clean controls using the same full staged context and hidden ground
truth. Include functional, concurrency and money/security cases when relevant.
Measure actionable defect recall, false blockers, cost and review time; do not
reward verbose findings or a model's confidence. Repeated local outcomes should
replace these public-benchmark priors, within an authorized evaluation budget.

The same defaults apply to normal and elevated-risk reviews. Elevated risk
changes inspection depth and required evidence, not automatically the model bill.

### Qualification and limits

The 1 October 2026 AEST pilot used synthetic full files with hidden defect/control
labels. Flash completed simplification and quality; GLM completed all four roles.
Each role detected its material defect and accepted its clean control: duplicate
loss during simplification, public-catalogue eligibility diverging from the
canonical account check, invocation-ID replay mismatch (correctness), and stale
staged-tree receipt reuse (adversarial). No model was excluded from these lanes.

Six compact paired-case calls completed after one full-rubric Flash call exhausted
its output allowance without a review. That incomplete call was not accepted.
All seven inference calls requested `max`, capped output at 4,096 tokens and
matched the returned model ID; served effort was unverified. OpenRouter reported
US$0.012934 total under the 12-call / US$5 pilot limits. Pricing came from the
current [OpenRouter catalogue](https://openrouter.ai/api/v1/models), with a hard
provider price ceiling. These small cases do not establish general parity,
full-context review reliability or Windows delivery. A real pass must still meet
every coverage and report requirement; a truncated answer is incomplete.

| Pass | Preferred model, fixed effort | Ordered fallback models, fixed effort |
| --- | --- | --- |
| Simplification | `openai/gpt-6.1-sol` at `high` | `deepseek/deepseek-v4.1-flash` at `max` → `z-ai/glm-5.3` at `max` → `gpt-6.1-sol` at `high` |
| Correctness | `openai/gpt-6.1-sol` at `high` | `z-ai/glm-5.3` at `max` → `gpt-6.1-sol` at `high` |
| Quality | `openai/gpt-6.1-sol` at `high` | `deepseek/deepseek-v4.1-flash` at `max` → `z-ai/glm-5.3` at `max` → `gpt-6.1-sol` at `high` |
| Adversarial | `openai/gpt-6.1-sol` at `high` | `z-ai/glm-5.3` at `max` → `gpt-6.1-sol` at `high` |

Resolve the selected model's actual tool identifier from the active catalogue.
`openai/gpt-6.1-sol` is the OpenRouter route; `gpt-6.1-sol` is the native
subscription route. Native Sol is a listed alternative, not proof that the
OpenRouter route works. Check the active runtime's callable native identifier;
do not silently select a different Sol version. Verify the accepted request and
record served identity when available. Never claim an unavailable effort was used.

Fallbacks in this table are authorized by this policy when a preferred model is
unavailable. They do not need a new permission question. An explicit exact-model,
provider or effort requirement still blocks when unavailable until the owner
authorizes an exception. Never switch runtimes or weaken a gate to evade it.

## Handle failures without buying repeated failures

1. Before dispatch, check effective availability for the active key, region,
   account and runtime, plus supported effort and applicable data constraints.
   A public catalogue entry alone does not establish access. For OpenRouter,
   use its key-scoped `/models/user` list or the router's matching effective
   snapshot; do not reuse another key's or region's snapshot. Check native Sol
   through the active native catalogue. Skip known unavailable models and
   unsupported efforts without an inference call or fallback dispatch.
   Unknown access may be established by an actual review call. Resolve a wrong
   identifier through verified aliases; do not lower fixed effort.
2. For a model-specific capacity/access failure, use the next eligible fallback.
   Respect a useful supplied retry delay instead of repeating immediate calls.
3. For a shared OpenRouter outage, authentication or transport failure, skip
   its remaining candidates and try listed native Sol when its existing route
   is callable and unaffected. A shared Codex handoff/tool failure stops all
   dispatch, including native Sol. An unsafe encrypted handoff is a delivery
   error, not an OpenRouter outage; apply the one readable correction below.
   Do not change accounts, credentials, clients or data constraints. If no
   eligible path is known, the review is `BLOCK`.
4. Permit at most two fallback dispatches per pass, within the authorized cost
   envelope. A dispatched fallback counts even if it fails before inference;
   candidates skipped by step 1 or a shared-path failure do not count. Stop
   after two failed fallback dispatches even if a listed candidate remains.
   A failed dispatch is not a completed pass.
5. Brief each replacement with the same lane, full staged scope, context,
   Ponytail requirement and report contract. Stop any active prior pass before
   transferring its scope. All three final lanes remain independent subagent
   reviews; the parent cannot replace a lane with self-review.

Missing serving identity is `unverified` and does not itself block; an observed
model/effort mismatch invalidates that pass. Re-run it using an eligible policy
choice or report `BLOCK`. Record every material substitution and failed attempt,
and put the actually requested successful-pass identity in the hook receipt.

## Escalate for evidence, not ceremony

A returned answer that fails the acceptance check is not model unavailability.
Make one focused correction when concrete missing coverage or reasoning warrants
it; if the pass remains incomplete, use the next eligible fallback within the
dispatch limit. Preserve every finding for adjudication. A valid blocking
finding stops approval and cannot be erased by buying another model's opinion.
The general model-selection guide does not add reviewer choices to this table.

A no-findings review, model age or a general benchmark rank alone is not a reason
for another paid pass. Escalation never waives full staged-file coverage,
independence, secret scanning, tests, adjudication, re-review rules or exact-tree
approval. No allowed model can complete a mandatory pass means `BLOCK`.

## Runtime scope

Begin each review assignment message with the actual requested model, effort,
pass/role and task context, for example: "GPT-6.1 Sol High: pre-commit review
Pass 1 (code simplification) for the handoff fix." Include the same first line in any
file-based brief and update it for a fallback or follow-up assignment. Use a
real task name when no plan number exists. This makes the request traceable
from the message; it does not prove the served identity recorded separately.

Codex packaging and its active collaboration tools are the supported path.
Select the first eligible route for the pass, then use explicit `model`,
`reasoning_effort` and `fork_turns="none"`. OpenRouter recipients use
`collaboration_plaintext.spawn_agent`, `collaboration_plaintext.send_message`
and `collaboration_plaintext.followup_task`; native subscription recipients use
the original `collaboration` tools. Native saved tool names do not change an
OpenRouter recipient's provider route. An unsafe handoff refusal may end the
parent turn. Correct it once on the next user turn with a readable plaintext
brief and the same model and effort. If that correction fails or the required
handoff tool is unavailable, stop dispatch with `BLOCK`. The router cannot
create a recoverable tool result, and an encrypted message containing a file
path cannot repair it.
Other runtimes need their own verified installed adapter and identifiers;
this document does not install or certify Claude Code/OpenCode integrations.
Do not switch runtimes to work around an unavailable required pass.
