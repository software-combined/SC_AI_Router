# Changelog

## scg-optimise-ci 0.1.2 (2026-10-23)

- Replace the historical Router comparison with three samples per layout
  against identical source, tests and pinned Python versions.
  Publish each run, discovery digests, test/skip totals, runner use and limits.
- Separate preliminary runs after floating runtime selectors resolved differently.
  Teach finite sampling, actual environment checks and separate comparison cohorts.
- Keep elapsed time distinct from runner use and test inventory distinct from
  line or branch coverage. Preserve the existing verification and release gates.

## scg-optimise-ci 0.1.1 (2026-10-23)

- Apply the measured method across languages, build tools and CI providers.
  Inspect the critical path, actual input dependencies, acceptance results,
  runner capacity and timeout boundaries before changing the job graph.
- Record the actual tested checkout and tree, separate waiting time from
  runner use, and collect Git change states separately for affected checks.
- Retain Router CI as the only benchmark, with one successful sample per
  candidate and explicit limits on savings and reliability claims.

## scg-optimise-ci 0.1.0 (2026-10-23)

- Package the measured CI optimisation skill for Codex and Claude Code.
  Preserve required coverage and release gates, compare equivalent workloads,
  and keep elapsed time separate from aggregate runner use.
- Include the Router acceptance example: one successful before/after sample
  reduced elapsed time from 14m 18s to 9m 27s with all checks retained.
- Use router-managed delivery with no separate updater or schedule.

## scg-review 0.7.0 and scg-subagents 0.6.2 (2026-10-22)

- Add a mandatory, model-agnostic security reviewer for Codex and Claude Code.
  Trace changed trust boundaries, check the strongest defense, and independently
  verify surviving candidates. Keep source reasoning distinct from observed results.
- Require four lane identities and owner-selected security model preferences.
  Three-lane configurations need the documented explicit migration; plugin updates
  preserve local settings. Narrow adversarial review to operational failures.
- Adapt Cloudflare's source-first security method without its full audit fleet,
  target-code execution, coverage ledgers or additional dependencies.

## scg-prototypes 0.1.5 and scg-subagents 0.6.1 (2026-10-19)

- Remove environment-specific cloud and finance account details from the
  public plugins. Prototype publishing now requires a separate private channel
  config and fails closed when the bundled blank template is selected.

## scg-review 0.6.1 (2026-10-17)

- Export a sanitized review record for the current committed tree, including
  lane identities and repository-scoped verification links. Reject dirty,
  missing, expired, blocked or mismatched evidence. The local review gate
  retains its existing authority; an export creates no new approval.

## scg-review 0.6.0 and scg-subagents 0.6.0 (2026-10-15)

- Make pre-commit review model agnostic. Each machine owner sets ordered
  `review_models` preferences in their local Git hook configuration, with no
  shared model, provider or effort defaults. Client profiles keep Codex and
  Claude Code choices separate; read them with `scg-review-state models --client <client>`.
- Preserve simplification, independent lanes, the pinned secret scan, required
  checks, bounded fallbacks, identity records and exact-tree approval. Existing
  adapters need the documented refresh; owners supply their own model choices.

## scg-ponytail 0.1.3 (2026-10-15)

- Make Dietrich Gebert's Ponytail attribution visible in the skill and the
  repository's third-party notices. Preserve the original MIT licence.

## Public source metadata (2026-10-15)

- Point plugin repository links to the clean public source. Versions: scg-documentation 0.1.4, scg-finance 0.1.3, scg-ponytail 0.1.2, scg-prototypes 0.1.4, scg-review 0.5.2, scg-subagents 0.5.22.

## scg-subagents 0.5.21 (2026-10-14)

- Select truthful gateway model IDs; retire hashed Claude aliases.

## scg-ponytail 0.1.1 (2026-10-08)

- Include affected callers, tests, fixtures, configuration and exports when
  defining a change's scope, so a small edit still completes the task.
- Preserve existing architectural boundaries, interfaces and conventions
  during simplification. State material checks not completed and remaining
  risks in the final response.
- Retain the conditional shared-function fix, total-complexity guidance and
  risk-based verification requirements.

## scg-review 0.5.1 and scg-subagents 0.5.20 (2026-10-07)

- Resolve Codex child model reports from the installed router's bounded
  request evidence, using exact child and parent IDs and assignment times.
  Keep provider-reported identity separate from requested effort and from
  independent attestation. Missing evidence stays unverified; a known mismatch
  still invalidates a review. Older routers and other clients keep the existing
  unverified fallback. Review order, model selection and approval gates stay put.
- Document the current V1 tool schema without assuming V2 task names or
  fork arguments exist. A zero-paid real-client probe checks the ID mapping.

## scg-ponytail 0.1.0 and scg-review 0.5.0 (2026-10-01)

- Add the dedicated Ponytail plugin for Codex and Claude Code, with one
  shared skill adapted from Ponytail 4.10.0. Preserve the supplied simplicity,
  correctness and safety guidance, MIT licence and maintenance evaluation.
- Remove the older Ponytail copy from SCG Review. The simplifier and every
  review lane now read the installed `scg-ponytail:ponytail` skill at the path
  resolved by the active client. A missing, disabled or unreadable dependency
  blocks review; model routing, secret scanning and exact-tree approval remain.
- Deliver the new plugin through the existing SCG marketplace and router
  update path. Install Ponytail before updating Review when migrating a host.

## scg-review 0.4.20 and scg-subagents 0.5.19 - 2026-10-01

- Codex agents no longer pick handoff tools by the recipient's provider. When
  `collaboration_plaintext` handoff tools are offered, use them for every
  subagent assignment, message and follow-up, whatever the recipient;
  otherwise use the `collaboration` tools. Keep passing model and effort
  explicitly; external children need `fork_turns="none"`. The same wording
  works on routers before and after the change that shows native GPT parents
  only the plaintext tools. Reviewer selection and approval still follow
  the bundled policy.
- Drop the advice to correct a refused handoff on the next turn: the refusal
  ends the parent turn and never reaches the model. Report the delivery
  blocker instead.
- Claude Code parents now read their own tool-guide section instead of the
  Codex collaboration tools. It covers Claude and router models, follow-ups
  with SendMessage and foreground runs. `router_worker.py --list` now prints
  each model's router listing id for agent definitions, and a `fable`
  subagent inside a worker stays on the worker's model.

## scg-review 0.4.19 and scg-subagents 0.5.18 (2026-10-01)

- Every Codex review pass now has automatic availability fallbacks. OpenRouter
  Sol remains preferred at high; Flash and GLM provide the lane-specific cheaper
  alternatives at max, followed by native Sol at high. Astra is excluded.
- Check key-scoped availability and supported effort before spending a call.
  Skip remaining OpenRouter candidates after a shared provider failure; a shared
  Codex handoff failure stops dispatch. Limit each pass to two fallback dispatches
  and retain blocking findings through substitutions and adjudication.
- Qualify the cheaper models on role-specific synthetic defects and clean controls:
  six completed paired-case calls plus one incomplete call, US$0.012934 total,
  within the 12-call, 4,096-output-token and US$5 pilot caps. Full staged-file
  coverage, independent lanes, secret scanning, tests and exact-tree approval
  remain required. The Windows hook and receipt format are unchanged.

## scg-review 0.4.18 and scg-subagents 0.5.17 - 2026-10-01

- The parent now explicitly selects each fresh or partial-history child's model
  and effort. Full native history inheritance is a deliberate choice, and a
  model label in a brief never selects a serving model.
- Codex pre-commit guidance gives the complete plaintext dispatch for
  `openai/gpt-6.1-sol` at `high` with `fork_turns="none"`, including later
  assignments. GPT through OpenRouter is an external recipient even when the
  parent uses GPT. Native subscription GPT is a different provider route.
- An unsafe handoff refusal can end the parent turn. Correct it once on the
  next user turn through plaintext with the same model and effort; it does not
  show an OpenRouter outage or justify requesting native reviewers. An encrypted
  file path cannot repair delivery. Review lanes and approval gates stay unchanged.
- Run the SCG pre-commit review gate on native Windows. `setup.py check` and
  `install` no longer refuse the platform, so Windows gets the same
  staged-tree receipt gate, commit-msg check and hook provisioning as macOS
  and Linux, through the one shared adapter.
- The hook helper runs on an interpreter recorded in `config.json` as an
  absolute path. Windows defaults to the Python runtime shipped by the router
  (`%USERPROFILE%\.codex\mixed-model-router\runtime\python\python.exe`, or
  `ROUTER_HOME` when set) and never searches PATH: a missing runtime blocks
  setup rather than falling back. macOS and Linux keep the historical
  `python3` when the setting is absent, so an existing installation and its
  config bytes are unchanged. An explicit `interpreter` must be absolute and
  is probed before anything is written. Configurations record absolute
  interpreter paths as UTF-8, so paths containing non-ASCII characters work
  through the Bash shims.
- The Git-for-Windows Bash shims read that interpreter, so `pre-commit`,
  `commit-msg` and `bin/scg-review-state` work on Windows. A repository hook
  is chained through Git's hook runner on Windows, preserving its declared
  interpreter and its ability to reject a commit.
- The adapter's end-to-end tests now run on `windows-latest` as well as Linux.
  Tests that need a POSIX scanner stub stay POSIX-only; the portability
  module covers the scanner on both.
- Refresh the installed adapter before the next review. `setup.py check`
  compares every installed file with the bundled bytes, so copy the files it
  names (`pre-commit`, `commit-msg`, `bin/scg-review-state` and
  `lib/scg_agent_git_hooks.py`) and re-run the check. Keep `config.json`, the
  repository's `core.hooksPath` and the review receipts as they are.

## scg-review 0.4.17 and scg-subagents 0.5.16 - 2026-09-30

- At the owner's request, every pre-commit review pass in Codex now requires
  GPT-6.1 Sol through OpenRouter, `openai/gpt-6.1-sol`, at `high`, replacing
  `xiaomi/mimo-v2.6-pro` at `xhigh`. The requirement stays exact: there is no
  fallback model, and an unavailable route blocks the pass. Claude Code keeps
  its installed adapter agents and their configured Claude models.
- Drop GPT-5.6 Terra (`openai/gpt-5.6-terra`) from the model-selection
  catalogue, its benchmark and evidence rows, and the security selection table,
  to match the router dropping that OpenRouter model. The guide no longer
  steers subagents to Terra; the Codex subscription `gpt-5.6-terra` itself is
  unaffected.

## scg-review 0.4.16, scg-subagents 0.5.15, scg-prototypes 0.1.3, scg-finance 0.1.2 and scg-documentation 0.1.3 - 2026-09-30

- Align the shared update guide and every skill with the router-managed
  delivery model (Plan 179). The router carries the plugin trees, materialises
  a router-owned local marketplace and registers it with the attached clients,
  so the skills arrive and refresh with the router; there is no per-plugin
  updater and no native schedule to configure. The obsolete
  `scripts/updater.py`/`scripts/scheduling.py` setup steps are removed, since a
  shipped plugin no longer carries them. Wording only; delivery behaviour is
  unchanged.

## scg-review 0.4.15 - 2026-09-26

- Rewrite the pre-commit-review skill as a ten-step checklist that less
  capable models can follow in order. Each step names its exact commands and
  when to stop with `❌ Block`, and the severity and re-review decisions are
  tables.
- Give all three lanes one copy-ready reviewer brief, and move the lane
  definitions, reportability rules, severity scale and report format into
  `references/lanes.md`. Each lane reads it, and the main agent adjudicates
  against the same severity scale.
- State the runtime split: in Codex every pass uses the routing policy's
  required model; in Claude Code the passes run on the installed adapter
  agents with their configured Claude models, never router models.
- Add a worked example of the approval receipt's `--pass` encoding.
- No gate is removed or loosened. The secret scan, the single verification
  run, exact-tree approval, the re-review rules and the reportability
  thresholds keep their meaning.

## scg-subagents 0.5.14 - 2026-09-26

- Router workers reject empty, interrupted, narration-only and recognized
  missing-tool-result final replies instead of reporting them as successful
  results. The transcript is still saved for diagnosis.

## scg-review 0.4.14 and scg-subagents 0.5.13 - 2026-09-25

- Require `xiaomi/mimo-v2.6-pro` at `xhigh` for every pre-commit review pass,
  including simplification, correctness, quality and adversarial review. The
  exact model and effort have no fallback; an unavailable route blocks that
  pass instead of substituting a reviewer.

## scg-subagents 0.5.12 - 2026-09-25

- State that `router-workers` serves only a Claude desktop Code session in
  the subscription profile, the first-party profile that talks to Anthropic
  directly. Sessions that can already spawn router models natively, such as
  Codex, an attached terminal Claude Code session, or a desktop session in
  the gateway profile, keep native spawning through the optimal-subagents
  tool guide. Wording only; the runner is unchanged.

## scg-subagents 0.5.11 - 2026-09-23

- Stop a router worker when its runner is interrupted. The worker runs in a
  session of its own, so Ctrl-C, or SIGTERM or SIGHUP sent to the runner,
  reached only the runner. It exited at once and left the worker and its
  shell commands running with their pre-approved tools and no deadline; after
  Ctrl-C it had also deleted the worker's temporary configuration. The runner
  now catches those signals while the worker runs and stops it the way it
  already did at a timeout: SIGTERM, ten seconds, then a kill of its process
  group. It still saves the transcript and prints its JSON result, with
  `error` naming the signal. After Ctrl-C it then ends by SIGINT, so a shell
  loop of workers stops instead of starting the next worker; SIGTERM and
  SIGHUP exit 1. A signal the caller already ignores, such as SIGHUP under
  `nohup`, stays ignored, and SIGKILL still cannot be caught.
- Reproduced and verified on macOS with Claude Code 2.1.280, router
  0.6.119.113 and DeepSeek V4.1 Flash (`max`), on a synthetic brief that ran
  `sleep 295` in a scratch folder outside the home folder, one model turn per
  run. Before the fix, SIGINT and SIGTERM each left the worker and its `sleep`
  running after the runner exited without a result. After it, SIGINT, SIGTERM
  and SIGHUP each left nothing running, and the runner reported
  `interrupted by <signal>` with the served model. Stopping the runner's
  background task in Claude Code already ended the whole process tree; the
  task's output now also carries the JSON result. A new offline test sends the
  three signals to the runner with a fake worker and fails without the fix.
  Linux runs only that offline test, in CI, and Windows is not yet verified.

## scg-subagents 0.5.10 - 2026-09-23

- Add `router-workers`, which runs a bounded task on a router model as an
  isolated headless Claude Code worker. It serves clients whose own subagents
  cannot reach the SCG Router, such as the Claude desktop app, which talks to
  Anthropic directly. The runner resolves the model against the router's live
  list, gives the worker shell and file tools in its folder but none of the
  caller's settings, connectors, tokens or `~/.claude` instructions, stops it
  and its shell commands at a deadline and prints one JSON result with the
  served model. optimal-subagents still chooses the model and effort, and now
  points to the skill.
- Verified on macOS with Claude Code 2.1.280 and router 0.6.114.107 on a
  synthetic failing-test fix, four workers in parallel: DeepSeek V4.1 Flash
  (`max`), GLM 5.3 Flash (`max`), MiMo V2.6 Flash (`xhigh`) and Muse Spark
  1.3 Contributor (`xhigh`) each ran the tests in the shell, fixed the bug,
  left the tests unchanged and were served by the requested model, in 10 to
  44 seconds and about 26,000 input tokens each. Live checks also confirmed
  that a timed-out worker leaves no shell command running, that the caller's
  `~/.claude/CLAUDE.md` stays out of a worker whose folder is under the home
  folder, and that the folder's own `CLAUDE.md` still loads. Claude Code's
  `--bare` mode was rejected because it dropped the worker's Grep and Glob
  tools. Linux and Windows are not yet verified.

## scg-review 0.4.13, scg-subagents 0.5.9 and scg-documentation 0.1.2 - 2026-09-23

- Resolve the finance role's required analyst skill through the current
  `scg-finance` capability instead of its retired NetSuite-specific name.
- Keep Ponytail's minimal implementation guidance while removing its fixed
  code-first, three-line response rule. Preserve requested scope, review
  evidence, safety boundaries and acceptance gates.
- Treat article outlines and writer-brief examples as optional documentation
  aids. Follow the user's format, length, tone and punctuation preferences;
  do not prescribe em dashes or an article structure for every task.

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
  `example/prototype-archive`, sync it to the private channel bucket,
  invalidate the CloudFront path and verify the live URL before printing it.
- Fail closed before writing when the slug, the asset base path or the
  SHA-256-verified gitleaks scan reports a problem; refuse slug collisions
  unless `--update`, refuse a scanner configured through `GITLEAKS_CONFIG`,
  and re-check the copied artifact and any `--source` snapshot before they are
  committed or uploaded.
- Ship `list` and `unpublish` alongside `publish`, keep the archived source when
  a prototype is unpublished, and require the same shared updater setup as the
  other SCG plugins.
- The channel foundation lives in `example-infrastructure`
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
