# Plan 037: Split the request handler into a provider interface and a thin relay

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
- **Risk**: MED (touches the request path; mitigated by Plan 036's tests, which must stay unchanged)
- **Depends on**: Plan 036 (characterisation tests), Plan 038 (registry supplies `provider` per model), Plan 035 (`load_state`, `log_event`)
- **Category**: tech-debt
- **Planned at**: commit `749a6b8d`, 2026-09-07

## Path convention

`ROUTER_ROOT` is `domains/ai-platform/codex-model-router` pre-Plan 034 or the repository root post-034. Post-034 module names are used below; pre-034 use the flat names (`mixed_router.py`, new `providers.py`).

## Why this matters

`Handler.do_POST` is about 115 lines that mix authentication, body decoding, model validation, OpenRouter preparation, credential loading, compaction, routing, the upstream call, streaming adaptation and metrics. Provider-specific behaviour is spread through it as `if model in OPENROUTER_MODELS` branches. Adding a third provider today means adding more branches to the same method. The bug of 7 September 2026 (a state key read inside that method) hid in exactly this density. Two providers already exist, so a small provider interface is the smallest abstraction that pays for itself: each provider owns "does this model belong to me", "prepare the outgoing request", and "adapt the response stream". The handler becomes a thin relay that is easy to read and to test.

## Current state

- Router module `:31-43` `route(model, path, headers, openai_models, key)` returns `(host, upstream_path, headers)` and is called from `do_POST`.
- `:23-29` `prepare_openrouter(payload, path)` mutates and serialises the payload.
- `:50-67` `summarize_for_compact(model, key, payload_items)` posts to OpenRouter directly with its own `HTTPSConnection`.
- `:140-154` OpenRouter branch: `prepare_tools`, `prepare_openrouter`, cap, credential read.
- `:155-180` compaction branch for OpenRouter, returns its own 200.
- `:183-229` upstream relay: `HTTPSConnection(host, timeout=120)`, copy status and non-hop headers, stream chunks through `stream_events` when `custom_tools` and SSE, else raw `read1(65536)`; metrics dict with keys `provider`, `model`, `path`, `request_bytes`, `tool_definitions`, `local_prepare_ms`, `upstream_headers_ms`, `first_chunk_ms`, `total_ms`, `status`.
- `NATIVE_SERVICE_PATHS` (`:21`) always go to `chatgpt.com` regardless of model.
- `capabilities.py:10-14` defines `OPENROUTER_MODELS` and `:49` `OPENROUTER_HOST = 'openrouter.ai'`. After Plan 038 these derive from the registry.
- Tests import `Router, route, prepare_openrouter` from the router module (`test_mixed_router.py:10`) and patch `mixed_router.summarize_for_compact` and `mixed_router.http.client.HTTPSConnection` (`:130`, `:172`).

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Tests | `python3.14 -m unittest discover -s tests -t . -v` | `OK` |
| Source limits | `python3.14 tools/check_source_limits.py` | `failures=0`; `router.py` and `providers.py` each under 250 lines |
| Compile | `python3.14 -m compileall -q codex_router tests` | exit 0 |

## Scope

**In scope**: `codex_router/router.py`, new `codex_router/providers.py`, `tests/test_mixed_router.py` (import paths and patch targets only), `tests/test_handler.py` (patch target for `HTTPSConnection` only, if it moves).

**Out of scope**: `tool_adapter.py`, `compaction.py`, `capabilities.py`, `registry.py`, catalogue scripts, any assertion in `tests/test_handler.py`, any change to what reaches upstream.

## Git workflow

- Branch `codex/router-providers-<yyyymmdd>`; commits `refactor:`; pre-commit review per the shared skill. Do not push unless instructed.

## Steps

### Step 1: Introduce `providers.py` with two providers behind one shape

Create `codex_router/providers.py`:

```python
"""Provider adapters. Each owns model membership, request preparation, upstream target and response adaptation."""
import json
from . import compaction as comp
from .tool_adapter import prepare_tools, stream_events, ToolEvents
from .registry import MODELS, by_slug   # Plan 038

HOP_HEADERS = {...}  # move from router.py unchanged
NATIVE_SERVICE_PATHS = {...}  # move from router.py unchanged

class Prepared:
    __slots__ = ('host', 'path', 'headers', 'body', 'tool_names', 'provider')
    def __init__(self, host, path, headers, body, tool_names, provider):
        ...

class SubscriptionProvider:
    name = 'openai-subscription'
    host = 'chatgpt.com'
    def owns(self, model, path):
        return path in NATIVE_SERVICE_PATHS or (model is not None and by_slug(model) is not None and by_slug(model).provider == 'openai')
    def prepare(self, model, path, payload, raw_body, headers, credentials):
        if not headers.get('Authorization', '').startswith('Bearer '):
            raise PermissionError('Codex subscription authentication required')
        fwd = {k: v for k, v in headers.items() if k.lower() not in HOP_HEADERS}
        return Prepared(self.host, '/backend-api/codex' + path, fwd, raw_body, set(), self.name)
    def adapt(self, response, tool_names):
        while chunk := response.read1(65536):
            yield chunk

class OpenRouterProvider:
    name = 'openrouter'
    host = 'openrouter.ai'
    def owns(self, model, path):
        entry = by_slug(model) if isinstance(model, str) else None
        return entry is not None and entry.provider == 'openrouter' and path not in NATIVE_SERVICE_PATHS
    def prepare(self, model, path, payload, raw_body, headers, credentials):
        if path not in ('/responses', '/responses/compact'):
            raise ValueError('OpenRouter supports responses only')
        tool_names = prepare_tools(payload)
        payload['input'] = comp.rewrite_input(payload.get('input', []))
        payload.pop('service_tier', None)
        payload['max_output_tokens'] = min(payload.get('max_output_tokens') or 32768, 32768)
        return Prepared(self.host, '/api/v1/responses',
                        {'Authorization': 'Bearer ' + credentials.openrouter_key(), 'Content-Type': 'application/json'},
                        json.dumps(payload).encode(), tool_names, self.name)
    def adapt(self, response, tool_names):
        if tool_names and response.status == 200:
            if 'text/event-stream' in response.getheader('Content-Type', ''):
                yield from stream_events(response, tool_names)
            else:
                result = json.load(response)
                adapter = ToolEvents(tool_names)
                result['output'] = [adapter.item(item) for item in result.get('output', [])]
                yield json.dumps(result).encode()
        else:
            while chunk := response.read1(65536):
                yield chunk

PROVIDERS = (OpenRouterProvider(), SubscriptionProvider())

def select(model, path):
    for provider in PROVIDERS:
        if provider.owns(model, path):
            return provider
    raise ValueError('Model is not in the configured catalog')
```

`credentials` is an object with `openrouter_key()`; until Plan 040 lands, implement it in `router.py` as a tiny class reading `state['opencode_auth']` exactly as the current `:151-154` lines do. Keep the exact error messages that tests assert on (`'Model is not in the configured catalog'`, `'Codex subscription authentication required'`).

Move `COMPACT_PROMPT` and `summarize_for_compact` into `OpenRouterProvider.compact(self, model, payload, credentials)` returning the V1 output list, raising `ValueError` for empty user messages or summary and `OSError`/`http.client.HTTPException` for transport failures, exactly as `:155-176` does today.

**Verify**: `python3.14 -m compileall -q codex_router` exits 0.

### Step 2: Rewrite `do_POST` as a relay

Target shape for `codex_router/router.py` (keep `Router`, `Handler.error`, `authorized_path`, `do_GET` as they are after Plan 035):

```python
def do_POST(self):
    started = time.monotonic()
    path = self.authorized_path()
    if path is None:
        return self.error(403, 'Forbidden')
    if path not in NATIVE_SERVICE_PATHS | {'/responses', '/responses/compact'}:
        return self.error(404, 'Unsupported route')
    try:
        raw, payload, size = self.read_body()            # Content-Length, MAX_BODY, zstd, json
        model = payload.get('model')
        if not isinstance(model, str) and path not in NATIVE_SERVICE_PATHS:
            return self.error(400, 'Missing model')
        provider = providers.select(model, path)
        if path == '/responses/compact' and provider.name == 'openrouter':
            return self.send_json(200, {'output': provider.compact(model, payload, self.server.credentials)})
        prepared = provider.prepare(model, path, payload, raw, dict(self.headers), self.server.credentials)
    except PermissionError as exc:
        return self.error(401, str(exc))
    except ValueError as exc:
        return self.error(409 if provider_is_openrouter_prep_error else 400, ...)  # see note
    except (KeyError, OSError, TypeError, AttributeError, zstd.ZstdError):
        return self.error(400, 'Invalid model, payload, or local authentication configuration')
    self.relay(prepared, model, path, size, len(payload.get('tools', [])), started)
```

Note on status codes: today `prepare_tools`/`prepare_openrouter` `ValueError`s return 409 (`:144-145`) while other `ValueError`s return 400 (`:181-182`), and compaction `ValueError`s return 409, transport failures 502. Preserve this exactly: raise a dedicated `class PreparationError(ValueError)` from `OpenRouterProvider.prepare` and `compact` for the 409 cases and map `PreparationError` to 409, other `ValueError` to 400, `(OSError, http.client.HTTPException)` from `compact` to 502.

`read_body` holds the `Content-Length`, `MAX_BODY`, `Transfer-Encoding`, zstd and decoded-size logic from `:121-133` unchanged. `send_json(status, obj)` holds the header sequence used by `error` and the compaction 200. `relay(prepared, ...)` holds `:183-229` unchanged except that `chunks()` becomes `prepared_provider.adapt(response, prepared.tool_names)` and `metrics['provider']` becomes `prepared.provider`, plus the `inflight` increment/decrement from Plan 035.

**Verify**: `python3.14 -m unittest tests.test_handler -v` ten `ok`, unchanged assertions (`git diff --stat tests/test_handler.py` shows at most the patch-target line change).

### Step 3: Update the older tests' import and patch targets

In `tests/test_mixed_router.py`: `route` no longer exists; replace the `RoutingTests` that call `route(...)` with equivalent calls to `providers.select(model, path).prepare(...)` asserting the same `(host, path, headers)` facts, or delete a test only when Plan 036's suite covers the same fact (record which). Patch `codex_router.providers.http.client.HTTPSConnection` instead of `mixed_router.http.client.HTTPSConnection` where the summariser is exercised, and patch `OpenRouterProvider.compact` where `summarize_for_compact` was patched.

**Verify**: full suite `OK`, and the test count equals the Plan 036 count minus any tests deleted as exact duplicates (list them in the report).

### Step 4: Remove dead code

Delete `route`, `prepare_openrouter`, `summarize_for_compact`, `COMPACT_PROMPT` from `router.py` once nothing imports them.

**Verify**: `grep -n "def route\|def prepare_openrouter\|def summarize_for_compact" codex_router/router.py` returns nothing; source limits pass.

## Test plan

- No new behaviour; Plan 036's ten tests are the acceptance suite and must pass byte-identical.
- Add two small tests in `tests/test_providers.py`: `test_select_prefers_native_paths_regardless_of_model` (`select('z-ai/glm-5.3', '/alpha/search')` is the subscription provider) and `test_select_rejects_unknown_model`.

## Done criteria

- [ ] `tests/test_handler.py` assertions unchanged (`git diff tests/test_handler.py` shows only patch-target edits or nothing).
- [ ] Full suite `OK`.
- [ ] `router.py` under 250 lines, `providers.py` under 250 lines, `check_source_limits.py` `failures=0`.
- [ ] `grep -n "OPENROUTER_MODELS" codex_router/router.py` returns nothing (membership lives in providers via the registry).
- [ ] `plans/README.md` status row updated.

## STOP conditions

- Any Plan 036 test needs an assertion change to pass. That means behaviour changed; report the diff and stop.
- `providers.py` cannot stay under 400 lines: stop and propose a split rather than exceeding the hard limit.
- Plan 038's `registry.by_slug` does not exist yet: implement the two providers against `capabilities.OPENROUTER_MODELS` and `state['openai_models']` temporarily, and note that Plan 038 must replace those two lookups.

## Maintenance notes

- A third provider is a new class in `providers.py` plus registry entries; the handler must not change. Reviewers should reject any new `if model ...` branch in `router.py`.
- `Prepared.body` for the subscription path is the raw (possibly zstd) bytes forwarded untouched; keep it that way so OpenAI receives exactly what Codex sent.
