# Plan 058: One client-adapter interface for Codex, Claude Code, and Kiro

> REJECTED RETRY DRAFT. Do not execute. See this folder's README and the active parent plan index.

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 6840312..HEAD -- codex_router tests`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/056-runtime-provider-client-domain-split.md
- **Category**: tech-debt
- **Planned at**: commit `6840312`, 2026-09-09

## Why this matters

Each supported client is currently wired by hand across unrelated
files. Codex owns `catalogue.py` merge logic with a `client='codex'`
parameter, `tool_adapter.py` envelopes, `compaction.py` V1/V2 handling,
and config-block writing inside `packaging/install.py` (`config.toml`
`# BEGIN local mixed model picker` block) plus the `AGENTS.md` rules
block in `tools/global_instructions.py`. Claude Code was added as a
second, parallel ingress (`claude.py`: alias/un-alias, `models_listing`,
`CLAUDE_PATHS`, subscription passthrough) with its own `--client
codex|claude` flag on the catalogue CLI and `visible_for()`/`models_for()`
picker-hiding rules in `registry.py`. Kiro has no adapter at all. The
next client will otherwise mean a third copy of the alias/listing/
visibility/config quartet and another flag threaded through the CLI. After
this plan every client implements one `ClientAdapter` interface, the
router dispatches ingress through it, and Kiro arrives as a small
fourth module instead of a fourth special case.

## Current state

The relevant files, each with one line on its role (post-Plan-056 paths;
if Plan 056 renamed modules, resolve through its shims first):

- `codex_router/clients/catalogue.py` — `merge(catalog, roster, client)`,
  `check(path, client)`, `openrouter_entry()`, `subscription_stub()`
- `codex_router/registry.py` — `visible_for(model, client)` with the
  hardcoded `{'codex': 'openai/', 'claude': 'anthropic/'}` hidden-prefix map
- `codex_router/claude.py` — `claude_alias/unalias/resolve/models_listing`,
  `CLAUDE_PATHS`, `ClaudeOpenRouterProvider`, `ClaudeSubscriptionProvider`, `select()`
- `codex_router/tool_adapter.py` — Codex-only tool envelopes (`json_text`, namespaces, search rename)
- `codex_router/compaction.py` — Codex V1/V2 compaction items
- `packaging/install.py` `do_install()` (~lines 430-470) — writes the
  Codex `config.toml` block inline; no other client config writer exists
- `tools/global_instructions.py` — writes the Codex `AGENTS.md` rules block
- `tools/disable.py` — removes the Codex config block + rules block only

Key excerpts as they exist today:

`registry.py:visible_for` — the map a new client must currently edit:

```python
hidden = {'codex': 'openai/', 'claude': 'anthropic/'}[client]
```

`claude.py:models_listing` — the per-client listing a new client must currently duplicate:

```python
def models_listing():
    rows = []
    for entry in MODELS:
        alias = claude_alias(entry.slug)
        ...
```

Repo conventions that apply here, with exemplar:

- Provider classes expose `name/owns/prepare/adapt` (see
  `providers.py:SubscriptionProvider/OpenRouterProvider`). Client
  adapters mirror that shape so both sides read the same way.
- Error handling: adapters raise cases from `errors.py`
  (`PreparationError`, `unknown_model`, `claude_subscription_required`)
  rather than inventing messages.
- Test pattern: `tests/test_claude_ingress.py` drives the Claude paths
  through fakes; `tests/test_catalogue.py` asserts merge output.
  New-adapter tests follow both.

## Commands you will need

| Purpose   | Command                                             | Expected on success |
|-----------|-----------------------------------------------------|---------------------|
| Tests     | `python3.14 -m unittest discover -s tests -t .`     | `OK`                |
| Compile   | `python3.14 -m compileall -q codex_router tools tests packaging` | exit 0   |
| Limits    | `python3.14 tools/check_source_limits.py`           | `failures=0`        |

## Scope

**In scope** (the only files you should modify):

- `codex_router/clients/base.py` (create) — the `ClientAdapter` interface
- `codex_router/clients/codex.py` (create) — Codex adapter (catalogue rows, tool envelopes, compaction, config writer)
- `codex_router/clients/claude.py` (create or rename) — Claude Code adapter moved behind the interface
- `codex_router/clients/kiro.py` (create) — Kiro adapter stub implementing the interface (see Step 3)
- `codex_router/registry.py` — replace the hardcoded hidden-prefix map with per-adapter `hidden_prefix`
- `codex_router/router.py` (or `runtime/`) — dispatch ingress through the adapter registry instead of hardcoded `claude.CLAUDE_PATHS` checks
- `packaging/install.py` — call adapter config writers instead of inline Codex block
- `tools/disable.py`, `tools/global_instructions.py` — route removal through the adapter that owns each block
- `tests/test_client_adapter.py` (create)

**Out of scope** (do NOT touch, even though they look related):

- Upstream provider logic (`prepare`/`adapt` bodies) — behavior identical, only the dispatch moves
- OS service backends — Plan 057 owns those
- `docs/`, `README.md`, `CHANGELOG.md` — no user-visible change ships here
- Live Kiro acceptance (real Kiro session through the router) — stays a release gate; this plan lands the adapter with faked tests

## Git workflow

- Branch: `advisor/058-client-adapter-interface` off `develop`
- Commit per step; message style `<type>: <short summary>` (`feat`/`fix`/`refactor`/`test`/`chore`/`docs`)
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Define the ClientAdapter interface

Create `codex_router/clients/base.py` (target under 100 lines):

```python
class ClientAdapter:
    name = 'interface'          # 'codex' | 'claude' | 'kiro'
    hidden_prefix = ''          # registry slugs hidden from this picker when OpenRouter-billed
    ingress_paths = frozenset() # request paths this client may hit
    def aliases(self, entry): ...      # discovery ids for one registry row (claude_alias today)
    def resolve(self, model): ...      # discovery id -> registry slug (resolve/unalias today)
    def models_listing(self): ...      # picker discovery payload
    def catalogue_entry(self, model): ...  # catalogue row (openrouter_entry/specialization)
    def install_config(self, home, state): ...   # (config_path, block) this client owns
    def remove_config(self, home): ...           # inverse for uninstall
```

`registry.visible_for(model, client)` keeps its signature but looks up
`hidden_prefix` from the registered adapter instead of its hardcoded
dict, raising `ValueError(f'unknown client: {client}')` for
unregistered names exactly as today.

**Verify**: `python3.14 -m compileall -q codex_router` → exit 0

### Step 2: Move Codex and Claude Code behind the interface

Implement `CodexAdapter` (composing the existing `catalogue`,
`tool_adapter`, `compaction` functions without changing their bodies)
and `ClaudeAdapter` (composing the existing `claude_alias/unalias/
resolve/models_listing` functions without changing their bodies).
Register both in an adapter registry (`ADAPTERS = {'codex': ...,
'claude': ...}`) owned by `clients/base.py` or `clients/__init__.py`.

Rewire `router.py` ingress dispatch: replace the direct
`path in claude.CLAUDE_PATHS` checks with a lookup over registered
adapters' `ingress_paths`. Rewire the catalogue CLI `--client` flag to
validate against the registry keys. Byte-for-byte behavior for both
existing clients is the requirement: `tests/test_claude_ingress.py`,
`tests/test_catalogue.py`, and `tests/test_mixed_router.py` must pass
unmodified in intent.

**Verify**: `python3.14 -m unittest discover -s tests -t .` → `OK`

### Step 3: Add the Kiro adapter as the first consumer of the interface

Create `codex_router/clients/kiro.py` with a `KiroAdapter` implementing
every interface method. Kiro speaks an OpenAI-compatible surface, so:

- `hidden_prefix`: Kiro has no subscription side in this router, so no
  OpenRouter-billed row is hidden from it: use `''` semantics (every
  OpenRouter row visible), documented in one comment line.
- `ingress_paths`: the `/responses` family only (no compaction, no
  native paths) until a live Kiro session proves otherwise.
- `aliases/resolve`: identity (registry slugs pass through untouched).
- `models_listing`: reuse the Codex catalogue-row shape via
  `catalogue_entry`, not a new schema.
- `install_config/remove_config`: write/remove a Kiro-side config
  pointer file under the router home (not the Kiro app's own config
  yet — the live path gets proven in acceptance); the method exists so
  install/uninstall route through the adapter from day one.

Mark the module docstring `Preview: live Kiro session acceptance pending
per docs/operations.md release gates.` Do not claim Kiro works
end-to-end anywhere in code comments or logs.

**Verify**: `python3.14 -m unittest discover -s tests -t .` → `OK`

### Step 4: Route install/uninstall config through adapters + full gate

In `packaging/install.py`, replace the inline Codex `config.toml`
block construction with `ADAPTERS['codex'].install_config(home,
state)` (same bytes out), and add `ADAPTERS['kiro'].install_config`
behind the existing install flow so both owned blocks are written with
per-adapter receipts. In `tools/disable.py` and
`tools/global_instructions.py`, route removal through the owning
adapter's `remove_config`. Extend the activation receipt to record one
`inserted_block` per adapter instead of a single Codex block.

Add `tests/test_client_adapter.py`:

- Unknown client name raises `ValueError` from `visible_for` (existing
  fail-closed behavior preserved).
- Codex and Claude catalogue merges are byte-identical to pre-plan
  output (golden assertions on one row each).
- Kiro adapter: every OpenRouter registry row is visible; unknown slugs
  pass through `resolve` untouched; `ingress_paths` contains no native
  or Claude paths.
- Disable-removes-what-install-wrote round trip for both Codex and
  Kiro blocks with fakes (no real home directory).

**Verify**: full trio — suite `OK`, compileall exit 0, limits `failures=0`

## Test plan

- New `tests/test_client_adapter.py` (5+ cases above), modeled on
  `tests/test_claude_ingress.py` + `tests/test_catalogue.py`.
- Existing Claude/Codex/catalogue/mixed-router tests green unmodified
  in intent.
- No network, no real client apps, no real home directory in tests.

## Maintenance note

The fourth client is a new `clients/<name>.py` implementing the seven
interface members plus one registry line — no router, catalogue CLI, or
installer edits. Reviewers: reject any client-specific `if` in
`router.py`, `catalogue.py`, or `install.py`; it belongs in the adapter.

## STOP conditions

- If the drift check shows in-scope files changed since `6840312`, stop and reconcile.
- If any existing client's catalogue bytes, ingress routing, or error
  text changes (golden tests fail), stop and report: this plan is a seam
  change, not a behavior change.
- If the Kiro adapter requires inventing a wire detail the repo cannot
  evidence (a guessed endpoint, header, or schema), stop and leave that
  method raising `NotImplementedError` with the missing evidence named —
  do not guess protocols.
- If the suite drops below its incoming pass count, stop and report.

## Done criteria

- [ ] `ClientAdapter` interface exists with all seven members documented
- [ ] Codex + Claude behind the interface with byte-identical behavior
- [ ] Kiro adapter implements the interface (Preview-marked, no invented wire details)
- [ ] Install/uninstall route config through owning adapters
- [ ] `python3.14 -m unittest discover -s tests -t .` → `OK`
- [ ] `python3.14 tools/check_source_limits.py` → `failures=0`
- [ ] Status row for this plan updated in `plans/README.md`
