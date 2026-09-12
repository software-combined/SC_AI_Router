# Implementation Plans

The router backlog. Renumbered 2026-09-10: the live set is **090-140** — the core
backlog **090-121**, the refactor wave **122-134** from the 2026-09-11 four-lane
refactoring/reorganisation audit, the new-model prompt plan **135**, the
security wave **136-138** from the 2026-09-11 router external security audit
(`2026-09-11-router-external-security-audit.md`), and the publication wave
**139**, the standalone delegation delivery plan **140**, plus the amended
Claude plans 113-115 and 120-121 from the 2026-09-11
Claude router development-branch review
(`2026-09-11-claude-router-development-branch-review.md`). The
recommended overall execution order is below the tables. The pre-renumbering 034-089 series is
archived: completed plans were removed from the tree (git history and the dated
reports preserve them), parked decisions moved to `parked/`, and the old-to-new
mapping is at the bottom of this file. Dated audit, roadmap and brief files at the
top level are historical snapshots and keep the old numbering.

Executor rules for every plan:

- One writable worktree per session, based on `develop`, integrated back to `develop`.
- Run the plan's drift check first; reconcile the cited lines or STOP as the plan says.
- Verify with `python3.14 -m unittest discover -s tests -t .`,
  `python3.14 -m compileall -q ai_router tools tests packaging`, and
  `python3.14 tools/check_source_limits.py`; run the shared `pre-commit-review`
  before every commit; update the plan's status row here when done.

## Live backlog (execution order)

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [090](090-router-ingress-lifecycle-hardening.md) | Ingress lifecycle: request timeout, drain accounting, single listener | DONE: ingress lifecycle hardening 2026-09-11 | supersedes 109's `allow_reuse_port` fallback |
| [091](091-router-adaptation-stream-fast-path.md) | Adaptation fast path: no re-serialize when unchanged | DONE: adaptation fast path 2026-09-11 | — |
| [092](092-router-test-suite-hygiene.md) | Offline test suite, isolated home, three guard tests | DONE: offline test suite + ingress guard tests 2026-09-11 | coordinate with 105 |
| [093](093-router-prepare-path-serialization.md) | Prepare/failure path: no double serialization or re-parse | DONE: prepare-path serialization 2026-09-11 | — |
| [094](094-router-atomic-write-consolidation.md) | One atomic writer for installer state/config | DONE: atomic writer consolidation 2026-09-11 | — |
| [095](095-router-activation-receipt-consolidation.md) | One writer for the activation receipt | DONE: activation receipt consolidation 2026-09-11 | depends 094 |
| [096](096-router-streaming-robustness.md) | SSE frame cap and mid-stream error containment | DONE: streaming robustness 2026-09-11 | — |
| [097](097-router-discovered-lock-scope.md) | Narrow the discovered-recall lock scope | DONE: discovered lock scope 2026-09-11 | — |
| [098](098-router-model-refresh-bindings.md) | Refresh-safe registry consumers | DONE: refresh-safe registry consumers 2026-09-11 | before 099 |
| [099](099-codex-router-model-onboarding-at-scale.md) | Model onboarding: one-command add, data-driven dispatch, refresh wiring | PARTIAL | 098 landed; refresh wiring awaits 106's qualified feed, then publish `models_url`; wiring must also fix `model_refresh.apply()` swap publication order (see plan 098) |
| [100](100-router-retired-slug-single-source.md) | Shared retired-subscription slug set | DONE: retired-slug single source 2026-09-11 | depends 094 |
| [101](101-router-dead-code-and-lint-gate.md) | Delete dead code; add F401/F811 gate | DONE: dead code + F401/F811 lint gate 2026-09-11 | before 102/103 |
| [102](102-router-install-option-collapse.md) | Collapse installer option handling below the cap | DONE: installer option collapse 2026-09-11 | serialize with 103 |
| [103](103-router-darwin-backend-extraction.md) | Move launchd helpers out of service.py | DONE: darwin backend extraction 2026-09-12 | serialize with 102; before 104 |
| [104](104-router-docs-metadata-correction.md) | Version, architecture and README corrections | DONE: docs/metadata corrections 2026-09-12 | after 103; coordinates README with 117 |
| [105](105-python-314-interpreter-provisioning.md) | Provision and maintain a private CPython 3.14 runtime | PARTIAL | Stage 1 in; hardening + maintenance owner left |
| [106](106-group-distribution-private-feed-and-auto-update.md) | Group distribution, private feed and auto-update | PARTIAL | publication split into 139 (tag-driven, GitHub Releases kept; runtime mirror and bootstrap published); group gating and the library page left here |
| [107](107-central-key-federation-and-first-use-key-window.md) | Central per-user key federation and first-use key window | PARTIAL | Stage 4 depends 106; Stage 2 installer acceptance left |
| [108](108-router-service-recovery-and-update-readiness.md) | Live router recovery and safe update readiness | PARTIAL | live update/rollback evidence; serialize with 109/110 |
| [109](109-codex-router-continuous-release-and-seamless-restart.md) | Continuous release and seamless restart (live evidence) | PARTIAL | live restart evidence; release-trigger conflict settled by 139: tags publish, no push-to-main release |
| [110](110-codex-router-installer-and-auto-updater.md) | Versioned installer and auto-updater acceptance | PARTIAL | acceptance owned with 105/106/108/116/117 |
| [111](111-codex-router-no-subscription-mode.md) | No-subscription mode for staff | PARTIAL | desktop sign-in + isolated install proof left |
| [112](112-agent-plugin-and-three-os-installation.md) | Plugin and three-OS installation | PARTIAL | plugin publication + staff acceptance left |
| [113](113-claude-cli-and-desktop-gateway-setup.md) | Claude CLI and desktop qualification | PARTIAL | CLI/desktop qualification left; amended 2026-09-11 (per-surface setup, billing policy F5, superseded claims) |
| [114](114-claude-code-private-plugin.md) | Claude Code private plugin: validation and publication | PARTIAL | after 113; local validation then publication; amended 2026-09-11 (same-version attach/repair F1, preflight F2, key window F3, restore F4, desktop distribution W4) |
| [115](115-claude-billing-probes-and-release-acceptance.md) | Claude billing and tool-execution probes | TODO | after 113; paid authority; amended 2026-09-11 (per-surface routes, real MCP proof, ingress contract F8/F9) |
| [116](116-windows-install-and-service-support.md) | Windows install and service support (acceptance) | PARTIAL | sign-out/in + later stages left |
| [117](117-recipient-readiness-for-windows-and-linux.md) | Linux and Windows recipient readiness | PARTIAL | native desktop acceptance + Stage 5b left; the README 503/Claude-listing claims were corrected by plan 104 — do not re-edit those passages |
| [118](118-codex-router-full-capability-parity.md) | Capability parity: paid per-model/client probes | PARTIAL | remaining paid per-model legs |
| [119](119-mixed-provider-agent-instruction-delivery.md) | Mixed-provider agent instruction delivery | PARTIAL | paid live probe left |
| [120](120-claude-desktop-gateway-discovery-and-attach.md) | Claude desktop gateway: release and live picker proof | PARTIAL | extends 113; source merged (PR 56); amended 2026-09-11 (safe lifecycle F4/F7, no promotion of the listener probe) |
| [121](121-claude-desktop-models-effort-and-connectors.md) | Claude desktop models, effort readout, and connectors (planning) | PLANNING | amends 113/120; amended 2026-09-11 (blockers before descriptions, connector/tool-search/marketplace rewrite) |

## Refactor and feature wave (122-135)

Added 2026-09-11: 122-134 from the refactoring/reorganisation audit, 135 from the
update-prompt request. Each plan depends on the core plans listed; the overall order
below interleaves them.

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [122](122-plan-hygiene-sweep.md) | Backlog hygiene: runnable drift checks, current paths and counts | DONE: backlog hygiene sweep 2026-09-11 | before 094/101/102/103 |
| [123](123-packaging-plumbing-single-sources.md) | One 3.9 loader, one release inventory, one subscription roster | DONE: packaging plumbing single-sources 2026-09-11 | before 094; pairs with 100 |
| [124](124-test-harness-consolidation.md) | Shared test harness; installer fixtures out of a test file | DONE: test harness consolidation 2026-09-12 | after 092 |
| [125](125-runtime-shared-primitives.md) | Runtime primitives: path sets, image blocks, catalogue predicate, capability maps | DONE: runtime shared primitives 2026-09-12 | after 090/091/093/096/101 |
| [126](126-error-taxonomy.md) | Typed error classification; drop the dead CLI error half | DONE: typed error classification 2026-09-12 | after 101 |
| [127](127-providers-setup-module-splits.md) | Split upstream failure policy and setup pages out | DONE: landed by 141 2026-09-11 | after 101; before 128 |
| [128](128-router-handler-decomposition.md) | Decompose router.py into ingress + relay | DONE: router decomposition 2026-09-12 | after 090/091/093/096 |
| [129](129-tool-merge-unification.md) | One tool-definition merge rule | DONE: shared tool-merge rule 2026-09-12 | after 091/096/097 |
| [130](130-installer-bundle-split.md) | packaging/bundle.py: real installer headroom | DONE: installer bundle split 2026-09-12 | after 102/123 |
| [131](131-service-state-writer-decomposition.md) | Service/state/writer decomposition | PARTIAL: writer leaf, sinks and the state-read contract landed 2026-09-12; service split and diagnostics/key privacy left | after 094/095/100/103/123; coordinate 106 |
| [132](132-windows-backend-cleanup.md) | Windows backend cleanup | TODO | before/with 116; after 123 |
| [133](133-probe-harness-consolidation.md) | One app-server probe harness | DONE: shared AppServer harness 2026-09-12 | before 118/119 |
| [134](134-repo-hygiene-feed-ci-docs.md) | feed_verify move, CI single owner, docs index, shim owner | DONE: repo hygiene 2026-09-12 (verifier in packaging/, one setup composite + policy-scan script, kiro pointer, shim owner, tools/ rule); CI-side run of the composite pends the first push | after 101; before 106 (feed work) |
| [135](135-new-model-prompt.md) | New-model prompt: notify + one-click Codex restart only when new models appear | TODO | after 128/131; hooks into 099; coordinate 106 |

## Security wave (136-138)

Added 2026-09-11 from the three-model external security audit of the loopback
router's exposure surface (Kimi K3 `max`, GLM 5.3 `max`, Qwen 3.8 Max `xhigh`).
The report, its verifications and its rejected findings are in
`2026-09-11-router-external-security-audit.md`.

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [136](136-unauth-ingress-crash-containment.md) | Contain the unauthenticated ingress compare crash | DONE: unauth ingress compare containment 2026-09-11 | P1; independent; a few lines in router.py (398 today) |
| [137](137-loopback-host-header-validation.md) | Validate the Host header on loopback ingress | TODO: unblocked by 128 (router.py 204/400); the guard belongs in ingress.py | 090 landed; 128 landed |
| [138](138-subscription-cookie-hygiene.md) | Drop Cookie on subscription passthrough and make the tests honest | DONE: subscription cookie hygiene 2026-09-12 | independent |

## Standalone delegation delivery (140)

Added 2026-09-11 after cross-task messages stopped reaching tasks on
OpenRouter models: the standalone app-injected output shape was dropped as an
orphan tool fragment.

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [140](140-standalone-delegation-output-delivery.md) | Deliver standalone delegation outputs to OpenRouter models | DONE: live acceptance 2026-09-11 on router 0.6.27.44 (deepseek child echoed the marker) | P1; independent; OpenRouter prepare path only |

## Tool alias resilience (145)

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [145](145-router-tool-alias-repair.md) | Namespaced tool aliases: readable, repaired, self-explaining | DONE: tool-alias resilience 2026-09-12 (source) | independent; paid probe leg after deploy |

## Publication wave (139)

Added 2026-09-11: the tag-driven feed publication that makes installed
routers update without repository access. Plan 106 keeps the first-install
and group-distribution work; this plan owns the update path only.

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [139](139-router-private-feed-publication.md) | Private feed publication: tag publishes to the token-gated feed | PARTIAL: feed live (stacks deployed, token seeded, 0.6.25 transition released); first-install assets published via `tools/publish_first_install.py`; gated library page and per-install tokens stay with 106 | supersedes 106's push-trigger and feed-only variants; before 106's remaining first-install stages |

## Provider abstraction wave (141)

Added 2026-09-11 from the owner request to replace the hard-wired OpenRouter identity with a
definition per upstream. One `ai_router/provider_defs.py` entry plus registry rows must be enough
to add or swap an external provider; no protocol translation is in scope.

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [141](141-provider-abstraction.md) | Provider abstraction: one definition per upstream | DONE: provider abstraction 2026-09-11 (also lands 127's provider and setup-page splits) | independent; 126/128/134 rebase on it |

## Public release wave (142-144)

Added 2026-09-11, amended 2026-09-12: relicence to Apache-2.0, replace the
token-gated update feed with the public token-free feed, and harden the
repository before the visibility flip.

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [142](142-apache-2-public-licence.md) | Relicense the repository to Apache-2.0 only | PARTIAL: source landed 2026-09-11; owner approval and prompt-file provenance before merge | before 143/144 |
| [143](143-enrolment-only-auto-update.md) | Enrolment-only auto-update | SUPERSEDED 2026-09-12: the public token-free feed replaced it; kept as history | superseded by the owner decision |
| [144](144-public-repo-controls.md) | Public repository controls and visibility flip | TODO: owner-gated | after 142/143 |

## External router review wave (145-148)

Added 2026-09-12 from the read-only review of `duolahypercho/codex-router`
(`2026-09-12-external-router-review.md`, which also records the explicit
rejections, the no-copy rule and the client-catalogue spike).

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [145](145-model-verification-gate.md) | Model verification gate: hidden until probed | DONE: verification gate landed 2026-09-12 (source, uncommitted) | after 133; before 135 stage 2 |
| [146](146-ingress-hardening-wave-2.md) | Ingress hardening, second wave | TODO | after 137; serialize with 135 on `ai_router/router.py` |
| [147](147-operator-surface-doctor-status-rollback-support.md) | Operator surface: doctor, status, rollback, support bundle | TODO | after 131; serialize with 134's CI step |
| [148](148-claude-drift-and-contract.md) | Claude Code drift check and attachment contract | TODO | after 146's guard; coordinate 113/120/121 |

## Carried-history portability (150)

Added 2026-09-12 from the Muse Contributor refusal incident: a ~21 h
DeepSeek thread swapped to Muse was refused twelve times by OpenRouter's
Meta upstream on the carried turn.

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [150](150-carried-history-portability.md) | Carried-history portability for routed models | PARTIAL: slices 2a+2b + coded 409 + refusal cache landed 2026-09-12; bisect complete (a carried reasoning item is the trigger); slices 2c/2d and the Muse row probe stay owner-gated on new evidence | independent; re-probe after client upgrades |

## First-run key window (149)

Added 2026-09-12: the native key window is the intended first-run flow but is
unreachable on the documented bootstrap path (no `--setup` flag, env key
mistaken for service configuration). Number 149 is the next free after the
external-router wave 145-148 on `origin/develop`.

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [149](149-first-run-key-window-reachability.md) | First-run key window reachability | DONE: key window opens on fresh install 2026-09-12 | after 139/141; independent |

## Subagent model visibility (151)

Added 2026-09-12 after the task 01a09477 incident: the Codex client caps the
`spawn_agent` model-override list at five rows taken in catalogue order, so the
roster-first catalogue hides every OpenRouter model from the agent even though
the picker lists them all.

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [151](151-subagent-model-visibility.md) | Subagent model visibility: every catalogue model is delegable | PARTIAL: repo side lands in 0.6.36 (instructions roster + starter rule + tests); owner-machine step, stage 3 and 4-5 open | after 133/145; serialize with 135 on `ai_router/catalogue.py` and this file |

## Recommended overall order

Work top to bottom; stop at owner gates and report. Phases 0-2 are local; 3-5 are largely
owner-gated.

- **Phase 0 (prep):** 122, 123.
- **Phase 1 (core backlog):** 090, 091, 092, 093, 094, 095, 096, 097, 098, 100, 101, 102, 103, 104.
- **Phase 2 (refactor and feature wave):** 124, 125, 126, 127, 129, 128, 130, 131, 134 (rest),
  133, 145, 135 (stage 2), 132, 137, 146, 147, 148, 151 (stages 1-2).
- **Phase 3 (infrastructure, mostly owner-gated):** 105, 106, 107, 099, 108, 109, 110.
- **Phase 4 (clients and OS acceptance, owner-gated):** 111, 112, 113, 114, 115, 116, 117.
- **Phase 5 (paid probes and desktop, owner-gated):** 118, 119, 120, 121, 150.

Phase notes: 099 executes only after 139's feed is qualified; 134's feed_verify move lands before
106 and its CI step after 101; 133 and 132 land before Phase 5 paid probes and Phase 4 Windows
acceptance respectively; 135 exposes the pending-model hook that 099's refresh wiring calls once
it lands, and needs no owner gate itself. The security wave rides Phase 1: 136 and 138 are
independent, and 137 proceeds now that 090 has landed. The provider abstraction (141) rides
Phase 2 and needs no owner gate: it changes no routing behaviour, and 126/127/128 must rebase on
it rather than run alongside it.

External-adoption notes: 135 stage 1 (the client-catalogue spike) is done and recorded in
`2026-09-12-external-router-review.md`; its stage 2 waits for 145 so an unverified row never
prompts a restart. 133 lands before 145 because 145 consumes its `AppServer` client. 137 and 146
both edit the ingress file and its baseline entry: 137 first, then 146 rebases and re-syncs.
135 and 146 both touch `ai_router/router.py`: serialize them in that order.
147's `--check-update` change is a user-visible contract change and must also move the installed
scheduler commands to `--update`. 148 is source and offline tests only; its live proof stays with
113/115/120. Everything in this wave is local: no owner gate except the billed probe runs that
145's harness can perform.

## Dependency and coordination notes

- 094 → 095 and 094 → 100 (the receipt and retired-slug work extend the atomic writer).
- 098 must land before or with 099 (the refresh wiring consumes dynamic reads).
- 101 before 102/103; serialize 102 and 103. 103 before 104.
- 092 and 105 touch the same runtime-lock test area; fix the test (092) before or with
  105 Stage 2.
- 106 before 107 Stage 4. 108/109/110 share owner-Mac update/rollback acceptance —
  serialize them; one writer per machine state.
- 099's hourly refresh leg awaits 139's authenticated/versioned feed; publish
  `models_url` after that.
- 113 is the CLI/desktop contract; 114 (publication) and 115 (paid probes) follow it.
  120 and 121 extend 113.
- 113-115 and 120-121 were amended 2026-09-11 by
  `2026-09-11-claude-router-development-branch-review.md`. The installer
  lifecycle fixes F1-F4 are specified in 112's installer contract and accepted
  by 114 whichever plan executes them; do not run both writers at once.
- Refactor wave: 122 and 123 land first; 124 follows 092; 125 follows the runtime edits
  in 090/091/093/096; 126/127 follow 101; 128 follows 090/091/093/096 and 127; 130
  follows 102; 131 follows 094/095/103 and coordinates 106.
- Cross-wave: 131's writer changes should land before 106's feed work; 132 lands
  before 116's real-machine acceptance; 133 lands before 118/119 paid probes.
- Security wave: 090 landed at `02e8e6e` and left `ai_router/router.py` at 395
  lines, so 136 and 137 both fit under the 400 hard cap (sync the baseline
  entry in each). Execute 136 before 137 and serialize them: both edit
  `authorized_path`, `tests/test_ingress_guards.py` and the router baseline
  entry, so the second to land re-syncs the count after the first. 138 touches
  transport and tests only.
- 135 follows 128 (router cap), 131 (state/writer rules) and 127 (page split); its
  pending-model check is the hook 099's refresh wiring must call; coordinate 106.
  It starts with a client-behaviour spike: if Codex re-reads the catalogue without a
  restart, the owner re-scopes it before any implementation.
- References in older plans to numbers 034-089 are historical: completed numbers
  resolve in the removal log below; renumbered numbers resolve in the old→new map
  below; parked numbers resolve under `parked/`.

## Parked (not approved; reopen only on the stated condition)

- `parked/039-codex-router-live-merged-catalogue.md` — live merged-catalogue route:
  reopen only if a supported client fetch is proven.
- `parked/073-remote-support-companion.md` — not approved.

## Rejected drafts

`rejected-muse-retry/` holds rejected retry drafts kept for provenance only.
Never execute them; their filenames reuse the old number series (its `056-...`
draft is unrelated to the removed router plan 056).

## Transitional shim owner (Plan 134, 2026-09-12)

`codex_router/` stays as a deprecated alias re-exporting `ai_router` (owner:
Plan 134 until a dedicated removal plan names its own owner). A removal plan
may delete it only after an external-consumer search finds no live importer
outside this repository and records the result. Live in-repo importers of the
old name today: none outside `codex_router/` itself (`packaging/router_launch.py`
prefers `ai_router` and falls back to `codex_router` only for pre-rename
installed releases); the `codex_router` log name stays so existing installs
keep working.

## Completed and removed (archived 2026-09-10)

Removed after completion at source: 034, 035, 036, 037, 038, 040, 042, 047,
048 (both files), 056, 060, 061, 062, 063, 064, 065, 067, 068 (both files),
069, 070, 071 (both files), 072 (both files), 074. The dated reports record the
results; git history holds the plan text.

Note: 056's Stage 4 cross-OS CI runners were never built; that residual is
subsumed by Plan 116 Stage 7, and the single-Ubuntu CI scope is a recorded cost
decision (see `.github/workflows/check.yml`).

## Renumbering map (old → new, 2026-09-10)

076→090, 077→091, 079→092, 078→093, 080→094, 081→095, 082→096, 083→097,
084→098, 046→099, 089→100, 085→101, 086→102, 087→103, 088→104, 059→105,
054→106, 055→107, 050→108, 045→109, 041→110, 043→111, 049→112, 051→113,
053→114, 052→115, 057→116, 058→117, 044→118, 066→119, 073→120, 075→121.
Parked without renumbering: 039, 073 (remote-support companion).
