---
name: optimal-subagents
description: Choose the right model and coordinate subagents for research, coding, documents, analysis and independent plan review before action. Covers delegation, model evidence, workload-specific comparisons and refreshing recommendations as models change.
---

# Optimal subagents

Read this entrypoint at each session start when required by host instructions.
Use it to decide whether delegation helps; reading it does not require spawning.
Keep the current user's scope, exact model requests and required review gates.
This guide does not replace the installed pre-commit-review procedure. Its
[review routing source](references/reviews.md) is bundled unchanged in that
plugin; the installed review plugin's release copy governs a running review.

## Decide before spending

1. For a trivial or tightly coupled task, work locally. Delegate a concrete,
   bounded part only when it can run independently alongside useful parent work.
2. Identify the capability floor: tools, modality, context, reliability and
   consequence of error. Check the active runtime's callable tools and catalogue.
   A picker entry, an accepted spawn and a verified served model are different.
3. Select by model capability and comparable published cost, independent of
   subscriptions, account plans or billing routes. Never promote a model because
   it appears free under a plan. Resolve its callable identifier after selection.
4. Choose the cheapest eligible model likely to pass the task's acceptance check.
   Include parent context, reasoning/output, retries and verification in cost.
   A cheap failed attempt followed by a full redo can cost more than one capable
   attempt. Use observed task success when available, not token prices alone.
5. Start with one child; add parallel children only for independent work that
   saves useful time. Avoid duplicate recon, ceremonial reviewers, and asking
   every child to reread the entire conversation. Required review lanes still run.

## Current starting choices

Evidence checked **2026-09-12**. These are task-specific priors, not local proof.
Read [the catalogue evidence](references/catalogue.md) when selecting a model;
refresh live prices before material spend, long runs, or relying on a promotion.

| Work | Cost-first starting point | Escalate when the acceptance check needs it |
| --- | --- | --- |
| Bounded text extraction, simple edits, recon | `z-ai/glm-5.3-flash` at `max` | `deepseek/deepseek-v4.1-flash` at `max`; Luna at `max` when its task evidence fits better |
| Repository investigation, scripts, bounded implementation, tool workflows | `deepseek/deepseek-v4.1-flash` at `max`, or GLM Flash at `max` | `z-ai/glm-5.3` at `max`; Sol or Astra at `max` for difficult debugging |
| Synthesis, reasoning, business documents and polished deliverables | `meta/muse-spark-1.3` at `max` | `anthropic/claude-opus-5` at `max`; Fable at `max` only for a demonstrated quality need |
| Independent review of a proposed plan before action | Standard Muse Spark 1.3 at `max`; read [planning advisor](references/planning.md) | Sol at `max` for intricate operational reasoning; domain-specific requirements still apply |
| UI and frontend | GLM Flash or DeepSeek Flash at `max`; `qwen/qwen3.8-max-0902` at `xhigh` as a stronger visual candidate | `moonshotai/kimi-k3` at `max`, then Astra/Fable at `max` for a difficult focused slice |
| Images and multimodal reasoning | Verify actual input support; Gemini Flash at `high`, Muse or Luna at `max` according to task and budget | Astra at `max` for harder visual reasoning; use task-specific tests, not text scores |
| Long-document extraction | Luna or DeepSeek Flash at `max`, with citations and spot checks | Muse at `max`; Kimi at `max` for demanding long-context reasoning |
| Pre-commit review | Use the installed review skill and its bundled model routing | Apply its authorized fallbacks; exact user requirements still take precedence |

**Cybersecurity exception:** read [security model selection](references/cybersecurity.md)
before assigning any cybersecurity work, including defensive analysis, pentesting,
incident response, vulnerability research or a security acceptance decision.
Establish accuracy, scope and usable access first;
then optimise cost among qualifying models. The cheapest general-purpose row is
not the default for high-consequence security work. This does not change the
installed pre-commit review policy.

**One effort per model:** use the single prescribed level in the catalogue table,
normally the highest supported plain reasoning level. Do not lower effort to
save cost; choose a cheaper capable model instead, unless the user overrides it.
Astra, Sol and Terra use `max`: the catalogue's `ultra` adds automatic delegation,
so it is outside this bounded-child policy. Never invent unsupported `max`.

**Muse policy:** standard 1.3 uses `max`. Treat its `xhigh` evidence as a similar
practical tier, per user preference, while preserving the separate measurements.
This is not a claim of equal scores, latency or billed reasoning.
Contributor (`meta/muse-spark-1.3-contributor`) uses `xhigh`: $0.10/$0.20
per million input/output tokens in the snapshot, but its own benchmark identity
is unverified and its terms permit training use. Use it only when that data use
is acceptable and a representative task check passes. Never transfer standard
Muse scores to Contributor or silently replace the requested route.

Effort names are provider-specific. If the prescribed level is unavailable,
report that constraint and select another eligible model; do not silently
change the level or borrow another effort's benchmark score.

For an unavailable model, read [fallback orders and failure handling](references/fallbacks.md).
Use the workload's next eligible model at its fixed effort, preserve acceptance
checks and data constraints, and report material substitutions. Stop model
cycling for a shared transport failure or an exact-model review gate.

## Run a bounded delegation

Read [tool operation and communication](references/tool-guide.md) before the
first spawn or when acting as a child. It includes exact examples for the current
collaboration tools, fork restrictions, replies, waiting and failure handling.

Give each child: one deliverable, relevant context/paths, write authority,
acceptance checks, cost/retry limits where useful, and a stop condition. One
writer owns each worktree/delivery stream; parallel agents must not edit the same
files or shared browser. Default children to no recursive delegation.

Start every initial or follow-up assignment message with the requested model,
effort, role/pass and task or plan context. For example: "GLM 5.3 Flash Max —
Pre-commit review Pass 1 (code simplification) for plan 147." Use the actual
selected model and a real task identifier; do not invent a plan number. Repeat
the label in a file-based brief. This labels the request, not verified serving
identity; keep recording the returned identity separately.

Keep parent work moving. Verify material claims and artifacts yourself before
integration. For an unexpected failure, distinguish transport, authorization,
identity, provider and task-quality errors. One diagnostic retry is usually
sufficient for a deterministic pre-inference failure; do not buy repeated calls
that cannot reach the task. Preserve exact required model gates.

Close or release finished agents if the runtime exposes that operation. Report
what was verified, remaining gaps, and material model/cost substitutions; do not
claim a spend total without actual usage evidence.

## Refresh the guide

Read [refresh methodology](references/refresh.md) to add models, update prices,
recompute workload-specific Pareto frontiers and validate new recommendations.
The bundled [evidence snapshot](references/model-evidence.json) is dated public
research. [pareto.py](scripts/pareto.py) computes reproducible candidate sets;
it does not make network calls or infer missing model scores.

When installing, pulling or updating this skill for use, complete
[automatic-update setup](references/updates.md) on macOS, Linux or Windows:
configure the native shared schedule, run it and verify installed versions.
This is part of installation, not an optional follow-up. Respect explicit
read-only scope and preserve custom schedules when reporting setup blockers.
A pull alone does not enable updates; an already verified working schedule
does not need reinstalling for each ordinary task.
