# Plan 155: The client contract - one owner for who sees what

> **Executor instructions**: Follow this plan step by step. If a STOP condition
> occurs, stop and report. When done, update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 0024a42..HEAD -- ai_router/clients/__init__.py ai_router/clients/codex.py ai_router/claude.py ai_router/catalogue.py ai_router/protocols/__init__.py packaging/install.py packaging/codex_config.py packaging/claude_config.py packaging/claude_desktop_config.py docs/architecture.md tests/test_client_activation.py tests/test_claude_ingress.py tests/test_model_projections.py tests/test_protocol_contracts.py config/source-limits-baseline.json`
> Land plans 153 and 154 first: both edit `ai_router/catalogue.py`. Plan 148
> owns the Claude published-catalog snapshot and drift check; this plan does
> not implement it. Reconcile every cited line before editing.

## Status and first proof

- Priority P2; effort M; risk MED; confidence HIGH; category architecture/clients.
- Depends on plans 153 and 154 (catalogue file). Coordinates with plans 113,
  120, 121 and 148, which own the Claude live surfaces.
- Source: `plans/2026-09-12-architecture-scalability-review.md`, rows
  "Client visibility has two owners that disagree" and "The client set is an
  enum repeated in four places".
- First proof: one table lists every supported client with its protocol,
  visibility policy and activation adapter; both Claude projections read that
  table; a test states the current difference between the picker projection and
  the Messages discovery listing as a deliberate, documented fact; and
  `docs/architecture.md` carries a client contract a reader can follow.

## Why this matters

Two functions answer "what does Claude Code see" and they disagree.
`clients.visible_for` (`ai_router/clients/__init__.py:11-29`) hides externally
billed Anthropic rows from the `claude` client.
`claude.models_listing` (`ai_router/claude.py:65-79`) never calls it and lists
those same rows under bare ids, because `claude_alias`
(`:28-37`) treats an `anthropic/` slug as already passing the client filter.
Measured at `0024a42`: `GET /v1/models` returns 19 rows including
`anthropic/claude-fable-5.1`, `anthropic/claude-haiku-4.5`,
`anthropic/claude-opus-5` and `anthropic/claude-sonnet-5`, while
`models_for(MODELS, 'claude')` returns 15 and none of those four.

Either answer can be defended. What cannot be defended is that no single place
records which is intended, and no test would notice if one of them changed.

The second half is cost of entry. The supported client set is an enum in four
places: `ai_router/clients/__init__.py:22`, `ai_router/catalogue.py:371`,
`packaging/install.py:207` and `:577-580`. `docs/architecture.md` rule 5 says
"A client is not a provider and an OS is neither. New clients reuse a proven
wire protocol", which is the right rule but not a contract. A reader who wants
to attach Cursor, OpenCode, Cline, a Gemini CLI or a plain
`/v1/chat/completions` client has no way to learn what that costs without
reading four modules. The good news, which this plan should make visible, is
that the protocol layer is already separable: `ai_router/protocols/__init__.py`
dispatches on method and path only, and activation lives entirely in
`packaging/codex_config.py`, `packaging/claude_config.py` and
`packaging/claude_desktop_config.py`, none of which the request path imports.

## Scope

**In scope**: the files named in the drift check, plus new tests.
**Out of scope**: attaching any new client (no demand is recorded and the
2026-09-12 external review rejected the named candidates), plan 148's published
snapshot and drift check, any change to installer options a recipient already
uses, and any change to which models route.

## Steps

1. **Add the client table.** Create `ai_router/clients/registry.py` holding one
   `ClientDef` per supported client: `id`, `label`, `protocol` (the
   `provider_defs.RESPONSES` or `MESSAGES` constant), `picker_visible`
   (the predicate `visible_for` applies today) and `discovery_visible` (the
   predicate the live listing applies today). Two rows: `codex` and `claude`.
   The module imports `provider_defs` only, so it is a leaf beside
   `provider_defs` in the dependency map.

2. **Make both projections read the table.** `clients.visible_for`
   (`ai_router/clients/__init__.py:11-29`) resolves its client through the
   table instead of the hard-coded tuple at `:22`, keeping the same
   fail-closed `ValueError` for an unknown client.
   `claude.models_listing` (`ai_router/claude.py:65-79`) gains an explicit call
   to the table's `discovery_visible` predicate for the `claude` row. Set that
   predicate to reproduce today's behaviour exactly, so this step changes no
   output.

3. **State the difference as a test, not an accident.** Add to
   `tests/test_model_projections.py` a test that names both surfaces, asserts
   the current counts (19 discovery rows, 15 picker rows) derived from the
   registry rather than hard-coded, and carries a comment saying why they
   differ: the Codex catalogue hides externally billed Anthropic rows from the
   Claude picker, while the Messages discovery listing exposes them so a Claude
   Code user can choose an externally billed Claude model. If the executor
   cannot state a defensible reason from the code and the plans, that is a STOP
   condition, not a guess.

4. **Derive the installer's client options.** `packaging/install.py` must keep
   accepting exactly the option values it accepts today, but derive the choice
   lists from the table rather than repeating them. The installer is Python
   3.9-safe and spec-loads router modules through `service.load`
   (`packaging/service.py:40`), which is the pattern to reuse; do not import
   the `ai_router` package from the installer. `--client` keeps its
   `('codex', 'none')` values and `--clients` keeps
   `('codex', 'claude', 'both')`, because those are a user-facing contract:
   the derivation must produce the same strings, proven by a test.

5. **Derive the catalogue CLI's client option.** `ai_router/catalogue.py:371`
   validates `--client` against a literal tuple; read the table instead.

6. **Write the contract down.** Add a "Client contract" section to
   `docs/architecture.md` listing exactly what a new client needs: a row in
   `ai_router/clients/registry.py`; a protocol the router already serves
   (`/responses` or `/v1/messages`), or a STOP if it needs a third; a
   capability projection module under `ai_router/clients/` if its catalogue
   shape differs from Codex's; an activation adapter under `packaging/` that
   owns its config file, its owned keys, its conflict refusal and its detach
   path, following `packaging/claude_config.py` as the smaller of the two
   examples; a receipt entry through the shared receipt writer; and an entry in
   `docs/compatibility.md` recording the client version that was verified. Name
   the one thing that is genuinely hard: a client that speaks neither protocol
   needs a new adapter class, never a branch in the request path
   (`AGENTS.md` section 3).

7. **Add the contract test.** Add `tests/test_client_contract.py` asserting
   that every row in the client table has a protocol the router serves, that
   every protocol in `ai_router/protocols/__init__.py:17-26` is claimed by at
   least one client row, that both projections resolve for every row, and that
   an unknown client id fails closed in all three consumers. Include a
   synthetic third row in a temp fixture, as
   `tests/test_domain_boundaries.py:84-102` does, so the test is proven not to
   pass vacuously.

## Verification

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_client_contract tests.test_model_projections tests.test_claude_ingress tests.test_catalogue tests.test_client_activation tests.test_install_config tests.test_protocol_contracts` | pass |
| Installer options unchanged | `python3.14 packaging/install.py --help` | `--client {codex,none}` and `--clients {codex,claude,both}` exactly as today |
| Catalogue | `python3.14 -m ai_router.catalogue --merge ./ci-catalogue.json && python3.14 -m ai_router.catalogue --check ./ci-catalogue.json` | exit 0 |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Policy scans | `python3.14 tools/check_policy_scans.py` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | `failures=0` |

## STOP conditions

- The two projections cannot be reconciled with a defensible reason drawn from
  the code and the existing plans: stop and report both behaviours with their
  line references. Unifying them silently would change what a Claude Code user
  can select, and that is an owner decision.
- Deriving the installer options would change any accepted option string: stop.
  Recipients' scripts and the plugin manifests depend on them.
- The installer would have to import the `ai_router` package: stop. The
  installer runs on Python 3.9 and must keep using `service.load`.

## Acceptance checklist

- [ ] One client table exists and is a leaf importing only `provider_defs`.
- [ ] Both Claude projections read it; output is byte-identical to today.
- [ ] A test states the picker versus discovery difference with its reason.
- [ ] `install.py` and `catalogue.py` derive their client options from the
      table and accept exactly the same strings.
- [ ] `docs/architecture.md` carries a client contract a newcomer can follow.
- [ ] `tests/test_client_contract.py` exists and is proven non-vacuous.
- [ ] Full suite, compile and limits pass; `plans/README.md` row updated.

## Maintenance notes

- This plan deliberately attaches no new client. It makes the next attachment a
  bounded decision instead of an investigation.
- Plans 113, 120, 121 and 148 own the live Claude surfaces. If any of them lands
  first, rebase here rather than duplicating their work.
