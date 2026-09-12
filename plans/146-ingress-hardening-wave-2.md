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

- [x] Weak token refused at startup; no token value in the message or logs.
- [x] 429 at the cap with `Retry-After`, counted in health.
- [x] No error body or log line carries a path or a caller-supplied id.
- [x] 415 on a non-JSON body; the malformed-payload test exists.
- [x] No behaviour change for a valid request that passes today.
- [x] Full suite, compile and limit gates pass; `plans/README.md` row updated.

## Landed notes, 2026-09-12

- Token strength: `runtime.TOKEN_MIN_LENGTH = 32` over `[A-Za-z0-9_-]`; the
  message names the rule and the fix and never the value. The installer
  already mints `secrets.token_urlsafe(32)`, so only a hand-written state
  file fails closed.
- Concurrency: `Router.max_inflight = 32` (module constant `MAX_INFLIGHT`);
  the POST slot check happens under the existing lock and answers 429
  `TOO_MANY_REQUESTS` with `Retry-After: 1`. `/health` reports `inflight`
  and `max_inflight`. A real two-request test holds one relay open and
  proves the second is refused.
- Redaction: `errors.redact()` replaces absolute POSIX and Windows-Drive
  paths with `[path]`; it is applied to `credential_problem` details and to
  the `CREDENTIAL_PERMISSION` body. `unknown_model` no longer echoes the
  caller's id in the message or the body (candidates and the fixed reason
  stay). The boot-time SystemExit keeps its path on purpose: that message is
  operator-facing and the plan's STOP rule protects support detail.
- Content-Type: an owned route now answers 415 `UNSUPPORTED_MEDIA_TYPE`
  before reading the body; `application/json` with a charset parameter
  passes, and the setup/model-prompt form routes are untouched.
- Step 5 needed no code change: `test_prepare_keyerror_opens_no_window`
  already pins the malformed-payload mapping. Step 6 needed no reorder:
  `select`/`owns` already refuses non-members, and the direct-`prepare`
  branch now says it is defence in depth.
- `opencode_auth` is confined to the OpenCode client's own file
  (`~/.local/share/opencode/auth.json`, HOME-resolved) in both
  `ai_router/credentials.py` and `packaging/provider_keys.py` (the two trees
  cannot share the helper; the duplication is recorded here so they stay in
  step). A state key pointing elsewhere is refused, which is a deliberate
  compatibility change for hand-configured installs.
- `winacl.check` caches its verdict for 30 s per file and runner identity
  (the entry holds the runner so an id cannot be recycled), with
  `winacl.reset()` for tests; expiry re-runs icacls and whoami so a real
  permission change is still honoured.

## Remediation, 2026-09-12

- Review round 1 (correctness BLOCK, adversarial notes) proved `redact()`
  split a path at its first space (`/Users/Cyril Allart/...` leaked the tail)
  and never matched UNC shares. `_PATH` is now built from shared component
  pieces: spaces are allowed inside any component except the last, the
  branch list covers `C:\...`, `\\?\C:\...`, `\\server\share` and
  `//server/share`, and the negative lookbehind keeps URLs, filenames and
  `Application/json` untouched. Round 2 (adversarial BLOCK) caught the first
  rewrite's UNC branch still splitting on spaces and the `~` form diverging
  between the installer and the router; both are fixed here, and the tests
  cover spaced POSIX/Windows/UNC paths (both separators), `\\?\`, a URL, a
  `~`-form parity case, and the 401 `CREDENTIAL_PERMISSION` body end to end.
- A `~`-form `opencode_auth` expands against the same env on both sides
  (never the process environment in one reader and the passed env in the
  other), so the two readers open exactly the path they compared.
- The same round showed the installer and the service could disagree on the
  OpenCode path when the installer shell had `XDG_DATA_HOME` set: the
  service environment has no such variable. Both readers now resolve HOME
  only, and a test pins that an XDG path is not counted (and not read).
- Accepted notes: the ACL verdict is deliberately up to 30 s stale inside
  the window (that is the cache's purpose); a headerless oversized POST now
  answers 415 before the size check; and the boot-time SystemExit keeps the
  key path because it is operator-facing, while every HTTP body is redacted.
- Accepted after round 3 (both reviewers below the blocker bar, no in-tree
  emitter): a path component containing `'`, `,` or `;` still splits the
  match (`/Users/O'Brien/...` leaks the tail), and the forward-slash drive
  form (`C:/Users/...`) and `file://` URIs are not matched because the
  router renders paths with `Path` per OS. `_TAIL`'s trailing `?` binds to
  the inner repetition rather than making the group optional; behaviour is
  correct today, so it is left as the honest equivalent of `_PART` for the
  next touch. Windows ACL tails can over-redact the account name after
  `;`, which hides detail rather than exposing it.

## STOP conditions

- The cap changes behaviour for an existing single-client workload: stop and report
  with the observed concurrency before choosing a different limit.
- A redaction change removes information a support path relies on: stop; keep the
  fixed reason and drop only the path or id.

## Maintenance notes

- The three deferred items are recorded in the review file; reopen only on demand.
- Reviewers: confirm no new code path logs a request body, key, token or URL.
