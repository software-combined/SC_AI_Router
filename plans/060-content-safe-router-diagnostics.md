# Plan 060: Keep request and upstream content out of router diagnostics

> Planning only. Execute only when implementation is authorised. Follow the
> steps and stop conditions; update this plan's row in `plans/README.md` with
> the actual source/integration/runtime gate reached.
>
> Drift check: `git diff --stat 6840312..HEAD -- codex_router/router.py codex_router/providers.py codex_router/errors.py codex_router/runtime.py tests/test_providers.py tests/test_router_response.py tests/test_safe_diagnostics.py config/source-limits-baseline.json CHANGELOG.md packaging/VERSION plans/README.md`
> Compare changed code with the excerpts before proceeding. Rebase the plan if
> another fix has already closed this defect.

## Status and outcome

- Priority P1; effort S; risk LOW; confidence HIGH; category security/correctness.
- Planned at `6840312`, 2026-09-09. Depends on no other plan.
- First proof: a fake upstream error containing a synthetic private-text marker
  produces a useful client failure, but no marker appears in captured log
  records. No paid request is needed.

## Current state

`codex_router/providers.py:31-67` parses `metadata.raw` or `error.message`, then
returns a substring of arbitrary upstream prose:

```python
reason = text.strip()
if len(reason) > 300:
    reason = reason[:297] + '...'
return provider, reason, tool
```

`describe_failure` includes it in its message (`providers.py:85-92`).
`Handler.relay` passes the message to `Handler.error` (`router.py:255-268`):

```python
log_event('request_rejected', status=err.status, code=err.code,
          reason=err.message, path=suffix.split('?')[0][:200])
```

The parent reproduced this with a synthetic `error.message`, mocked `log_event`
and an unbound Handler instance. The marker reached the `reason` field. No real
credentials or user data were used. Traceback formatting at `router.py:208,299`
can also include exception text; apply the same content boundary there.

The repository explicitly forbids logging request/tool content. Existing
`RouterError(status, code, message)` in `errors.py:12-23` and metadata-only
`upstream_rejected` at `router.py:265` are the conventions to build on. Preserve
stable error codes, requested-model context and actionable known remedies.

## Scope

Only: `codex_router/{router,providers,errors,runtime}.py`,
`tests/test_providers.py`, `tests/test_router_response.py`, new
`tests/test_safe_diagnostics.py`, `config/source-limits-baseline.json`,
`CHANGELOG.md`, `packaging/VERSION`, and this plan/index status.

Out: protocol extraction, credentials/state changes, existing log deletion,
feed/signature behavior, live service mutation, and a general logging framework.
Do not collect historical logs to prove an exposure; the synthetic repro is
sufficient. No claim that real secrets were exposed has been established.

## Commands

Run from the owned worktree. Baseline was Python 3.14.4, 473 tests passing.

| Purpose | Command | Expected |
|---|---|---|
| Existing behavior | `python3.14 -m unittest tests.test_providers tests.test_router_response` | Pass before edits |
| Regression | `python3.14 -m unittest tests.test_safe_diagnostics` | Fails on the original content-bearing log; passes after fix |
| Full tests | `python3.14 -m unittest discover -s tests -t .` | Exit 0 |
| Compile | `python3.14 -m compileall -q codex_router tools tests packaging` | Exit 0 |
| Size gate | `python3.14 tools/check_source_limits.py` | Zero failures |
| Diff gate | `git diff --check` | Exit 0 |

## Steps

### 1. Capture the content boundary regression

Create `tests/test_safe_diagnostics.py`. Follow the fake upstream and local
handler pattern in `tests/test_router_response.py`, mocking only the upstream
and log sink. Include generic upstream `error.message`, nested `metadata.raw`,
and a caught transport exception with a synthetic marker in its text. Assert
that no captured log argument/record contains the marker, and assert the
expected HTTP code and stable router error code. Keep the test finite and close
the local server and socket.

**Verify:** the new regression command fails on the current implementation for
the reason field, while the existing behavior command passes. Record the failing
assertion without printing any real payload.

### 2. Separate diagnostics from arbitrary text

Remove `err.message` from structured rejection logs. Log the stable code,
status, known route and already-safe timing/identity metadata. Avoid introducing
another free-text `detail` field that reproduces the same defect.

For exception diagnostics, use exception class and stack locations without
formatted exception text or locals. Keep logs useful for finding the code path.

At the upstream parser, arbitrary prose is not a safe structural reason. Keep
known diagnostic categories and remedies using fixed wording. Include upstream
provider identity or an offending tool only after validating it against a
bounded known identity/structural rule; otherwise use the generic category.
Do not treat truncation or a token-shaped regex as privacy protection. Unknown
errors still report upstream status and requested model, with a safe fallback.

This deliberately tightens the existing error-message safety rule in
`errors.py:3-6`; preserve HTTP status/retry semantics. Any test expecting arbitrary
upstream prose must be replaced by the same actionable category plus the new
no-content assertion, with that behavior change explained in the changelog.

**Verify:** focused commands above pass; a deliberate local reintroduction of
`reason=err.message` makes the regression fail. Remove that deliberate mutation
before proceeding. Do not mutate the primary checkout to perform this check.

### 3. Complete source and review gates

Run full tests, compilation, source limits and diff check. Update changelog and
semver for the user-visible diagnostic change; do not update the size baseline
to conceal a larger design. Run the current installed pre-commit-review process
and exact reviewer-model policy before committing. Integrate into `develop`
only under the implementation task's authority; do not push to `main` or deploy.

**Verify:** integrated source repeats the focused regression and full required
checks. Report live runtime validation separately if later authorised.

## Done criteria

- [ ] Synthetic upstream and exception canaries cannot reach structured logs.
- [ ] Unknown upstream prose cannot be reflected by the descriptive error path.
- [ ] Existing retry status, credential separation and streaming tests pass.
- [ ] All verification commands pass; diff contains only scoped files.
- [ ] Review, commit, target integration and worktree disposition are recorded.
- [ ] Live installation/paid acceptance is not marked complete from source tests.

## STOP conditions and maintenance

Stop if the proposed fix needs production log access, changes authentication or
retry behavior, requires out-of-scope edits, or fails the same verification
twice after a reasonable repair. If extraction already moved the code, refresh
paths first. Future diagnostic fields must be reviewed as a data boundary:
provider-supplied prose and exception text are content, even when short.

Git: one owned `codex/` worktree from `develop`, conventional `fix:` subject,
current pre-commit-review and hooks, PR/integration target `develop`, then verify
and clean up according to repository ownership rules. Never bypass hooks.
