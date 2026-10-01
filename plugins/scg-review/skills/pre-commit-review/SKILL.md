---
name: pre-commit-review
description: Run the required staged-diff review (a simplification pass, a secret scan, then three read-only review lanes) before every git commit, and record the approved staged-tree state for the shared Git hook. Use when an agent is about to commit, runs /pre-commit-review, reviews staged commit scope, or decides whether a commit may proceed after code, workflow, documentation, test, configuration or infrastructure edits.
---

# Pre-Commit Review

These skills ship with the SCG router, which delivers and refreshes them; see
[automatic updates](../../references/updates.md). There is no per-plugin updater
to configure. Respect explicit read-only scope.

This skill is the gate before every commit. You, the main agent, prepare the staged change, run a simplification pass, scan for secrets, run the required checks once, have three read-only reviewer subagents inspect the exact staged tree, decide on their findings, and record one approval for that tree. The shared Git hook refuses a commit without that approval. If this process does not run, the task is incomplete and you must not commit.

**Materiality over coverage.** The gate catches realistic failures that this change causes. Report, fix and block only on failures with a plausible path in normal or demonstrably reachable use, never on speculative edge cases. A proportionate review that finishes is success; an exhaustive review that never converges is a failed review.

## The ten steps

Do them in this order. Each section below says exactly what to run.

| Step | Do | Stop with `❌ Block` when |
|---|---|---|
| 1 | Setup and Ponytail dependency check | the check fails or Ponytail cannot be read |
| 2 | Stage only the intended change and check its size | unrelated work is staged, or it is oversized without a reason |
| 3 | Pass 1: simplification, then stage its edits | no permitted model can complete Pass 1 |
| 4 | Capture the reviewed tree | |
| 5 | Secret scan | the scan exits non-zero |
| 6 | Run the required checks once | a required check fails |
| 7 | Brief and run the three review lanes | a lane cannot complete |
| 8 | Adjudicate the findings and fix blockers | an accepted blocker needs owner input |
| 9 | Re-review if the staged tree changed | |
| 10 | Record the approval and commit | |

## Ponytail dependency

Before Pass 1, resolve `scg-ponytail:ponytail` from the active client's skill
catalogue or installed-plugin inventory (`/scg-ponytail:ponytail` in Claude
Code), and read its `SKILL.md` in full. Supply that same resolved absolute
path to the simplifier and every review lane; each pass reads it before
inspection and confirms its path. Resolve the current installation, never a
hard-coded cache version or the former standalone or SCG Review copy.

If the plugin is missing, disabled or unreadable, report `❌ Block` before
dispatching any pass. Install and enable `scg-ponytail@scg-agent-plugins` in
the active client, then retry the setup check. Never omit this dependency or
fall back to older Ponytail guidance.

## Models and runtimes

Read the bundled [reviewer routing policy](../../references/reviews.md) before every review. It sets the model and fixed effort for each pass, any authorised fallbacks, and escalation. It is an unchanged copy of the canonical optimal-subagents policy. Exact user or project model/effort requirements take precedence over it.

- **Codex:** prefer `openai/gpt-6.1-sol` at `high` (GPT-6.1 Sol through OpenRouter) for every pass. Apply the bundled policy's ordered fallbacks automatically, checking effective access and supported effort before dispatch. Use the bundled [code-simplifier](../code-simplifier/SKILL.md) for Pass 1 and the active subagent tools for the three lanes.
- **Claude Code:** use the installed adapter agents `code-simplifier`, `review-correctness`, `review-quality` and `review-adversarial`, with the Claude models configured in them. Do not route these passes to router models. This plugin does not install those agents.
- **Other runtimes:** use only a verified installed adapter that implements this procedure.

When a policy has a listed eligible fallback and the preferred model is unavailable, use that fallback and record the substitution. Fallbacks are enabled for every pass unless the current user explicitly forbids substitution or an applicable instruction requires an exact route. Follow the policy's two-fallback dispatch limit and shared-failure rules. A required pass is `❌ Block` when no permitted model can complete it. Never switch runtimes, accounts or data constraints, or weaken a gate, to get around a requirement. Confirm access through actual review calls: an accepted dispatch is not a completed review. See [provider access and identity rules](../../references/reviewer-models.md).

Record each pass's requested and returned model and effort in your notes. Missing served identity is `unverified`; a known mismatch invalidates that pass. Fallbacks never remove staged-tree coverage, lane independence or the need for a genuine review.

Use the **elevated-risk profile** when the staged change, or a directly relevant context file, touches auth, security, money, destructive data, migrations, concurrency or deployment. You decide the profile in step 2 and state it in every brief. It deepens inspection and the evidence required for the whole review; it does not by itself require a more expensive model.

### Codex: select the model and handoff

For Pass 1 and each review lane, select the first eligible route from the policy.
Call `spawn_agent` directly from the tool set chosen below, with explicit model
and effort and `fork_turns="none"`. A preferred correctness-lane dispatch is:

```json
{
  "task_name": "review_correctness",
  "fork_turns": "none",
  "model": "openai/gpt-6.1-sol",
  "reasoning_effort": "high",
  "message": "GPT-6.1 Sol High: pre-commit review, correctness lane. Replace this message with the complete Step 7 brief, including the worktree, reviewed tree, staged files and context."
}
```

Set model and effort to the selected route for each pass, including fallbacks.
Pass 1 receives the code-simplifier assignment; the lanes receive Step 7's brief.
A model label in the message does not select the model. Do not omit tool arguments
or rely on installation-wide subagent defaults.

If `collaboration_plaintext` handoff tools are offered, use them for every
subagent assignment, message and follow-up, whatever the recipient. Otherwise
use the `collaboration` tools. Pass model and reasoning_effort explicitly;
external children need `fork_turns="none"`. The native subscription id
`gpt-6.1-sol` is a different route from `openai/gpt-6.1-sol` and is an
authorized fallback in the policy.

A handoff refusal is not model or provider unavailability and does not justify
asking to replace the required OpenRouter reviewer with a native model. The
router ends the parent turn before the bad call executes and cannot invent a
recoverable tool result. Report the exact delivery blocker as `❌ Block` and
preserve the work.

## Step 1: Setup check

Find the repo root and branch, and read the root and nested `AGENTS.md` files that govern the staged files. Then run this with the installed plugin root, which is two folders above this skill's folder:

```bash
python3 <plugin-root>/scripts/setup.py check --repo <absolute-repo-path>
```

On native Windows, use Git Bash for this guide's Bash commands. In PowerShell,
run setup with an absolute interpreter, for example the router's runtime:

```powershell
& "$env:USERPROFILE\.codex\mixed-model-router\runtime\python\python.exe" "<plugin-root>\scripts\setup.py" check --repo "<absolute-repo-path>"
```

A failure is `❌ Block`. Use [review-setup](../review-setup/SKILL.md) to diagnose it. Installing never counts as a review or an approval.

## Step 2: Stage only the intended change

Run `git status --short`. Stage only this commit's scope, and move unrelated staged work out first. Apply the host or project size rule. Otherwise keep a commit within 800 meaningful changed lines (additions plus deletions), not counting generated, vendored and mechanical files. An unavoidable oversized but coherent change needs a short written justification before review; unjustified oversize is `❌ Block`. Then decide the risk profile: normal, or elevated (see Models and runtimes) with the reason.

## Step 3: Pass 1, simplification

Run the simplification pass before the lanes, then stage its edits. A no-op is valid and is recorded as one. Use your runtime's entry under Models and runtimes and the installed code-simplifier skill. Pause your own edits while the simplifier has write ownership. It edits staged files only, reads ponytail first, follows project instructions and reports its changes or a no-op. If it edits outside the staged scope, undo only its own out-of-scope edits and keep any pre-existing work. Verify its result, then stage it; the staged scope must still be the intended commit. The hook receipt still lists only the three review lanes.

Pass 1 is often the slowest phase. The simplifier may read the staged scope, instructions, callers and tests for a long time before it edits or reports, so a quiet child is not a stalled child: do not cancel, interrupt, respawn, or launch a duplicate simplifier because it is quiet. Check on it through the runtime's bounded wait or status mechanism. Treat Pass 1 as stalled only when the runtime reports a failure, the child asks for attention, or an established runtime/transport timeout occurs. Then inspect the worktree and index before one focused retry with a fresh brief.

## Step 4: Capture the reviewed tree

```bash
git diff --cached --name-only
git diff --cached --stat
git diff --cached
git write-tree
```

The `git write-tree` output is the reviewed tree id. Every later step refers to it.

## Step 5: Secret scan

Run this before any reviewer call:

```bash
~/.config/scg-agent-git-hooks/bin/scg-review-state scan
```

On native Windows, run this Bash command in Git Bash. Git for Windows also runs
the installed hook shims through Bash; the helper uses the interpreter recorded
in `config.json` (the router's runtime by default).

The scan checks the pinned Gitleaks binary (absolute path, version and SHA-256 in `~/.config/scg-agent-git-hooks/config.json`). It refuses to run if `GITLEAKS_CONFIG` or `GITLEAKS_CONFIG_TOML` is set or the repository supplies `.gitleaks.toml` or `.gitleaksignore`, and it scans the exact staged tree with redacted output. Any non-zero exit (a missing, changed, timed-out or failed scanner, or any leak) means zero reviewer calls and `❌ Block`. Never print or paste a secret: report the credential type and `file:line`, and recommend rotation. Changing the pin or allowing a repository config is an owner change to the hook adapter, never a session workaround. A different target must supply and prove its own adapter before this skill is usable there.

## Step 6: Run the required checks once

Run the required checks yourself, once, on the frozen tree. This comes after Pass 1 because Pass 1 edits the tree; an earlier run would describe a tree that no longer exists.

- **Required:** documented pre-commit checks, targeted tests for changed behaviour, new or changed tests, and the typecheck, lint, build, contract and snapshot checks that normally gate the repo. Expect exit code 0 unless the repo documents stricter output.
- **Optional:** broad, slow, destructive, production-impacting or unrelated commands. Never run destructive or production-impacting commands without explicit approval.
- If no required command exists, record a verification gap.

Record the exact commands, their results and the reviewed tree id. Every lane receives this record and does not repeat the checks. A failed required check is `❌ Block`: fix the cause, re-freeze the tree, repeat the secret scan and rerun the affected checks.

Right before spawning reviewers, confirm `git write-tree` still prints the reviewed tree id. If it does not, isolate the change, recapture the scope, rescan and rerun the affected checks.

## Step 7: Brief and run the three review lanes

Run the three lanes in parallel, only after Pass 1 is finished and staged, so no more than three reviewers run at once. Each lane owns one failure class, defined in the [lane guide](../../references/lanes.md): correctness, quality and adversarial.

List the context files reviewers need beyond the staged files: direct callers or importers of changed exports; adjacent tests and fixtures; schemas, contracts, builders, snapshots, workflow definitions or config that define the changed behaviour; and docs or runbooks when behaviour or deployment changes. If a lane cannot inspect required context, its review is incomplete.

Send every lane this brief, changing only the lane name and model line. Do not write per-model prompts.

```text
<requested model> <effort>: pre-commit review, <lane> lane, for <task or branch>.
Worktree: <absolute worktree path>
Reviewed tree: <tree id>
Staged files: <list>
Context files: <absolute paths>
Risk profile: <normal, or elevated because ...>
Verification already run: <commands and results>
First read in full: <resolved absolute path of scg-ponytail's ponytail SKILL.md>, then <absolute path of references/lanes.md>, applying its <lane> section.
Inspect the staged change with these commands, run in the worktree, and read the listed context files; inspect nothing else:
  git write-tree            must print the reviewed tree id; on a mismatch, report it and stop
  git diff --cached --stat
  git diff --cached
  git show :path            for every staged file, in full
You are read-only: do not edit, stage, commit, push, delegate or change any system. You may run one narrow, non-destructive check to prove or disprove a finding; report what you ran and what it showed.
Reply in the lane report format from the lane guide, then stop.
```

`git show :path` covers only the listed staged files, and context is a named path list. Do not reconstruct trees, extract the repository to `/tmp`, inspect unlisted files, or continue after the Markdown report. A failed report is not unavailability: do not rerun the same model with the same brief. Make one focused correction, then use the next listed fallback if the policy has one.

If delivery goes wrong:

- A child that misses the brief or starts unrelated work is stopped, not sent the full review again. As a fallback, write the same brief to a non-secret temporary Markdown file and deliver its absolute path through the same handoff tool; a file path cannot repair a brief that arrived encrypted. If only task labels arrive, put the file name in the label too. This changes the transport only, never the models, pass order or approval rules. Never replace a lane with a top-level task or a self-written review.
- A short acknowledgement, a task name or an accepted spawn is not review evidence. A report must cover the full staged diff and every staged file in full, including an index or README file beyond its changed hunk. When a report conflicts with what the child actually did, verify the missing inspection before accepting it. Do not add delivery probes or extra approval questions to ordinary successful reviews.
- Use a distinct brief for each pass and each changed tree. Reject a result that repeats an old tree's review; start a fresh subagent with the new brief.
- If file handoff also fails, report the exact error, apply the policy's bounded fallbacks where eligible, and preserve the work if no permitted pass can run. Do not repeat unbounded review calls.

## Verdicts

Every lane report, every interim update while other lanes are still running, and the final recap use only these labels, emoji included:

- `✅ All Clear`
- `📝 Proceed With Notes`
- `❌ Block`

These three labels are the whole verdict vocabulary. A verdict keeps its label and its emoji wherever it is relayed, from the first mention, not only in the recap. It is never paraphrased into prose (`All Clear`, `blocks`, `passed`), stripped of its emoji, or replaced by another symbol such as `🟡` or `🔴`. Snake_case appears only in the hook's `--decision` values.

## Step 8: Adjudicate the findings and fix blockers

1. Confirm all three lanes inspected the full staged diff and every staged file, and read ponytail first. A lane missing either confirmation is incomplete and blocks the commit.
2. Merge duplicate findings by root cause; the lane that owns the failure class keeps it.
3. Decide each item: Accept, Downgrade or Reject, against the staged evidence and the reportability and severity rules in the [lane guide](../../references/lanes.md). Accept only when the change caused or worsened it, the failure path is executable or deterministic, the impact is material, the confidence is justified and the smallest fix is in scope. A downgrade must fit the severity scale: a finding that breaks a contract, a safety boundary, data integrity or required operability is at least `HIGH`, never `MEDIUM`. Write a short reason for any decision that is not obvious. A rejected `❌ Block` triggers no edits and no further review.
4. Act on what you accepted:

| Accepted item | Action |
|---|---|
| `CRITICAL` or `HIGH` finding, or a `HIGH` or `CRITICAL` missing test | Fix it before committing. If the fix needs owner or product input, stop and ask |
| `MEDIUM` finding | Do not auto-fix. Accept the residual risk with a reason (`📝 Proceed With Notes`) or ask the owner to widen the scope |
| `LOW`, speculative, style-only, pre-existing or optional hardening | Not reportable: no edits, and no follow-up work unless the owner asks or the evidence shows a separate material risk |

5. Rerun the required checks that a fix affects, or all of them when unsure. A failed required check blocks. If one cannot run because of an environment or dependency problem, record the blocker, the residual risk and the next check before allowing `📝 Proceed With Notes`.
6. Record in the repo's task notes, when it has them (`tasks/todo.md`, `tasks/lessons.md` or similar): staged scope, simplification outcome, reviewed tree id, requested and returned model and effort per lane, verdicts, fixed findings, final staged delta, accepted residual risks, and verification results.
7. Write a short recap for the person: the combined verdict, then one bullet per lane with its verdict and `Model: <returned-model> at <effort>` (or `unverified`). For `📝 Proceed With Notes` or `❌ Block`, add a flat list of the accepted notes: lane, one-line point, and why it was accepted or why it blocks.

The combined decision:

- `✅ All Clear`: every lane passed, no unresolved material risk remains, and every required check ran and passed.
- `📝 Proceed With Notes`: only accepted `MEDIUM` findings or unavoidable verification or runtime risks remain, each with a recorded reason. Notes create no automatic follow-up work.
- `❌ Block`: any unresolved `CRITICAL` or `HIGH` finding, an incomplete lane, a required pass that no permitted model could complete, staged scope that is not isolated, a failed required check, or an unresolved high-severity missing test. Speculative concerns never block on their own; reject them at adjudication so the gate converges.

## Step 9: Re-review if the staged tree changed

Compare the final staged tree with the reviewed tree id. If they match, no re-review is needed. If not, inspect `git diff <reviewed-tree-id> --cached` and classify the delta:

| Delta | Examples | What to do |
|---|---|---|
| Mechanical | typos, behaviour-neutral formatting, adding exactly the regression test a reviewer asked for without changing test strategy, narrowing a change exactly as asked without altering behaviour, prose-only corrections | No lane reruns. Self-verify, run targeted checks, rescan, and record why the original review still covers the final tree |
| Material | any change to behaviour or public contracts; auth, security, permissions or secrets handling; payments, sends, deletes, record writes or other side effects; migrations, deployment, rollback or infrastructure; concurrency, idempotency, retry or state; test strategy or coverage boundaries; agent instructions, approval rules, executable runbooks, specs, schemas or workflow JSON when a contract or required behaviour changes; any simplification pass run after the lanes | Rerun the owning lane on the final tree, plus correctness when another lane owned the finding or behaviour changed. Rerun all three only when one fix spans several lanes, adds a new risk area, or cannot be bounded from the delta |

A delta that touches anything in the Material row is material, even when part of it also looks mechanical.

An unaffected lane's result carries over only after you inspect the exact reviewed-to-final delta and record why its conclusion still holds. Record the original tree, the final tree, the rerun lanes, the carried-over lanes and your reasons before approving. Fix and re-review cycles are not capped: keep going until the combined decision is `✅ All Clear` or `📝 Proceed With Notes`, and stop only when an accepted blocker needs owner input. A rephrased version of the same root cause is not a new finding.

## Step 10: Record the approval and commit

Check that the effective `core.hooksPath` is `~/.config/scg-agent-git-hooks/`. The hook checks for an approved receipt matching this repository, branch, exact staged tree, required lane identities and maximum age. It does not run the review or the scan itself; those steps belong to this skill. Rescan whenever the staged tree changed after the passing scan, including mechanical deltas.

Then record the approval under `~/.cache/scg-agent-git-hooks/reviews/`:

```bash
~/.config/scg-agent-git-hooks/bin/scg-review-state approve --decision ALL_CLEAR --pass correctness=<requested-model>@<requested-variant>::<returned-model>@<returned-variant> --pass quality=<requested-model>@<requested-variant>::<returned-model>@<returned-variant> --pass adversarial=<requested-model>@<requested-variant>::<returned-model>@<returned-variant>
```

- `✅ All Clear` maps to `--decision ALL_CLEAR` and `📝 Proceed With Notes` maps to `--decision PROCEED_WITH_NOTES`. Never record approval for `❌ Block`.
- Each `--pass` value is `<requested-model>@<requested-variant-or-unavailable>::<returned-model-or-unverified>@<returned-variant-or-unverified-or-unavailable>`. For example, `--pass quality=openai/gpt-6.1-sol@high::openai/gpt-6.1-sol@high`, or `--pass quality=openai/gpt-6.1-sol@high::unverified@unverified` when the runtime does not echo its serving identity. A returned side of `unverified` is expected in that case and never blocks approval.
- Never invent a value, and never record approval without a genuine three-lane review having run. Self-attesting the review is a bypass of the gate, not a review.

Commit with `<type>: <short summary>`, where type is `feat`, `fix`, `refactor`, `test`, `chore` or `docs`, matching the shared commit-msg hook.

## Rules that apply throughout

- Run this process once for the intended staged commit scope.
- Reviewers are read-only. They inspect the staged diff and the full staged files from the git index, never snippets or working-tree content, and the main agent's single verification run stands for all three lanes.
- Every pass reads the installed `scg-ponytail:ponytail` skill in full before inspecting anything; give each pass its resolved absolute path under [Ponytail dependency](#ponytail-dependency). Ponytail informs judgement about the smallest correct change. It never makes style-only, `LOW`, speculative or out-of-lane findings reportable, and never justifies editing for rejected items.
- The parent owns orchestration. A reviewer must not run the whole gate or spawn its own reviewers. Use the runtime's actual subagent tools and schemas, and the current policy rather than model names remembered from an earlier turn.
