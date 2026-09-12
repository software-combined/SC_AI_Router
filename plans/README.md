# Implementation plans

The router backlog. Every numbered file is a self-contained brief an agent can
execute in one session, and the tables below hold only open work. Completed
plans leave the tree when they land: git history keeps their text and the
removal log at the bottom of this file records each one with its landing date.
The live numbering runs 099-160; the pre-renumbering 034-089 series is archived
and mapped at the bottom. Dated audit, review and brief files in this directory
are historical snapshots and keep their original numbering.

Executor rules for every plan:

- One writable worktree per session, based on `develop`, integrated back to `develop`.
- Run the plan's drift check first; reconcile the cited lines or STOP as the plan says.
- Verify with `python3.14 -m unittest discover -s tests -t .`,
  `python3.14 -m compileall -q ai_router tools tests packaging`,
  `python3.14 tools/check_source_limits.py` and
  `python3.14 tools/check_policy_scans.py`; run the shared `pre-commit-review`
  before every commit; update the plan's status row here when done.
- "Local" work is finished offline by one agent in one session. "Owner-gated"
  work needs the owner's machines, subscriptions, billed probes or a GitHub
  setting, and stops at that point with a report.

## Core backlog (099-121)

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [099](099-codex-router-model-onboarding-at-scale.md) | Model onboarding: one-command add, data-driven dispatch, refresh wiring | PARTIAL | 098 landed; refresh wiring awaits 106's qualified feed, then publish `models_url`; wiring must also fix `model_refresh.apply()` swap publication order (see plan 098) and call the plan-135 prompt check inside the same guarded wrapper after `apply()` |
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
| [117](117-recipient-readiness-for-windows-and-linux.md) | Linux and Windows recipient readiness | PARTIAL | native desktop acceptance + Stage 5b left; the README 503/Claude-listing claims were corrected by plan 104 (landed) and must not be re-edited |
| [118](118-codex-router-full-capability-parity.md) | Capability parity: paid per-model/client probes | PARTIAL | remaining paid per-model legs |
| [119](119-mixed-provider-agent-instruction-delivery.md) | Mixed-provider agent instruction delivery | PARTIAL | paid live probe left |
| [120](120-claude-desktop-gateway-discovery-and-attach.md) | Claude desktop gateway: release and live picker proof | PARTIAL | extends 113; source merged (PR 56); amended 2026-09-11 (safe lifecycle F4/F7, no promotion of the listener probe) |
| [121](121-claude-desktop-models-effort-and-connectors.md) | Claude desktop models, effort readout, and connectors (planning) | PLANNING | amends 113/120; amended 2026-09-11 (blockers before descriptions, connector/tool-search/marketplace rewrite) |

## Refactor and feature wave (131-135)

The 2026-09-11 four-lane refactoring audit produced plans 122-134 and the
update-prompt request produced 135. Everything except the two rows below has
landed.

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [131](131-service-state-writer-decomposition.md) | Service/state/writer decomposition | PARTIAL: writer leaf, sinks and the state-read contract landed 2026-09-12; service split and diagnostics/key privacy left | after 094/095/100/103/123 (all landed); coordinate 106 |
| [135](135-new-model-prompt.md) | New-model prompt: notify + one-click Codex restart only when new models appear | PARTIAL: steps 1-6 landed (`0844c5d`, `f4bfef4`, `27abff5`, trigger commit 2026-09-12), trigger only in the updater; the hourly refresh call lands with 099 | after 128/131; hooks into 099; coordinate 106 |

## Security wave (137)

Added 2026-09-11 from the three-model external security audit of the loopback
router's exposure surface; the report, its verifications and its rejected
findings are in `2026-09-11-router-external-security-audit.md`. Plans 136 and
138 landed.

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [137](137-loopback-host-header-validation.md) | Validate the Host header on loopback ingress | DONE: Host guard first in `ingress.authorized_path` 2026-09-12 | 090 landed; 128 landed |

## Publication wave (139)

Added 2026-09-11: the tag-driven feed publication that makes installed
routers update without repository access. Plan 106 keeps the first-install
and group-distribution work; this plan owns the update path only.

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [139](139-router-private-feed-publication.md) | Private feed publication: tag publishes to the token-gated feed | PARTIAL: feed live (stacks deployed, token seeded, 0.6.25 transition released); first-install assets published via `tools/publish_first_install.py`; gated library page and per-install tokens stay with 106 | supersedes 106's push-trigger and feed-only variants; before 106's remaining first-install stages |

## Public release wave (142-144)

Added 2026-09-11, amended 2026-09-12: relicence to Apache-2.0, replace the
token-gated update feed with the public token-free feed, and harden the
repository before the visibility flip.

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [142](142-apache-2-public-licence.md) | Relicense the repository to Apache-2.0 only | PARTIAL: source landed 2026-09-11; owner approval and prompt-file provenance before merge | before 143/144 |
| [143](143-enrolment-only-auto-update.md) | Enrolment-only auto-update | SUPERSEDED 2026-09-12: the public token-free feed replaced it; kept as history | superseded by the owner decision |
| [144](144-public-repo-controls.md) | Public repository controls and visibility flip | PARTIAL: rulesets on `main`, `develop` and tags, secret scanning with push protection, and the repository metadata applied 2026-09-12 on the owner's instruction (readback in the plan); all-tag protection and Cyril/Brent-only merge/release access applied; existing-tag workflow prepared; next beta acceptance, immutable releases, Gitleaks in CI, `cfn-lint` pin, text audit and the flip remain | after 142; 160 owns the identifiers in source |

## External router review wave (146-148)

Added 2026-09-12 from the read-only review of `duolahypercho/codex-router`
(`2026-09-12-external-router-review.md`, which also records the explicit
rejections, the no-copy rule and the client-catalogue spike). Plan 145
(model verification gate) landed.

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [146](146-ingress-hardening-wave-2.md) | Ingress hardening, second wave | DONE: token strength, 32-request cap, redaction, 415 guard, opencode confinement, ACL verdict TTL 2026-09-12 | after 137; serialize with 135 on `ai_router/router.py` |
| [147](147-operator-surface-doctor-status-rollback-support.md) | Operator surface: doctor, status, rollback, support bundle | DONE: `--doctor` row registry, state-backed `--status`, read-only `--check-update` with `--update` applying, rollback listing, redacted `--support` 2026-09-13 | after 131; serialize with 134's CI step (landed) |
| [148](148-claude-drift-and-contract.md) | Claude Code drift check and attachment contract | TODO | after 146's guard; coordinate 113/120/121 |

## Carried-history portability (150)

Added 2026-09-12 from the Muse Contributor refusal incident: a ~21 h
DeepSeek thread swapped to Muse was refused twelve times by OpenRouter's
Meta upstream on the carried turn.

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [150](150-carried-history-portability.md) | Carried-history portability for routed models | PARTIAL: slices 2a+2b + coded 409 + refusal cache landed 2026-09-12; bisect complete (a carried reasoning item is the trigger); slices 2c/2d and the Muse row probe stay owner-gated on new evidence | independent; re-probe after client upgrades |

## Subagent model visibility (151)

Added 2026-09-12 after the task 01a09477 incident: the Codex client caps the
`spawn_agent` model-override list at five rows taken in catalogue order, so the
roster-first catalogue hides every OpenRouter model from the agent even though
the picker lists them all.

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [151](151-subagent-model-visibility.md) | Subagent model visibility: every catalogue model is delegable | PARTIAL: repo side lands in 0.6.36 (instructions roster + starter rule + tests); owner-machine step, stage 3 and 4-5 open | after 133/145 (landed); serialize with 135 on `ai_router/catalogue.py` and this file |

## Architecture and scalability wave (152-160)

Added 2026-09-12 from `2026-09-12-architecture-scalability-review.md`, the
read-only architecture review run ahead of the public flip. It found the
provider table, protocol dispatch and offline suite sound, and the remaining
OpenRouter-shaped assumptions, the quadratic catalogue growth, the two
disagreeing Claude projections and the single-OS CI as the things that do not
scale. `2026-09-12-continuation-prompt.md` is the hand-over brief for the agent
that executes this wave; it carries the execution order and the owner gates.

| Plan | Title | Status | Sequencing |
|---|---|---|---|
| [152](152-provider-dialect-and-key-shapes.md) | Provider abstraction wave 2: dialects, key shapes and prose | TODO | after 141 (landed); before 153 |
| [153](153-model-identity-and-upstream-ids.md) | Model identity: separate the client slug from the upstream id | TODO | after 152; serialize with 154 on `ai_router/catalogue.py` |
| [154](154-catalogue-size-budget.md) | Catalogue size budget: a roster that can grow | TODO | after 153; serialize with 135 and 151 on `ai_router/catalogue.py` |
| [155](155-client-contract.md) | The client contract: one owner for who sees what | TODO | after 153/154; coordinate 113/120/121/148 |
| [156](156-ci-and-test-hardening-for-a-public-repo.md) | CI and test hardening for a public repository | TODO: targeted platform checks; blanket three-OS push matrix superseded by owner-requested minimal CI | independent; serialize with 146 on `tests/test_ingress_guards.py` |
| [157](157-source-reference-hygiene.md) | Source reference hygiene: every plan pointer resolves | TODO | after 159; quiet tree, one session |
| [158](158-changelog-and-docs-restructure.md) | Changelog and docs restructure for a first-time reader | TODO | after the public-readiness documentation pass merges |
| [159](159-backlog-consolidation-and-acceptance-split.md) | Backlog consolidation and the acceptance split | TODO | after the public-readiness backlog pass merges; before 157 |
| [160](160-publication-identifiers-out-of-source.md) | Move publication identifiers out of tracked source | TODO | independent; feeds 144 Step 3 |

## Recommended overall order

Work top to bottom; stop at owner gates and report.

- **Local, now:** 156, 152, 153, 154, 155, 160, 137, 146, 131, 147, 148,
  135 (remaining stages), 151 (stages 1-2); then 159, 157 and 158 once the
  public-readiness backlog and documentation passes have merged.
- **Owner-gated infrastructure:** 105, 106, 107, 099, 108, 109, 110, 139
  (remaining stages), 142, 144.
- **Owner-gated client and OS acceptance:** 111, 112, 113, 114, 115, 116, 117.
- **Owner-gated paid probes and desktop:** 118, 119, 120, 121, 150.

Sequencing notes:

- 099 executes only after 139's feed is qualified; its refresh wiring calls the
  plan-135 prompt check.
- 137 and 146 both edit the ingress file and its baseline entry: 137 first, then
  146 rebases and re-syncs. 135 and 146 both touch `ai_router/router.py`:
  serialize them in that order. 153, 154, 135 and 151 all touch
  `ai_router/catalogue.py`: one writer at a time.
- 147's `--check-update` change is a user-visible contract change and must also
  move the installed scheduler commands to `--update`. 148 is source and offline
  tests only; its live proof stays with 113/115/120.
- 106 before 107 Stage 4. 108/109/110 share owner-Mac update/rollback
  acceptance: serialize them, one writer per machine state.
- 113 is the CLI/desktop contract; 114 (publication) and 115 (paid probes)
  follow it; 120 and 121 extend it. 113-115 and 120-121 were amended 2026-09-11
  by `2026-09-11-claude-router-development-branch-review.md`. The installer
  lifecycle fixes F1-F4 are specified in 112's installer contract and accepted
  by 114 whichever plan executes them; do not run both writers at once.
- 131's writer changes land before 106's feed work.
- References in older plans to numbers 034-089 are historical: completed
  numbers resolve in the removal log below, renumbered numbers in the map
  below, parked numbers under `parked/`.

## Model allocation review (repository-only)

`model-allocation/review-process.md` is the monthly process that decides which
model and reasoning effort each agent role uses, and
`model-allocation/suggestion.md` is its current dated output. They live here
rather than under `docs/` because the release bundle ships every `docs/*.md`
page to installed hosts and these two are internal governance, not operator
documentation.

## Parked (not approved; reopen only on the stated condition)

- `parked/039-codex-router-live-merged-catalogue.md`: live merged-catalogue
  route; reopen only if a supported client fetch is proven.
- `parked/073-remote-support-companion.md`: not approved.

## Transitional shim owner (`codex_router/`)

`codex_router/` stays as a deprecated alias re-exporting `ai_router` (owner:
Plan 134, landed 2026-09-12, until a dedicated removal plan names its own
owner). A removal plan may delete it only after an external-consumer search
finds no live importer outside this repository and records the result. Live
in-repo importers of the old name today: none outside `codex_router/` itself
(`packaging/router_launch.py` prefers `ai_router` and falls back to
`codex_router` only for pre-rename installed releases); the `codex_router` log
name stays so existing installs keep working.

## Completed and removed

Removed 2026-09-12 after landing on `develop` (the date is the landing date
each status row recorded): 090, 091, 092, 093, 094, 095, 096, 097, 098, 100,
101, 102, 122, 123, 136, 140 and 141 on 2026-09-11 (127 landed inside 141);
103, 104, 124, 125, 126, 128, 129, 130, 132, 133, 134, 138, 149 and both 145
files (the model verification gate and the tool-alias repair) on 2026-09-12.
The
second plan numbered 139, the native first-run key popup, shipped as the key
window (`ai_router/key_dialog.py`, `ai_router/key_prompt.py`,
`ai_router/setup_page.py`; CHANGELOG 0.6.33 and 0.6.34) and was removed in the
same pass; the number stays with the feed publication plan. The five
`rejected-muse-retry/` drafts, never approved and kept only for traceability,
were removed too. Git history holds every removed file.

Removed 2026-09-10 (the pre-renumbering series): 034, 035, 036, 037, 038, 040,
042, 047, 048 (both files), 056, 060, 061, 062, 063, 064, 065, 067, 068 (both
files), 069, 070, 071 (both files), 072 (both files), 074. The dated reports
record the results; git history holds the plan text.

Note: 056's Stage 4 cross-OS CI runners were never built; that residual is
subsumed by Plan 116 Stage 7 and by plan 156, and the single-Ubuntu CI scope
was a recorded cost decision (see `.github/workflows/check.yml`).

## Renumbering map (old to new, 2026-09-10)

076→090, 077→091, 079→092, 078→093, 080→094, 081→095, 082→096, 083→097,
084→098, 046→099, 089→100, 085→101, 086→102, 087→103, 088→104, 059→105,
054→106, 055→107, 050→108, 045→109, 041→110, 043→111, 049→112, 051→113,
053→114, 052→115, 057→116, 058→117, 044→118, 066→119, 073→120, 075→121.
Parked without renumbering: 039, 073 (remote-support companion).
