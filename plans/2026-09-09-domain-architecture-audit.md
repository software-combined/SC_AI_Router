# Domain architecture audit, 9 September 2026

> Consolidated at `96db57f`: Plans 056-059 and AGENTS.md section 9 have since
> integrated, and this audit worktree was advanced to that base. The current
> [complete roadmap](2026-09-09-router-roadmap.md) reconciles all Plans 034-067.
> Source findings below retain their original evidence stamp; obsolete
> worktree/ownership statements below are historical, not instructions.

## Verdict

Targeted reorganisation is warranted before adding more clients and operating
systems. Keep the stdlib runtime, immutable model registry, provider-owned
credential construction, and existing lifecycle tests. Extract responsibilities
at the boundaries below as small runnable slices. A product rename, framework,
universal conversation format, or wholesale directory move would add risk
without resolving the observed problems.

The first observable proof of the refactor should be an extracted install and
router bundle that preserves both existing wire contracts and passes the
existing macOS/Linux lifecycle harness. Source imports alone are insufficient.

## Baseline and authority

- Audited source: local `develop`, commit `6840312510c182f4a7e2f439ab5229e36293fc6a`.
  It was two commits ahead of the locally recorded `origin/develop`; no fetch,
  push, release, or deployment was performed by the audit owner.
- Audit owner: this Codex task, `/root`. Writable worktree:
  `/Users/cyrilallart/Documents/Github/.worktrees/router-domain-audit-20260909`;
  branch `codex/router-domain-audit-20260909`; eventual integration target
  `develop`. Only `plans/` is changed. Plans grant no implementation authority.
- Python 3.14.4 on macOS. `python3.14 -B -m unittest discover -s tests -t .`
  completed with exit 0; discovery contains 473 tests. Existing socket/resource
  cleanup warnings occurred. No claim of a warning-free run.
- `python3.14 -m compileall -q codex_router tools tests packaging`: exit 0.
  `python3.14 tools/check_source_limits.py`: 78 files, zero failures.
  `python3.14 -B -m codex_router.models check --offline`: 20 models, zero problems.
- Three audit subagents requested `meta/muse-spark-1.3-contributor`, `xhigh`.
  Calls were accepted; returned served model and effort were **unverified**.
  Two agents reported empty task briefs, including a follow-up retry; their
  generic inventories were not accepted as independent architecture reviews.
  The remaining lane was interrupted. At the user's request, two further Muse
  retries received recent context plus a written brief and were resumed after
  interruption. They returned architecture observations but did not confirm the
  scoped brief. Their useful observations were checked against source; they
  do not count as completed scoped plan reviews. One also wrote five duplicate
  plans and five index rows in the primary checkout despite its read-only task.
  The parent moved those files, hash-verified, to `plans/rejected-muse-retry/`
  and removed only those five index rows. The primary checkout is clean again.
  Rejected drafts are not executable plans. Findings below were inspected and
  vetted directly by the parent. An earlier agent also inspected live macOS
  state read-only; that out-of-scope snapshot is excluded from this report.
- During the audit, another task advanced `develop` to `c863a65` (0.6.9 release
  preparation). Compared with the frozen audit source, only changelog,
  operations documentation, VERSION and pyproject metadata changed. The audit
  worktree remains at `6840312`; future executors must run the drift checks.

## Vetted findings

All listed source findings have HIGH confidence. Risk means risk of the fix,
not a claim that the existing system is insecure in every use.

| # | Finding and concrete impact | Category | Priority / effort / risk | Evidence at audited commit | Plan |
|---|---|---|---|---|---|
| F1 | Upstream free text reaches structured logs. An upstream error echoing prompt or tool content is persisted as `reason`, despite the no-content logging rule. A synthetic canary reproduced the path without a network call. | security / correctness | P1 / S / LOW | `codex_router/providers.py:31-67,85-92`; `codex_router/router.py:86-93,255-268`; `codex_router/errors.py:3-6` | 060 |
| F2 | Platform dispatch treats every non-Linux system as macOS. `install.py` has 699 lines against a 700 hard limit; `service.py` has 601 and combines feed, state, filesystem, interpreter and launchd duties. Adding Windows inline compounds both issues. | architecture / portability | P1 / M-L / HIGH | `packaging/install.py:77-94,321-323,370-397,619-651`; `packaging/service.py:1-7,49-133,186-226`; `config/source-limits-baseline.json:7-8` | Existing 056/057, with 061 guardrails |
| F3 | Protocol and provider responsibilities are coupled. The HTTP handler branches into a second Claude selector, while shared relay code applies Codex-specific 429 and model-header behavior to Messages too. New clients would otherwise add more branches or inherit policy accidentally. | architecture / tests | P1 / M / MED | `codex_router/router.py:154-172,252-279`; `codex_router/providers.py:19-28,108-127,314-335`; `codex_router/claude.py:16,81-129` | 062 |
| F4 | Installation always activates Codex and owns one Codex-shaped receipt. A Claude-only install would still touch `.codex/config.toml`; uninstall judges restoration by an English output substring. `openai_mode` also controls Claude subscription routing, preventing independent choices. | architecture / correctness | P1 / L, staged / HIGH | `packaging/install.py:430-470,629-638`; `tools/disable.py:9-31`; `codex_router/router.py:164-166`; `codex_router/claude.py:123-129`; `tests/test_claude_ingress.py:128-138` | 063, then existing 051/053 |
| F5 | Model facts, Codex presentation, and refresh operations overlap. `live_refresh` calls back into the model CLI for naming; ingestion filters to Codex modalities; two catalogue writers disagree about audio. Claude discovery has its own selection policy despite a separate registry client policy. | architecture / consistency | P2 / M / MED | `codex_router/live_refresh.py:15-17,35-48`; `codex_router/models.py:15,35-60`; `codex_router/apply_catalogue.py:9-24`; `codex_router/catalogue.py:113-136,139-156`; `codex_router/registry.py:106-124`; `codex_router/claude.py:52-59` | 064 |
| F6 | Reorganisation is not fully protected by release and dependency checks. Runtime Python files are recursively bundled, runtime data files are only top-level, and installer helpers use a fixed list. The bundle closure test imports only the registry. Line counts do not constrain dependency direction. | tests / tooling | P1 / M / LOW-MED | `packaging/release.py:20-28`; `packaging/install.py:132-139`; `tests/test_release.py:64-85`; `tools/check_source_limits.py:15-25` | 061 |
| F7 | Platform test coverage is not support evidence. CI runs Ubuntu only; Windows skips install/service and POSIX permission tests. No Windows credential ACL enforcement exists in the runtime. | tests / security | P1 / M-L / HIGH | `.github/workflows/check.yml:17-37`; `tests/_platform.py:1-20`; `codex_router/credentials.py:23-30`; `packaging/install.ps1:1-3` | Existing 056/057/058/059 |

F5 is an ownership inconsistency, not a claim that hiding a picker row changes
billing. Current Claude listing tests intentionally include all OpenRouter
rows (`tests/test_claude_ingress.py:140-155`); changing that policy must be a
separate, explicit behavior change, not hidden in a file move.

## Domains and rules to adopt

| Domain | Owns | Must not own |
|---|---|---|
| Local HTTP transport | Loopback auth, limits, drain/inflight, connection lifecycle, safe event fields | Client model naming, OS service commands, vendor quirks |
| Wire protocols | Responses or Messages body/stream shapes, history and tool adaptation, protocol-specific errors | Client settings files, service installation, a universal lossy conversation format |
| Upstream routing and credentials | Target host/path and credential construction for the selected protocol/upstream pair | Picker visibility, tool execution, inherited client auth on OpenRouter requests |
| Model catalogue | Canonical identity, measured model capabilities, shared normalization | Codex config writes or a single global claim of support across all clients |
| Client integration | Client-specific listing, aliases, config ownership, activation/restoration, compatibility evidence | OS lifecycle or changing a native client's execution permissions implicitly |
| Installation and distribution | Release transaction, integrity checks, pointer/rollback, update transport | Hard-coded client setup or inline platform branches |
| Platform backend | Native per-user services, scheduling, interpreter/platform behavior, OS file protection | Provider logic, client model filtering, duplicate installer transactions |

Dependency direction: entrypoints compose these domains; small shared contracts
are leaves. Keep the package name `codex_router`, existing command entrypoints,
service labels, router home and state files for compatibility. Introduce
`protocols/` and `clients/` only while moving their live callers. Retain small
flat modules where they already have one clear responsibility. Do not create
empty Kiro or Windows stubs to make a directory diagram look complete.

## Existing roadmap reconciliation

Plans 049-055 remain authoritative for plugin packaging, Claude acceptance,
private distribution and key provisioning. This audit grants no paid probes,
publication, staff changes or AWS/OpenRouter writes. Signature enforcement stays
removed by the recorded decision; checksum, serial and identity checks remain.

Another writer owns **unmerged draft Plans 056-059** in
`/Users/cyrilallart/Documents/Github/.worktrees/router-plans-xplat` on
`claude/plans-cross-platform-install`. Their files were read, not edited or
adopted. Numbers 056-059 are reserved. They cover platform backends, Windows,
recipient readiness and interpreter provisioning. Reconcile the index after
those drafts integrate; do not create competing OS plans.

Before executing those drafts, resolve these concrete planning overlaps:

- 056's snapshot is already stale: it says 696 installer lines; this source has
  699. Refresh excerpts before moves. Move the relevant platform behavior out
  of `service.py` too; reducing `install.py` alone leaves a second mixed owner.
- Select a non-shadowing import name for installer backends. A directory named
  `platform` beside an executed script can shadow the stdlib `platform` module.
  Preserve the existing file-based bootstrap until extracted-bundle imports are
  proven. Do not introduce third-party `packaging` dependency assumptions.
- 056/057 own the three-OS CI matrix and removing platform skips. 061 adds
  bundle/import gates to that same workflow; merge the work, not a second CI.
- 057 treats Task Scheduler as a decision to settle although 054 already names
  it. 059 revisits private Python provisioning although 054 already plans a
  pinned native runtime. Reconcile with the latest owner decision before asking
  the same questions or building alternative bootstrap machinery.
- Cross-platform drafts' real-machine/container results were not rerun here.
  Their source, simulated manager, real manager and staff-client gates must
  retain those separate labels.

## Recommended execution order

1. **060**: close the reproduced logging boundary defect.
2. **061**: document domain ownership and protect extracted-bundle imports.
3. **056**: existing platform extraction; **062** runtime extraction and **064**
   model projection work can follow 061 independently if write ownership is
   separated. Coordinate shared test, release and index files.
4. **063**: client activation extraction, after 056 and 062; then execute 051
   and 053 for Claude setup. **057/058/059** continue the OS delivery stream.
5. **065**: Kiro feasibility can run alongside the above without source changes.
   Only a verified client inference extension mechanism earns an implementation
   slice. Kiro support is not a prerequisite for the existing two-client work.

## Direction options

1. **Use a small explicit client/protocol matrix.** Codex currently uses
   Responses and native service paths; Claude uses Messages and a gateway
   listing. Kiro IDE and CLI are distinct targets until verified. Record tested
   client versions, route, tool round trip, compaction and auth separately;
   health or a global model `tier` is not proof of each combination.
2. **Keep setup plugins thin.** Reuse the installer and client activation API.
   A plugin catalog or MCP tool integration is not itself a way to replace the
   client's inference provider. This preserves Plans 049/053's ownership model.

Kiro's current official [agent model field](https://kiro.dev/docs/custom-agents/configuration-reference/#model-field)
selects a model available from Kiro's model service; its
[model overview](https://kiro.dev/docs/models/) describes the supplied selection.
These inspected pages do not establish a custom OpenRouter/loopback inference
endpoint. Plan 065 records that uncertainty and separates IDE from CLI. This is
not a claim that every possible Kiro integration is unsupported.

## Considered and rejected or deferred

- Full rewrite, runtime dependencies, dependency-injection framework, dynamic
  plugin loading, and universal message translation: unnecessary for this
  small stdlib codebase; threaten existing streaming and auth contracts.
- Renaming `codex_router`, service labels or existing homes: migration cost
  with no demonstrated extension benefit. Clear internal ownership is enough.
- Hot-reloading model data: already deferred by 039/046. Import-time indexes
  are coherent for the current versioned release model; do not reopen the gate.
- Calling Claude's broad listing an introduced regression: tests and docs
  explicitly implement it. Plan 064 makes that policy explicit before changing it.
- Claiming old Linux uninstall is still broken: `tools/disable.py:26-29` now
  chooses systemctl on Linux. Historical memory was rechecked and corrected.
- Performance rewrites: no measured throughput problem was established. No
  pooling, async server or additional cache is proposed.
- ResourceWarning cleanup: observed in baseline tests; defer unless it makes
  the refactor harness unreliable. It does not invalidate the passing result.
- Muse suggestion that no platform backend exists: too broad; `systemd.Manager`
  exists. The missing piece is consistent selection across platforms.
- Muse suggestion that `service.py` violates an unenforced 400-line hard limit:
  incorrect. `check_source_limits.py:8-9` explicitly gives packaging 400 soft /
  700 hard, with the current 601 lines baselined. It is mixed responsibility,
  not a failing size gate.
- Combining router/updater launchers: deferred. Their stable entrypoints serve
  different lifecycles (`router_launch.py:18-22`, `update_launch.py:21-25`).
  Small pointer-reading duplication alone is not a reason for a shared loader.
- Removing the supposedly unexplained OpenCode credential fallback: rejected.
  Plan 040 and `credentials.py:21-42` explicitly define the ordered fallback.
- Assuming Kiro speaks Responses because the router already does: rejected.
  No Kiro inference-hook evidence supports that inference; use Plan 065.
- Windows ACLs are a real gap, but not a proven small low-risk fix. Their
  native create/read/restore behavior belongs to existing Plan 057 acceptance.
- README allegedly promises a managed Windows installer: overstates the text.
  README explicitly distinguishes the runtime from macOS/Linux managed services;
  057/058 own support messaging as actual Windows support changes.

## Coverage limits and closeout

Hotspot-weighted source audit of runtime, lifecycle, registry, tests, CI, release
packaging and relevant docs/plans. No exhaustive line-by-line security review,
load benchmark, dependency vulnerability database scan, live provider metadata
refresh, Windows/Linux host execution, real client inference, billing validation
or release acceptance. Runtime is stdlib-only; Python provisioning belongs to
the existing distribution plans.

Plans are the deliverable, retained uncommitted in the owned worktree for review.
No source implementation or integration is claimed. No durable KnowledgeVault
update is needed: implementation decisions remain proposals and their canonical
home is this repository's plans.
