# Plan 138: Drop Cookie on subscription passthrough and make the tests honest

> **Executor instructions**: Follow this plan step by step. If any "STOP
> conditions" item occurs, stop and report. When done, update this plan's status
> row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 08aff1e..HEAD -- ai_router/transport.py ai_router/providers.py ai_router/claude.py tests/test_providers.py tests/test_handler.py tests/test_claude_ingress.py config/source-limits-baseline.json`
> If any in-scope file changed, compare the "Current state" excerpts before
> proceeding; on a mismatch, STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `08aff1e`, 2026-09-11

First proof: a subscription POST that carries `Cookie` arrives at
`chatgpt.com` / `api.anthropic.com` without it, while `Authorization`,
`ChatGPT-Account-ID`, `anthropic-version` and `anthropic-beta` still forward
unchanged, and the OpenRouter path remains key-only.

## Why this matters

`HOP_HEADERS` strips hop-by-hop headers from subscription passthrough, but
`Cookie` is not in the set, so a client-supplied cookie rides along to the
upstream. That is header-smuggling hygiene rather than a live compromise
(`Cookie` handling is post-auth and the upstream ignores foreign cookies), but
the repo already intends to drop it: `tests/test_handler.py:92` asserts `Cookie`
is not forwarded while the request in that test never sends one, so the
assertion is vacuous. This plan makes the intent real on both the code and the
test side. See `plans/2026-09-11-router-external-security-audit.md`, finding 5.

## Current state

- `ai_router/transport.py:10-11`:

```python
HOP_HEADERS = {'host', 'connection', 'content-length', 'transfer-encoding',
               'upgrade', 'keep-alive', 'proxy-authorization', 'proxy-authenticate', 'te', 'trailer'}
```

- `ai_router/providers.py:168` - subscription prepare copies every header not
  in `HOP_HEADERS`; `ai_router/claude.py:132` does the same for Anthropic.
- `ai_router/transport.py:91-100` - `relay_headers` also skips `HOP_HEADERS`
  members plus `set-cookie` and `openai-model`, so response cookies were already
  never maintained; the router keeps no cookie jar.
- Tests today:
  - `tests/test_providers.py:51-58` - subscription exact-dict test whose input
    has no Cookie, so it cannot prove dropping.
  - `tests/test_handler.py:87-94` - the assertion list includes `Cookie` but the
    request sends none.
  - `tests/test_claude_ingress.py:83-99` - subscription test asserts
    `headers.get(...)` values; it never sends a Cookie either.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Focused tests | `python3.14 -m unittest tests.test_providers tests.test_handler tests.test_claude_ingress -v` | all pass |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Source limits | `python3.14 tools/check_source_limits.py` | exit 0 |

## Scope

**In scope**: `ai_router/transport.py`, `tests/test_providers.py`,
`tests/test_handler.py`, `tests/test_claude_ingress.py`.
**Out of scope**: OpenRouter request headers (already key-only), the setup
route, response-header policy, and any change to `set-cookie` handling.

## Git workflow

- One writable worktree per session, branch based on `develop`, integrated back
  to `develop`.
- Commit subject: `fix: drop Cookie on subscription passthrough`.
- Run the shared `pre-commit-review` skill before committing.

## Steps

### Step 1: complete the hop-header set

Add `'cookie',` to `HOP_HEADERS` in `ai_router/transport.py:10-11`. This
single change covers both subscription providers because both filter through
that set; `transport.py` stays far below the 250 soft cap, so no baseline
change is needed.

Note the response-side consequence: an upstream `Cookie` response header
(nonstandard) would now also be skipped by `relay_headers`. That is acceptable
and consistent with the existing `set-cookie` skip.

**Verify**: `python3.14 -m unittest tests.test_providers tests.test_handler tests.test_claude_ingress -v`
-> all pass unchanged.

### Step 2: make the tests exercise Cookie (line-neutral where possible)

- `tests/test_providers.py:54-55` - extend the request headers in
  `test_subscription_prepare_forwards_bearer_and_strips_hop_headers` by adding
  `'Cookie': 'c=1'` to the existing `'Connection': 'keep-alive', ...` line.
  The expected-dict assertion on the next lines stays as-is and now proves the
  drop. Keep the line count unchanged if possible.
- `tests/test_handler.py:86-87` - extend the sent headers on the existing
  `'Connection': 'keep-alive'` line with `, 'Cookie': 'c=1'`; the existing
  `for dropped in (...)` loop already asserts the outcome.
- `tests/test_claude_ingress.py:89-92` - add `'Cookie': 'c=1',` to the
  subscription request headers and add `self.assertNotIn('Cookie', headers)` next
  to the other assertions. That assertion adds one line to a file pinned at 320
  in `config/source-limits-baseline.json`; sync that entry to the new exact
  count (321 if it is the only addition) and rerun the limits gate.

Only touch these three tests; do not restructure them.

**Verify**: focused tests pass. Temporarily removing `'cookie'` from
`HOP_HEADERS` must make at least two of the three updated tests fail - restore
it afterwards.

### Step 3: full gates

Run the full suite, compile and limits commands from the table. Then confirm no
client depends on cookie passthrough:

`rg -n -i "cookie" ai_router packaging tools docs`

**Verify**: the only hits are the `HOP_HEADERS` entry and tests; full suite,
compile and limits exit 0.

## Test plan

- New coverage: subscription request carrying Cookie is forwarded without it
  (providers unit test and handler end-to-end test); Anthropic passthrough
  likewise.
- OpenRouter key-only behaviour stays pinned by
  `tests/test_providers.py:36-51` and `tests/test_handler.py:60-76`.
- Structural pattern: the three existing tests edited in Step 2.

## Done criteria

- [ ] `'cookie'` is in `HOP_HEADERS`; both subscription providers drop it.
- [ ] Every Cookie assertion sends a Cookie, so it can actually fail.
- [ ] Full suite, compile and limits gates exit 0; any baseline count that
      changed is synced.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- Any existing test asserts Cookie passthrough (none today): STOP and reconcile
  before changing the set.
- A subscription path fails after the change in a way attributable to the
  missing Cookie (for example a probe harness regression): STOP and report;
  do not add provider-specific exceptions without evidence.

## Maintenance notes

- New header-hygiene rules belong in `HOP_HEADERS`, not in per-provider copies.
- If a future client genuinely uses cookie auth for subscription traffic, that
  is a product decision with a recorded rationale - reopen this plan.
