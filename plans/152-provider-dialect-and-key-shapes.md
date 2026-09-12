# Plan 152: Provider abstraction wave 2 - dialects, key shapes and prose

> **Executor instructions**: Follow this plan step by step. If a STOP condition
> occurs, stop and report. When done, update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 0024a42..HEAD -- ai_router/provider_defs.py ai_router/relay.py ai_router/upstream.py ai_router/key_store.py ai_router/errors.py ai_router/credentials.py .gitignore tests/test_provider_defs.py tests/test_provider_swap.py tests/test_upstream_failures.py tests/test_handler.py config/source-limits-baseline.json`
> Reconcile every cited line before editing. Plan 153 extends the same
> definition table: land 152 first, then rebase 153 on it.

## Status and first proof

- Priority P1; effort M; risk MED; confidence HIGH; category architecture/provider.
- Depends on plan 141 (landed). No owner gate: everything here is offline.
- Source: `plans/2026-09-12-architecture-scalability-review.md`, rows
  "The relay compares the dialect as a literal string", "The failure describer
  parses OpenRouter's metadata envelope", "The key-info check assumes
  OpenRouter's `{"data": {...}}` body", and "Only one provider key file is
  ignored by git".
- First proof: a synthetic external provider declared with
  `dialect='openai_compatible'` and a plain
  `{"error": {"message": ..., "code": ...}}` failure body gets a described
  409 or 502, a context-window SSE frame, and the key window on a 401, all
  without any module naming that provider or that dialect.

## Why this matters

Plan 141 moved every upstream fact into `ai_router/provider_defs.py`, and the
transport half genuinely follows the table. Three decisions did not move.
`ai_router/relay.py:53` and `:57` compare `provider.defn.dialect` to the
literal `'openrouter'`, so a provider with any other dialect silently loses
the context-window frame and the key-rejected window. `ai_router/upstream.py`
lines 99-128 parse OpenRouter's `error.metadata.provider_name` and
`error.metadata.raw` envelope; a plain OpenAI-compatible error body yields
`None`, `describe_failure` gives up, and the raw upstream body is relayed to
the client with no bounded code and no fixed reason.
`ai_router/key_store.py:44-50` assumes OpenRouter's `{"data": {...}}` key-info
body, so a provider whose key endpoint answers differently reports a live key
as rejected. The result is that `tests/test_provider_swap.py:38-40` has to
declare its fixture provider with `dialect='openrouter'` and
`catalogue_shape='openrouter'` to pass, which means the acceptance proof for
"a second provider is one table entry" never exercises a genuinely foreign
provider.

## Scope

**In scope**: the files named in the drift check, plus new tests.
**Out of scope**: model identity and slug namespacing (plan 153), the live
catalogue projection shape (plan 154 records the ceiling; a second live shape
stays unbuilt until a real provider needs it), any real second provider or
billed probe, and any change to routing, credentials precedence or the
loopback trust boundary.

## Steps

1. **Name the failure dialects in the table.** In
   `ai_router/provider_defs.py`, add the module constants
   `DIALECT_OPENROUTER = 'openrouter'`, `DIALECT_OPENAI = 'openai'`,
   `DIALECT_ANTHROPIC = 'anthropic'` and `DIALECT_OPENAI_COMPATIBLE =
   'openai_compatible'`, and use them in the three built-in definitions. Add a
   `ProviderDef` validation that `dialect` is one of the known set, with the
   same fail-closed `ValueError` shape as the existing checks at `:57-64`.
   Extend `tests/test_provider_defs.py::DefinitionTests` with a case that an
   unknown dialect is refused.

2. **Move the relay's dialect decisions onto the definition.** Add three
   boolean capability methods to `ProviderDef`:
   `sends_context_error_frame()`, `opens_key_window_on_auth_failure()` and
   `caches_deterministic_refusals()`. Each returns True for the external
   dialects (`openrouter` and `openai_compatible`) and False for the
   subscription dialects. Replace `ai_router/relay.py:20-23` (the
   `prepared.provider == provider_defs.OPENROUTER.id` compare) with
   `provider.defn.caches_deterministic_refusals()`, and
   `ai_router/relay.py:53` and `:57` with the two other methods. The protocol
   gate (`metrics.get('protocol') == provider_defs.RESPONSES`) stays exactly as
   it is: it is a protocol fact, not a provider fact.

3. **Make the failure parser dialect-driven.** In `ai_router/upstream.py`,
   split `_provider_reason` into a shared tail (tool extraction, fixed reason
   selection, `_error_code`) and two envelope readers: the existing OpenRouter
   metadata reader, and a plain reader that takes `error.message` and
   `error.code` directly from an OpenAI-compatible body. Select the reader from
   the dialect, which `describe_failure` must now receive through `info`
   (`ai_router/relay.py:67-72` already builds that dict, so add
   `'dialect': provider.defn.dialect`). Unknown dialects keep today's behaviour
   of returning `None`. Nothing else in the module changes: no raw body, no
   schema text and no upstream prose may leave, and the `_CODE_SHAPE` guard at
   `:65` still bounds every code.

4. **Make the key-info check shape-driven.** Add `key_info_shape` to
   `ProviderDef` (default `'openrouter'`, also accepting `'none'` and
   `'plain'`). In `ai_router/key_store.py`, replace the direct
   `payload.get('data')` read at `:47-50` with a small projector table: the
   `openrouter` shape keeps today's `(label, limit, usage)` extraction, `plain`
   treats any 2xx as a live key and returns `(label, None, None)`, and `none`
   is the existing no-endpoint path at `:38-39`. A shape that does not match
   its declared projector still raises `KeyRejected`, so nothing gets looser.

5. **Stop naming one provider in client-facing prose.** In
   `ai_router/errors.py`, replace the two `'use an OpenRouter model'` fragments
   at `:59` and `:127` with wording that names no provider, for example
   `'select a routed model instead'`. Update the assertions in
   `tests/test_handler.py` and `tests/test_claude_ingress.py` that pin those
   strings. Do not touch the catalogue instruction text here; plan 154 owns it.

6. **Ignore every provider key file.** `.gitignore:14` ignores `openrouter.key`
   only. Replace that line with `*.key` and add a test in
   `tests/test_policy_scans.py` that every `provider_defs.external_defs()`
   key file name is matched by a `.gitignore` pattern, so a future provider
   cannot be added with an unignored key file.

7. **Retarget the acceptance proof at a foreign provider.** In
   `tests/test_provider_swap.py`, change the `_acme_def()` fixture at `:31-40`
   to declare `dialect=provider_defs.DIALECT_OPENAI_COMPATIBLE`,
   `catalogue_shape='manual'`, `key_info_shape='plain'` and no
   `catalogue_url`. Keep every existing assertion passing. Add new cases:
   a plain `{"error": {"message": "bad tool", "code": "invalid_request"}}`
   body produces a described 409 carrying the code; a 401 opens the key window
   through `caches_deterministic_refusals`/`opens_key_window_on_auth_failure`
   rather than a name compare; and `models add --provider acme` refuses with
   the `manual` shape message from `ai_router/models.py:46-48`.

8. **Re-sync the source-limits baseline.** `ai_router/upstream.py` is 253
   lines and its soft cap is 250, so its baseline entry already exists in
   `config/source-limits-baseline.json`. Update the recorded count after the
   split, and if the module crosses 400 move the two envelope readers into a
   new `ai_router/dialects.py` leaf rather than raising the cap. That leaf may
   import `provider_defs` only.

## Verification

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_provider_defs tests.test_provider_swap tests.test_upstream_failures tests.test_handler tests.test_claude_ingress tests.test_policy_scans` | pass |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0, 1217 or more tests |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Lint | `python3.14 -m ruff check --select F401,F811 ai_router packaging tools tests` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | `failures=0`, baseline re-synced |
| Policy scans | `python3.14 tools/check_policy_scans.py` | exit 0 |

## STOP conditions

- Making the failure parser dialect-driven would change the message any
  existing OpenRouter turn receives: stop and report the differing message.
  This plan is behaviour-preserving for the built-in providers.
- `ai_router/upstream.py` cannot stay under 400 lines even after the leaf
  extraction: stop and report the line count rather than raising the cap.
- A dialect method would need to read a request or response body to decide:
  stop. The definition table must decide from the definition alone.

## Acceptance checklist

- [ ] `ai_router/relay.py` contains no provider id or dialect string literal.
- [ ] `ai_router/upstream.py` describes a plain OpenAI-compatible error body
      with a bounded code and a fixed reason, and still leaks no upstream prose.
- [ ] `ai_router/key_store.py` validates a key against a declared shape, and an
      endpointless provider still stores and fails closed on first use.
- [ ] No client-facing error message names a provider.
- [ ] `.gitignore` covers every external provider's key file, with a test.
- [ ] `tests/test_provider_swap.py` proves the second provider with its own
      dialect and shape, not by borrowing OpenRouter's.
- [ ] Full suite, compile, lint, limits and policy scans pass;
      `plans/README.md` row updated.

## Maintenance notes

- The one-line rule in `AGENTS.md` section 3 stays true and gets stronger: an
  upstream is one entry in `provider_defs.py`, and after this plan the failure
  dialect is part of that entry rather than a compare somewhere else.
- Reviewers: confirm no new code path logs a request body, key, token or URL,
  and that the plain envelope reader cannot emit upstream prose.
