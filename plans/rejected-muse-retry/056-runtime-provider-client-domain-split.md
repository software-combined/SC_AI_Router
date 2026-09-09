# Plan 056: Split the router into runtime, provider, and client domains

> REJECTED RETRY DRAFT. Do not execute. See this folder's README and the active parent plan index.

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 6840312..HEAD -- codex_router packaging tools`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `6840312`, 2026-09-09

## Why this matters

Today `codex_router/` mixes three jobs in one flat package: the HTTP
runtime (`router.py`, `runtime.py`, `activation.py`), the billing/provider
split (`providers.py`, `claude.py`, `credentials.py`), and the per-client
shapes (`catalogue.py`, `tool_adapter.py`, `compaction.py`,
`discovered.py`, `live_refresh.py`, `models.py`). Adding Windows service
management, Kiro, or a second Claude-style ingress means touching files
that also own the request hot path, which raises the odds of a routing
regression. After this plan the three domains live in three subpackages
with one documented seam each, so a new OS backend or a new client is a
new module behind an existing interface, never a branch in the request
path.

## Current state

The relevant files, each with one line on its role:

- `codex_router/router.py` (318 lines) — ThreadingHTTPServer request path
- `codex_router/runtime.py` (73 lines) — home, state validation, logging
- `codex_router/activation.py` (19 lines) — launchd socket inheritance
- `codex_router/providers.py` (335 lines) — OpenRouter vs subscription select/prepare/adapt
- `codex_router/claude.py` (129 lines) — Anthropic Messages ingress, same billing split
- `codex_router/credentials.py` (47 lines) — ordered OpenRouter key lookup
- `codex_router/catalogue.py` (243 lines) — Codex picker catalogue merge
- `codex_router/tool_adapter.py` (282 lines) — Codex tool discovery adaptation
- `codex_router/compaction.py` (287 lines) — V1/V2 compaction handling
- `codex_router/discovered.py` (150 lines) — discovered-tool schema store
- `codex_router/registry.py` (124 lines) — the one model registry loader
- `codex_router/capabilities.py` (120 lines) — per-model capability derivations
- `codex_router/models.py` (223 lines) — model onboarding command
- `codex_router/live_refresh.py` (93 lines) — live metadata refresh
- `codex_router/local_services.py` (21 lines) — no-subscription native answers
- `codex_router/errors.py` (255 lines) — stable error catalogue
- `codex_router/setup.py` (204 lines) — first-run key window route
- `codex_router/__main__.py` (29 lines) — daemon entrypoint

Today `providers.py` imports from `compaction`, `capabilities`,
`tool_adapter`, and `discovered` directly, and `router.py` imports
`claude`, `providers`, `local_services`, and `setup` as flat siblings.
There is no enforced direction; a client helper can reach into provider
internals and vice versa. Keep the public behavior identical: same
routes, same status codes from `errors.py`, same registry semantics.

Repo conventions that apply here, with exemplar:

- Stdlib only, Python 3.14+ for the router, 3.9+ for installer-time code.
  No third-party dependencies anywhere.
- Source limits enforced by `tools/check_source_limits.py`: modules 250
  soft / 400 hard, entrypoints and tools 400/700, tests 300/500.
- Error handling: callers select a case from `errors.py`, never invent
  wording. New modules must import error cases, not construct messages.
- Test pattern: `tests/test_mixed_router.py` and `tests/test_providers.py`
  build a Router/Handler against fakes in `tests/fakes.py`. Match that
  style for any moved-code regression test.

## Commands you will need

| Purpose   | Command                                             | Expected on success |
|-----------|-----------------------------------------------------|---------------------|
| Tests     | `python3.14 -m unittest discover -s tests -t .`     | `OK`, 473 tests     |
| Compile   | `python3.14 -m compileall -q codex_router tools tests packaging` | exit 0, no output |
| Limits    | `python3.14 tools/check_source_limits.py`           | `failures=0`        |

## Scope

**In scope** (the only files you should modify):

- `codex_router/` — create `runtime/`, `providers/`, `clients/` subpackages, move existing modules, leave thin re-export shims
- `tests/` — update imports to the new locations; add one seam test per new subpackage boundary
- `packaging/install.py`, `packaging/service.py` — update only the import paths they reference (catalogue merge entrypoint)
- `tools/probe_codex_runtime.py`, `tools/probe_media.py` — update only broken import paths
- `config/source-limits-baseline.json` — regenerate entries for moved paths

**Out of scope** (do NOT touch, even though they look related):

- Any request-path logic change: no new branches, no renamed error codes, no changed status messages
- `packaging/systemd.py`, `packaging/launchd.py`, `packaging/install.ps1`, `packaging/install.sh` — OS backends move in Plan 057, not here
- `tools/disable.py`, `tools/global_instructions.py` — client-config writers move in Plan 058, not here
- `docs/`, `README.md`, `CHANGELOG.md`, `packaging/VERSION` — no user-visible change ships in this plan

## Git workflow

- Branch: `advisor/056-runtime-provider-client-split` off `develop`
- Commit per step; message style `<type>: <short summary>` with type `feat`, `fix`, `refactor`, `test`, `chore`, `docs` (see `git log --oneline -10` for examples)
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Create the three subpackages with the domain rule written down

Create `codex_router/runtime/__init__.py`, `codex_router/providers/__init__.py`,
`codex_router/clients/__init__.py`. Each `__init__.py` carries a 3-6 line
docstring stating the domain rule:

- `runtime`: owns the HTTP server, state, logging, errors, setup route.
  Imports from `providers` only through `providers.select`-style entry
  points; never imports from `clients`.
- `providers`: owns billing split, credentials, upstream preparation and
  adaptation. Pure with respect to client wire shapes except through the
  `Prepared` value object already defined in `providers.py`.
- `clients`: owns per-client wire shapes (catalogue rows, tool envelopes,
  compaction items, discovery stores). Never imports transport or
  credential state.

Move (with `git mv`, no content edits yet):

- `runtime/`: `router.py` (Handler + Router stay together), `runtime.py`
  (rename to `state.py` only if every importer is updated in the same
  commit), `activation.py`, `errors.py`, `setup.py`, `__main__.py` stays
  at package root and imports from `runtime`.
- `providers/`: `providers.py` (rename to `openai_ingress.py` only if
  every importer moves in the same commit), `claude.py` (rename to
  `claude_ingress.py` under the same condition), `credentials.py`,
  `local_services.py`.
- `clients/`: `catalogue.py`, `tool_adapter.py`, `compaction.py`,
  `discovered.py`, `registry.py`, `capabilities.py`, `models.py`,
  `live_refresh.py`, `apply_catalogue.py`, `feed_verify.py`,
  `update_reasoning_catalog.py`.

Leave a thin shim at each old import path that re-exports the moved
names (e.g. `codex_router/providers.py` becomes
`from .providers.openai_ingress import *` plus the moved symbol list),
so existing tests and installer entrypoints keep working during the move.

**Verify**: `python3.14 -m compileall -q codex_router tools tests packaging` → exit 0

### Step 2: Point every importer at the new homes, then delete the shims

Update all imports in `codex_router/`, `packaging/`, `tools/`, and
`tests/` to the canonical new paths. Then delete the compatibility
shims from Step 1 so exactly one import path exists per symbol. Check
with:

`rg -n "from \.providers import|from codex_router import providers|from \.claude import" codex_router tools packaging tests`

which must return no hits for the old flat names (only the new
`codex_router.providers.*` / `codex_router.clients.*` /
`codex_router.runtime.*` paths remain).

**Verify**: `python3.14 -m unittest discover -s tests -t .` → `OK` (473 tests)

### Step 3: Add one boundary test per seam

Add three focused tests (new files, following `tests/test_providers.py`
as the structural pattern, using `tests/fakes.py`):

- `tests/test_runtime_seam.py`: constructing the Handler/Router does not
  import any `codex_router.clients` module (assert on `sys.modules`
  after importing only the runtime entrypoint in a subprocess).
- `tests/test_provider_seam.py`: `providers.select` returns a provider
  object exposing exactly `name`, `owns`, `prepare`, `adapt` (and
  `compact`/`summarize` only on the OpenRouter provider); assert the
  attribute surface so a new provider knows the contract.
- `tests/test_client_seam.py`: catalogue merge output for one registry
  row is byte-identical before/after the move (golden assertion on
  `catalogue.openrouter_entry` for one fixed slug).

**Verify**: `python3.14 -m unittest discover -s tests -t .` → `OK` (476 tests)

### Step 4: Refresh the source-limits baseline and run the full gate

Run `python3.14 tools/check_source_limits.py`. If moved files trip the
baseline comparison, update `config/source-limits-baseline.json` entries
to the new paths with unchanged line counts (moves only, no growth).
Then run the full verification trio from the Commands table.

**Verify**: `python3.14 tools/check_source_limits.py` → `failures=0`;
`python3.14 -m compileall -q codex_router tools tests packaging` → exit 0;
`python3.14 -m unittest discover -s tests -t .` → `OK`

## Test plan

- New tests in Step 3 (three files, one seam each), modeled on `tests/test_providers.py` + `tests/fakes.py`.
- Full existing suite must stay green throughout: 473 tests before, 476 after.
- No network in tests (repo rule); the seam tests use subprocess import
  checks and golden catalogue output, no live fetches.

## Maintenance note

Future client additions (Kiro, a second Claude-style surface) add a
module under `codex_router/clients/` plus a provider class under
`codex_router/providers/` implementing the Step-3-tested surface. They
must not add imports from `clients` into `runtime`. Reviewers: reject
any PR that adds a cross-domain import outside the three `__init__`
seams.

## STOP conditions

- If the drift check shows in-scope files changed since `6840312`, stop
  and reconcile the Current-state excerpts first.
- If any move requires a behavior edit to keep tests green (not just an
  import-path edit), stop and report: the move must be behavior-neutral.
- If the suite drops below 473 passing tests at any step, stop and
  report which test broke rather than weakening the test.

## Done criteria

- [ ] `codex_router/runtime/`, `codex_router/providers/`, `codex_router/clients/` exist with domain-rule docstrings
- [ ] No compatibility shims remain; one import path per symbol
- [ ] `python3.14 -m unittest discover -s tests -t .` → `OK` (476 tests)
- [ ] `python3.14 tools/check_source_limits.py` → `failures=0`
- [ ] Status row for this plan updated in `plans/README.md`
