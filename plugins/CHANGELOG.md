# Changelog

## scg-review 0.4.6 and scg-subagents 0.5.4 — 2026-09-15

- Route all four pre-commit review passes to Muse Spark Contributor 1.3 at
  `xhigh`, keeping the existing bounded fallback policy and review gates.

## scg-review 0.4.5 — 2026-09-15

- Pin the reviewer inspect commands in the brief: `git write-tree`, `git diff --cached --stat`, `git diff --cached`, and `git show :path` for listed staged files. Do not reconstruct trees, extract the repository, or rerun the same model with the same brief.

## scg-review 0.4.4 — 2026-09-15

- Remove the one-cycle cap on material remediations and targeted re-reviews. Keep cycling until the commit is All Clear or Proceed With Notes, or an accepted blocker needs owner or product input.

## scg-review 0.4.3 — 2026-09-14

- Write review verdicts for people: `✅ All Clear`, `📝 Proceed With Notes`, `❌ Block`. Keep `ALL_CLEAR` and `PROCEED_WITH_NOTES` only as Git-hook `--decision` tokens.
- Each lane names the model that ran it. The main agent recaps lane verdicts, models, and accepted notes as short bullets.


## scg-subagents 0.5.3 — 2026-09-14

- Keep the local-first delegation default in `optimal-subagents` and state the delegation test in outcome terms: delegate a bounded part when a better-fit model or an independent check raises quality, the parent cannot meet the capability floor, or the part runs independently and overlaps parent work, keeps bulky output out of the parent context, or needs a separate tool or write boundary. The brief, fresh-context child, result read and parent verification must return more in quality, time or context than they consume; cost is one factor. When the parent is the wrong fit for most of the task, ask the user to change the session model. Rename the workload table header from "Cost-first starting point" to "Starting point". No change to model choice, review lanes or the mandatory tool-guide read.

## scg-subagents 0.5.2 — 2026-09-14

- Port the plaintext handoff guide from the retired `SC_Agent_plugins` branch
  work: use `collaboration_plaintext` handoff tools for external recipients
  on the mixed-provider Codex route, including later messages and follow-ups.
  Keep native OpenAI encryption and require fresh external children without
  encrypted history. Recover from rejected handoffs without repeating the
  failing call or treating an empty completed turn as success.

## scg-subagents 0.5.1 — 2026-09-13

- Make reading `references/tool-guide.md` mandatory before the first spawn in
  a session: the entrypoint alone no longer authorizes a delegation.

## scg-finance 0.1.0 — 2026-09-13

- Add the `finance-analyst` skill as a new `scg-finance` plugin: controller
  and finance-director grade analysis across NetSuite, Xero, Airwallex,
  exported reports and pasted figures. Works in Codex and Claude Code through
  the client's own MCP or connector tools; read-only by default, with an
  explicit per-mutation write guard.
- Ship both `.codex-plugin` and `.claude-plugin` manifests at the same
  version, the shared marketplace updater, and the shared update guide.

## scg-subagents 0.5.0 — 2026-09-13

- Add the department delegation briefs: `sales-subagent`, `csm-subagent`,
  `support-subagent`, `finance-subagent` and `operations-subagent`. Each brief
  sets role, inputs, authority and acceptance for one department; model choice
  stays with `optimal-subagents`. Starting models follow the researched
  evidence (2026-09-12 snapshot, live-checked 2026-09-13).

## scg-review 0.4.2 and scg-subagents 0.4.0 — 2026-09-13

- Refresh the `scg-review` bundled routing copy for the rename; the review
  procedure itself is unchanged.

## scg-subagents 0.4.0 — 2026-09-13

- Rename the `cost-first-subagents` skill to `optimal-subagents`: it is the
  global subagent skill (delegation, model choice, coordination), with cost
  as one criterion rather than its identity. Update host instructions to the
  new name.

## scg-review 0.4.1, scg-subagents 0.3.1 and scg-prototypes 0.1.1 — 2026-09-13

- Move the `scg-agent-plugins` marketplace from `SC_Agent_plugins` into this
  repository: `plugins/scg-review`, `plugins/scg-subagents` and
  `plugins/scg-prototypes` with the marketplace manifest at
  `.agents/plugins/marketplace.json`. Marketplace and plugin names are
  unchanged; only the Git source URL changes.
- Rewire updater sources, repository fields, update guides and test fixtures
  to `software-combined/SC_OpenRouter_adapter`. Accept the pre-move released
  updater runner by hash so `install --migrate` retires it cleanly.
- Reinstall from the new source after this lands: remove the marketplace,
  re-add it from this repository, reinstall the wanted plugins, then run the
  updater installer with `--migrate` once.

## scg-prototypes 0.1.0 — 2026-09-12

- Add the `publish-prototype` skill: publish a built static prototype to
  `https://prototypes.softwarecombined.com/<slug>/`, archive it in
  `software-combined/SC_Prototypes`, sync it to the private channel bucket,
  invalidate the CloudFront path and verify the live URL before printing it.
- Fail closed before writing when the slug, the asset base path or the
  SHA-256-verified gitleaks scan reports a problem; refuse slug collisions
  unless `--update`, refuse a scanner configured through `GITLEAKS_CONFIG`,
  and re-check the copied artifact and any `--source` snapshot before they are
  committed or uploaded.
- Ship `list` and `unpublish` alongside `publish`, keep the archived source when
  a prototype is unpublished, and require the same shared updater setup as the
  other SCG plugins.
- The channel foundation lives in `SC_Infrastructure`
  (`web-edge/static-site-cloudfront-s3`). Until its owner-gated deploy lands,
  `channel.json` has no distribution id and every publish stops with a clear
  "not deployed yet" message.

## scg-review 0.4.0 and scg-subagents 0.3.0 — 2026-09-13

- Add an independent planning advisor role with researched model choices,
  a reusable read-only plan review brief and qualification criteria.
- Label every subagent assignment with its requested model, effort, role/pass
  and task context, including the shared pre-commit reviewer routing.
- Reconcile the marketplace-wide updater with native macOS, Linux and Windows
  scheduling. Either plugin configures one shared updater for all enabled SCG
  plugins, including future skills delivered in those plugins.
- Preserve the reviewed migration safeguards and Windows windowless execution.
- Require agents installing or pulling skills for use to configure and verify
  automatic updates; require all new skills to support all three platforms.

## scg-review 0.3.0 and scg-subagents 0.2.0 — 2026-09-12

- Extend both updater installers to Linux systemd user timers and Windows
  Task Scheduler, using the same daily approach as macOS.
- Preserve known existing Mac runners and user-owned schedules; verify native
  registration and keep disabled/uninstalled plugins disabled.
- Add native Linux and Windows CI execution using a local test CLI, alongside
  macOS/Linux regression checks. Keep the existing Git marketplace source.

## scg-subagents 0.1.1 — 2026-09-12

- Add security-first model selection for defensive analysis and authorised
  pentesting, with full catalogue coverage and task-specific evidence limits.
- Distinguish production safeguards and approved access from benchmark capability;
  add cyber qualification criteria and preserve the separate pre-commit policy.

## scg-review 0.2.0 — 2026-09-12

- Use the shared cost-first reviewer policy: GLM Flash for simplification/quality,
  DeepSeek Flash for correctness/adversarial, fixed max effort and bounded
  availability fallbacks. Keep explicit model requirements and all review gates.
- Bundle a synchronized policy copy so review-only installations remain usable.
- Correct marketplace refresh scope: other configured plugin caches may update.

## scg-subagents 0.1.0 — 2026-09-12

- Add cost-first model selection with full catalogue evidence and reproducible
  workload-specific Pareto comparisons.
- Document parent/child tools, messaging, exact model identity, cost accounting
  and a repeatable methodology for researching and qualifying new models.
- Add an independent daily macOS updater and document marketplace-wide cache refresh.
- Assign one effort per model, add workload fallbacks, and own shared reviewer routing.

## 0.1.4 — 2026-09-11

- Route every Codex and OpenCode review pass to DeepSeek V4.1 Flash at max
  effort, replacing the GLM and Muse rows.
- Collapse the runtime mapping to one reviewer row per runtime after each
  runtime's four passes agreed.

## 0.1.3 — 2026-09-11

- Route the Codex review passes across GLM 5.3 Flash (simplification,
  adversarial), Muse Spark 1.3 (correctness) and DeepSeek V4.1 Flash (quality),
  all at max effort. The OpenCode placeholder row mirrors the same mapping.

## 0.1.2 — 2026-09-08

- Show the existing Muse Contributor/xhigh defaults directly in the review
  skill and remove the obsolete Kimi/Luna fallback table.
- Preserve the latest review procedure, Ponytail, simplification and exact-tree gates.

## 0.1.1 — 2026-09-08

- Add an explicit daily macOS updater for separate Codex accounts.
- Refresh only the approved SCG Git marketplace and enabled review plugin.
- Preserve disabled/uninstalled state and keep machine hooks and pins unchanged.

## 0.1.0 — 2026-09-08

- First Codex marketplace release of SCG Pre-Commit Review.
- Bundle the current review skill, Code Simplifier and Ponytail with portable
  references and an explicit reviewer model policy.
- Include the unchanged SCG hook adapter and regression tests, with explicit
  provisioning that preserves existing configuration and validates scanner pins.
- Document workspace sync, direct Git refresh and future Claude Code packaging.
