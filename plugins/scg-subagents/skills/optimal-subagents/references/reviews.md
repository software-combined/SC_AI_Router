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

Local user policy override: all pre-commit passes use
`openai/gpt-6.1-sol` at `high`, which is GPT-6.1 Sol through OpenRouter.
This exact model and effort requirement overrides the table below and has no
model fallback. If that route is unavailable, the affected pass is `BLOCK`.

These are provisional, evidence-based choices from the September 12, 2026 evidence.
Public benchmarks do not directly measure code-review defect recall. Validate
with representative real regressions before claiming superiority. Use one fixed
reasoning level per model, not a cheaper effort variant. Subscription/account
arrangements do not influence this selection.

For future routing changes, compare a small sanitized set of known regression
diffs and clean controls using the same full staged context and hidden ground
truth. Include functional, concurrency and money/security cases when relevant.
Measure actionable defect recall, false blockers, cost and review time; do not
reward verbose findings or a model's confidence. Repeated local outcomes should
replace these public-benchmark priors, within an authorized evaluation budget.

The same defaults apply to normal and elevated-risk reviews. Elevated risk
changes inspection depth and required evidence, not automatically the model bill.

| Pass | Required model, fixed effort | Ordered fallback models, fixed effort |
| --- | --- | --- |
| Simplification | `openai/gpt-6.1-sol` at `high` | None |
| Correctness | `openai/gpt-6.1-sol` at `high` | None |
| Quality | `openai/gpt-6.1-sol` at `high` | None |
| Adversarial | `openai/gpt-6.1-sol` at `high` | None |

Resolve the selected model's actual tool identifier from the active catalogue.
`openai/gpt-6.1-sol` is the OpenRouter route; `gpt-6.1-sol` is the native
subscription route. They are not interchangeable identifiers under an exact
provider requirement. Verify the accepted request and record
served identity when available. Never claim an unavailable effort was used.

Fallbacks in this table are authorized by this policy when a preferred model is
unavailable. They do not need a new permission question unless the user or an
applicable instruction explicitly requires an exact model/effort or forbids the
substitution. Such exact requirements still block when unavailable until the
owner authorizes an exception. Never switch runtimes or weaken a gate to evade
an exact requirement.

## Handle failures without buying repeated failures

1. Read the actual error. Resolve a wrong identifier through known catalogue
   aliases; skip models already known unavailable. Do not lower fixed effort.
2. For a model-specific capacity/access failure, use the next eligible fallback.
   Respect a useful supplied retry delay instead of repeating immediate calls.
3. For a shared router/tool/transport failure before inference, skip candidates
   sharing that failing path. Use a listed model only when its existing tool
   path is known to be unaffected. Do not change accounts, credentials, clients
   or data constraints. If no eligible path is known, the review is `BLOCK`.
4. Default to at most two alternative-model attempts per pass, within the task's
   authorized cost envelope. Preserve the work if they fail; do not walk the
   whole catalogue indefinitely. A failed dispatch is not a completed pass.
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
Request a focused correction only when concrete unresolved reasoning warrants
it. Corrections and escalations retain the exact model and effort above.
A different model or provider needs an explicit owner exception; the general
model-selection guide does not override the review policy.

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
For every Codex pass, call `spawn_agent` with explicit
`model="openai/gpt-6.1-sol"`, `reasoning_effort="high"` and `fork_turns="none"`.
If `collaboration_plaintext` handoff tools are offered, use them for every
subagent assignment, message and follow-up, whatever the recipient. Otherwise
use the `collaboration` tools. A handoff refusal is not evidence of an
OpenRouter outage or grounds to request native reviewers, and the router cannot
create a recoverable tool result.
Other runtimes need their own verified installed adapter and identifiers;
this document does not install or certify Claude Code/OpenCode integrations.
Do not switch runtimes to work around an unavailable required pass.
