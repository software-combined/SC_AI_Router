# Plan 062: Separate HTTP transport from wire-protocol policy

> Planning only. Implement only under a later implementation instruction.
> Keep every stage runnable and update `plans/README.md` with evidence.
>
> Drift check: `git diff --stat 6840312..HEAD -- codex_router/router.py codex_router/providers.py codex_router/claude.py codex_router/transport.py codex_router/protocols tests/test_handler.py tests/test_providers.py tests/test_claude_ingress.py tests/test_router_response.py tests/test_v2_compaction.py tests/test_protocol_contracts.py tests/test_domain_boundaries.py tests/test_release.py docs/architecture.md config/source-limits-baseline.json CHANGELOG.md packaging/VERSION plans/README.md`
> Read the 060 diagnostic change and 061 boundary rules if integrated. Refresh
> changed excerpts; do not undo their contracts to reproduce the old layout.

## Status and outcome

- Priority P1; effort M; risk MED; category architecture/tests.
- Planned at `6840312`, 2026-09-09. Depends on 060 and 061 source integration.
- First proof: Responses and Messages traverse the same HTTP transport using
  explicitly selected protocol policy, with unchanged routing, auth separation,
  payload fidelity, streaming, errors and compaction regression results.

## Current state

`router.py:154-172` selects two different paths in the HTTP handler:

```python
if path in claude.CLAUDE_PATHS:
    provider = claude.select(model, path, mode)
else:
    provider = providers.select(
        model, path, self.server.state.get('openai_models', []), mode)
```

`providers.py` owns both `Prepared` transport data (`:122-127`) and Responses
model preparation/compaction (`:162-296`). It also has Codex-specific relay
rules: 429 becomes retryable 503 (`:19-28`), `openai-model` is pinned to the
requested slug (`:108-119`). `router.py:252-279` applies both rules to Messages.
`claude.py:16,98-105,116-120` imports provider internals for shared headers,
Prepared and a private passthrough helper.

This is a coupling finding. It is not proof that Claude currently fails on
those response headers/statuses. Preserve that behavior during extraction and
make later changes depend on a client contract test or live compatibility gate.

Good exemplars: `Prepared` is a small explicit data object; provider classes
construct their own headers; `tests/test_claude_ingress.py:41-100` verifies exact
auth separation and body fidelity; `tests/test_router_response.py:51-60` pins the
Codex header contract. Keep those assertions rather than replacing them with
tests that merely assert which new helper got called.

## Scope and proposed shape

Only the files in the drift check. New runtime files are limited to:

```text
codex_router/transport.py          Prepared, hop-header rules, raw stream helper
codex_router/protocols/__init__.py  explicit method/path selection
codex_router/protocols/responses.py
codex_router/protocols/messages.py
```

Keep `providers.py` and `claude.py` as thin compatible exports where existing
commands/tests or released callers rely on them; remove only exports proven
internal in the same stage. Move failure-description policy from providers only
if needed to keep the Responses module within limits; its existing `errors.py`
owner is preferred over an unrelated new utility module.

Out: universal conversation schema, automatic plugin discovery, new upstreams,
Kiro implementation, installer/platform work, model registry changes, changing
subscription mode defaults, live client configuration or probes. Do not route
by a guessed User-Agent; only an established path/contract selects protocol.

## Steps

### 1. Freeze the two observable protocol contracts

Create `tests/test_protocol_contracts.py` using `tests.fakes.FakeUpstream` and the
existing local handler harness. Pin both streaming and JSON Responses with tool
round trips; direct Messages body bytes and alias-only model rewriting; allowed
methods/paths; missing-token rejection; subscription header preservation and
OpenRouter header isolation. Pin current 429/Retry-After and response-header
behavior for each protocol, including the currently shared behavior.

Reuse existing compact/V2 tests. Do not duplicate their cases to inflate a
matrix. Add only missing cases needed to tell whether this extraction changes
on-wire behavior. Check unknown paths cause no upstream call.

**Verify:** `python3.14 -m unittest tests.test_protocol_contracts tests.test_handler tests.test_claude_ingress tests.test_router_response tests.test_v2_compaction`
passes on existing code. A deliberately wrong selected protocol in a test
fixture fails the concrete host/path/body assertion.

### 2. Extract the transport leaves and wire their callers

Move Prepared, HOP_HEADERS and the raw passthrough iterator into `transport.py`.
Update both current protocol implementations to consume them. Keep provider
targets and credential construction with their existing adapters; do not add a
service locator or make transport read model data. Transport cannot import
`router`, `claude`, registry or the installer.

**Verify:** `python3.14 -m unittest tests.test_providers tests.test_claude_ingress tests.test_domain_boundaries tests.test_release`
passes, including extracted-bundle import closure. This stage must already
route real local fake-upstream requests through the new leaves.

### 3. Extract protocol ownership and use explicit dispatch

Move Responses preparation, adaptation, local native paths and compaction
selection into `protocols/responses.py`. Move Messages route selection and
preparation/adaptation into `protocols/messages.py`; client-specific discovery
aliases can retain their compatibility exports until 064 relocates them.

Use a small explicit method/path table at `protocols/__init__.py`. Each result
supplies its selector and response policy. The HTTP handler should read/auth a
request, ask for the protocol, invoke it and relay; it should not branch on
`openrouter-claude` or duplicate client/provider tables. Keep health, shutdown
and setup as explicit local control endpoints in the handler.

Make retry and model-header handling explicit protocol callbacks with the
existing behavior initially selected for both protocols. Responses-specific
tool/history/compaction rules must never be applied to Messages payloads.
Keep compaction's inflight slot and credential lookup ordering. Preserve
connection cleanup and post-header streaming failure handling.

**Verify:** the Step 1 command plus
`python3.14 -m unittest tests.test_providers tests.test_lifecycle tests.test_domain_boundaries tests.test_release`
passes. Handler control flow contains no client-specific provider selection
branch; review the diff and the explicit dispatch table together.

### 4. Integrate and prove the same runnable paths

Update the architecture map with actual moved responsibilities and temporary
exports. Run all repository checks below. Split work into coherent commits
under the staged-line limit; mechanical moves may be reported separately, but
each stage must compile and route both protocols before the next begins.

**Verify:** all commands exit 0:

```sh
python3.14 -m unittest discover -s tests -t .
python3.14 -m compileall -q codex_router tools tests packaging
python3.14 tools/check_source_limits.py
python3.14 -m codex_router.models check --offline
git diff --check
```

## Done criteria

- [ ] Existing two protocols still pass body/stream/auth/status contracts.
- [ ] Handler uses one explicit protocol selection path; providers are new
      adapter classes, never new vendor branches in the HTTP handler.
- [ ] Shared transport leaves do not import client/provider orchestration.
- [ ] Compaction inflight handling, content-safe logs and credentials are preserved.
- [ ] Packaged imports pass, old command entrypoints remain usable, size limits pass.
- [ ] Review, commit, `develop` integration and worktree disposition are recorded.

## STOP conditions and maintenance

Stop if a move changes Messages framing/body bytes, widens subscription access,
alters retry semantics without evidence, needs a universal normalized payload,
exceeds scope, or fails the same check twice. Existing route bugs discovered
during characterization get separate focused fixes; do not quietly change them
inside the move. New clients should reuse a protocol only after proving it;
wire-compatible does not mean client-compatible.

Git: one owned `codex/` worktree from `develop`, current pre-commit-review and
exact model routing before every commit, conventional `refactor:` subjects,
target `develop`, verify integration and clean up. Runtime rollout and paid
client acceptance require their own authorised task/gate.
