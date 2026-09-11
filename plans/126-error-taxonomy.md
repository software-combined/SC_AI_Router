# Plan 126: Make error classification explicit and delete the dead CLI/tool error half

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat b642de9..HEAD -- ai_router/errors.py ai_router/providers.py ai_router/claude.py ai_router/router.py tests/test_handler.py tests/test_claude_ingress.py`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P2; effort S-M; risk LOW-MED; confidence HIGH; category tech-debt; depends on 101
  (run after it, so both deletions land in a known baseline).
- Planned at `b642de9`, 2026-09-11.
- First proof: subscription/unknown-model classification is by exception type, not message text,
  and every error constructor in `errors.py` has a caller.

## Why this matters

- `ai_router/providers.py:385` raises a bare `ValueError` with the message
  "Model is not available without a ChatGPT subscription"; `claude.py:155-156` raises the Claude
  twin; `errors.py:283-292` re-derives the response code by substring-matching that text
  (`'without a ChatGPT subscription' in text`, `'unknown model:' in lowered`). Rewording one message
  silently reclassifies the client response, and the catalog message at `errors.py:194-202` can
  drift from the raise site without a test noticing.
- `errors.py:3-7` promises "CLI and tool exits print CODE: message", but `fail()` (`:54-56`) and the
  code block at `:62-127` have zero callers repo-wide; meanwhile `packaging/install.py` and
  `tools/*` raise raw `SystemExit`. The documented contract is unrealized, and a future editor
  trusts a taxonomy that never runs.
- Plan 101 deletes four unrelated dead symbols and adds an F401/F811 gate; it explicitly excludes
  unused non-import names, so this cleanup needs its own owner.

## Current state (verified at b642de9)

- Substring classification: `errors.py:283-292`; raise sites `providers.py:385`,
  `claude.py:155-156`; catalog messages `errors.py:194-202`, `:239`.
- `errors.py:54` `fail()`; dead block `:62-127`; module docstring `:3-7`.
- Router catches broad `(ValueError, ...)` at `router.py:244-246`; `map_client_error` converts to
  `RouterError`.

## Scope

**In scope**: `ai_router/errors.py`, `ai_router/providers.py`, `ai_router/claude.py`,
`ai_router/router.py` (import/catch only if needed), focused tests.
**Out of scope**: introducing coded errors into `packaging/`/`tools/` (deferred; note it in
maintenance), changing any response body or status, restructuring other error constructors.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_handler tests.test_claude_ingress tests.test_providers tests.test_router_response` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; errors.py baseline updated if its count changes |

## Steps

1. **Typed failures (commit 1).** Add `SubscriptionRequired` and `ClaudeSubscriptionRequired`
   subclasses (of `ValueError`, so existing broad catches keep working) with the exact current
   messages. Raise them at `providers.py:385` and `claude.py:155-156`. In `map_client_error`,
   classify by `isinstance` and delete the substring branches for these two cases; keep the
   `'not in the configured catalog'`/`unknown model:` handling unless it is also convertible
   (convert if cheap, preserve every existing response).
2. **Dead half (commit 2).** Run `rg -n 'errors\.fail|from .errors import .*fail'` and
   `rg -n '<name>'` for every symbol in `errors.py:54-127`; delete only symbols with zero callers
   (including tests) and correct the module docstring lines 3-7 to match reality. If a symbol is
   used by a test as a contract, keep it and note why.
3. **Tests (same commits).** Add a classification test: raising the typed error from a provider
   select path yields the same status/code as today; a reworded message no longer changes the
   classification. Keep every existing response-body assertion green.

**Verify**: focused tests; `rg -n "without a ChatGPT subscription' in" ai_router/errors.py` → no matches (the catalog/unknown-model branch may remain as-is); `rg -c 'def ' ai_router/errors.py` sanity.

## Done criteria

- [ ] Subscription classification is type-based; no substring branch remains for it.
- [ ] Every constructor/helper left in `errors.py` has a caller; docstring matches reality.
- [ ] Response bodies/statuses unchanged (existing tests untouched).
- [ ] Full suite, compile and limit gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- A supposedly dead code is referenced dynamically (string lookup, docs, external tool): keep it,
  add a caller test or a comment, and report.
- Making the new exception type non-`ValueError` would change a catch path: do not; keep the base
  class and stop if a test requires otherwise.

## Maintenance notes

- New provider failure classifications must raise typed errors from `errors.py`; substring matching
  is gone for the converted cases.
- Installer/tool coded errors remain an open decision (owner: plan 134 if it chooses); the docstring
  now states what is true.
- Reviewers: scan for any remaining message-text classification.
