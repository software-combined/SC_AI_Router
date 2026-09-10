# Implementation Plans

For the earlier backlog, start with the [router backlog and execution order](2026-09-09-router-roadmap.md)
and the [complete executor prompt](2026-09-09-execute-all-router-plans.md).
Reconciled at `96db57f`, 9 September 2026: platform Plans 056-059 and
AGENTS.md section 9 are integrated; audit Plans 060-067 and this consolidation
remain planning deliverables. No source refactor or rollout is implied.

The inherited 001-033 material below belongs to the former SC_Infrastructure /
SC_AI index. Those plan files are absent from this repository and are historical
context, not work for the router executor. The router scope is 034-067.

Plans 001-003 were generated on 2026-07-13. Plan 004 was added on 2026-07-14
after read-only inspection of the active v0.2 OpenCode stream, the installed
desktop/config surface, current OpenCode contracts, OpenRouter routing, and
Artificial Analysis model evidence. Plan 005 was added on 2026-07-24 after
read-only inspection of the current AWS and Entra identities, the authoritative
Technology/IT documentation, Open WebUI, OpenRouter, and Amazon Bedrock
AgentCore Gateway. Plan 005 was then reduced after adversarial architecture
review to keep the first deployment focused on product validation rather than
multi-company control-plane work.
Plan 006 was added on 2026-08-02 after read-only review of the verified AWS n8n
host, the existing host-sidecar and atomic transaction patterns, the Beacon
worker runtime contract, and the blocking transport, quota, lifecycle, and
rollback gates. It deliberately uses bounded disposable storage for the pilot
instead of preempting the future company data-lake design.
Plan 007 upgrades that private sidecar for the read-only full-period Last Yard
revenue pilot. It adds the live Accounts baseline as a seventh read-only input,
centralises the complete mount and environment identity, binds the corrected
N8N worker image, and tracks deployment through local Finance-report proof.
Its retained immutable ECR registry is live and drift-clean. The final worker
image from N8N commit `5ca3252be` is running healthy on its continuously
scanned Linux/amd64 child digest. A bounded authenticated diagnostic proved cap
zero with zero provider calls. Integrated readback exposed only a stale literal
n8n container name, so source now resolves the single peer through stable
Compose project/service labels. The exact recovery passed semantic readback,
proved zero provider calls, and finalized the journal. Ingress and workflow
proofs remain open. Reviewed commits `11adf17`
and `b894542` own
one one-shot manual operator and its deterministic bundle: one executable, one
Compose overlay, no Caddy/systemd/lifecycle path, and no automatic resume or
rollback. Commits `ac59aec` and `de6d596` own the final readback-only
continuation and operator contract; loose root shell steps and unbound operator
files remain rejected. Xero remains read-only; cap zero dispatched no provider
call.
Plan 008 records the live Open WebUI configuration for centrally administered
MCP servers, per-user delegated authentication, API keys, folders, model
defaults, and runtime tuning. The application configuration is live; MCP server
connections remain pending and are not baked into source.
Plan 026 replaces the rejected Beacon host-side session lifecycle transaction
with pruning through the worker's existing non-blocking health boundary and
the existing immutable-image replacement path.
Plan 011 defines the SCG AI Workplace direction and links one independently
releasable implementation plan for each trust, tenancy, connector, usability,
preview, generation, write-control, and scale slice. Plans 011-024 are source
plans only; they do not alter the live Open WebUI task definition `:7`.

## MCP-00 reconciliation (2026-08-20)

The implementation baseline remains a pinned Open WebUI `v0.10.2` derivative
with narrowly hash-guarded security patches. Plan 012's standalone v0.11.0 fork
is parked. Plans 013-019 remain the infrastructure/security source sequence;
Plan 015's Connection Centre UI is parked while its durable OAuth plumbing is
retained. Plans 020-023 are parked, and Plan 024's branding/workspace-switcher
UI is parked. No item in this reconciliation authorizes deployment or provider
registration.

## Execution order and status

| Plan | Title | Priority | Effort | Depends on | Status |
|---|---|---:|---:|---|---|
| 001 | Build the portfolio agent engineering setup starter | P1 | M | - | COMPLETE |
| 002 | Stabilize the n8n worker lock lease for long production executions | P1 | S | - | COMPLETE |
| 003 | Stabilize worker-side task-runner admission | P1 | S | 002 | COMPLETE |
| 004 | Evaluate and route OpenCode models for the shared development setup | P1 | L | - | SUPERSEDED |
| 005 | Pilot Open WebUI on AWS Fargate | P1 | M | Existing SCG AWS account and provider approval | LIVE PILOT |
| 006 | Deploy the bounded Beacon Xero worker sidecar | P1 | L | Fixed AWS/SSM transport and live apply proof | COMPLETE |
| 007 | Upgrade Beacon worker for the read-only Last Yard revenue pilot | P1 | M | 006 and N8N `0e9e1f9ea` | IN PROGRESS |
| 008 | Open WebUI admin-configured MCP readiness, API keys, defaults and tuning | P1 | S | 005 (live pilot) | LIVE CONFIG; MCP SERVERS PENDING |
| 009 | Single-account COMPLIANCE (WORM, 90d) Object Lock on Attio/Monday/NetSuite backup buckets | P1 | S | - | COMPLETE (live) |
| 010 | Backup deploy/rollback gate v2 (fail-closed deploy-time guard, reviewed) | P1 | M | 009 | COMPLETE (lands with this commit) |
| 011 | SCG AI Workplace roadmap and architecture index | P0 | M | 005 and 008 | COMPLETE (docs only) |
| 012 | Private Open WebUI fork and v0.11.0 parity release | P0 | L | 011 | PARKED; v0.10.2 derivative retained |
| 013 | Open WebUI trust baseline and admin-issued API keys | P0 | L | pinned v0.10.2 derivative | POLICY SOURCE IMPLEMENTED; admin grant/claim/rotation/revocation and legacy cutover pending; deployment gated |
| 014 | Tenant and managed-connector manifest compiler | P0 | L | 013 | SOURCE COMPILER IMPLEMENTED; runtime registration/deploy pending |
| 015 | Connection Centre and durable per-user OAuth | P0 | L | 014 | UI PARKED; source-only OAuth plumbing retained |
| 016 | NetSuite delegated read pilot | P1 | M | 015 plumbing | MANIFEST SOURCE ONLY; registration/deploy pending |
| 017 | Monday delegated read pilot | P1 | M | 015 plumbing; pilot after 016 | PENDING; no production manifest in this slice |
| 018 | Attio delegated read pilot | P1 | M | 015 plumbing; pilot after 017 | PENDING; no production manifest in this slice |
| 019 | Microsoft/SharePoint compatibility pilot | P1 | L | 015 plumbing; pilot after 018 | PENDING; no manifest in this slice |
| 020 | Non-technical Projects, Skills, and assistant UX | P1 | L | 013 and 015 | PARKED |
| 021 | Claude-style Work Product preview | P1 | L | 020 | PARKED |
| 022 | Hardened NEURA Office generation pilot | P2 | L | 021 | PARKED |
| 023 | Controlled connector writes | P2 | L | 013, 015, and one accepted read pilot | PARKED |
| 024 | Tenant factory, workspace switcher, and branding gate | P1 | L | 014, 020, and 021 | IMPLEMENTATION PARKED; dedicated-plane design retained |
| 025 | SCG multi-account landing zone + Central Immutable Backup | P1 | L | 009, 010 | IN PROGRESS (Phase 0 + Phase 1 steps 1–2 done; replication build-out + Phases 2–3 pending) |
| 026 | Simplify Beacon worker session retention | P1 | S | 007 | DONE (`af4b262d`) |
|027 | MCP platform architecture, centralisation and scaling |       P1 |      M | 005, 008, 014 | SOURCE PLAN ONLY (audit + target design; no deployment) |
|028 | GitHub MCP as an Open WebUI managed connector |       P1 |      S | 027, 013/015 plumbing | SOURCE PLAN ONLY (candidate; not registered) |
|029 | Google Workspace MCP as an Open WebUI connector |       P1 |    S/L | 027, 013/015 plumbing | SOURCE PLAN ONLY (first-party primary; self-host fallback spike-gated) |
|030 | Xero MCP integration |       P1 | S/M–XL | 027, 006/007 reconciliation | SOURCE PLAN ONLY (decision plan; X3 interim then X1) |
|031 | Compact managed-connector activity in Open WebUI chat |       P1 |    S/M | 033, final Microsoft OAuth handoff | FINAL LOCAL SOURCE + IMAGE/BROWSER EVIDENCE (`review-final2`); 993 PASS + 1 INTENTIONAL SKIP + 0 FAIL; FIVE INHERITED BEACON LIMIT BASELINES AND TWO PINNED-UPSTREAM SECRET HEURISTICS; FRESH REVIEW, COMMIT/INTEGRATION, PROMOTION/DEPLOYMENT/LIVE ACCEPTANCE PENDING |
|032 | SC_AI v0.11.1 fork platform slice (build provenance, SBOM, migration qualification, maintenance-window deployment) |       P1 |      L | 011; SC_AI branch `codex/open-webui-v0111-claude-projects-20260828` | DESIGN ONLY — implementation BLOCKED at its own four-pass review (2026-08-30); eight-item worklist in the plan; deployment execution remains owner-gated |
|033 | Open WebUI non-technical UX simplification |       P1 |      M | 005 (live pilot), 008 | FINAL LOCAL SOURCE + IMAGE/BROWSER EVIDENCE (`review-final2`); 993 PASS + 1 INTENTIONAL SKIP + 0 FAIL; FIVE INHERITED BEACON LIMIT BASELINES AND TWO PINNED-UPSTREAM SECRET HEURISTICS; FRESH REVIEW, COMMIT/INTEGRATION, PROMOTION/DEPLOYMENT/LIVE ACCEPTANCE PENDING |

## Dependency notes

- Plan 001 is one coherent delivery stream. Its canonical setup instruction,
  templates, role starters, hook entries, policy checklist, and compact vault
  starter ship together. Enforcement is implemented and proved by the consuming
  setup agent in the target repository.
- Plan 002 is an independent production-runtime stabilization. Source review and
  tests completed before the separately gated host backup and rolling rollout.
  Main and all ten workers read back the reviewed values. Natural AP execution
  `111657` then completed successfully after 7m20s with no fatal queue-job
  signature. A corrected container-name scan found separate task-runner
  offer-expiry retries, which Plan 003 owns.
- Plan 003 follows the lease stabilization because correct-container logs showed
  that natural AP runs finish but still incur task-runner offer-expiry retries.
  Worker capacity five was merged and rolled out, but execution `111785`
  finished with five retries and disproved capacity as the root cause. The
  follow-up restores the documented 15-second worker-runner idle lifecycle so
  n8n's non-expiring launcher offer owns admission after AP's long native-node
  phase. Worker execution concurrency and all workflow write controls remain
  unchanged. The lifecycle rollout completed across all ten worker runner
  sidecars, and natural execution `111842` finished with zero offer-expiry or
  fatal queue signatures.
- AP v1 supersession note (2026-07-30): workflow `DQRgnMDYERZ2SAOa`, referenced
  by Plans 002 and 003 as their historical workload, is retired and has been
  replaced operationally by AP v2. This retirement does not apply to the shared
  `ap-triage-worker` or `n8n-ap-assistant-bot` runtime services captured under
  `reference/compose/n8n-aws`; both remain current AP v2 dependencies and must
  not be retired, disabled, or removed on the basis of the v1 workflow
  retirement. The N8N repository and live n8n readback remain authoritative for
  workflow ownership and runtime state.
- Plan 004 is retained only as a historical design record. The source delivery
  took a different path and is represented on `main` by `cb424e7` and
  `3919cf5`; its named implementation worktree and branch no longer exist. Do
  not execute the plan's obsolete worktree lifecycle, caps, paths, rollback, or
  integration steps. A fresh plan from current `main` is required for the
  remaining blinded evaluation, authenticated route/privacy checks,
  cost-per-accepted-task evidence, interactive canary, and team rollout.
- Plan 005 starts with one Software Combined workspace on one private ECS
  Fargate task in the existing SCG AWS account. It tests Entra SSO, governed
  chat, controlled file upload, private RAG, product value, cost, recovery, and
  administration effort. SCIM, MCP server onboarding, web search, multiple
  company keys, and the onboarding operator are separate post-pilot proofs.
  Plan 008 records the live MCP-readiness configuration and pending centrally
  administered server connections. Future shared-instance
  company workspaces are soft access and cost partitions, not hard tenants;
  portcos that need a real trust boundary receive a dedicated Fargate
  deployment.
- Plan 011 is the umbrella for Plans 012-024, but its roadmap does not reopen
  any parked or pending slice. The retained source path is
  pinned-v0.10.2-derivative -> 013-policy -> 014 -> 015-plumbing. Plan 013's
  admin-issued API-key grant, claim, rotation, revocation, and legacy-cutover
  lifecycle remains pending. Reusable
  provider-neutral source profiles/contracts/compiler/tests now cover NetSuite,
  monday, and Attio, while the production manifest and generated production
  contract remain NetSuite-only. Connector Plans 016-019 are not currently
  releasable; after explicit owner reopening their designs are technically
  separable but must be piloted serially so each OAuth flow informs the next.
  monday/Attio registration, verified
  identities, live catalogue/schema readback, deployment approval, and two-user
  acceptance remain pending. Plans 020-024 branch from that trusted base; no
  slice authorizes a combined big-bang deployment.
- Plan 006 keeps the Last Yard worker on the existing private n8n host as a
  bounded exception to the Fargate default. The worker has one caller, needs
  the existing Docker-private name, and requires a hard no-backup session
  ceiling; a digest-pinned sidecar was historically the smallest deployable shape; the current sidecar uses disk-backed sessions and /tmp with no tmpfs.
  It must move with n8n when the runtime becomes ECS/Fargate, and durable lake
  storage remains a separate post-Finance-acceptance design.
- Plan 026 keeps pruning with the worker that owns the session-store lock and
  policy. It removes the unaccepted systemd installer and reuses Plan 007's
  existing digest-bound healthy-worker replacement and rollback boundary.

## Findings considered and rejected

- Reusing the personal `~/.config/scg-agent-git-hooks` directory directly was
  rejected because it is SCG/path-coupled and lacks deterministic secret scanning.
- Claiming that the starter itself installs or proves three-model enforcement was
  rejected; the target setup instruction requires a deterministic repo-native
  implementation and disposable Git verification.
- Automatic tool acquisition inside a commit hook was rejected because hooks must
  not download mutable or unverified software during a commit.
- Hard-coding a GPT-, GLM-, or Kimi-led stack from benchmark rankings was
  rejected. Sol, Luna, GLM 5.2, Kimi K2.7 Code, MiniMax M3, and DeepSeek V4
  Flash enter role-specific quality/safety gates before cost is revealed.
- Selecting the lowest token price was rejected. The economic measure is billed
  cost per accepted task, including retries, failed tests, review rework, and
  human corrections.
- Treating three different model vendors as a review invariant was rejected.
  The safety contract is three independent read-only lanes bound to the exact
  staged tree with honest model/effort receipts. Normal/elevated aliases share a
  lane cap when the runtime cannot select effort per call.
- A dedicated EBS session volume was rejected for the Beacon pilot because the
  reports are intentionally retained on the operator's local machine, not on
  the production host. EBS would add KMS, snapshot exclusion, attachment,
  mount, backup, and recovery machinery while still requiring an independent
  deletion process. Bounded tmpfs supplies the required physical byte ceiling
  and disappears when the worker stops.
- A public or Fargate worker endpoint was rejected for this slice because the
  only caller is the existing EC2-hosted n8n service. It would create public or
  VPC ingress, DNS, IAM, and service-discovery surfaces with no current user
  value. The exception has an explicit reevaluation condition in Plan 006.
- A separate systemd prune script, service, timer, lifecycle journal, CLI/SSM
  action family, and rollback state machine were rejected for worker-session
  retention. They duplicate deployment ownership, cannot delete while the
  worker is stopped because they use `docker exec`, and introduced unresolved
  pre-journal crash windows.
- Extending the existing host deployment transaction to own those systemd
  assets was rejected because it widens a proven single-overlay/image boundary
  into a host package manager. A worker background-task framework was also
  rejected because the existing 30-second non-blocking health call already
  supplies the required periodic trigger.

## Router plans 034-068: reconciled 9 September 2026, 068 added 10 September 2026

The [roadmap](2026-09-09-router-roadmap.md) owns remaining requirements,
sequencing, evidence and acceptance gates. Read individual plans for execution
detail. Original source excerpts are dated: rebase their intent onto current
source, never recreate an already integrated predecessor.

Seven plans have delivered their principal source work, two designs are parked
or superseded, and 25 plans or umbrella plans retain work. These are not 25
independent implementations: the owner mapping prevents duplicate execution.

| Plan | Current status | Remaining owner / next action |
|---|---|---|
| [034](034-codex-router-own-repository-and-governance.md) | Repository/package/CI delivered; governance incomplete | 054 owns branch-protection/publisher controls; verify target before changes |
| [035](035-codex-router-startup-self-check-state-home-and-logging.md) | Startup/state/structured logging delivered | 060 owns content safety; 058 closes supervisor-log retention documentation |
| [036](036-codex-router-handler-characterisation-tests.md) | DONE: handler characterization | Preserve tests through 062 |
| [037](037-codex-router-provider-interface-and-handler-decomposition.md) | DONE: provider interface | 062 extends domain ownership without replaying original extraction |
| [038](038-codex-router-single-model-registry.md) | DONE: registry | 064 owns projection consistency |
| [039](039-codex-router-live-merged-catalogue.md) | PARKED: live catalogue route not proven | Keep static merged catalogue; reopen only on actual supported client fetch |
| [040](040-codex-router-credential-lookup.md) | DONE: ordered credential lookup | 055/057 own new writer/recovery/ACL requirements |
| [041](041-codex-router-installer-and-auto-updater.md) | PARTIAL: versioned install/update/rollback source and owner-Mac layout exist | 050, 054, 057-059 own remaining operational/platform acceptance |
| [042](042-codex-router-docs-and-release-hygiene.md) | Original docs rewrite delivered; current README inaccurate | 058 Stage 5 is the active correction owner, coupled with pinned docs tests |
| [043](043-codex-router-no-subscription-mode.md) | PARTIAL: no-subscription CLI route exists | Desktop sign-in decision, isolated install and native-services tolerance proof |
| [044](044-codex-router-full-capability-parity.md) | PARTIAL: capability plumbing/probe harness exists | 064 projection fix then approved per-model/client capability probes |
| [045](045-codex-router-continuous-release-and-seamless-restart.md) | PARTIAL: drain/socket/update source exists | 054 owns branch publishing and observed 15-minute update; 058 cross-OS acceptance |
| [046](046-codex-router-model-onboarding-at-scale.md) | PARTIAL: model add/remove/check/preview exists | Manual unseen-model picker proof; hourly refresh follows authenticated update acceptance and its live-change gate |
| [047](047-router-remediation-handover.md) | PARTIAL umbrella; source C/D fixes integrated | B recovery via 050; A delivery via 054; E/F/G replaced by 049/053/055-059 |
| [048](048-router-managed-key-provisioning.md) | SUPERSEDED design; retain relevant acceptance requirements | 054/055 own onboarding, budgets, revocation, Business/Enterprise and person isolation; no old invitation service |
| [049](049-agent-plugin-and-three-os-installation.md) | TODO umbrella: shared installer and Codex plugin | 063/059/056/057 foundations; 053 Claude plugin; 054/055 distribution; all three OS staff gates |
| [050](050-router-service-recovery-and-update-readiness.md) | PARTIAL: healthy owner-Mac versioned service and both launchers observed | Fresh readback; real successful update + rollback evidence, no replay of old repair |
| [051](051-claude-cli-and-desktop-gateway-setup.md) | TODO: separate Claude CLI and desktop setup | 063 activation seam; preserve native auth and independent discovery/restoration |
| [052](052-claude-billing-probes-and-release-acceptance.md) | TODO: Claude tool and billing acceptance | 051 plus paid authority; CLI and desktop each tested |
| [053](053-claude-code-private-plugin.md) | TODO: private Claude plugin | 063 then 051 client contract; local package before 054 publication and 052 acceptance |
| [054](054-group-distribution-private-feed-and-auto-update.md) | TODO: private distribution and identity onboarding | 067/056/059/063 source reused; AWS/DNS, Team decision, publisher and machine gates |
| [055](055-central-key-federation-and-first-use-key-window.md) | TODO: central keys and first-use recovery | Stage 3 independently first; operator path then 054 Stage 4 for automated issuance |
| [056](056-installer-platform-backends-refactor.md) | TODO: platform backends | After 067; own actual backend modules and shared OS CI |
| [057](057-windows-install-and-service-support.md) | TODO: Windows support | Stage 1 refusal early; 056/059/063 for remaining source; named Win11 x64 and entry-policy proof for acceptance |
| [058](058-recipient-readiness-for-windows-and-linux.md) | TODO: recipient preflight, native acceptance and README | Wrong-today docs now; native preflight before runtime download; consumes 056/057/059 |
| [059](059-python-314-interpreter-provisioning.md) | TODO: private CPython 3.14 runtime | Single pinned lock/native wrappers, isolated bootstrap then 054 mirror; ongoing patch owner required |
| [060](060-content-safe-router-diagnostics.md) | TODO: content-safe diagnostics | First small source fix; synthetic regression already reproduced |
| [061](061-domain-rules-and-bundle-contracts.md) | DONE: domain map, boundary tests, bundle closure, 3.9 grammar gate (2026-09-10) | `3bed26d` + extraction follow-ons on develop; 062/064 unblocked under the rules |
| [062](062-protocol-and-upstream-boundaries.md) | DONE: transport leaves + explicit protocol dispatch (2026-09-10) | `a40dcc7` on develop; 112 contract tests OK; 064 consumes the seam next |
| [063](063-client-activation-and-subscription-policy.md) | DONE: Codex adapter extracted, service-only route, independent subscription modes (2026-09-10) | `f5cf136`+`b40f82e` on develop; 107 focused tests OK; 051/053 consume the seam next |
| [064](064-model-facts-and-client-projections.md) | DONE: one metadata/projection owner each; claude.py move deferred to 051/053 (2026-09-10) | `0d0634f` on develop; 104 focused tests OK; step 4 note in plan |
| [065](065-kiro-client-compatibility-spike.md) | DONE: negative spike, no verified Kiro inference hook (2026-09-10) | `docs/kiro-compatibility.md`; IDE and CLI separately decided; reopen only on dated official custom-endpoint evidence |
| [066](066-mixed-provider-agent-instruction-delivery.md) | TODO: mixed-provider instruction delivery | Early containment/capture; real plaintext delivery remains separate from file-brief workaround |
| [067](067-installer-updater-extraction.md) | DONE: updater extracted to `packaging/updater.py` (2026-09-10) | `8808349` on develop; 50 focused tests OK plus release-bundle omission smoke; 056 unblocked |
| [068](068-portco-model-policy.md) | TODO: per-portco model allowlists as resolved data | Amends 046/064/055; no groups on the machine; Stage 0 tests first, then grant/loader/picker/routing/refresh/docs |

### Consolidated decisions and dependencies

- Private relocatable CPython 3.14 is the target already selected in 049/054;
  059 implements and maintains it. Do not install system packages as root.
- Use one installer, platform manager family, runtime lock, bootstrap pair,
  client receipt/status contract and release workflow. Local synthetic
  artifacts unblock source work before AWS or staff-machine acceptance.
- Installer writers serialize: 067 → 056 → 063, with 059/057 rebasing as needed.
  061 protects extracted-bundle closure before adding nested modules.
- 054 owns private S3/CloudFront at `dist.softwarecombined.com`, Entra/member/B2B
  download access, branch-to-channel publishing, token rotation and the
  publisher-control decision. 055 owns Management API keys, person budgets and
  recovery. Shared feed access never authorizes key issuance.
- 054 Stage 4 is included in the complete backlog because 055 Stage 4 depends
  on its per-install identity; it is later-stage work, not a first-install gate.
- A named Windows machine gates native acceptance, not offline source work.
  Windows entry must work under the actual device policy without bypass.
  A plugin invoking the same blocked script is not a proven remedy.
- Preserve CLI/IDE-only no-subscription scope until desktop sign-in is checked.
  Native Claude auth and Anthropic-via-OpenRouter are separate routes.
- Read upstream Codex/OpenCode/Claude sources per AGENTS.md section 9, pinned
  to commit/version; use official Kiro evidence under 065. No invented API.
- Required reviews use the current on-disk model table and skill. The
  file-brief audit workaround succeeded once, with served identity
  `unverified`; direct encrypted mixed-provider briefs remain broken.

### Open execution gates

See the roadmap's gate register for exact scope: Windows and Linux/Arch staff
targets, Windows entry policy, private-runtime maintenance owner, AWS/DNS/Entra
authority, GitHub Team and repository-access changes, publication/cutover,
paid client/billing probes and production per-user key operations. Plans and
this index do not themselves authorize those actions. Continue independent
source work while an external gate is pending.

### Findings considered and rejected

- A full rewrite, universal message format, dynamic plugin framework, renamed
  homes/services, or duplicate installers: bounded existing seams suffice.
- `router_launch.py` and `update_launch.py` are separate contracts, not
  accidental duplicates. `opencode_auth` is an intentional credential fallback.
- The installer Windows uninstall blocker is not the direct `disable.py`
  service call: installer restore passes `ROUTER_RESTORE_ONLY=1`.
  Standalone disable still needs the shared backend contract.
- Systemd/container Linux lifecycle evidence is useful but not native desktop
  or staff-machine acceptance; old Linux-uninstall memory is superseded.
- Do not remove README's runtime-file list without updating its pinning test
  and proving bundle closure. 058 owns the correction, 061 the artifact gate.
- Native OpenRouter multi-agent v1 metadata does not prove plaintext delivery
  from a v2 parent. 066 replaces that earlier assumption.
- Do not promote Muse audio or any capability from metadata alone. 044
  reconciles advertised capabilities with actual probe evidence after 064.
- Kiro MCP/tool integration is not proof of custom inference support.
- No new signing ceremony, request cap, inference proxy, old invitation
  service, or unapproved hourly model hot-reload.
- Retired Muse duplicate drafts are in [rejected-muse-retry](rejected-muse-retry/README.md);
  they are provenance, not active numbered plans.

## Optimisation plans 068-072: 10 September 2026

The [optimisation audit and adjudication](2026-09-10-router-optimisation-audit.md)
records the evidence, limitations and the independent
[Opus 5 high review](2026-09-10-opus-optimisation-review.md).
All five are planning deliverables at source `83a5023`; no runtime optimisation
has been implemented or deployed by this planning task.

| Plan | Outcome | Priority / effort | Depends on | Status |
|---|---|---|---|---|
| [068](068-router-latency-measurement.md) | Separate body/preparation, connection, upstream wait and forwarding metrics | P1 / S-M | None | TODO |
| [069](069-router-streaming-identity-inspection.md) | Preserve incremental forwarding during optional identity inspection | P1 / M | 068 for live attribution; offline regression independent | TODO |
| [070](070-discovered-schema-deduplication.md) | Deduplicate cached schemas without changing effective tools | P2 / S | None | TODO |
| [071](071-upstream-connection-reuse-experiment.md) | Measured go/no-go for connection reuse | P3 / S investigation | 068 evidence, 069 | TODO: investigation only |
| [072](072-client-cancellation-investigation.md) | Establish material residual cancellation delay and a safe signal | P3 / S-M investigation | 068 evidence, 069 | TODO: investigation only |

Recommended order: 068 then 069; 070 can proceed independently with separate
write ownership. 071/072 can finish with NO-GO or EVIDENCE-UNAVAILABLE; they do
not authorise runtime pooling, active cancellation or paid probes. Serialize
future transport writers. Reuse Plan 060 privacy, Plan 062 domain boundaries and
Plan 045 drain behavior; do not duplicate their implemented source work.

Rejected directions: cross-request caching of served-model identity; an async
rewrite without measured need; arbitrary schema eviction; automatic replay of
paid POSTs; calling a socket reset a client disconnect without its I/O phase;
or claiming absent upstream timeouts (the existing operation timeout is 120 s).
