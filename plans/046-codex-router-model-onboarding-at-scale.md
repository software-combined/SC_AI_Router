# Plan 046: Add a model with one command, ship it as data, and let routers pick it up without a release

> **Reconciliation 2026-09-09 at `96db57f`:** model CLI, previews and validation
> exist. Hourly registry pickup remains unimplemented. Resume that remaining
> stage after 064's projection contract and 054's authenticated/versioned feed
> are qualified; retain last-good state, atomic validation/swap and picker
> refresh proof. Do not depend on 039's unsupported live `/models` mechanism
> or advertise refresh from a timer alone. In-process inference data refresh
> and Codex's static catalogue/cache refresh require separate evidence.

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 749a6b8d..HEAD -- <ROUTER_ROOT>`
> On any in-scope change, compare the "Current state" excerpts against the
> live code first; on a mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (the router starts trusting a remotely fetched data file; mitigated by strict validation, fixed provider hosts, and a last-good cache)
- **Depends on**: Plan 038 (registry as data, see its amendment), Plan 039 (live catalogue), Plan 044 (probe flags and derived fields), Plan 045 (release feed)
- **Category**: direction / dx
- **Planned at**: commit `749a6b8d`, 2026-09-07

## Path convention

Repository root post-Plan 034 (`codex_router/...`, `tools/...`, `tests/...`).

## Why this matters

Cyril will keep enabling models. After Plan 038 a model is one row, but it is still a row in code that needs a release and a router restart on every machine, and every row is written by hand from live metadata. Plan 044 shows that each model also needs a short probe run before it is trusted. This plan turns onboarding into one command that fetches the live metadata, derives the fields, runs the probes and writes the row; adds a `preview` tier so a model can be offered before it is fully verified, clearly labelled in the picker; and moves the model list out of the release bundle into a data file that every router fetches from GitHub hourly, so merging a JSON change is all it takes for the new model to appear in everyone's picker.

## Current state

- After Plan 038 (as amended), `codex_router/models.json` holds one object per model with the fields of the `Model` dataclass (`slug`, `provider`, `display_name`, `vendor`, `reasoning`, `default_reasoning`, `modalities`, `excluded_efforts`, `schema_mode`, `max_tools`, `context_window`, `priority`) plus Plan 044's fields (`max_output_tokens`, `reasoning_summary`, `apply_patch`, `experimental_tools`, `web_search`). `registry.py` loads and validates it and exposes `MODELS`, `by_slug`, `openrouter_slugs`.
- Plan 044's `live_refresh.py` rewrites the derived fields (`modalities`, `context_window`, `max_output_tokens`, `reasoning`) in place from `https://openrouter.ai/api/v1/models`.
- Plan 039: the router answers `GET /models` by forwarding to OpenAI and appending `openrouter_entry(m)` for every registry OpenRouter model; providers route by `by_slug(model).provider`.
- Plan 044's probe flags: `--image`, `--audio`, `--reasoning-summary`, `--apply-patch`, `--web-search`, `--experimental-tools`, plus the base tool round trip.
- Plan 045: releases publish `latest.json`; the repository is public (Plan 034 decision) so raw files are fetchable at `https://raw.githubusercontent.com/software-combined/codex-model-router/main/codex_router/models.json`.
- OpenRouter live metadata provides `name` (for example `Z.ai: GLM 5.3 Flash`), `architecture.input_modalities`, `context_length`, `top_provider.max_completion_tokens`, `reasoning.supported_efforts`, `reasoning.default_effort`.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Tests | `python3.14 -m unittest discover -s tests -t . -v` | `OK` |
| Add a model (dry) | `python3.14 -m codex_router.models add qwen/qwen4-coder --dry-run` | prints the derived row, writes nothing |
| Add and probe | `python3.14 -m codex_router.models add qwen/qwen4-coder --probe` | row written with `tier: verified` when the round trip passes, else `preview` |
| Validate the file | `python3.14 -m codex_router.models check` | `models.json: N models, 0 problems` |
| Remove | `python3.14 -m codex_router.models remove qwen/qwen4-coder` | row removed |

(`qwen/qwen4-coder` is an example slug; use whatever Cyril wants next, it must exist in the live OpenRouter list.)

## Scope

**In scope**: `codex_router/models.json`, `codex_router/registry.py` (tier, hot reload), new `codex_router/models.py` (the command), `codex_router/catalogue.py` (preview labelling), `codex_router/router.py` (hourly refresh thread), `packaging/release.py` and `latest.json` (`models_url`), `.github/workflows/check.yml` (models validation step), `tests/test_models_cmd.py`, `tests/test_registry.py`, `docs/adding-a-model.md`, `.github/pull_request_template.md`.

**Out of scope**: adding a new quirk type in code (a model that needs behaviour the adapter does not have is a normal code change and release); OpenAI models; provider hosts (fixed in `providers.py`, never data).

## Git workflow

- Branch `codex/router-model-onboarding-<yyyymmdd>`; commits `feat:`/`test:`/`docs:`. Do not push unless instructed.

## Steps

### Step 1: Tiers in the data and the picker

Add field `tier` to every row: `verified` (all current six) or `preview`. `registry.py` rejects any other value. `openrouter_entry` for a preview model appends ` · Preview` to `display_name`, prefixes the description with `Preview, not yet verified with Codex. `, and sets `priority` after all verified models. Nothing else differs; preview models route exactly like verified ones.

**Verify**: `tests/test_registry.py::test_tier_required_and_validated`, `tests/test_catalogue.py::test_preview_entry_is_labelled`.

### Step 2: The `models` command

Create `codex_router/models.py` with subcommands:

- `add <slug> [--probe] [--dry-run] [--tier preview|verified]`: fetch the live OpenRouter list (`urllib`, 20 s timeout), STOP with a clear message if the slug is absent; derive `display_name` as `<live name without the vendor prefix> · OpenRouter`, `vendor` as the text before the first colon in the live name, `modalities` as the intersection with `('text', 'image', 'audio')`, `context_window`, `max_output_tokens`, `reasoning` in canonical order, `default_reasoning` as `low` when available else the lowest advertised, `priority` as the next free integer at or above 100, `schema_mode: native`, `max_tools: null`, `excluded_efforts: []`, `reasoning_summary: none`, `apply_patch: none`, `experimental_tools: []`, `web_search: <pricing has web_search>`, `tier: preview`. With `--probe`: run the base tool round trip from `tools/probe_codex_runtime.py` on the installed router at low effort; if it passes, set `tier: verified` and, when `--probe` is combined with `--full`, run the Plan 044 capability flags and set the flags per the results; append a row to `docs/compatibility.md`. Write through `write_guarded`. With `--dry-run` print the row only.
- `remove <slug>`: delete the row; refuse if the slug is not present.
- `check`: validate the file with the registry loader, check slugs are unique, priorities unique, every slug present in the live OpenRouter list (skip the live check with `--offline`), print `models.json: N models, M problems`, exit 1 when M is not zero.
- `list`: print slug, tier, modalities, reasoning levels.

Never accept API keys or tokens as arguments; the probe uses the installed router's own credential lookup.

**Verify**: `tests/test_models_cmd.py`: derivation from a fixture live payload (name split, intersection, priority allocation, default reasoning), `add` refuses unknown slugs, `check` reports duplicates, `remove` refuses missing slugs, `--dry-run` writes nothing. Live: `python3.14 -m codex_router.models add <slug> --dry-run` prints a plausible row for a real slug.

### Step 3: Routers fetch the model list

- `latest.json` (Plan 045's `release.py`) gains `"models_url": "https://raw.githubusercontent.com/software-combined/codex-model-router/main/codex_router/models.json"` (or the beta branch for the beta channel).
- `registry.py` becomes reloadable: `load(text) -> Registry` validates and returns an object with `MODELS`, `by_slug`, `openrouter_slugs`; the module keeps a `current()` accessor that providers and the catalogue call instead of importing constants. Swapping is a single attribute assignment, so requests in flight see either the old or the new registry, never a mix.
- `router.py` starts a daemon thread at startup: load the bundled `models.json` first, then `ROUTER_HOME/models-cache.json` if present and valid, then every 60 minutes (plus 0 to 5 minutes jitter) fetch `models_url` with `If-None-Match`; on 200, validate with `load()`; on success write the cache atomically (mode 0600) and swap; on any failure keep the current registry and log `log_event('models_refresh_failed', reason=<class name>)`. Validation rules that must hold before a swap: JSON object list, every field typed, `provider` only `openrouter`, no unknown fields, at most 200 models, every slug matching `^[~a-z0-9._-]+/[a-z0-9._:-]+$`. The provider host is not part of the data and cannot be changed by it.
- Codex sees new models the next time it requests `/models` (picker open or restart); no router restart is needed.

**Verify**: `tests/test_registry.py::test_reload_swaps_atomically_and_rejects_bad_payload`, `tests/test_handler.py::test_models_endpoint_reflects_reloaded_registry`; on the author's machine, temporarily point `models_url` at a local file with a seventh preview model, wait for the refresh (or send `SIGHUP`, which Step 3 also wires to "refresh now"), and confirm the picker shows the seventh model with the Preview label.

### Step 4: Guard the data in CI and PRs

- `check.yml` gains a step `python -m codex_router.models check` (with network; falls back to `--offline` when the OpenRouter fetch fails, and prints which mode ran).
- `.github/pull_request_template.md`: a checklist with "If `models.json` changed: `models check` output pasted, probe result pasted (or `tier: preview` chosen on purpose)".

**Verify**: a PR that adds a duplicate priority fails the `Check` workflow.

### Step 5: Documentation

Rewrite `docs/adding-a-model.md`: the one-command path (`models add <slug> --probe`), the preview path (edit the JSON or `add` without `--probe`), what the labels mean to staff, how long propagation takes (next hourly refresh, then picker refresh), how to remove a model, and the rule that new quirk types are code changes.

**Verify**: `grep -n "models add" docs/adding-a-model.md README.md` shows both.

## Test plan

As listed per step; pattern `tests/test_apply_catalogue.py` for temp files and `tests/test_handler.py` for the endpoint. Verification: full suite `OK`.

## Done criteria

- [x] All six existing models carry `tier: verified`; `models check` prints `0 problems`. (Verified 2026-09-09: 22 models — 16 verified, 6 preview — 0 problems.)
- [x] `models add <slug> --dry-run` derives a row from live metadata without writing. (Verified 2026-09-09 against `openai/gpt-4o`.)
- [ ] Router reloads `models.json` hourly from `models_url`, keeps a last-good cache, and rejects invalid payloads without swapping (tests plus a manual seventh-model check on the author's machine). (Deferred per 2026-09-08 audit brief, pending versioned-update proof; manual check needs the live gate.)
- [x] Preview models are labelled in the picker. (`catalogue.py:61-64,70-71`: Preview display-name suffix, description note, priority offset.)
- [x] CI validates `models.json`; the PR template has the checklist. (`check.yml:27-31` models check + catalogue merge check; PR template line 6.)
- [x] Full suite `OK`; `plans/README.md` status row updated. (Suite green 2026-09-09; row updated same turn.)

## STOP conditions

- The repository is private (Plan 034 decision changed): the raw URL needs a token; stop and ask whether to serve `models.json` as a release asset instead (the installer already fetches release assets anonymously only for public repositories).
- The live OpenRouter list lacks the fields the derivation needs.
- A validation rule would have to be relaxed to accept a model Cyril wants (for example a slug format); report the slug and the rule instead of loosening it silently.

## Maintenance notes

- Adding a model is now: `python3.14 -m codex_router.models add <slug> --probe`, review the diff, merge. Everyone's picker shows it within about an hour, labelled Preview until verified.
- Reviewers should refuse any change that lets `models.json` influence hosts, headers, credentials or paths. Data selects among behaviours the code already has; it never adds behaviour.
- Deferred: allowlisting by pattern (for example every `qwen/*` model) as auto-preview. It is a small addition to the refresh thread once staff ask for breadth over curation.
