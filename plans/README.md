# Implementation Plans

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

## Codex model router plans (034 to 048), added 2026-09-07

Written after a read-only audit of `domains/ai-platform/codex-model-router` at
commit `749a6b8d` on branch `codex/codex-adapter-20260907` (the router is not
on `main`; the branch is pushed, no pull request), the deployed copy in
`~/.codex/mixed-model-router`, its logs (10,609 structured lines), a live probe
of the running service, the Codex desktop binary (`codex-cli 0.153.4`) and the
live OpenRouter model metadata. Baseline: 58 unit tests pass at `749a6b8d`
(`/opt/homebrew/bin/python3 -m unittest discover -s domains/ai-platform/codex-model-router -p 'test_*.py'`).
Plan 034 moves the router into its own repository; the plans are written to
travel with the code, so copy `plans/034-*` to `plans/046-*` into the new
repository's `plans/` and continue there. Paths inside the plans use
`ROUTER_ROOT` for the router directory before and after the move.

### Execution order and status

| Plan | Title | Priority | Effort | Depends on | Status |
|------|-------|----------|--------|------------|--------|
| 034 | Own product repository, package layout, governance, CI | P1 | M | none (two operator decisions) | DONE |
| 035 | Startup self-check, `ROUTER_HOME`, timestamped rotating logs, `/health` version and inflight | P1 | S | none | DONE |
| 036 | Handler characterisation tests (ten end-to-end tests, fake upstream) | P1 | S | 035 | DONE |
| 038 | Single model registry, quirks as data, generated OpenRouter catalogue entries | P1 | M | 036 | DONE |
| 037 | Provider interface and thin relay handler | P2 | M | 036, 038, 035 | DONE |
| 040 | Ordered credential lookup (env, key file, OpenCode fallback), startup fail-closed | P1 | S | 035 (037 either order) | DONE |
| 043 | No-subscription mode: spike three Codex login shapes, `openai_mode`, local native services | P1 | M | 037, 038 | IN PROGRESS (spike ran 2026-09-08 on Codex 0.153.4: Shape C custom provider works with no login, thread+turn reach the router with bearer auth; `openai_mode` + local 404 services + path-token none-mode config + probe `--provider` + docs landed in source; source boxes verified 2026-09-09; desktop sign-in check + sandboxed live install proof per owner 2026-09-09; GPT Teams likely, so no-subscription path stays CLI/IDE-only) |
| 039 | Live merged catalogue served by the router, retire the snapshot file | P2 | M | 038, 037, 035, 043 (fallback rules) | BLOCKED (Step 1 no-go: no /models fetch observed; static-file fallback retained per 2026-09-08 audit brief until a replacement is proven) |
| 041 | Versioned release bundle, stdlib installer, health check and rollback, update agent | P1 | L | 034, 035, 040 (039 optional) | IN PROGRESS (installer/updater landed in source, never deployed to a versioned layout; fleet updates need the 047-A feed decision) |
| 045 | Release on every push to `main`/`beta`, 15-minute updates, drain and socket-activated restart | P1 | M | 041 | IN PROGRESS (drain + socket activation landed; push-to-release and the live 15-minute loop need the 047-A feed decision and the 047-B cutover gate) |
| 044 | Full capability parity from live metadata, probe-gated (audio, limits, summaries, freeform patch, web search) | P2 | M to L | 038, 037 (039 for live entries) | IN PROGRESS (partial: registry flags, live_refresh, `models add`, probe media/effort/deferred legs plus offline reasoning-summary/apply-patch/web-search/experimental-tools legs with harness coverage landed; paid per-model probes pending) |
| 046 | Model onboarding at scale: `models add` command, preview tier, hourly remote model list, CI validation | P1 | M | 038, 039, 044, 045 | IN PROGRESS (partial: `models add` + preview tier + compat record + isolated verify landed; source boxes verified 2026-09-09; hourly hot-reload deferred per 2026-09-08 audit brief pending versioned-update proof; manual seventh-model check needs the live gate) |
| 042 | Documentation rewrite, compatibility matrix, retire manual release artefacts, vault note | P3 | S | 035, 038, 039, 040, 041, 046 | DONE (docs rewrite landed; two inaccurate plan-text claims corrected in-file 2026-09-08) |
| 047 | Router remediation handover: working delivery, versioned cutover, protocol fixes, installers, key window | P0 | L | 041, 045 | IN PROGRESS (source merged to main 9bbdc28: feed serial and signatures, catalogue seeding wired into installer, protocol C/D fixes, pointer-file releases, launcher in bundle, shutdown, setup key claim, none-mode auth, probe provider flag, guidance via current_release_dir; live cutover remains; feed = AWS 651116729473 ap-southeast-2 (owner 2026-09-09, key home TBD); macOS/Windows signing deferred, plugin route to investigate instead of paid certs; Linux install notes expected via contributor PR) |
| 048 | [Invitation-only managed OpenRouter keys across portcos](048-router-managed-key-provisioning.md) | P1 | L | 040, 037, 041; account/auth/distribution preflight | IN PROGRESS (owner 2026-09-09: IT issues one OpenRouter key per portco user, pasted once into the setup window; full provisioning service not built) |

Status values: TODO | IN PROGRESS | DONE | BLOCKED (one-line reason) | REJECTED (one-line rationale).

### Dependency notes

- Plan 048 (owner decision 2026-09-09): IT issues one OpenRouter key per portco
  user, pasted once into the setup window; the full provisioning-service design
  below is retained for reference only and its slice order no longer applies.
  It does not reopen 039/046.
  Its observed release/distribution preflight supersedes older assumptions for
  this rollout; the plan itself does not authorise publishing or account writes.
- 036 before 037: the ten characterisation tests are the acceptance suite for the refactor and must pass with unchanged assertions.
- 038 before 037: providers look models up through the registry (`by_slug`).
- 043's spike (Step 1) should run early, right after 037 and 038 land, because its outcome (which Codex login shape works without a subscription) changes what 039 falls back to and what 041 writes into the Codex configuration.
- 041 before 045: 045 replaces 041's update cadence, release trigger and restart, but relies on its installer core.
- 044 runs paid probes per model; do it after 039 so the generated entries are live and one restart shows the result.
- 046 after 044 and 045: it reuses the probe flags and the release feed, and it is what makes "enable more models as we go" a data change instead of a release.
- 042 last; it documents what actually landed.

### Decisions required from Cyril

1. Repository name and visibility (Plan 034 Step 1). Settled in practice: `software-combined/SC_Codex_openRouter_adapter`, private. The public recommendation was not adopted, so the 047-A feed design must serve updates without anonymous GitHub access.
2. Request cap: SETTLED 2026-09-08. Removed; the `No request cap` CI step fails the build if it returns. There is no local spend cap: see the KnowledgeVault picker note before promising budget behavior.
3. Whether CLI and IDE only is acceptable for no-subscription staff if the desktop app turns out to require ChatGPT sign-in (Plan 043 Step 1).
4. A named Windows test machine before any Windows work (Plan 041 Step 9).
5. Approval to edit the KnowledgeVault note (Plan 042 Step 5) and to make the first push to `main` that becomes an automatic release (Plan 045).

### Findings considered and rejected or deferred

- Central AWS hosting of the whole router: rejected for now. It would carry every staff member's ChatGPT bearer through a shared service, needs real per-user authentication instead of a path token, adds a network hop to request bodies of up to 1.5 MB, and Codex's catalogue still has to be answered locally. Revisit only as an OpenRouter gateway with per-user sub-keys and spend limits, which the provider interface from Plan 037 makes possible.
- Video and file input modalities: not actionable. Codex's client only knows `text`, `image`, `audio`; Codex reads files through its own tools.
- `tool_mode = code_mode_only` and multi-agent `v2` for OpenRouter models: rejected per the trial evidence recorded in the KnowledgeVault note (code mode is not a substitute for provider compatibility; v1 plaintext sub-agents are the proven setting).
- OpenAI API-key mode (`openai_mode = api_key`): deferred until someone without a subscription but with an API key asks (Plan 043 notes).
- Signed release manifests and keychain-backed credentials: historical deferral
  superseded for managed installations by Plan 048. Personal installs retain
  their existing credential behaviour; managed rollout has its own OS-store,
  publisher-verification and private-repository distribution gates.
- The transient 7 September outage (state key missing after a deploy): fixed the same evening by the owning session; not planned, but it is the reason for Plan 035's startup self-check and Plan 041's health-checked rollback.
