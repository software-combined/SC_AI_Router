# Plan 118: Expose every capability each OpenRouter model has that Codex can use, driven by live metadata and proven by probes

> **Reconciliation 2026-09-09 at `96db57f`:** execute remaining capability
> qualification with Plan 064's consistent client projections and Plan 119's
> agent-transport checks. The overlay-file criterion is SUPERSEDED, not undone
> implementation: `live_refresh` updates registry data in place. Test current
> promised models/capabilities, not a stale count of six. Failed or unproven
> audio/image cells cannot justify advertised support. Preserve provider facts
> separately from proven client delivery; tier alone is not capability proof.

> **Amended 2026-09-07**: there is no separate `live-capabilities.json` overlay. `live_refresh.py` rewrites the derived fields (`modalities`, `context_window`, `max_output_tokens`, `reasoning`) in place inside `ai_router/models.json` (Plan 038 as amended), and Plan 099's `models add` command uses the same derivation. Pinned fields (`excluded_efforts`, `schema_mode`, `max_tools`, the capability flags) are never overwritten by the refresh.

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b642de9..HEAD -- ai_router/registry.py ai_router/live_refresh.py ai_router/catalogue.py ai_router/providers.py ai_router/models.json tools/probe_codex_runtime.py tests/ docs/compatibility.md`
> On any in-scope change, compare the "Current state" excerpts against the
> live code first; on a mismatch, STOP.

## Status

- **Priority**: P2
- **Effort**: M to L (each capability is a small change plus one paid probe run per model)
- **Risk**: MED (a capability that passes a probe can still misbehave in daily use; every enablement is per model and reversible in the registry)
- **Depends on**: Plan 038 (registry and generated entries), Plan 037 (providers). Plan 039 makes the generated entries live.
- **Category**: direction / correctness
- **Planned at**: commit `749a6b8d`, 2026-09-07 (drift base refreshed to `b642de9`, 2026-09-11)

## Path convention

Repository root post-Plan 034 (`ai_router/...`, `tools/...`, `tests/...`); pre-034 the flat names under `domains/ai-platform/codex-model-router/`.

## Why this matters

The OpenRouter catalogue entries were pinned conservatively during the trial: text and image input only, a 32,768-token output cap, no reasoning summaries, no freeform patch tool, no experimental Codex tools. The models can do more. Live OpenRouter metadata on 2026-09-07 shows Muse Spark accepting text, image, video, file and audio input with a 943,718-token output limit, GLM 5.3 Flash and Kimi K3 accepting video, and Grok accepting files, with context windows between 500,000 and 1,310,720 tokens. Codex itself only understands three input modalities (`text`, `image`, `audio`, from the `InputModality` enum in the binary), so video and file input cannot be expressed through the picker and are not a loss: Codex reads files through its own tools. What can be enabled is audio for Muse, the real output and context limits, reasoning summaries, the freeform `apply_patch` tool, the experimental Codex tools, and web search where the provider prices it. Each of these is a per-model flag in the registry, refreshed from live metadata, and switched on only after the probe proves it.

## Current state

- Live OpenRouter metadata (`https://openrouter.ai/api/v1/models`, fetched 2026-09-07, no key needed):

| Model | `architecture.input_modalities` | Codex-expressible | `context_length` | `top_provider.max_completion_tokens` | `pricing.web_search` present | `reasoning.supported_efforts` |
|---|---|---|---|---|---|---|
| `meta/muse-spark-1.3` | text, image, video, file, audio | text, image, audio | 1,048,576 | 943,718 | yes | max, xhigh, high, medium, low, minimal |
| `meta/muse-spark-1.3-contributor` | same as above | text, image, audio | 1,048,576 | 943,718 | yes | same (max rejected in practice) |
| `z-ai/glm-5.3-flash` | text, image, video | text, image | 1,310,720 | 131,072 | no | max, high, low |
| `z-ai/glm-5.3` | text | text | 1,310,720 | 943,718 | no | max, high, low |
| `moonshotai/kimi-k3` | text, image, video | text, image | 1,048,576 | 943,718 | no | max, high, low (reasoning optional) |
| `~x-ai/grok-latest` | text, image, file | text, image | 500,000 | 450,000 | yes | xhigh, high, medium, low |

  All six advertise `tools`, `tool_choice`, `reasoning`, `response_format` and `structured_outputs` in `supported_parameters`; all have `output_modalities: ["text"]`.
- Codex catalogue vocabulary observed in the binary: `InputModality` values `text`, `image`, `audio`; `default_reasoning_summary` values `auto` and `none`; field `supports_reasoning_summary_parameter` (boolean); `web_search_tool_type` values `text` and `text_and_image`; `apply_patch_tool_type` values `freeform` and null; `tool_mode` values `code_mode_only` and null; `experimental_supported_tools` (OpenAI entries list `send_user_message_async` and `clock`).
- Current pinned OpenRouter entry values (Plan 038 template): `input_modalities` text plus image where live metadata says image; `default_reasoning_summary: "none"`; `apply_patch_tool_type: null`; `experimental_supported_tools: []`; `tool_mode: null`; `multi_agent_version: "v1"`; `web_search_tool_type: "text_and_image"`; `context_window` copied once from a past catalogue.
- Output cap in the OpenRouter provider (`prepare_openrouter`, router `:26` at the planned commit): `payload['max_output_tokens'] = min(payload.get('max_output_tokens') or 32768, 32768)`.
- Prior evidence that must be respected (KnowledgeVault note "Codex Mixed Model Picker" and `capabilities.py` docstring): `code_mode_only` was rejected for OpenRouter; multi-agent `v1` plaintext sub-agents are the proven setting; Grok caps exposed tools at 350; Meta rejects recursive schemas (carried as JSON text); Contributor rejects `max` effort despite advertising it. None of these change here.
- `apply_catalogue.py` and `update_reasoning_catalog.py` already refresh reasoning levels and modalities from live metadata for existing entries.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Tests | `python3.14 -m unittest discover -s tests -t . -v` | `OK` |
| Live metadata snapshot | `curl -s https://openrouter.ai/api/v1/models -o /tmp/or-models.json` | file, 430-odd models |
| Refresh overlay | `python3.14 -m ai_router.live_refresh /tmp/or-models.json` | prints one JSON line per registry model with the derived fields |
| Probe, one capability | `python3.14 tools/probe_codex_runtime.py <slug> --installed --image` (and `--audio`, `--reasoning-summary`, `--apply-patch`, `--web-search`, `--experimental-tools`) | `{"model": ..., "capability": "<name>", "result": "passed"}` |

Probes are paid (a few cents each at low effort). Run them one model at a time on the author's machine at an idle moment.

## Scope

**In scope**: `ai_router/registry.py` (new fields), new `ai_router/live-capabilities.json` (overlay written by the refresh tool, committed), new `ai_router/live_refresh.py` (replaces `update_reasoning_catalog.py`), `ai_router/catalogue.py` (entry uses the new fields), `ai_router/providers.py` (output cap), `tools/probe_codex_runtime.py` (capability flags), `tests/test_registry.py`, `tests/test_catalogue.py`, `tests/test_providers.py`, `docs/compatibility.md`.

**Out of scope**: `tool_mode`, `multi_agent_version`, `use_responses_lite`, `node_repl_*` (rejected or OpenAI-specific per prior evidence); video and file input (Codex cannot express them); image or audio output (all six models output text only); the Grok tool ceiling and Meta schema handling; anything touching OpenAI entries.

## Git workflow

- Branch `codex/router-capabilities-<yyyymmdd>`; commits `feat:`/`test:`/`docs:`. Do not push unless instructed.

## Steps

### Step 1: Registry fields and the live overlay

Extend `Model` in `registry.py` with `max_output_tokens: int = 32768`, `reasoning_summary: str = 'none'` (`'none'` or `'auto'`), `apply_patch: str = 'none'` (`'none'` or `'freeform'`), `experimental_tools: tuple = ()`, `web_search: bool = True`. At import, merge `ai_router/live-capabilities.json` over the pinned rows: for each slug present, the overlay may set `modalities`, `context_window`, `max_output_tokens`, and `reasoning` (already filtered by `excluded_efforts`). Pinned Python values win for everything else, and any overlay slug not in `MODELS` is ignored with a `SystemExit` at import naming the unknown slug (fail closed so a typo cannot hide a model).

Create `live_refresh.py`: reads the OpenRouter models JSON (path argument, or fetches when `--fetch`), and for each registry model writes `modalities = [m for m in ('text', 'image', 'audio') if m in live input_modalities]` (this is the intersection with Codex's vocabulary), `context_window = context_length`, `max_output_tokens = top_provider.max_completion_tokens`, `reasoning = canonical order of supported_efforts minus excluded_efforts`, into the overlay with `write_guarded`. Print the derived fields per model. Delete `update_reasoning_catalog.py` and move its tests to `tests/test_live_refresh.py`.

**Verify**: `python3.14 -m ai_router.live_refresh /tmp/or-models.json` prints six lines; the overlay shows `["text", "image", "audio"]` for both Muse entries, `["text", "image"]` for GLM Flash and Kimi and Grok, `["text"]` for GLM 5.3, and `max_output_tokens` 131072 for GLM Flash. Tests in `tests/test_live_refresh.py` cover the intersection rule and the unknown-slug refusal.

### Step 2: Real output and context limits

In `OpenRouterProvider.prepare` replace the 32768 cap with `limit = by_slug(model).max_output_tokens; payload['max_output_tokens'] = min(payload.get('max_output_tokens') or limit, limit)`. `openrouter_entry` uses `context_window` and `max_context_window` from the registry (after overlay) and `effective_context_window_percent` stays 90.

**Verify**: `tests/test_providers.py::test_output_cap_follows_registry` (a fake model with `max_output_tokens=1000` caps 5000 to 1000 and fills 1000 when absent); Plan 038's `--check` against the deployed catalogue now reports `context_window` differences only where the overlay changed them (record them; they are intended).

### Step 3: Probe flags, one per capability

Extend `tools/probe_codex_runtime.py` with mutually compatible flags, each keeping the 90-second deadline, low effort, `ephemeral: True`, shell and file tools disabled unless stated:

- `--image`: attach a generated 2 by 2 PNG (solid red, built in code with `zlib` and `struct`, no file on disk needed if the app-server accepts inline image input; otherwise write it to the temp cwd) as a `localImage` or `image` input item per the app-server protocol, ask "Reply with the single word naming the dominant colour", pass when the answer contains `red`.
- `--audio`: same with a 0.3-second 8 kHz WAV of silence and the instruction "Reply with the single word SILENT if the clip is silent"; pass on `SILENT`. If the app-server input schema has no audio item type, print `{"capability": "audio", "result": "unsupported_by_codex_client"}` and exit 0.
- `--reasoning-summary`: start the thread with `-c model_reasoning_summary=auto` and a temporary catalogue entry (via `--catalog`) whose `default_reasoning_summary` is `auto` and `supports_reasoning_summary_parameter` true; pass when at least one streamed item of type `reasoning` carries non-empty summary text.
- `--apply-patch`: temporary catalogue entry with `apply_patch_tool_type: "freeform"`, sandbox `workspace-write` on a temp directory containing `note.txt` with `alpha`, instruction "Change alpha to beta in note.txt using apply_patch and stop"; pass when exactly one `fileChange` item completes and the file reads `beta`.
- `--web-search`: `web_search` feature enabled, question "What is today's date according to a web search? Reply with the date only", pass when a `webSearch` item completes and the turn completes (do not assert the date).
- `--experimental-tools`: temporary catalogue entry with `experimental_supported_tools: ["clock"]`, instruction "Use the clock tool and reply with the hour only"; pass when a tool item named `clock` completes.

Each prints one JSON line `{"model", "capability", "result": "passed" | "failed" | "unsupported_by_codex_client", "detail"}` where `detail` never includes URLs or tokens.

**Verify**: `python3.14 tools/probe_codex_runtime.py z-ai/glm-5.3-flash --installed --image` prints a `passed` line on the author's machine (GLM Flash accepts images per live metadata).

### Step 4: Run the matrix and enable what passed

Run every applicable flag for every model (skip `--image` for GLM 5.3 and `--audio` for everything but Muse). Record results in `docs/compatibility.md` as a table (model by capability, with date and Codex version). Then set registry values only for passes: `modalities` come from the overlay but remove `audio` if the audio probe was `failed` (keep it if `unsupported_by_codex_client`, since the client, not the model, is the limit; note it); `reasoning_summary='auto'` where the summary probe passed; `apply_patch='freeform'` where the patch probe passed; `experimental_tools=('send_user_message_async', 'clock')` where the experimental probe passed (probe `clock` only; `send_user_message_async` needs no provider support beyond function calling, so enable both when `clock` passes); `web_search=False` where the search probe failed, which sets `web_search_tool_type` to `text` and removes the web search tool at request time.

`openrouter_entry` maps: `default_reasoning_summary = model.reasoning_summary`, `supports_reasoning_summary_parameter = model.reasoning_summary == 'auto'`, `apply_patch_tool_type = 'freeform' if model.apply_patch == 'freeform' else None`, `experimental_supported_tools = list(model.experimental_tools)`, `web_search_tool_type = 'text_and_image' if model.web_search else 'text'`.

**Verify**: `docs/compatibility.md` has a filled matrix; `tests/test_catalogue.py::test_entry_reflects_capability_flags` passes; regenerate and restart the router on the author's machine; the desktop picker shows the new modalities and, for a model with summaries enabled, a task shows reasoning summaries.

### Step 5: Keep it fresh

Add a `refresh` job to the release workflow (Plan 109) or a weekly scheduled workflow: run `live_refresh.py --fetch`, and if the overlay changed, open a pull request titled `chore: refresh live capabilities` (use `peter-evans/create-pull-request` pinned to a full SHA, `permissions: contents: write, pull-requests: write` at job scope). A human merges after glancing at the diff, which keeps a provider-side change from shipping unreviewed.

**Verify**: the workflow passes the policy checks from Plan 034 Step 5; a manual `workflow_dispatch` run creates a PR when the overlay differs.

## Test plan

- `tests/test_live_refresh.py`: intersection rule (`video`, `file` dropped, `audio` kept), excluded efforts removed, unknown overlay slug refused at import, missing `top_provider` falls back to the pinned value.
- `tests/test_registry.py`: new fields have defaults; overlay merge leaves pinned identity fields untouched.
- `tests/test_catalogue.py`: entry fields follow the flags (Step 4 mapping) for a fake model with every flag on and one with every flag off.
- `tests/test_providers.py`: output cap follows the registry.
- Probe flags: pure functions for PNG and WAV generation unit tested (`tests/test_probe_media.py`: PNG starts with the 8-byte signature; WAV header says 8000 Hz).

Verification: full suite `OK`.

## Done criteria

- [ ] Overlay file committed and reproducible from `live_refresh.py` against the same input. (Superseded by the 2026-09-07 amendment: no overlay file exists; `live_refresh` rewrites derived fields in place in `models.json`. Kept open as written.)
- [x] `grep -n 32768 ai_router/providers.py` returns nothing. (Verified 2026-09-09: clean.)
- [ ] Matrix in `docs/compatibility.md` filled for all six models with dates and the Codex version.
- [ ] Registry flags match the matrix (a reviewer can check row by row).
- [ ] Both Muse entries advertise `audio` in `input_modalities` unless the audio probe reported `failed`. (2026-09-09: both Muse rows carry text,image,audio, matching the matrix; upstream audio leg rejected with `invalid_prompt`, client shape unproven live — stays open per plan rule until audio is removed or a passed probe is cited.)
- [ ] Full suite `OK`.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- OpenRouter's models JSON no longer has `architecture.input_modalities` or `top_provider.max_completion_tokens`; report the new shape.
- A probe passes but the same capability breaks an ordinary task on the author's machine (for example freeform patches fail to apply): disable that flag for that model, record it, continue with the others.
- Any probe would need a real user file or a non-synthetic prompt.

## Maintenance notes

- Deferred with reasons: `structured_outputs` as `strict: true` on native function tools (schema features differ across providers; the adapter already sets strict where it controls the schema); a "Fast" service tier mapped to OpenRouter provider routing (`provider.sort = throughput`), add if staff ask; image or audio output (no model here produces them).
- Codex upgrades can widen `InputModality` (for example add `video`). When they do, change one line in `live_refresh.py` (the tuple `('text', 'image', 'audio')`) and rerun the matrix for the affected models.
- Reviewers: every enabled flag must have a matching `passed` cell in `docs/compatibility.md` dated within the release.
