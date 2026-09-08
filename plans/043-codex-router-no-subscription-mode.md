# Plan 043: Make the router work for staff who have no ChatGPT subscription

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
- **Effort**: M (spike S, implementation M)
- **Risk**: MED (depends on how Codex behaves without OpenAI login; Step 1 is a no-cost spike with hard go/no-go gates)
- **Depends on**: Plan 037 (providers), Plan 038 (registry). Plan 039 and Plan 041 consume this plan's `openai_mode` (their amendment notes point here).
- **Category**: direction / correctness
- **Planned at**: commit `749a6b8d`, 2026-09-07

## Path convention

Repository root post-Plan 034 (`codex_router/...`, `tools/...`, `tests/...`); pre-034 the flat names under `domains/ai-platform/codex-model-router/`.

## Why this matters

The router was built for one machine that has a paid ChatGPT subscription. Every OpenAI model request, the native service calls Codex makes (`/alpha/notes/v2/thread_hint` for thread titles, `/alpha/search`, `/guardian` for the approvals reviewer) and, after Plan 039, the catalogue request all forward to `chatgpt.com` with the user's subscription bearer. A staff member without a paid plan cannot use any of that, and today the router has no idea which situation it is in. The product goal is that such a person installs the router, signs in to Codex in whatever way Codex allows without a paid plan, and gets a picker with the OpenRouter models and a Codex that behaves normally. This plan first establishes, with no billing, which Codex login shape works without a subscription, then gives the router an explicit `openai_mode` so it never forwards to OpenAI when there is nothing to forward with, and answers the native service calls locally.

## Current state

- Router `route()` (`:31-43` at the planned commit): any path in `NATIVE_SERVICE_PATHS = {'/alpha/search', '/alpha/notes/v2/thread_hint', '/guardian', '/guardian-classifier'}` goes to `chatgpt.com` with the incoming headers minus hop headers, regardless of model. `do_POST` returns `401 Codex subscription authentication required` when a `chatgpt.com` target has no `Authorization: Bearer` header.
- Observed traffic on the author's machine (10,609 log lines): `/responses` 10,095, `/alpha/notes/v2/thread_hint` 446, `/alpha/search` 68, guardian paths 0. The author's config has `approvals_reviewer = "user"`, which is why guardian is never called.
- Codex binary facts (strings in `/Applications/ChatGPT.app/Contents/Resources/codex`, `codex-cli 0.153.4`): `chatgpt_base_url = "https://chatgpt.com/backend-api/"`; login accepts `--with-api-key` or `--with-access-token`; `CODEX_HOME` relocates the whole `~/.codex` directory including `auth.json` and `config.toml`, which allows a sandboxed spike without touching the real login; custom providers exist under `model_providers.<id>` with keys including `base_url`, `wire_api` (only `"responses"` is supported now), `env_key`, `http_headers`, `env_http_headers`; the string `You've hit your usage limit. Upgrade to Pro ...` shows plan gating happens on the OpenAI backend, not in the client.
- The probe harness `tools/probe_codex_runtime.py:24-35` starts `codex app-server --stdio` with `-c key=value` overrides and can run against a local sink (`--capture-tools <url>`), never billing when the sink answers errors. Plan 039 adds `tools/catalogue_sink.py`.
- State (after Plans 035 and 040): `{"port", "token"}` required; `openai_models` and `opencode_auth` optional. The registry (Plan 038) has no OpenAI rows.
- Plan 037 providers: `SubscriptionProvider.owns()` is true for native paths and known OpenAI models; `select()` raises `Model is not in the configured catalog` otherwise.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Tests | `python3.14 -m unittest discover -s tests -t . -v` | `OK` |
| Sandboxed Codex home | `export CODEX_HOME=/tmp/codex-nosub && mkdir -p $CODEX_HOME` | directory exists, contains no `auth.json` |
| Sink | `python3.14 tools/catalogue_sink.py 18999` | prints one line per request |
| Codex config help | `/Applications/ChatGPT.app/Contents/Resources/codex --help` and `... login --help` | lists `--with-api-key`, `--with-access-token` |

Never point `CODEX_HOME` at the real `~/.codex` during the spike, and never copy the real `auth.json` anywhere.

## Scope

**In scope**: `codex_router/router.py`, `codex_router/providers.py`, `codex_router/runtime.py` (state schema), new `codex_router/local_services.py`, `tests/test_handler.py` (new tests), new `tests/test_local_services.py`, `packaging/install.py` (`--openai-mode` flag and the config it writes; coordinate with Plan 041), `README.md` section "Without a ChatGPT subscription", `docs/compatibility.md` (login shapes verified).

**Out of scope**: OpenAI API-key forwarding to `api.openai.com` (`openai_mode = api_key`) is deferred, see Maintenance notes; any change to OpenRouter request handling; the real `~/.codex/auth.json` on any machine.

## Git workflow

- Branch `codex/router-no-subscription-<yyyymmdd>`; commits `feat:`/`test:`/`docs:`. Do not push unless instructed.

## Steps

### Step 1: Spike, no billing, three login shapes

Run each shape against the sink (`--capture-tools http://127.0.0.1:18999/backend-api/codex`) with a fresh `CODEX_HOME`. For each, record: whether `initialize` and `model/list` succeed, which paths the sink receives at startup and during `thread/start` plus `turn/start` for `z-ai/glm-5.3-flash`, and the exact error when something fails (redact URLs as the probe already does).

- **Shape A, no login at all**: empty `CODEX_HOME`. Expect app-server to refuse or to run in a limited mode; record which.
- **Shape B, API-key login with a placeholder**: `printf 'sk-placeholder-not-a-real-key' | CODEX_HOME=$CODEX_HOME codex login --with-api-key`, then run the probe. Record whether Codex validates the key against OpenAI before serving, and whether requests carry `Authorization: Bearer sk-placeholder...` and no `ChatGPT-Account-ID` header.
- **Shape C, custom provider, no OpenAI login**: write `$CODEX_HOME/config.toml`:

```toml
model_provider = "scg_router"
[model_providers.scg_router]
name = "SC router"
base_url = "http://127.0.0.1:18999/backend-api/codex"
wire_api = "responses"
env_key = "SCG_ROUTER_TOKEN"
```

  export `SCG_ROUTER_TOKEN=<sandbox-value>`, and run the probe with `-c model_provider=...` overrides removed (edit a copy of the probe or add a `--provider <id>` flag that sets `cfg['model_provider']`). Record whether `model/list` asks the sink for `/models`, which native paths (if any) are requested for a custom provider, and whether `turn/start` reaches `/responses` with `Authorization: Bearer <sandbox-value>`.

Then, if the desktop app is the target for staff, check the ChatGPT desktop app's Codex sign-in screen for an API-key or "use custom provider" option and record what is offered (screenshot description only).

Decision table:
- C works in app-server: preferred; the router accepts `Bearer <token>` as an alternative to the path token (Step 3), and the installer writes a custom-provider block for `--openai-mode none` (Step 5).
- Only B works: the installer keeps `openai_base_url` and staff run the placeholder-key login once; the router treats any OpenAI-model request in `none` mode as 400.
- Neither works in app-server: **STOP** and report the exact errors.
- App-server works but the desktop app requires ChatGPT sign-in: report that no-subscription staff can use the Codex CLI and IDE extension but not the desktop app, and ask Cyril whether to proceed on that basis.

**Verify**: your report contains the per-shape request lists from the sink and the decision-table outcome.

### Step 1 report (ran 2026-09-08, Codex Desktop/0.153.4 app-server, sandboxed CODEX_HOME, no real credentials)

- Shape A (empty CODEX_HOME, no login): `initialize` succeeds; `model/list` never answers (no result, no error, only a plugin-cache warning in stderr). No sink traffic possible since no base_url override is configured.
- Shape B (placeholder API-key login): `login --with-api-key` accepts the placeholder locally with no OpenAI validation and writes `auth.json`; `initialize` succeeds; `model/list` never answers. Plugin manager warns API-key auth cannot reach the remote catalog. No evidence Codex validates the key before serving.
- Shape C (custom provider, no OpenAI login, `SCG_ROUTER_TOKEN=<sandbox-value>`): `initialize` succeeds; `thread/start` for `z-ai/glm-5.3-flash` on `scg_router` succeeds with no `auth.json` present; `turn/start` reaches the sink as `POST /backend-api/codex/responses` with `Authorization: Bearer` present (retried 6x against the 404 sink, proving bearer + path routing works). No native `/alpha/*` or `/guardian` calls observed at startup or thread start in this shape.
- Decision-table outcome: Shape C works in app-server. Preferred path confirmed. Desktop-app sign-in screen check not run (CLI/IDE basis only so far; the owner question on desktop-app ChatGPT sign-in stays open).
- Note: `thread/start` requires the `experimentalApi` capability flag; without it the server returns `thread/start.dynamicTools requires experimentalApi capability`.


### Step 2: `openai_mode` in state and startup validation

Add optional state key `openai_mode` with values `subscription` (default when absent) and `none`. `load_state` rejects any other value with `SystemExit('openai_mode must be subscription or none')`. In `none` mode, `openai_models` and the cache file are ignored.

**Verify**: unit test `test_openai_mode_validation` passes.

### Step 3: Providers honour the mode

- `SubscriptionProvider.owns()` returns False for everything when `openai_mode == 'none'`, except native paths, which are claimed by a new `LocalServicesProvider` (Step 4) in that mode.
- `select()` error for an OpenAI slug in `none` mode: `Model is not available without a ChatGPT subscription` (status 400 via the existing `ValueError` path).
- Bearer alternative: `authorized_path()` also accepts a request whose first path segment is not the token when the header `Authorization` equals `Bearer <token>` (constant-time compare), so Shape C works with a plain base URL. The `Origin` rejection stays. Never log either value.

**Verify**: tests `test_none_mode_rejects_openai_models_without_upstream_call`, `test_bearer_token_authorises_when_path_token_absent`, `test_bearer_with_wrong_token_is_403` pass; Plan 036's ten tests unchanged.

### Step 4: Local answers for native service calls

Create `codex_router/local_services.py`, used only in `none` mode (and, as a fallback, when the subscription upstream returns 401 or 403 for these paths):

- `/alpha/notes/v2/thread_hint`: read the request JSON, find the first user message text (reuse `compaction.extract_user_messages`), build a title from its first eight words (strip newlines, cap 60 characters, fall back to `New task`), and respond with the same JSON shape the real service returns. The shape must come from Step 1's recording or from one real response captured on the author's machine (a JSON body with a title field; record the exact key name, never guess). If no recording exists, STOP for this path and return 404 instead.
- `/alpha/search`: respond with the empty-result shape recorded in Step 1. If the spike shows Codex fails the turn when this returns 404 and no shape was recorded, STOP.
- `/guardian`, `/guardian-classifier`: return 404 and document that `approvals_reviewer = "user"` must be set (the installer writes it in `none` mode).

Log `log_event('local_service', path=path)` for each.

**Verify**: `tests/test_local_services.py`: title from a long first message is eight words and under 60 characters; empty input gives `New task`; shapes match the recorded fixtures byte for byte (store the recorded shapes as fixtures in the test file, with any identifiers replaced by placeholders).

### Step 5: Catalogue and installer in `none` mode

- With Plan 039 (SUPERSEDED 2026-09-08: the 039 Step 1 spike showed Codex never issues `GET /models` through `openai_base_url`, so no router `/models` route exists; the static `model_catalog_json` file remains the catalogue mechanism): in `none` mode, `GET /models` would have returned the registry-only body with no upstream call; in `subscription` mode, upstream 401/403 would have fallen back to it with a `catalogue_fallback` log.
- Installer `--openai-mode none` (Plan 041): writes the Codex configuration matching the shape chosen in Step 1 (custom provider block with `env_key` set through the LaunchAgent-free path, meaning the staff member exports the token in their shell profile, or the `openai_base_url` block for Shape B), sets `approvals_reviewer = "user"` inside the marked block, and stores `openai_mode` in state. `tools/disable.py` continues to work because the block is still delimited by the same markers.

**Verify**: installer dry run with `--openai-mode none` prints the block it would write and contains `approvals_reviewer` (landed, tested).

Note 2026-09-08: the `test_models_in_none_mode_is_registry_only` / `test_models_upstream_403_falls_back_to_registry` criteria cannot land: the 039 Step 1 spike showed Codex 0.153.4 never issues `GET /models` through `openai_base_url` (catalogue arrives over app-server `model/list` RPC), so there is no router `/models` route to test. The static `model_catalog_json` file remains the catalogue mechanism in both modes.

### Step 6: Documentation

`README.md` gains "Without a ChatGPT subscription": what works (OpenRouter models, tools, compaction, web search where the model supports it), what does not (OpenAI models, the approvals reviewer, server-side thread titles are replaced by local ones), how to sign in per the chosen shape, and the one-line install command with `--openai-mode none`. `docs/compatibility.md` records the shapes tested and the Codex version.

**Verify**: `grep -n "openai-mode none" README.md` shows the command.

## Test plan

Listed per step; all in `tests/test_handler.py` and `tests/test_local_services.py`, modelled on Plan 036's fake upstream. Verification: full suite `OK`; the new tests exist by name.

## Done criteria

- [ ] Step 1 report with per-shape sink logs and the decision.
- [ ] State accepts `openai_mode` and refuses bad values at startup.
- [ ] In `none` mode no request ever reaches `chatgpt.com` (assert the recorded upstream list is empty in every `none` mode test).
- [ ] Native paths answered locally with recorded shapes, or 404 where the spike proved Codex tolerates it.
- [ ] Installer writes a working `none` configuration on a sandboxed `CODEX_HOME` and the probe's `model/list` through the router shows the OpenRouter models.
- [ ] Full suite `OK`; Plan 036 tests unchanged.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- Neither Shape B nor Shape C reaches `/responses` in the spike.
- A native path has no recorded response shape and Codex fails the turn when it gets 404.
- Cyril has not answered whether CLI and IDE only is acceptable, in the case the desktop app requires ChatGPT sign-in.
- Any step would require reading or copying the real `~/.codex/auth.json`.

## Maintenance notes

- Deferred: `openai_mode = api_key` (staff with an OpenAI API key but no subscription). It needs forwarding to `api.openai.com/v1/responses` and a different catalogue source; add only when someone asks.
- Codex upgrades can add native paths. Any new path Codex calls shows up in the router log as `request_rejected` 404; add it to `local_services.py` with a recorded shape, never a guessed one.
- Reviewers: check that `none` mode has no code path constructing a `chatgpt.com` connection, and that the bearer alternative uses `hmac.compare_digest`.
