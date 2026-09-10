# Router external security audit: what an outsider can do with the loopback port

> Read-only advisory, 2026-09-11. No source was changed by the audit itself.
> Remediation is planned in 136-138, with plan 090 annotated because its
> Step 3 already removes the highest-impact issue.

## Question

If someone outside Software Combined and its portfolio companies gets access to
the router - even without our API keys - can they hack us?

## Method and provenance

- Audited revision: `main` at `1fbd5d7` (release 0.6.14), clean tree. The three
  reviewers read the code read-only; no writes, no network, no delegation.
- Third-party review requests and efforts:
  - `moonshotai/kimi-k3` at `max` - returned identity `unverified`
  - `z-ai/glm-5.3` at `max` - returned identity `unverified`
  - `qwen/qwen3.8-max-0902` at `xhigh`, the model's highest available effort
    (the runtime rejects `max` for this model) - returned identity `unverified`
- Main-agent re-verification at `develop` `a02a881`: every cited line below was
  re-read there, the full test suite was run, and the two headline behaviours
  (rows 1-2) were reproduced locally. The live installed service (0.6.14.31,
  launchd `com.local.codex-mixed-model-router`, listening on
  `127.0.0.1:18749`) was inspected read-only: home directory `0700`, state and
  key files `0600`.
- While this report was being written, plan 090's ingress hardening landed on
  `develop` (`02e8e6e`, 2026-09-11), fixing findings 1 and 3 there. The plans
  and line references below were refreshed at `develop` `08aff1e`, where
  `ai_router/router.py` is 395 lines and no longer sets `allow_reuse_port`.

## Verdict

Without the path token, without keys, and without the ability to run a local
process or bind sockets, an outsider gets a uniform 403 on every route and no
credential, file, routing or billing capability. The realistic harm in that
case is nuisance denial of service, not compromise.

The router's safety rests on one secret: the per-install path token in the URL
(`http://127.0.0.1:<port>/<token>/...`). Treat that URL as a credential.

| Attacker has | Can do | Cannot do |
|---|---|---|
| HTTP reach to the port, no token, no keys | Send requests and get 403s; occupy threads until 090's timeout lands; trigger the unauthenticated crash and log-flood path in 136 | Read or spend anything; route traffic; reach any file, subprocess or upstream |
| Local socket-bind capability (audited revision) | Co-bind the loopback port with `SO_REUSEPORT` (reproduced on the audit host), receive client connections, capture the path token, prompts and subscription headers. Fixed on `develop` by 090 (`02e8e6e`); live 0.6.14.31 installs still carry it until updated | Do this on a launchd socket-activated install, whose `fileno` path does not set the flag |
| The path token, but no keys | Spend the router's stored OpenRouter key on approved models and read responses; restart the service via `/shutdown`; read `/health` | Read the key value; act beyond the portco allowlist; reach other files |
| Our API keys | Full upstream access - outside this router's threat model | - |

## Vetted findings

| # | Finding | Severity | Evidence | Outcome |
|---|---|---|---|---|
| 1 | `SO_REUSEPORT` on the fallback bind lets a local process co-bind the loopback port and intercept connections; each client URL carries the token and its prompts and subscription headers cross that socket | High (local) | Was `ai_router/router.py:34-39`; reproduced 2026-09-11: two sockets with `SO_REUSEPORT` co-bound `127.0.0.1:<port>` and a later plain bind failed with `EADDRINUSE` | Fixed on `develop` by 090 (`02e8e6e`); was live at the audited revision and in 0.6.14.31 |
| 2 | A non-ASCII path segment or `Authorization` value raises an unhandled `TypeError` before auth; the connection aborts and `socketserver` writes a traceback to the supervisor log, which rotates only at service start | Medium | `ai_router/router.py:99-113` (compares at `:107`, `:110-111` on develop); `packaging/service.py:250-251`; `packaging/router_launch.py:32`; reproduced end-to-end: raw `GET /\xff/x` closed with no response and a `TypeError` traceback | Plan 136 |
| 3 | No request timeout before authentication: an idle or slow connection pins a thread indefinitely, and `ThreadingHTTPServer` has no connection cap | Medium (local) | Was `ai_router/router.py:21-23` and `:77-78` with `settimeout` only after auth; develop now sets `Handler.timeout = 120` (`:71`) and spans the whole request in the drain accounting | Fixed on `develop` by 090 (`02e8e6e`) |
| 4 | No `Host` validation: a DNS-rebinding origin reaches the handler, and a no-`Origin` GET bypasses the rebinding gate; the token still returns 403 and POST routes are Origin-blocked, so impact is latent | Low | `ai_router/router.py:99-113`; no `Host` inspection exists anywhere in `ai_router/` | Plan 137 (ready now that 090 has landed) |
| 5 | `Cookie` is not in `HOP_HEADERS`, so it is forwarded to `chatgpt.com` / `api.anthropic.com` on subscription passthrough; the assertion that claims it is dropped never actually sends one | Low | `ai_router/transport.py:10-11`; `ai_router/providers.py:168`; `ai_router/claude.py:132`; `tests/test_handler.py:87-94` | Plan 138 |
| 6 | Token-gated `/shutdown` and `/health` | Accepted design | `ai_router/router.py:151-154`, `:178-183` | No change: the operator needs the restart path; health exposes version, inflight and served models, not secrets |
| 7 | The path token is a spending capability: whoever holds it uses the router's OpenRouter key without ever seeing it | Accepted design | `ai_router/providers.py:260-263` | No change; document that the token URL is a credential |

## Rejected or downgraded after verification

- Upstream response-header CRLF injection (raised low, unverified): rejected.
  `http.client` parses response headers with the `email` parser, which unfolds
  continuation lines into a single space; a probe showed `A: b\r\n c` arriving as
  `b c`. No raw CRLF reaches `send_header`, and the vector needs upstream or
  MITM compromise anyway.
- "An existing test contradicts production and fails" (raised for row 5):
  corrected. The suite is green: full `unittest discover` ran 820 tests with
  exit 0 at the planning revision (`develop` `08aff1e`, 2026-09-11) and was
  green at the audit revision too. The assertion is vacuous, not failing;
  plan 138 makes it real.
- Generic hardening proposals (connection cap, trimming `/health`, redacting
  post-auth path text): rejected as speculative. A local process able to open
  thousands of sockets has cheaper DoS paths, the timeout fix covers the
  realistic case, `/health` is token-gated, and credential errors disclose file
  paths only after auth.

## Defences that held (verified in code)

Line references in this section are from the audited revision (`1fbd5d7`)
unless a line says otherwise; the finding rows above were refreshed to
`develop` `08aff1e`, and the plans pin their own current references.

- Token first on every route: `/health`, `/v1/models`, `/setup/`, `/shutdown`
  and every relay path call `authorized_path()` before routing
  (`ai_router/router.py:143-146`, `:170-177`).
- Constant-time compares for the path token, bearer token and setup nonce
  (`ai_router/router.py:114-118`; `ai_router/setup.py:49`); one uniform 403 for
  unauthenticated requests (`ai_router/errors.py:135-136`), so there is no
  route or prefix oracle.
- 256-bit secrets via `secrets.token_urlsafe(32)` (`packaging/service.py:630`),
  state file `0600` inside a `0700` home (`packaging/service.py:604-632`;
  `packaging/install.py:352`); the key file is owner-only on POSIX and Windows
  (`ai_router/credentials.py:25-52`).
- Logs never carry token, key, header or body content: `log_message` is
  disabled (`ai_router/router.py:80-81`), rejected paths are stripped to
  `<unrouted>` (`:95-100`), and response descriptions collapse to fixed
  categories (`ai_router/transport.py:68-88`).
- Credential separation: OpenRouter requests build a fresh header dict with the
  router key only (`ai_router/providers.py:260-263`;
  `ai_router/claude.py:117-121`); subscription requests never receive the router
  key (`ai_router/router.py:200-201`).
- Fixed upstream hosts and allowlisted paths (`chatgpt.com`, `openrouter.ai`,
  `api.anthropic.com`; `ai_router/protocols/__init__.py:12-30`). No request data
  reaches a host, subprocess, eval or file path; the request path imports no
  installer, updater, catalogue or refresh module, so HTTP cannot mutate the
  catalogue, install anything or fetch an attacker-chosen URL.
- Bodies are bounded: 16 MiB decoded cap, `Transfer-Encoding` refused, zstd
  expansion capped (`ai_router/router.py:289-302`; `ai_router/runtime.py:14`).
- Setup window: requires the path token first, a single-use nonce with a
  15-minute TTL, and a same-origin POST against the bound socket; the
  token-bearing URL is printed only on a TTY (`ai_router/setup.py:24`,
  `:41-51`, `:54-55`, `:257-299`, `:352-378`).
- Since `02e8e6e` on develop: `Handler.timeout = 120` closes idle connections
  before auth (`ai_router/router.py:71`), the drain accounting spans the whole
  request, and the fallback listener no longer sets `SO_REUSEPORT`.

## Residual risk and unverified

- Browser behaviours (Origin on cross-origin POST, per-host connection limits,
  non-ASCII path encoding) were reasoned about, not executed in a browser;
  plans 136-138 add deterministic tests for the server side where ours can be
  pinned.
- Windows ACL enforcement depends on `icacls` output parsing; it was read, not
  executed, for this audit.
- Linux requires the same effective UID to co-bind with `SO_REUSEPORT`; BSD and
  macOS do not have that restriction. The macOS reproduction is direct; the
  different-user Linux case is inferred.
- Out of scope: packaging, the update feed and release pipeline, client-side
  token storage beyond permission checks, and paid subscription probes.

## Plans created from this audit

- `plans/136-unauth-ingress-crash-containment.md`
- `plans/137-loopback-host-header-validation.md` (ready: 090 has landed)
- `plans/138-subscription-cookie-hygiene.md`
- Plan 090 itself landed on develop at `02e8e6e` while this report was being
  written; its Step 3 fix is the remediation for finding 1.
