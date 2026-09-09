# Router backlog and execution roadmap

Reconciled 9 September 2026 against `develop` source `96db57f`. Planning only.
Scope: every router plan 034-067, including residual acceptance and later-stage
work. Historical 001-033 entries in the inherited index concern other products;
they are not additional router work. `048-review-status.md`, audit reports and
`rejected-muse-retry/` are evidence records, not execution plans.

Use the [executor prompt](2026-09-09-execute-all-router-plans.md) to hand this
backlog to another agent. [The index](README.md#router-plans-034-067-reconciled-9-september-2026)
contains one row per numbered plan and links to the detailed plans.

## What is actually delivered

The router already has a dedicated repository, registry, provider interface,
state-home validation, structured rotating logs, characterization tests,
credential lookup, versioned install/rollback, stable launchers, systemd user
units, Codex no-subscription CLI support and model onboarding commands.
Seven plans delivered their principal source work (034-038, 040, 042).
Their remaining governance, log-retention and current-documentation obligations
are assigned below, so a DONE label does not erase them.

Two designs are not active implementations: 039's client-fetched catalogue
has no proven client fetch, and 048's original invitation/key service was
superseded by 054/055. The remaining 25 plans include umbrellas and acceptance
plans as well as new source work. Execute each requirement once under its
current owner, not once for every historical plan mentioning it.

### Evidence refreshed in this audit

| Surface | Evidence | What it does not prove |
|---|---|---|
| Source baseline | `96db57f`; final rerun: 473 tests in 59.819s, exit 0; compilation exit 0; source limits 78 files, zero failures. Existing socket resource warnings remain | Deployed source or cross-platform acceptance |
| Arch/Linux contribution | GitHub PR 3 MERGED, merge commit `cc365629`; systemd code is present | Native staff Linux/Arch acceptance |
| Owner Mac | Read-only health reported `0.6.9.22`; versioned layout; router and updater jobs loaded, stable launchers, updater interval 900 | An observed unattended update, rollback or new private feed delivery |
| Release | `.github/workflows/release.yml` still tag-driven; `service.py` still GitHub feed | The proposed main-to-stable / develop-to-beta CloudFront pipeline |
| Governance | GitHub API reports both `main` and `develop` unprotected | Approval to change plan, collaborators, rules or publishing |
| Upstream insight | AGENTS.md section 9 is integrated at lines 66-82 | Client compatibility; pin and inspect the relevant upstream revision |
| Mixed-provider briefs | Five failed children, eleven encrypted agent items; installed adapter source matched; synthetic preparation forwards opaque content | Wire-body capture or a successfully repaired native handoff |
| File-brief fallback | One Muse Contributor xhigh audit read a named local brief, returned its marker and scoped findings | General plaintext agent delivery; served identity/effort remain `unverified` |

Source details and vetted findings are in the
[architecture audit](2026-09-09-domain-architecture-audit.md) and
[instruction-delivery investigation](2026-09-09-subagent-instruction-delivery.md).
Only structural session evidence and synthetic canaries are retained.

## Remaining requirements, with one execution owner

| Plans | Current implementation evidence | Work still required / owner |
|---|---|---|
| 034 | Package, CI and repo exist | 054: review/publisher controls and the recorded GitHub Team decision; do not rerun repository migration |
| 035 | `runtime.py:63-76` rotates structured logs and timestamps events | 060: content boundary; 058: supervisor/stdout/update log retention and accurate operations docs |
| 036/037/038/040 | Handler tests, provider classes, `registry.py`, `credentials.py` | Preserve as regression contracts; 062/064/055/057 own additions |
| 039 | Static merged catalogue retained | Park unsupported `/models` replacement; only reopen after observing supported client fetch |
| 041/045 | `install.py`, `service.py`, stable launchers, activation/drain and rollback tests | 067/056 refactors; 050 observed update/recovery; 054 branch publishing; 057-059 native lifecycle and bootstrap |
| 042 | Existing docs and compatibility matrix | 058 Stage 5: current README/runtime-file list plus its pinning tests; update each support claim only with matching evidence |
| 043 | `runtime.py:49-57`, `local_services.py`, `router.py:97-109`, installer mode and probe provider flag | Isolated no-login CLI/IDE install and `model/list`; real desktop sign-in behavior; tolerance/shape proof for native thread-hint/search/guardian calls. Do not invent local successes |
| 044 | Capability fields, model refresh, probe legs; `docs/compatibility.md` has partial evidence | 064 normalization/projection consistency, then actual current model/client matrix: tools, media, effort, output/context limits, compaction, summaries, patch, web/deferred/experimental tools and 066 delegation. Disable or withhold unsupported advertised capabilities; do not classify metadata as a passing probe |
| 046 | `models.py:98-184`, Preview tier, model validation in CI | Unseen-model add/dry-run/remove and actual picker proof; after authenticated update acceptance, hourly model-data refresh with validation/atomic last-good swap and separate static picker refresh proof. No new dependence on 039 |
| 047 | Protocol C/D source and installer foundations integrated | Close A through 054, B through 050, E/F through 049/053/056-059, G through 055. Reconcile old signing/native-package/cap instructions as superseded |
| 048 | Historical design and acceptance requirements | 054/055 retain verified work identity, per-person budget/revocation/isolation and Business/Enterprise acceptance. Do not build old invitation service or paste-once rollout |
| 049 | Current installer/platform foundations; no shared plugin/clients receipt yet | Codex `scg-openrouter` / `manage-router` package, explicit setup/status/update/disable/remove, native wrappers, receipts and designated Mac/Windows/Arch acceptance; consume 053 for Claude |
| 050 | Current owner service/jobs look healthy | Fresh readback, skip obsolete repairs; source-to-installed identity, observed successful update, recovery/rollback, safe operational diagnostics |
| 051/052 | Claude routing source and documented gateway controls | CLI and desktop independently: preserve login, discover model, scoped configuration/restoration, real tool round-trip, native/OpenRouter account/billing evidence, version-stamped compatibility and release acceptance |
| 053 | Plan only | Claude plugin source in adapter repo, private catalogue pointer in SC_Agent_plugins, shared installer/receipts, explicit writes, pin final integrated source; no automatic configuration on plugin refresh |
| 054 | Existing feed/serial/checksum/launcher foundations | Private AWS feed/bundles/runtime mirror; identity-gated Entra/B2B page; exact OIDC publisher; branch/channel publishing; origin-safe token/redirect handling, rotation including current-version hosts, transitional GitHub migration, revoked/offline-host recovery, per-install authority Stage 4 |
| 055 | Credential lookup, nonce page, keyless setup boot and empty-file claim | Shared secure writer, proven-dead-key replacement, keyless boot + one first-use window per nonce, Management API/Guardrail/audit operator path, TLS machine delivery, two-user revoke/budget proof, automated delivery only with 054 Stage 4 credential |
| 056 | Existing launchd/systemd dispatch mixed in installer | Explicit platform manager contract and unsupported-OS refusal; update standalone disable; reuse existing systemd behavior and shared OS CI |
| 057 | Wrapper exists; Windows native lifecycle/ACL not implemented | Early refusal; Task Scheduler logon/updater, locks/atomic writes/paths, current-user ACLs, real entry-policy solution and complete native lifecycle |
| 058 | Linux systemd container lifecycle evidence | Native OS preflight and deterministic actionable remedies, real desktop/staff acceptance, full README/docs correction and runtime-file pin test, log-retention closeout |
| 059 | Runtime requirement/detection exists | Pinned private CPython 3.14 lock, native wrappers with no preinstalled Python, secure extraction and zstd smoke, interpreter update/rollback and patch-owner runbook; no system package/PATH mutation |
| 060/061/062 | Synthetic diagnostic leak + bundle/domain audit | Safe errors first, extracted artifact closure and domain rules next, then protocol/transport extraction with unchanged observable bodies/streams/auth |
| 063 | Installer hardcodes Codex client work | Codex adapter and service-only route first, explicit independent subscription policy, client-owned receipts and restore, preserved update selection; Claude activation follows via 051/053 |
| 064 | Registry and writers exist but disagree | One pure model normalization and client capability projection, preserve routing facts/pinned quirks and native metadata, no silent tier or capability promotion |
| 065 | No verified Kiro inference contract | Separate IDE/CLI official-source spike; supported inference/tool hooks distinguished; positive result yields thin implementation plan, negative result records exact reopening evidence |
| 066 | Opaque agent item reproduced; file assignment workaround read once | Reject unreadable encrypted briefs before dispatch; capture supported native plaintext contract; normalize only proven shape and retain through compaction; synthetic then approved live initial/follow-up/control probes |
| 067 | `install.py` 699 lines, scheduled update logic at 514-620 | Extract updater preserving stable launcher, injected test seams, explicit-feed/serial/ETag/park/deferral behavior; below 600 installer lines with packaged helper present |

## Execution order

This is a stage order, not numeric order. Finish and integrate each runnable
slice before its dependent slice. Independent read-only work may run alongside
it, but shared installer/protocol files have one writer. Reuse any equivalent
work that has landed since the audit.

| Order | Execute | Observable milestone |
|---|---|---|
| 0 | Reconcile ownership/base; 050 read-only status; validate review-brief delivery; read AGENTS section 9; 058 Stage 5 wrong-today documentation and 057 Stage 1 refusal | A trustworthy baseline, truthful current docs, no Windows path falling into launchd; no service changes from an old snapshot |
| 1 | 060, then 066 containment + native plaintext capture | Synthetic content cannot enter diagnostics; opaque brief refuses before upstream. Keep full 066 open if client plaintext is unavailable |
| 2 | 061, then 067, then 056 | Extracted bundle is self-contained; updater separated; launchd/systemd share explicit platform dispatch with unchanged lifecycle |
| 3 | 062, then 064 | Existing Responses/Messages wire behavior preserved; merge/apply project identical capabilities from the same model facts |
| 4 | 063 | Codex and service-only installs/updates/uninstall work through client receipts; independent subscription choices preserve legacy state |
| 5 | 059 and 058 native preflight, then remaining 057 source | Clean no-Python bootstrap from synthetic/local archives on qualified OS targets; Windows backend and ACL tests; one runtime lock and wrapper pair |
| 6 | 055 Stage 3/shared writer; 043 residual isolated proof | Keyless/revoked-key recovery passes offline; subscription 401 never opens an OpenRouter window; no-login client behavior qualified |
| 7 | 051 source/setup contract, 049 Codex plugin source, 053 Claude plugin source | Local plugin validation calls the canonical installer and preserves client settings/receipts; no new distribution implementation |
| 8 | 054 source and isolated infrastructure validation; 055 Stages 1-2 fake API/operator path | Token/serial/rotation/migration and per-person key/guardrail failure paths work in isolation; complete reviewable AWS/DNS/Entra and Team proposals |
| 9 | Authorized 054 Stages 1-3, with 050 operational proof and 059 real runtime mirror | Protected/approved publisher and private feed; clean Mac/Linux/Windows install, update, rollback, uninstall; actual feed-to-version change within 15 min |
| 10 | Authorized 055 operator provisioning, 049/058 staff-machine acceptance and 051/052/044/066 real-client probes | Per-user budget/revocation, native-vs-OpenRouter billing separation, exact model/client tool/capability/delegation matrix; source/CI evidence is not substituted |
| 11 | 054 Stage 4 then 055 Stage 4 | Verified-email per-install issuance and revocation; self-service onboarding no longer requires operator key delivery |
| 12 | 046 remaining hourly model-data/picker refresh after authenticated update proof | New approved model reaches the real picker without code release; malformed/offline feed preserves last-good behavior; retain legacy static fallback unless replacement proven |
| 13 | 065 independent spike and any supported thin follow-on it defines | IDE and CLI each have supported outcome; negative spike is complete but is not claimed as Kiro support |
| 14 | Final 049/052/053/054 release/plugin/catalogue gates, 042/058 docs and 047 umbrella reconciliation | Every active requirement has implementation + integration + applicable live proof, or an explicit narrow gate; release and plugin pins match accepted source |

Stage 13 research can start during any source stage. If 066 cannot produce a
supported native plaintext route, keep that milestone blocked on the client,
continue independent work using a positively verified file-brief review path,
and do not deploy a containment change that silently breaks the only review
path without recording that consequence. A file-read workaround does not
complete native handoff acceptance.

## External gates and resolved decisions

| Item | Resolution / exact outstanding gate |
|---|---|
| Interpreter approach | Resolved: private relocatable, pinned CPython 3.14 from 049/054. 059 assigns maintenance to SCG IT router release maintainers, Cyril accountable for releases; confirm the operational assignee before fleet acceptance |
| Installer order | Resolved: 067 updater first, 056 platform split next; rebase any concurrent work and keep one writer. Never increase limits to fit Windows |
| Windows target | Still unnamed. Obtain Windows 11 x64 machine/user and current script policy before native acceptance; offline/CI work is not blocked |
| Other native targets | Designated macOS and Arch staff acceptance plus Ubuntu/Fedora desktop and required clean-bootstrap fixtures; container systemd proof is not sufficient |
| Windows entry | Resolve with actual machine policy. Do not claim plugin execution bypasses Restricted/RemoteSigned, or change policy/quarantine as a workaround |
| GitHub governance | Both branches unprotected. 054 records Team-before-stable and reduced writer-set proposals; recurring spend, exact account roles and rule changes require owner action. Preserve main-to-stable design; do not silently choose a tag fallback |
| AWS/private delivery | Target 651116729473, ap-southeast-2; proposed dist.softwarecombined.com/ACM us-east-1. Verify identity and current resources; prepare exact changes before requesting missing deploy/DNS/publication authority |
| Onboarding | 054: member/B2B portco groups and correctly permissioned SharePoint download surface; confirm actual membership/guest permissions. Do not grant guests access to staff-only TechnologyIT |
| Key administration | 055: Management API and Guardrails, Secrets Manager role, verified work email, no secrets in CLI/response/log/audit rows; real provisioning/budget/revoke actions owner-gated |
| Paid probes | Exact model/client matrix and spend ceiling need explicit authority. Existing health/discovery, metadata or a paid audit is not blanket probe authorization |
| Live source/cutover | Existing install does not authorize updater/release/channel changes. Verify installed version and pointer, authorized target, rollback and observed result |
| No-subscription/Business/Enterprise | Retain CLI/IDE path and separate desktop check; use actual intended account tiers and two distinct users for isolation evidence |
| Kiro | Supported-contract spike; do not invent authentication/protocol or treat an MCP integration as model replacement |

Every gate blocks only dependent work. Prepare the exact patch, test artifact,
target and rollback before seeking approval. The planning request itself does
not authorize recurring spend, staff-machine mutation, cloud/tenant changes,
provider billing, publication or key administration.

## Completion and exclusions

For every active requirement record source commit, tests, review receipt,
`develop` integration, deployed identity, applicable machine/client/billing
proof and remaining blocker. Mark superseded text as superseded with its new
owner; never check it off as implemented. Keep 039 parked absent new evidence.
Do not treat a healthy service, timer, current catalogue or green CI as proof
of update, rollback, recovery or acceptance.

Not performed by this audit: source implementation, AWS/Entra/OpenRouter
mutation, paid compatibility probes, native Windows/staff Linux acceptance,
feed publication, upgrade purchase or production cutover. This document and
its plans make that work executable and reviewable; they do not claim it done.

Handoff location: the integrated `plans/` directory in the canonical repository
on `develop`. The audit branch/worktree is retired after verified integration;
an executor uses its own runtime-supplied or owned worktree. Other active
worktrees belong to their respective tasks and are not cleanup targets.
Only planning documents changed. No durable KnowledgeVault update was needed
beyond the repository's canonical roadmap and handoff. Check Git status/history
for current integration evidence; the audit baseline is not the final commit.
