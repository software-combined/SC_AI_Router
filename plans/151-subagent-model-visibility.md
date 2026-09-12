# Plan 151: Subagent model visibility - every catalogue model is delegable

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If a
> STOP condition occurs, stop and report - do not improvise. When done, update
> this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat origin/develop..HEAD -- ai_router/catalogue.py ai_router/openrouter_base_instructions.txt ai_router/agents_general.txt ai_router/agents_dev.txt tests/test_catalogue.py tests/test_model_projections.py tests/test_setup_agents.py docs/compatibility.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" sections against the live code before proceeding; on a
> mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW for stages 1, 2, 4, 5; MEDIUM for stage 3 (changes what the spawn list shows)
- **Depends on**: 133 (probe harness), 145 (verification gate); serialize with 135 on `ai_router/catalogue.py` and `plans/README.md`
- **Category**: compatibility / usability
- **Planned at**: commit `48d5bae`, 2026-09-12
- **Status**: PARTIAL: the repo side (served instructions roster, starter rule,
  tests) lands in 0.6.36; the owner-machine global-instructions step, stage 3
  and stages 4-5 are open

## Problem

Codex builds the `spawn_agent` tool's "Available model overrides" text from the
first five picker-visible models that support the active multi-agent backend, in
catalogue order:

- `codex-rs/core/src/tools/handlers/multi_agents_common.rs:33` -
  `MAX_SPAWN_AGENT_MODEL_OVERRIDES: usize = 5`.
- `codex-rs/core/src/tools/handlers/multi_agents_spec.rs:763-772` -
  `.filter(|m| m.show_in_picker).filter(model_supports_multi_agent_backend).take(5)`.
- The cap is still 5 at `rust-v0.155.0-alpha.3.10`; the installed client is
  `0.153.4`.

The router's merge writes the subscription roster first
(`ai_router/catalogue.py:270`, `subs + sorted(shown, key=rank)`), so the five
slots are consumed by `gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra`,
`gpt-5.6-luna` and `gpt-5.5` - five of the eight roster rows. Every OpenRouter
row is cut off. Validation is not capped: `find_spawn_agent_model_name`
(`multi_agents_common.rs:388-417`) searches the full model list, so an explicit
`model="meta/muse-spark-1.3-contributor"` is accepted; the failure is
discoverability, not permission.

Observed 2026-09-12 in task 01a09477 (session model
`deepseek/deepseek-v4.1-flash`, `multi_agent_version: v1`): asked to spawn Muse
Contributor subagents, the agent reported "There's no muse" and spawned
`gpt-6-astra` x2, `gpt-5.6-sol`, `gpt-5.6-terra` and `gpt-5.6-luna` instead; all
five children then failed with 503 on the ChatGPT subscription upstream (five of
the 156 `upstream_rate_limited` events logged that day, every one
`provider: openai`).

The model picker itself is complete: `mixed-models.json` holds all 27 rows and
the live app-server `model/list` returns all 26 visible ones. Only the
subagent-override description is truncated.

## Goal

Any task routed through the router can delegate to any model in the catalogue,
even when the client truncates the model list it shows the agent - without the
user having to re-state a model the agent says it cannot see.

## Stage 1 - in-band rule for routed sessions (router only)

Add a short "## Subagent model overrides" section to
`ai_router/openrouter_base_instructions.txt`: the client truncates the
`spawn_agent` model list; the router routes every configured model id that the
install's policy allows; when the user names a model absent from that list,
pass the exact id (for example `model="meta/muse-spark-1.3-contributor"`) with
an explicit effort, do not substitute a different model, and report any router
rejection. The catalogue serves this text per row through
`model_messages.instructions_template` (`ai_router/catalogue.py:146,177`).

Keep the roster line current: generate the visible OpenRouter slugs at merge
time from the same projection the picker uses (reuse `catalogue._visible_rows`
or `model_prompt.visible_models`) instead of hard-coding model names in the
template.

**Files**: `ai_router/openrouter_base_instructions.txt`,
`ai_router/catalogue.py` (generated roster line), `tests/test_catalogue.py` or
`tests/test_model_projections.py`.

**Verify**: focused test asserts the generated instructions name every
`models_for(MODELS, 'codex')` OpenRouter slug; a merge into a temporary home
writes rows carrying the section; `python3.14 -m ai_router.catalogue --check
<file>` exits 0.

## Stage 2 - machine instructions for subscription sessions

Subscription-model sessions never see the router's instructions. Add the same
rule, phrased model-agnostically, to the "## Subagents and tool discovery"
section of `ai_router/agents_general.txt` and `ai_router/agents_dev.txt`; these
starter profiles are installed once as the user's global instructions and
existing files are kept. As the machine-side acceptance step, add the same rule
to the owner's live global instructions (`~/.codex/AGENTS.md`, KnowledgeVault
symlink).

**Files**: `ai_router/agents_general.txt`, `ai_router/agents_dev.txt`,
`tests/test_setup_agents.py`.

**Verify**: `python3.14 -m unittest tests.test_setup_agents -v` passes; both
starter texts stay under the source limits; a fresh subscription-model session
states the rule.

## Stage 3 - decide what the five slots show (owner gate)

Ordering is the only lever that changes the spawned description itself.
`merge()` currently emits `subs + sorted(shown)`; make the order explicit (state
key such as `spawn_order`, or a documented `merge()` argument) so the first five
multi-agent-capable rows can include named router models at the cost of the same
number of subscription rows. The list can show at most five of twenty-seven; the
picker is unaffected.

Default recommendation: keep the roster first (status quo) and rely on stage 1
unless the owner wants Muse/DeepSeek/GLM discoverable in the list itself.

**Verify**: a focused test pins the chosen order; the stage 4 capture shows the
expected five slugs.

## Stage 4 - no-billing regression probe

Extend the app-server probe harness (Plan 133) with a capture that starts a
thread against a local sink which answers 426 to the WebSocket upgrade and
records the `/responses` body, then asserts the spawn tool description lists the
expected override set. Prototype proven 2026-09-12 during the root-cause
investigation (zstd-compressed body decoded with `compression.zstd`). No paid
provider is used.

**Verify**: `python3.14 tools/probe_codex_runtime.py --capture-spawn-list` (name
TBD) prints the expected slugs and exits 0; `docs/compatibility.md` records the
client version.

## Stage 5 - upstream fix (the actual cap)

File an issue against `openai/codex` with this plan's evidence and propose either
listing every eligible model or raising/removing `MAX_SPAWN_AGENT_MODEL_OVERRIDES`
(or emitting "and N more"). If upstream accepts, prepare the PR with tests in
`codex-rs/core/tests/suite/spawn_agent_description.rs`. Record the client
versions where the cap holds in `docs/compatibility.md` and re-check after every
Codex upgrade (AGENTS.md section 7).

## Acceptance

- [ ] A fresh routed session asked to spawn `meta/muse-spark-1.3-contributor` at `xhigh` does so without substitution (one paid leg, marker echoed).
- [ ] The same session explains the truncated list and the explicit-id route when asked why only five models are shown.
- [ ] Offline suite, compile and source-limits checks pass.
- [ ] `docs/compatibility.md` records the client versions and the upstream issue link.
- [ ] CHANGELOG and VERSION released, updater deployed, Codex restarted, picker unchanged (27 rows, 26 visible).

## Non-goals

- Do not patch or replace the signed ChatGPT.app binary.
- Stages 1 and 2 do not change routing, policy or picker contents; stage 3 is the only ordering change and is owner-gated.
- Do not spawn test subagents on paid models inside CI.

## STOP conditions

- The cited upstream lines moved and the cap no longer exists: stop, re-verify, and reduce this plan to its documentation parts.
- Stage 3 collides with Plan 135's catalogue or README edits: serialize, do not improvise.
- A step needs paid inference or an upstream write without the owner present: stop and report.
