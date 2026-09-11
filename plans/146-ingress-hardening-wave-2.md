# Plan 146: Ingress hardening, second wave

> **Executor instructions**: Follow this plan step by step. If a STOP condition
> occurs, stop and report. When done, update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 3515c6a..HEAD -- ai_router/ingress.py ai_router/router.py ai_router/relay.py ai_router/providers.py ai_router/errors.py ai_router/credentials.py ai_router/winacl.py ai_router/runtime.py tests/ config/source-limits-baseline.json`
> Plan 137 (Host header) shares this file: land 137 first, then rebase here and
> re-sync the baseline entry. Reconcile every cited line before editing.

## Status and first proof

- Priority P2; effort M; risk MED; confidence HIGH; category security.
- Depends on 137 (serialized on the ingress file). Also serialized with 135: both
  edit `ai_router/router.py`.
- Source: `plans/2026-09-12-external-router-review.md`, the findings row
  "Ingress hardening" and the "Their weaknesses we must not copy" section.
- First proof: a weak install token is refused at startup, the 33rd concurrent
  request answers 429 with `Retry-After`, and no error response or log line
  carries a filesystem path or a caller-supplied model id.

## Why this matters

The external router hardened eight things we do not; each is small and
offline-testable, and together they close the gap between "loopback only" and
"loopback only and bounded".

## Scope

**In scope**: the files in the drift check plus new tests.
**Out of scope (deferred, recorded)**: a chunked/streaming request-body reader,
a subscription-sharing consent marker, and caller-token rotation. Do not
implement them here; they are separate owner decisions.

## Steps

1. **Token strength at load.** `runtime.py` validates the install token as at
   least 32 characters of `[A-Za-z0-9_-]` and refuses to start with a precise
   message. A legacy short token fails closed and the message names the fix
   (reinstall to mint a new token), never the token itself.
2. **Concurrency cap.** Count in-flight requests where the drain counter already
   lives; above 32, answer 429 with `Retry-After` and a distinct error code, and
   report `inflight` and the cap in `/health`.
3. **One redactor.** Add a single `redact()` used by error construction and any
   diagnostic that could receive a path or an identifier: strip filesystem paths
   from `credential_problem` details and stop echoing the caller-supplied model id
   in `unknown_model`. Keep the diagnostic useful: the fixed reason and the
   provider label stay.
4. **Content-Type guard.** On JSON routes, a body that is not
   `application/json` answers 415 before parsing, beside the existing Origin
   rejection. Do not narrow any client that currently sends a charset parameter.
5. **Malformed payload versus missing key.** Verify the existing `KeyError`
   branch (`router.py`, the `LookupError` handler) still maps a malformed body to
   400 without opening the key window, and add the missing regression test. Change
   nothing if it already holds.
6. **Membership before rewriting (verify, then defence only).** The external
   `ExternalResponsesProvider.owns()` already returns False for a slug that is not a
   matching registry row (the subscription provider deliberately owns
   client-advertised slugs and is out of scope here), so `prepare` never sees an
   unknown model through `select` and no test can drive one through that layer. Keep
   the reorder as defence in depth if it is behaviour-neutral, correct the comment to
   say so, and do not invent a test for an unreachable path.
7. **Confine `opencode_auth`.** Read the credential only from the one explicit
   path the client owns; a state key pointing elsewhere is refused rather than
   followed.
8. **Windows ACL check with a TTL.** Cache the `icacls`/`whoami` verdict for a
   short interval per file so a key read does not spawn two processes every time;
   the cache expires and re-checks, and a permission change is still honoured.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_ingress_guards tests.test_handler tests.test_credentials tests.test_windows_acl tests.test_safe_diagnostics` | pass |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; baseline re-synced after 137 |

## Done criteria

- [ ] Weak token refused at startup; no token value in the message or logs.
- [ ] 429 at the cap with `Retry-After`, counted in health.
- [ ] No error body or log line carries a path or a caller-supplied id.
- [ ] 415 on a non-JSON body; the malformed-payload test exists.
- [ ] No behaviour change for a valid request that passes today.
- [ ] Full suite, compile and limit gates pass; `plans/README.md` row updated.

## STOP conditions

- The cap changes behaviour for an existing single-client workload: stop and report
  with the observed concurrency before choosing a different limit.
- A redaction change removes information a support path relies on: stop; keep the
  fixed reason and drop only the path or id.

## Maintenance notes

- The three deferred items are recorded in the review file; reopen only on demand.
- Reviewers: confirm no new code path logs a request body, key, token or URL.
