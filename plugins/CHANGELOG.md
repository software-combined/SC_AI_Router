# Changelog

## scg-subagents 0.5.8 — 2026-09-22

- Move the Grok recommendation to `x-ai/grok-4.7`, the id the router roster
  now pins. The entry, its prescribed effort and the catalogue row all moved
  together, and the price was re-read from the live OpenRouter listing
  (1.6 / 4.8 per million, 0.4 cache read).
- Refresh the benchmark fields from a 4.7 source instead of carrying 4.6's
  numbers across: the Artificial Analysis row is measured at the prescribed
  `xhigh`, so Grok is now compared on the AA frontier instead of being
  excluded from it, while its Arena WebDev row has no 4.7 measurement yet and
  stays empty. The `grok-4.6 / high` row is kept in the catalogue as the
  superseded version's measurement.
- Record in `cybersecurity.md` that the repeatability and pooled-finding
  numbers were measured on Grok 4.6 and are unmeasured for 4.7. No local paid
  evaluation was run for this refresh.

## scg-review 0.4.12 — 2026-09-22

- Run the configured Gitleaks scanner on native Windows. `load_gitleaks_pin`
  accepts a platform-native absolute binary path instead of requiring a leading
  `/`, and the scan passes `os.devnull` rather than the literal `/dev/null`.
  Verified against the official `gitleaks_8.30.1_windows_x64.zip` release asset
  (ZIP SHA-256
  `d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e`; extracted
  `gitleaks.exe` SHA-256
  `17157e2ee8b76fc8b1d8bee607a250e34b8a8023c8bc81822d4b5ee4d78fcb7c`;
  `gitleaks version` reports `8.30.1`). On native Windows,
  `--gitleaks-ignore-path nul` loaded no ignore entries, raised no null-device
  error, and left findings controlling the exit code; the repository's own
  `.gitleaksignore` is still refused, so the override stays load-bearing.
- The hook adapter's tests now execute in CI on `windows-latest` as well as
  Linux. They ran in no job before. The Windows leg runs the new portability
  module, because the pre-existing end-to-end tests drive a `/bin/sh` scanner
  stub and override `HOME`, which `Path.home()` ignores on Windows.
- Refresh the installed hook adapter on macOS/Linux before the next review.
  `setup.py check` compares the installed helper with the bundled bytes and
  refuses a mismatch, so replace only
  `~/.config/scg-agent-git-hooks/lib/scg_agent_git_hooks.py` with the bundled
  `support/git-hooks/lib/scg_agent_git_hooks.py`, keep `config.json`, the hooks
  and the review receipts as they are, then re-run `setup.py check` and confirm
  it passes. See `references/setup.md`.
- Scanner support only. `setup.py` provisioning, Git hook installation,
  approval-receipt enforcement and the static `required_lanes` lane set remain
  unimplemented on Windows, and `bin/scg-review-state` stays a Bash shim.

## scg-review 0.4.11 — 2026-09-18

- Run the required verification commands once, in the main agent, on the
  frozen staged tree after the simplification pass and before any reviewer is
  spawned, so the run describes the tree the lanes actually review. Record the
  commands, outcomes and reviewed tree id, and pass that record to every lane
  as the shared evidence. A failed required command blocks before reviewer
  calls.
- Stop the review lanes repeating the required verification set. A lane may run
  one narrowly targeted, non-destructive check to prove or disprove a specific
  finding, and must report what it ran and what it showed.
- After an accepted fix, re-run only the verification commands that fix
  affects; re-run the full set when the affected scope is unclear.

## scg-review 0.4.10, scg-subagents 0.5.7, scg-prototypes 0.1.2, scg-finance 0.1.1 and scg-documentation 0.1.1 — 2026-09-18

- Accept the pre-rename plugin runner `bd06fc55` in the shared updater's
  `LEGACY` list. It is the runner actually deployed before the repository
  rename, and without an entry `install --migrate` refuses it as an
  unrecognised file, which leaves automatic updates dead on every machine that
  installed it. Content-verified by SHA-256; no other runner is accepted and
  the existing entries are unchanged.

## scg-documentation 0.1.0 — 2026-09-18

- Add the `documentation` skill as a new `scg-documentation` plugin:
  structure, voice, punctuation and reader-level clarity for READMEs, folder
  and module docs, technical articles and explanatory prose.
- Lead with writing for readers at any technical skill level: expand jargon on
  first use, never assume history, lead with the common case, prefer the short
  common word, one idea per sentence, show rather than describe, and test the
  document against a reader who lacks your context.
- Ship both `.codex-plugin` and `.claude-plugin` manifests at the same
  version, the shared marketplace updater, and the shared update guide.

## scg-review 0.4.9 — 2026-09-16

- Keep lane verdicts legible in every relay: `✅ All Clear`, `📝 Proceed With Notes` and
  `❌ Block` stay verbatim with their emoji in the reviewer's own summary, in the main
  agent's interim update while other lanes still run, and in the final recap. Never
  paraphrase the verdict, drop its emoji, or substitute another symbol.

## scg-review 0.4.8 and scg-subagents 0.5.6 - 2026-09-16

- Route the Pass 1 simplification review to DeepSeek V4.1 Flash at `max`,
  keeping the bounded fallback order and the other review lanes unchanged.

## scg-review 0.4.7 and scg-subagents 0.5.5 — 2026-09-15

- Clarify that Pass 1 simplification can be the slowest review phase and may
  stay quiet while the executor reads and reasons. Tell parent agents to wait
  for the active child, avoid duplicate retries, and retry only after a
  diagnosed runtime or transport failure.

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
