# Prompt: execute the complete router backlog

Copy the text below into the next agent's task. This is a handoff prompt, not
an instruction to the current planning agent to start implementation.

---

Implement the entire active SC_OpenRouter_adapter backlog in the dependency
order below. Deliver working, integrated increments and complete all applicable
acceptance gates; do not stop after a plan rewrite, scaffold or green source
tests. Preserve the full Mac, Windows, Linux/Arch, Codex, Claude CLI/desktop,
private-plugin, distribution, per-user-key and Kiro compatibility scope.

Canonical repository:
`/Users/cyrilallart/Documents/Github/SC_Codex_openRouter_adapter`.
Planning handoff is under `plans/` in the canonical repository. Its source
audit baseline is `96db57f`; use the integrated `develop` version and current
Git status rather than an old audit-worktree path.
Read `plans/2026-09-09-router-roadmap.md`, `plans/README.md`, then every
numbered plan 034-067. The inherited 001-033 entries belong to other products;
do not execute them. Audit reports, `048-review-status.md` and
`plans/rejected-muse-retry/` are supporting/retired records, not extra plans.

Inspect worktree/branch/status/ownership before writing. Use the runtime's
supplied worktree, or create one independently owned worktree from current
develop if none was supplied. Never edit the primary checkout or adopt an
unrelated active worktree. Keep one writable worktree per session per repo
and reuse it across every phase. The planning task's worktree is retired
after its reviewed commits are integrated; do not attempt to resume there.

Start by reading current KnowledgeVault routing, repo/global AGENTS.md,
ponytail and the installed pre-commit-review procedure. Section 9 of this
repo's AGENTS.md already records upstream Codex/OpenCode/Claude sources: pin
the actual revision/version for each contract inspection. Read Agent 57
standards before changing deployed agent models/tools/authority, and the goal
standard if goal mode is explicitly enabled. Do not create goal mode merely
because the backlog is long.

Reconcile live Git status, worktrees, latest develop/PRs and source against the
dated plans. Their excerpts are evidence of the old state, not code to restore.
Skip equivalent integrated work with proof. The index/roadmap maps historical
requirements to their current owner. Do not rerun 034 repository migration,
the original 036-038/040 refactors, 048's superseded invitation service, or
unsupported 039 live `/models`. Do preserve all residual governance, docs,
Business/Enterprise, billing and native-machine acceptance requirements.

Execute this stage order, integrating each slice before its dependants:

1. Establish source/review baseline and read-only 050 service status. Correct
   058 Stage 5 wrong-today README claims with their pinning tests. Land 057
   Stage 1 unsupported-Windows refusal before native support is available.
2. 060 safe diagnostics; 066 encrypted-brief containment and native plaintext
   contract capture. A refusal alone is not working delegation acceptance.
3. 061 domain rules/extracted-bundle closure; 067 updater extraction;
   056 explicit platform backends. Serialize installer writers.
4. 062 protocol/transport separation; 064 model facts/client projections.
5. 063 Codex/service-only activation, receipts/restoration and independent
   subscription policy. Preserve scheduled-update client choices.
6. 059 one pinned private CPython 3.14 runtime and native wrappers;
   058 native preflight; remaining 057 Windows Task Scheduler/ACL/lifecycle
   source. Use synthetic/local artifacts until private hosting is available.
7. 055 Stage 3 keyless/revoked-key recovery and shared secure writer;
   043 remaining isolated no-subscription CLI/IDE and desktop-sign-in proof.
8. 051 Claude setup contract; 049 Codex plugin source; 053 Claude plugin
   source. Both plugins call the same installer and never silently change
   configuration on refresh. Local validation precedes catalogue publication.
9. 054 distribution/feed/bootstrap/onboarding source and isolated infrastructure
   validation; 055 Stages 1-2 fake-API operator provisioning/delivery. Prepare
   exact AWS/DNS/Entra/publisher/Team changes for the relevant owner gates.
10. After required authority, 054 Stages 1-3 private feed/mirror/publication,
    050 observed update/recovery, 059 real bootstrap, 049/058 native staff
    Mac/Windows/Arch acceptance. Demonstrate install, health, 15-minute update,
    busy deferral, rollback, disable/removal and no collateral config loss.
11. Complete approved 055 operator provisioning plus 051/052/044/066 real
    client/model/tool/billing/delegation probes. Record installed client and
    router versions; use real intended Business/Enterprise account tiers and
    distinct users where required. Failed media/effort cells cannot be
    advertised as proven capabilities. Keep provider facts separate.
12. 054 Stage 4 per-install identity and revocation, then 055 Stage 4 automated
    key delivery. Include these later stages in the backlog; the shared feed
    token must never authorize billable key issuance.
13. 046 hourly model-data and picker refresh after authenticated versioned
    update qualification. Retain validated atomic last-good fallback; prove
    a newly onboarded model actually appears without a code release. Do not
    depend on the unproven 039 route or count a timer as picker evidence.
14. 065 separate Kiro IDE/CLI supported-contract spike, which may run earlier
    as independent research. A supported negative result completes the spike
    but does not constitute Kiro support. If positive, write and execute the
    thinnest supported follow-on within this scope, preserving approval gates.
15. Finish final 049/052/053/054 release/plugin/catalogue gates and 042/058
    documentation. Reconcile 041/045/047 umbrellas and every row in the index.

Resolved choices: private relocatable CPython 3.14 rather than root system
package installation; one runtime lock and bootstrap pair; updater extraction
before platform split; one installer and platform manager family; same shared
client receipts/status; no signing ceremony, request cap, inference proxy,
duplicate invitation service, speculative Kiro protocol or scope reduction.

Mixed-provider instructions are currently unreliable. Astra's encrypted native
agent messages were unreadable to Muse; child-side v1 metadata did not solve
it. One Muse Contributor xhigh audit did successfully read a named local brief
and return its marker. For delegation/reviews, use a non-secret scoped brief
file with a unique marker and explicit read-only authority; make the path
discoverable without relying solely on the encrypted message. Require the
child to read and acknowledge it before counting work. Do not infer delivery
from task name, inherited turns, spawn acceptance or a greeting. No recursive
delegation unless explicitly authorized. Use actual runtime schemas.

Immediately before every required review, read the current reviewer-model
table and skill from disk. Honor exact model/effort; record missing served
identity/effort as `unverified`. No substitution, runtime switching or hook
bypass. A model that cannot receive its brief cannot approve the tree.
If 066 hits an upstream client limitation, preserve that narrow blocker and
continue independent plans through a verified review path; do not claim native
delivery fixed or deploy containment without evaluating the review-path impact.

Use Python 3.14+, stdlib-only runtime, no network calls in tests. Reproduce
bugs before fixing them; add realistic behavior tests without weakening
existing valid assertions. Every structural move must run from an extracted
release without checkout imports and preserve required resources. Keep source
limits and staged commits below the mandated meaningful-line budget; split
coherent independently testable increments, not arbitrary halves.

At each commit run relevant focused tests, then:

```sh
python3.14 -m unittest discover -s tests -t .
python3.14 -m compileall -q codex_router tools tests packaging
python3.14 tools/check_source_limits.py
git diff --check
```

Complete simplification, secret scan, three read-only review lanes,
adjudication and exact-tree approval using the current installed review skill.
User-visible changes update CHANGELOG.md and packaging/VERSION. Commit with
the required type prefix, integrate through develop, verify the integrated
result and clean up or reuse the owned worktree at each milestone. Never work
off or push directly to main. Release PRs develop-to-main, publication,
installation and runtime acceptance are distinct gates.

This task authorizes implementation and ordinary source integration. It does
not grant new cloud/tenant/staff-machine mutations, paid probes, GitHub Team
purchase, collaborator demotion, key provisioning/budget/revocation, production
cutover or publication beyond authority already established for the exact
action. Build and test the full reviewable change first, then request only
missing authority with exact target, change, proof and rollback. Do not re-ask
for already authorized actions. A pending external gate blocks dependants
only: continue independent source work and retain the full backlog.

Outstanding named dependencies: Windows 11 x64 machine/user and actual entry
policy; designated Mac/Arch and Linux desktop acceptance targets; private
runtime patch-maintenance owner; AWS 651116729473/ap-southeast-2 and proposed
dist.softwarecombined.com DNS/ACM authority; Entra/SharePoint membership/guest
access; publisher/Team decision; bounded paid matrix; OpenRouter Management
API/Guardrail authority. Verify current state rather than trusting the snapshot.

Do not log requests, tool content, encrypted task blocks, credentials or
secret-bearing URLs. Feed read tokens are not user identity; Codex login email
is not the verified work-email budget anchor. Keep subscription headers away
from OpenRouter. Never bypass Windows script policy or weaken permissions.

Maintain a concise stage ledger with source commit, verification/review,
develop integration, installed/deployed identity, live update/rollback,
client/tool/billing evidence and blocker. Give periodic outcome-focused
updates. Finish only when all active requirements are implemented and accepted
or individually blocked on a concrete external dependency with the exact next
action. Do not stop the whole task at the first owner gate or count source
tests as production acceptance. Final response must reconcile every plan and
state `Worktrees: cleaned up` or exact retained path/branch/owner/reason.
