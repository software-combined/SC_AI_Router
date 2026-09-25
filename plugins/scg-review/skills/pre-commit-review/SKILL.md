---
name: pre-commit-review
description: Run the required staged-diff review (a simplification pass, then three read-only review lanes) before a git commit and record the approved staged-tree state for the shared Git hook. Use when an agent is preparing to commit changes, running /pre-commit-review, reviewing staged commit scope, or deciding whether a commit may proceed after code, workflow, documentation, test, configuration, or infrastructure edits.
---

# Pre-Commit Review

When installing or updating this plugin for use, complete the shared
[automatic-update setup](../../references/updates.md) on macOS, Linux or Windows.
Verify the native schedule and an update run; a pull alone is not setup.
Respect explicit read-only scope. Ordinary reviews reuse the existing schedule.

This skill is the mandatory gate before every commit. One main agent prepares and risk-classifies the staged scope, runs the simplification pass and stages its edits, runs the secret scan and the required verification once on the frozen tree, has three read-only reviewer subagents inspect the resulting staged tree in parallel, adjudicates their evidence, fixes accepted blockers, and records one approved staged-tree state for the shared Git hook. If this process does not run, the task is incomplete and commit is forbidden.

**Materiality over coverage.** The gate catches realistic, change-caused failures before they land; it does not enumerate speculative or theoretical edge cases. Report, fix, and block only on failures with a plausible, executable path in normal or demonstrably reachable use. A proportionate review that completes and ships is success; an exhaustive review that never converges is a failed review.

## Runtime Mapping

Before each review, read the bundled [reviewer routing policy](../../references/reviews.md)
and the effective host/project policy. The routing reference owns default models,
fixed reasoning levels, authorized availability fallbacks and escalation. It is
an unchanged release copy of the canonical optimal-subagents policy, not a
second independently maintained model table. Exact user or project model/effort
requirements take precedence.

Local user policy override: every pre-commit pass, including code
simplification, correctness, quality and adversarial review, uses
`xiaomi/mimo-v2.6-pro` at `xhigh`. This exact model and effort requirement has
no model fallback. If that route is unavailable, the affected pass is `❌ Block`;
do not substitute another model or effort.

If the effective policy includes a listed eligible fallback and the preferred
model is unavailable, use that fallback and record the substitution. When the
policy requires an exact model/effort or lists no fallback, the affected pass is
`❌ Block` and no substitution is permitted. A required pass is also `❌ Block`
when no permitted model can complete it. Never change runtimes, accounts, data
constraints or review gates to bypass the requirement. Confirm access through
actual review calls; accepted dispatch is not completed review. See
[provider access and identity rules](../../references/reviewer-models.md).

- **Codex:** use the bundled [code-simplifier](../code-simplifier/SKILL.md) for
  Pass 1 and the active subagent tools for the three independent review lanes.
- **Other runtimes:** use a verified installed adapter implementing the same
  procedure and its applicable routing policy. Only Codex packaging is delivered;
  do not assume that this plugin installs Claude Code or OpenCode agents.

Record each pass's requested and returned identity in review notes; the hook
receipt contains only the three successful final review lanes. Missing served
identity is `unverified`; a known mismatch invalidates that pass. Fallbacks never
remove staged-tree coverage, three-lane independence or genuine-review requirements.

Use the **elevated-risk profile** when the staged change touches auth, security,
money, destructive data, migrations, concurrency, or deployment risk. A material
match in staged or directly relevant context files escalates the whole review's
inspection profile; it does not automatically require a more expensive model.

## Sending The Review Brief

Use the active runtime's subagent tools and their actual schemas; discover deferred tools when discovery is available. Pass the assigned lane, absolute worktree path, staged tree/scope, recorded verification result, required context, ponytail-first instruction, read/write authority and expected report. The parent owns orchestration: an individual reviewer must not try to run the entire gate or spawn its own reviewers. Use the effective reviewer model policy, not model names remembered from an earlier turn.

### Pass 1 timing and liveness

Pass 1, the simplification pass, is often the slowest review phase. It may
spend substantial time reading the full staged scope, project instructions,
callers and relevant tests before it edits or returns a report. A quiet child
or a long interval without a progress message is not evidence that the pass has
stalled. Keep the active simplifier's write ownership and wait for its result;
do not cancel, interrupt, respawn, or launch a duplicate simplifier merely
because it is quiet. Check status through the runtime's bounded wait/status
mechanism. Treat Pass 1 as stalled only after the runtime reports a failure, the
child requests attention, or an established runtime/transport timeout occurs.
If it fails, inspect the worktree and index before retrying and use one focused
fresh brief after identifying the failure cause.

Every reviewer brief includes these inspect commands, not a tree-equality goal:

```bash
git write-tree
git diff --cached --stat
git diff --cached
git show :path
```

`git write-tree` must print the captured reviewed-tree id; on mismatch, report and stop. `git show :path` covers only the listed staged files. Context is a named path list. Do not reconstruct trees, extract the repository to `/tmp`, inspect unlisted files, or continue after the Markdown report. The inspect contract is shared; do not write per-model prompts. A failed report is not unavailability: do not rerun the same model with the same brief. One focused correction, then the next listed fallback.

Normally send this brief in the tool's message field. If an accepted child demonstrably misses the brief or starts unrelated work, stop it rather than repeating full reviews. A supported fallback is to write the same brief to a non-secret temporary Markdown file on the shared filesystem and invoke the subagent tool with an instruction to read that absolute path first. If only task labels are arriving, make the brief file identifiable in the task label too. This changes brief transport only; the effective model/fallback policy, tool-based delegation, pass order and approval rules remain intact. Do not substitute a top-level task or a self-written review receipt.

Check the returned review against the assigned scope. A brief acknowledgement, task name or accepted spawn is not review evidence. Reports must cover the full staged diff and every complete staged-index file, including an index/README file beyond its changed hunk. When a report conflicts with observed actions, verify the missing inspection before accepting it. Do not add delivery probes or extra approval questions to ordinary successful reviews. If file handoff also fails, report the exact tool error or missing coverage, apply the bounded availability fallback policy where eligible, and preserve the work if no permitted pass can run; do not repeat unbounded review calls.

Use a distinct brief file for each pass or changed reviewed tree. If a resumed child repeats a result for the old tree without reading the updated brief, reject that stale result and use a fresh subagent invocation with the new brief; do not relabel the old review as current.

## Hard Rules

- Run this process once for the intended staged commit scope. Stage only that scope; isolate unrelated staged work first.
- Apply applicable host/project staged-size rules. Otherwise limit a commit to 800 meaningful changed lines (additions plus deletions), excluding generated, vendored and mechanical files; an unavoidable oversized coherent change needs a short justification before review. Unjustified oversize is `❌ Block`.
- The simplification pass runs before the review lanes and its edits are staged before the secret scan. A simplification pass that runs after the lanes is a material delta under the Re-Review Rule.
- Reviewers are read-only. They inspect the staged diff and full staged file content from the git index (`git diff --cached`, `git show :path`), not snippets or working-tree content, and must not edit, format, stage, commit, push, delegate, or mutate any system. The main agent runs the required verification once on the frozen tree before the lanes; the lanes do not repeat it. A lane may run one narrowly targeted, non-destructive check to prove or disprove a specific finding, and must report what it ran and what it showed.
- Every pass reads ponytail first. The simplification pass and each of the three reviewer lanes must read the bundled [ponytail](../ponytail/SKILL.md) in full before inspecting the staged scope, and apply it within their own lane ownership. Pass its resolved absolute path to the reviewer. Ponytail informs judgment about the smallest correct change; it never overrides the reportability, severity, or scope rules below, and never justifies reporting style-only, LOW, speculative, or out-of-lane findings, or editing for rejected items.
- Fix every accepted `CRITICAL` or `HIGH` finding before commit. A reviewer label alone is not acceptance; the main agent verifies causality, proof, impact, and scope.
- Do not edit for rejected, duplicate, pre-existing, speculative, style-only, polish, or optional-hardening observations, and do not turn them into follow-up work unless the owner asks or the evidence shows a separate material risk.
- Commit only with an allowed combined decision and approval for the final staged tree. Subjects use `<type>: <short summary>`, with type `feat`, `fix`, `refactor`, `test`, `chore`, or `docs`, consistent with the shared commit-msg hook.

## Preflight

1. Identify the repo root and current branch. Read the root and nested `AGENTS.md` files that govern the staged files.
   Run `python3 <plugin-root>/scripts/setup.py check --repo <absolute-repo-path>` using the installed plugin root (two directories above this skill directory). Failure means `❌ Block`; use [review-setup](../review-setup/SKILL.md) to diagnose missing dependencies. Installation never constitutes a completed review or approval.
2. Inspect `git status --short` and confirm the staged scope is intentional and within the size rule above.
3. **Run the simplification pass (Pass 1)** and stage its edits; a no-op is valid and is recorded as such. Expect this pass to take time, including quiet periods while the executor reads and reasons. Do not treat silence as a stall or start a duplicate pass; the staged scope must still be the intended commit set afterwards.
   - Invoke `code-simplifier` using the active runtime's entry in the Runtime Mapping and its installed skill. Pause main-agent edits while the simplifier has write ownership. It may edit staged files only; undo only its own out-of-scope edits, preserving pre-existing work. It reads ponytail first, follows project instructions, verifies behavior preservation, and reports changes or a no-op. The main agent verifies and stages the result; the hook receipt keeps exactly the three review lanes.
4. Capture the reviewed scope: `git diff --cached --name-only`, `git diff --cached --stat`, `git diff --cached`, and `git write-tree` as the reviewed index tree id.
5. **Run the secret-scan gate** before spawning any reviewer:

   ```bash
   ~/.config/scg-agent-git-hooks/bin/scg-review-state scan
   ```

   On native Windows, where the Bash shim above is unavailable, run the same
   scan through the module directly:
   `python <plugin-root>/support/git-hooks/lib/scg_agent_git_hooks.py scan`.
   Windows scanner support does not include hook or receipt enforcement.

   The command verifies the approved native Gitleaks binary against the pin in `~/.config/scg-agent-git-hooks/config.json` (absolute path, version, and binary SHA-256, with the Homebrew bottle recorded as provenance), refuses to run if `GITLEAKS_CONFIG` or `GITLEAKS_CONFIG_TOML` is set or the repository supplies `.gitleaks.toml` or `.gitleaksignore`, and scans the exact staged tree with redacted output. Any non-zero exit (missing, drifted, timed-out, or failed scanner, or any leak) means zero reviewer calls and `❌ Block`. Never print or paste secrets; report the credential type and `file:line` only, and recommend rotation. Changing the pin or allowing a repository config is an owner change to the hook adapter, never a session workaround. A different target must supply and prove its own adapter before this skill is usable.
6. Identify the context files reviewers need beyond the staged files and pass their paths in each reviewer prompt: direct callers/importers of changed exported functions or modules; adjacent tests and fixtures; schemas, contracts, builders, snapshots, workflow definitions, or config files that define the changed behavior; relevant docs/runbooks when behavior or deployment changes. Reviewers read these themselves. If a required context cannot be inspected, that lane's review is incomplete.
7. Classify the verification commands, then run the required ones once, in the main agent, on the frozen staged tree. Required: documented pre-commit checks, targeted tests for changed behavior, new or changed tests, typecheck/lint/build checks that normally gate the repo, and contract/snapshot regeneration checks relevant to the staged files; expected result is exit code 0 unless the repo documents stricter output. Optional: broad, slow, destructive, production-impacting, or unrelated commands; never run destructive or production-impacting commands without explicit approval. If no required command exists, record a verification gap. This run comes after Pass 1 because the simplification pass edits the tree; an earlier run would describe a tree that no longer exists. Record the exact commands, outcomes and reviewed tree id, and pass that record to every lane as the shared verification evidence. A failed required command is `❌ Block` before any reviewer call: fix the cause, re-freeze the tree, repeat the secret scan, and run the affected commands again.
8. Immediately before spawning reviewers, confirm `git write-tree` still equals the captured tree. If it changed, inspect and isolate the delta, recapture the intended scope, repeat the secret scan, and re-run the affected verification commands before any reviewer calls.
9. If `tasks/todo.md`, `tasks/lessons.md`, or another repo task note exists, prepare to record the review output there.

## Reviewer Lanes

Run the three lanes in parallel after Pass 1 has finished and its edits are staged, so no more than three subagents run concurrently. Each lane owns a distinct failure class and does not report the others' findings. The main agent includes in every reviewer prompt the bundled `ponytail` skill's absolute path and an instruction to read it in full first and apply it within that lane's ownership; a lane that cannot confirm it read ponytail is incomplete, the same as missing staged-scope inspection.

### Pass 2: Correctness

Owns functional defects, broken contracts, blocking verification failures, and missing tests for changed high-consequence behavior. Not naming, cleanup, optional refactors, or generic hardening. For replacements or consolidation introduced by simplification, trace affected callers and compare the old and new input/output contracts, exceptions, side effects, and meaningful execution order; a standard-library or native replacement still needs to satisfy the existing contract. Report concrete regressions, not the choice to simplify.

Focus: Can the staged behavior fail for common, edge, empty, malformed, stale, or concurrent inputs? Does it preserve public contracts, schemas, file formats, workflow contracts, and API behavior? Are errors handled in the repo's established pattern? Are security, auth, secret handling, permissions, and untrusted-input boundaries preserved? Are new or changed tests sufficient to catch the likely regression?

### Pass 3: Quality

Owns only change-introduced maintainability defects with a concrete near-term correctness or operability consequence. Style, naming preferences, cleanup, soft line-count thresholds, possible future abstractions, and optional simplification are omitted. Use reuse opportunities as investigation clues, not automatic findings: report duplicate logic, parallel paths, or wrappers only when the staged evidence shows a concrete near-term consequence, naming the canonical path and the harmful divergence. Fewer lines or a single caller alone never justify a finding or another simplification pass.

Focus: Is this the smallest correct change that matches local patterns? Does it introduce a parallel path where a canonical path exists? Is the code easier to read, test, and maintain after the change? Are comments useful and sparse? Are tests structured like existing tests rather than bespoke one-offs?

### Pass 4: Adversarial

Owns trust-boundary abuse, destructive side effects, replay, rollback, concurrency, deployment, and fail-open risks. It must prove a concrete failure path and does not report hypothetical hardening or duplicate a correctness finding. When simplification removes or consolidates a guard or wrapper, trace the reachable failure or abuse path it controlled and check the validation, authorization, idempotency, and data-loss or recovery protections on the remaining path. Report only concrete lost protections or fail-open behavior.

Focus: What hidden regression would pass a casual review? What missing test would let this bug return? What race, replay, idempotency, rollback, deployment, migration, or observability failure could occur? What happens if dependencies, schemas, credentials, permissions, live state, or external services drift? What breaks if the change is partially deployed, retried, or reverted?

## Reviewer Output And Severity

Each reviewer returns a Markdown lane summary written for a person, not a parser. Lead with one of these verdicts, emoji included, never snake_case:

- `✅ All Clear`
- `📝 Proceed With Notes`
- `❌ Block`

These three labels are the whole verdict vocabulary. A verdict keeps its label and its
emoji wherever it is relayed — a reviewer's own summary, the main agent's interim update
while other lanes still run, and the final recap — and is never paraphrased into prose
(`All Clear`, `blocks`, `passed`), stripped of its emoji, or replaced by another symbol
such as `🟡` or `🔴`.

Name the model that actually ran the lane on the next line as `Model: <returned-model> at <effort>` (use `unverified` when serving identity is missing). Then confirm ponytail and full staged-index inspection, inspected files, evidence-backed findings, missing tests, and residual risks. Each finding includes staged `file:line`, failure path, impact, confidence, and the smallest remedy. Omit empty findings, missing-test, and risk sections; `✅ All Clear` requires all three to be empty. Any `CRITICAL` or `HIGH` finding or missing test requires `❌ Block`. Keep snake_case only for the Git-hook `--decision` values below.

A finding is reportable only when all of these hold: the staged change introduced or materially worsened it; the reviewer names an executable or deterministic failure path with exact staged evidence; the concern is realistic rather than speculative (theoretical edge cases without a reachable path, defense-in-depth-only observations, and completeness for its own sake are omitted even when technically arguable); the impact is at least `MEDIUM`; and confidence is at least `0.80`. Each finding recommends the smallest in-scope remedy, including narrowing or reverting the staged change. A real blocker with no safe in-scope remedy is reported as `❌ Block` with a request for scope or owner direction, never suppressed.

Missing tests are reportable only at `HIGH` or `CRITICAL`: the change alters high-consequence behavior, the missing test would prevent a named failure, and no equivalent deterministic verification already covers it. Residual risks are for concrete, unavoidable runtime or verification uncertainty only, not a parking lot for rejected findings or cleanup ideas.

- `CRITICAL`: likely data loss, secret exposure, serious security flaw, destructive production action, or the commit would obviously break core behavior.
- `HIGH`: likely regression, broken contract, missing required safety gate, security or data-integrity exposure, required-operability failure, meaningful untested high-consequence risk, or the commit would fail expected verification.
- `MEDIUM`: proven change-caused defect whose impact is bounded, reversible, and does not break a contract, safety boundary, data integrity, or required operability. It proceeds only with an explicit acceptance rationale and does not trigger an automatic edit.
- `LOW`: not reportable.

## Main-Agent Synthesis

1. Confirm all three reviewers inspected the staged diff and full staged index files and attest they read the installed `ponytail` skill in full before inspecting. A lane missing either confirmation is incomplete and blocks the commit.
2. De-duplicate findings by root cause and assign cross-lane duplicates to the owning lane.
3. Adjudicate every item as Accept, Downgrade, or Reject against the staged evidence: the change caused or worsened it, the failure path is executable or deterministic, the consequence is material, confidence is justified, and the smallest fix is in scope. Record a short rationale for every non-obvious decision. A rejected reviewer `❌ Block` triggers no edits and no further review cycle.
4. Fix accepted `CRITICAL` and `HIGH` findings and missing tests. Stop if an accepted blocker requires user or product input. Do not automatically fix `MEDIUM` findings: accept the concrete residual risk with rationale as `📝 Proceed With Notes`, or ask the owner to expand scope.
5. Re-run the required verification commands that an accepted fix affects; the recorded pre-lane run stands for everything it already covered. When the affected scope is unclear, re-run the full set. A failed required command blocks the commit. If one cannot run because of an environment or dependency blocker, record the exact blocker, residual risk, and next verification step before allowing `📝 Proceed With Notes`.
6. Record in the task notes when available: staged scope; simplification outcome (ran or no-op, files changed, verification); reviewed tree id; requested and returned model plus effort per lane; reviewer verdicts; fixed findings; final staged delta after review; accepted residual risks; verification commands and results.
7. After adjudication, write a short person-facing recap in the main-agent reply: the combined verdict, then one bullet per lane with that lane's verdict and the model that ran it (`Model: <returned-model> at <effort>`, or `unverified`). Lane verdicts carry their
   label and emoji from the first mention, not only in the recap. For `📝 Proceed With Notes` or `❌ Block`, add a second flat bullet list of the accepted notes: lane, one-line point, and why it was accepted or why it blocks. Do not dump snake_case tokens in that recap.
8. Apply the Re-Review Rule, then record the approval and commit as described below.

Combined decision (same human labels as the lane verdicts):

- `✅ All Clear`: all reviewers pass, no unresolved meaningful risk, every required verification command ran and passed.
- `📝 Proceed With Notes`: only accepted medium or unavoidable verification/runtime residual risks remain, with rationale recorded. Notes create no automatic remediation or follow-up scope.
- `❌ Block`: any unresolved `CRITICAL` or `HIGH` finding, incomplete reviewer inspection, inability to complete a required pass using its exact mandated model/effort or an eligible policy fallback, missing staged scope isolation, failed required verification, or unresolved high-severity missing test. Speculative, unproven, or theoretical concerns never block on their own; they are rejected at adjudication so the gate converges.

## Re-Review Rule

Before committing, compare the final staged tree with the reviewed tree id. If unchanged, no re-review is needed. If changed, inspect the delta with `git diff <reviewed-tree-id> --cached` and classify it:

- **Mechanical delta** (fix and restage; no pass re-runs): typos, behavior-neutral formatting, adding the exact regression test a reviewer requested without changing test strategy, or narrowing a change exactly as requested without altering behavior. Prose-only corrections are mechanical; changes to agent instructions, approval rules, executable runbooks, OpenAPI, specs, schemas, or workflow JSON are material when they alter a contract or required behavior, regardless of file extension. The delta must not touch behavior, contracts, security, data, deployment, migration, concurrency, idempotency, retry, or test strategy. Self-verify it, run targeted verification, and record why the original review still covers the final scope.
- **Material delta**: any change to behavior or public contracts; auth, security, permissions, or secrets handling; payments, sends, deletes, record writes, or other side effects; migrations, deployment, rollback, or infrastructure; concurrency, idempotency, retry, or state management; test strategy or coverage boundaries. A simplification pass run after the lanes is always material. Re-run the finding's owning lane on the final staged scope, plus correctness when another lane owned the finding or runtime behavior/contracts changed. Re-run all three lanes only when one remediation spans more than one lane's ownership, introduces a new risk domain, or cannot be cleanly bounded from the staged delta.

An unaffected lane's result may be inherited only after inspecting the exact reviewed-to-final delta and recording why its conclusion still holds. Record the original tree, final tree, re-run lanes, inherited lanes, and rationale before approving the final tree.

Material remediations and targeted re-review cycles are not capped. After each accepted CRITICAL or HIGH fix, apply this rule to the new staged tree and continue until the combined decision is ALL CLEAR or PROCEED WITH NOTES. Stop only when an accepted blocker needs owner or product input. A rephrased version of the same root cause is not a new finding.

## Record Approval And Commit

Verify the effective `core.hooksPath` uses `~/.config/scg-agent-git-hooks/`. The hook validates an approved receipt for the repository, branch, exact staged tree, required lane identities, and configured lifetime; it does not itself run the review or secret scan. Those are mandatory steps owned by this skill. Re-scan whenever the staged tree has changed since the passing scan, including mechanical deltas. After required verification and an allowed combined decision, record approval under `~/.cache/scg-agent-git-hooks/reviews/`:

```bash
~/.config/scg-agent-git-hooks/bin/scg-review-state approve --decision ALL_CLEAR --pass correctness=<requested-model>@<requested-variant>::<returned-model>@<returned-variant> --pass quality=<requested-model>@<requested-variant>::<returned-model>@<returned-variant> --pass adversarial=<requested-model>@<requested-variant>::<returned-model>@<returned-variant>
```

Map the human combined decision onto the hook token: `✅ All Clear` -> `--decision ALL_CLEAR`, `📝 Proceed With Notes` -> `--decision PROCEED_WITH_NOTES`. Never record approval for `❌ Block`. The hook treats each `--pass` value as an opaque identity, so encode both sides exactly as `<requested-model>@<requested-variant-or-unavailable>::<returned-model-or-unverified>@<returned-variant-or-unverified-or-unavailable>`; a returned side of `unverified` is expected when the runtime does not echo serving identity and never blocks approval. Never invent a value, or record approval without a genuine three-lane review having run; self-attesting the review is a bypass of the gate, not a review. Then commit.
