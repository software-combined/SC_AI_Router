# Plan 039: Serve a live merged model catalogue from the router and retire the frozen snapshot file

> Archived plan: pre-2026-09-10 numbering; see plans/README.md for the renumbering map and removal log.

> **Amended 2026-09-07**: Plan 043 adds `openai_mode = none`. In that mode `GET /models` is served from the registry with no upstream call, and in `subscription` mode an upstream 401 or 403 falls back to the registry-only body. Apply those two rules when implementing Step 2.

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

- **Priority**: P2
- **Effort**: M
- **Risk**: MED to HIGH (depends on how the Codex desktop fetches its catalogue; Step 1 is a no-cost spike that decides go or no-go)
- **Depends on**: Plan 038 (`openrouter_entry`), Plan 037 (providers and `do_GET` structure), Plan 035 (`ROUTER_HOME`, `load_state`)
- **Category**: tech-debt / migration
- **Planned at**: commit `749a6b8d`, 2026-09-07

## Path convention

`ROUTER_ROOT` is the repository root post-Plan 034 (module names `codex_router/...`), or `domains/ai-platform/codex-model-router` with flat names before it.

## Why this matters

Codex is pointed at a local catalogue file by `model_catalog_json` in `~/.codex/config.toml`. That file (553 KB on the author's machine) holds nine OpenAI entries copied from OpenAI at one moment in time, including their long system prompts, plus the six OpenRouter entries. While the file is in place, Codex never asks OpenAI for its catalogue (the router log shows only `/responses`, `/alpha/search` and `/alpha/notes/v2/thread_hint`), so every router user stops receiving new OpenAI models and prompt updates until someone re-captures the file by hand. For a team rollout this is the largest hidden maintenance cost, and the file is also the biggest thing the installer would have to ship. If the router itself answers the catalogue request by forwarding it to OpenAI and appending the registry's OpenRouter entries, the OpenAI half is always live, the OpenRouter half is generated, and no catalogue file needs distributing.

## Current state

- Config block written by the original activation (see `activation.json` `inserted_block` on the author's machine):

```toml
# BEGIN local mixed model picker
openai_base_url = "http://127.0.0.1:18749/<token>/backend-api/codex"
model_catalog_json = "/Users/cyrilallart/.codex/mixed-model-router/mixed-models.json"
# END local mixed model picker
```

- The Codex binary at `/Applications/ChatGPT.app/Contents/Resources/codex` (`codex-cli 0.153.4`) contains the strings `/models`, `client_version=` and `model_catalog_json path`, and a module `codex-api/src/endpoint/models.rs`, which indicates a remote models endpoint reached through the configured base URL with a `client_version` query. This is inferred from strings, not documented; Step 1 confirms it.
- `tools/probe_codex_runtime.py:12-13` has a `--capture-tools <base_url>` mode that starts the desktop app-server with `openai_base_url` set to the given sink and **without** `model_catalog_json` (only `--catalog` sets it, `:14-15`), and then calls `model/list` (`:89`). It never bills a provider when the sink returns errors.
- Router `do_GET` (post-Plan 035) handles `/health`, WebSocket upgrade (426) and returns 404 for everything else. `NATIVE_SERVICE_PATHS` lists the POST paths forwarded to `chatgpt.com` with the subscription bearer.
- `authorized_path()` strips the token prefix and the `/backend-api/codex` prefix but keeps the query string in `self.path`; check how `path.removeprefix` interacts with `?client_version=...` (the query stays attached to the returned path today).
- `state['openai_models']` (nine slugs) is how the subscription provider recognises OpenAI models; unknown models get 400 `Model is not in the configured catalog`. Plan 036 test 4 asserts that.
- Plan 038 provides `codex_router.catalogue.openrouter_entry(model)` and `registry.MODELS`.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Tests | `python3.14 -m unittest discover -s tests -t . -v` | `OK` |
| Spike sink (Step 1) | `python3.14 tools/catalogue_sink.py 18999` | prints one line per incoming request |
| Spike driver (Step 1) | `python3.14 tools/probe_codex_runtime.py gpt-6-astra --capture-tools http://127.0.0.1:18999/backend-api/codex` | exits non-zero (expected); the sink shows a `GET /backend-api/codex/models?...` line |
| Live check (Step 4) | `curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:18749/$(python3.14 -c "import json;print(json.load(open('$HOME/.codex/mixed-model-router/mixed-router-state.json'))['token'])")/backend-api/codex/models?client_version=0.153.4" -H "Authorization: Bearer <subscription token from Codex, never paste into a file>"` | `200` |

The live check needs the subscription bearer, which only Codex holds. Prefer Step 4's Codex-driven verification over the curl.

## Scope

**In scope**: new `tools/catalogue_sink.py` (spike only, may be deleted after), `codex_router/router.py` (`do_GET` branch), `codex_router/providers.py` (subscription membership), `codex_router/runtime.py` or `router.py` (`load_state` required keys), `tests/test_handler.py` (new tests only), `README.md`, `docs/operations.md` (Plan 042 owns the full rewrite; add one section here).

**Out of scope**: `~/.codex/config.toml` on any machine except the author's own manual migration in Step 5 (Plan 041's installer performs it for everyone else); the OpenRouter entry template (Plan 038); any change to `/responses` handling.

## Git workflow

- Branch `codex/router-live-catalogue-<yyyymmdd>`; commits `feat:`/`test:`/`docs:`. Do not push unless instructed.

## Steps

### Step 1: Spike, no cost, decides go or no-go

Write `tools/catalogue_sink.py` (about 25 lines): an `http.server` on the given port that prints `METHOD PATH` (strip any `Authorization` header from what you print; never print headers) and answers every request with 404 JSON. Start it, then run the spike driver command with the desktop app closed or open (either is fine). Watch the sink output for up to three minutes.

Outcomes:

- You see `GET /backend-api/codex/models?client_version=...` (or a `/models` path variant): **go**. Record the exact path and query in your report and continue.
- You see no `/models` request at all: **STOP**. Codex fetches its catalogue from somewhere other than `openai_base_url`, or only when a flag is set. Report exactly which requests the sink did see. The fallback is a capture-and-merge build step (Step 6), which the operator must approve.

**Verify**: your report contains the sink's request lines.

### Step 1 report (ran 2026-09-08, Codex Desktop/0.153.4 app-server, no billing)

- Driver: `probe_codex_runtime.py z-ai/glm-5.3-flash --capture-tools http://127.0.0.1:18998/backend-api/codex` with a sandboxed `CODEX_HOME` carrying the Shape C custom-provider config (no login, no credentials).
- Sink lines observed: `GET /backend-api/codex/responses` (x3, then the turn errored on the 404 sink as expected). No `GET /models` or `/models` path variant appeared during startup, `model/list` (which answered over app-server RPC with the subscription catalogue), `thread/start`, or `turn/start`.
- Outcome: **STOP / no-go**. Codex 0.153.4 fetches its catalogue over the app-server `model/list` RPC, not through `openai_base_url`. The `/models`-forward design in Step 2 does not match observed client behavior.
- Consequence: the static-file fallback (`model_catalog_json`) stands. Any replacement needs the operator-approved capture-and-merge build step (Step 6) or a different discovery mechanism; not improvised here.


### Step 2: Forward and merge `/models`

In `do_GET`, before the WebSocket check, add a branch for a path whose part before `?` equals `/models` (match the path recorded in Step 1):

- Require `Authorization: Bearer ...` on the incoming request; otherwise 401 `Codex subscription authentication required`.
- Forward `GET` to `chatgpt.com` with the same path and query and the incoming headers minus hop headers (reuse the subscription provider's header filtering).
- If upstream status is not 200 or the body is not JSON with a top-level `models` list, relay the upstream status and body unchanged (fail closed, no merge).
- Otherwise: build `existing = {m['slug'] for m in body['models']}`; append `openrouter_entry(model)` for every registry model with `provider == 'openrouter'` whose slug is not in `existing`; persist `sorted(slug for slug in existing)` to `ROUTER_HOME/openai-models-cache.json` (atomic write, mode 0600); update `self.server.openai_models` (a set) with those slugs; respond 200 with the merged JSON and `Content-Type: application/json`.
- Log `log_event('catalogue_merged', openai=len(existing), openrouter=<appended count>)`. Never log entries.

**Verify**: new tests in the Test plan pass.

### Step 3: Subscription membership becomes live, still fail closed

- `Router.__init__`: `self.openai_models = set(state.get('openai_models', [])) | set(json.loads(cache).get('slugs', []))` when `ROUTER_HOME/openai-models-cache.json` exists.
- `SubscriptionProvider.owns(model, path)`: `path in NATIVE_SERVICE_PATHS or model in server.openai_models` (pass the server's set into `select`, or give providers a reference to the server at construction).
- `load_state`: `openai_models` becomes optional (remove it from `REQUIRED_STATE`; keep the type check when present).
- Unknown models still return 400 `Model is not in the configured catalog`. Plan 036 test 4 must stay green.

**Verify**: `python3.14 -m unittest tests.test_handler -v` all green including `test_unknown_model_is_400_and_never_reaches_upstream`.

### Step 4: Prove it with the desktop app on the author's machine

Restart the router from the new code (operator action at an idle moment), then run `python3.14 tools/probe_codex_runtime.py gpt-6-astra --router-state ~/.codex/mixed-model-router/mixed-router-state.json` **without** `--catalog`. The probe prints `{"catalog": [...]}` from `model/list`.

**Verify**: the printed catalogue contains both `gpt-6-astra` and `z-ai/glm-5.3-flash`, and `ROUTER_HOME/logs/router.jsonl` has one `catalogue_merged` event. The paid part of the probe (a `low` effort tool round trip on `gpt-6-astra`) must also print `desktop_runtime_tool_round_trip: passed`.

### Step 5: Migrate the author's config and retire the file

Only after Step 4 passes. Using a small Python one-off (not `sed`): read `~/.codex/config.toml`, confirm the exact BEGIN/END block from `activation.json['inserted_block']` occurs once, replace it with the same block minus the `model_catalog_json` line, write atomically with mode 0600, and update `activation.json['inserted_block']` to the new block so `tools/disable.py` continues to match. Restart Codex. Confirm the picker still lists all fifteen models. Then move `~/.codex/mixed-model-router/mixed-models.json` and `.bak` to `~/.codex/mixed-model-router/retired/` (do not delete yet; Plan 042 deletes after a week of use).

**Verify**: `grep -c model_catalog_json ~/.codex/config.toml` prints `0`; `tools/disable.py` dry-read (`python3.14 -c "import json;print(open('$HOME/.codex/config.toml').read().count(json.load(open('$HOME/.codex/mixed-model-router/activation.json'))['inserted_block']))"`) prints `1`.

### Step 6 (only if Step 1 said no-go, operator approved): capture-and-merge build step

Write `tools/capture_catalogue.py`: runs the app-server via the probe's mechanism with `openai_base_url` pointing at the real router and `model_catalog_json` unset, calls `model/list`, and writes the OpenAI entries it returns plus `openrouter_entry` for registry models to `ROUTER_HOME/mixed-models.json` through `write_guarded`. Schedule it weekly from the updater (Plan 041). Keep `model_catalog_json` in the config block. Note in the README that OpenAI additions appear within a week rather than immediately.

**Verify**: running it reproduces a file whose OpenRouter entries pass `python3.14 -m codex_router.catalogue --check`.

## Test plan

Add to `tests/test_handler.py` (fake upstream from Plan 036):

- `test_models_get_forwards_bearer_and_query_and_merges_registry`: GET `/test-token/backend-api/codex/models?client_version=1.2.3` with `Authorization: Bearer sub`; fake upstream returns `{"models": [{"slug": "gpt-6-astra", "display_name": "GPT-6-Astra"}]}`; assert the recorded upstream request is `GET chatgpt.com /backend-api/codex/models?client_version=1.2.3` with the bearer and no hop headers; response is 200 JSON with 7 models; the six OpenRouter entries equal `openrouter_entry(m)` for the registry models; `server.openai_models == {'gpt-6-astra'}`; the cache file exists under the test `ROUTER_HOME` with `{"slugs": ["gpt-6-astra"]}`.
- `test_models_get_without_bearer_is_401`.
- `test_models_upstream_error_is_relayed_unmerged`: upstream 503 with `{"error": "down"}`; assert 503 and the body unchanged; no cache write.
- `test_models_get_does_not_duplicate_existing_openrouter_entry`: upstream already includes `z-ai/glm-5.3`; assert exactly one entry with that slug and it is the upstream one.
- `test_openai_membership_loaded_from_cache_at_startup`: write the cache file before `Router(state)` with `openai_models` absent from state; POST for `gpt-6-astra` reaches `chatgpt.com`.

Pattern: `test_handler.py` from Plan 036. Verification: full suite `OK`.

## Done criteria

- [ ] Step 1 report shows the `/models` request Codex makes (or the plan stopped at Step 1).
- [ ] Five new tests pass; Plan 036's ten remain unchanged.
- [ ] Step 4 probe printed a merged catalogue containing both an OpenAI and an OpenRouter slug and `desktop_runtime_tool_round_trip: passed`.
- [ ] Author's config has no `model_catalog_json` line and `disable.py` still matches the block.
- [ ] `README.md` states that the catalogue is live and no catalogue file is shipped.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- Step 1 shows no `/models` request (see Step 1 outcomes).
- The upstream `/models` response shape is not a JSON object with a `models` list of objects each having `slug`.
- Codex, after Step 5, shows fewer models in the picker than before (record which are missing; restore `model_catalog_json` from `activation.json`'s previous block and stop).
- The probe in Step 4 fails its tool round trip. Do not proceed to Step 5.

## Maintenance notes

- Codex fetches the catalogue at startup and when the picker opens; a router restart empties the in-memory set, which is why the cache file exists. Plan 041's updater restarts the router only when idle, and Codex keeps working because the set reloads from the cache.
- If OpenAI changes the endpoint or adds required query parameters, the router relays whatever Codex sends; only the merge step assumes the `models` list shape.
- Deferred: caching the upstream response. Codex calls the endpoint rarely; add a 10-minute cache only if the log shows repeated `catalogue_merged` events per minute.
