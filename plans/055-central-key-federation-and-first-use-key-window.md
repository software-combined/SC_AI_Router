# Plan 055: Central per-user key federation and the first-use key window

> Planning only. No AWS resource creation, OpenRouter organisation write, key
> provisioning, staff-machine install or release is authorised by this
> document. Each is a separate owner gate listed below.

Priority P1; effort M; risk HIGH (credential handling and spend).
Planned 2026-09-09 at `db3eb406c3406e7487cc4e2a51ec7f157c9ee246`.
Updated 2026-09-09: Entra `mail` recorded as the verified work email anchor for Plan 054 Stage A onboarding (owner discussion).

## Outcome

A staff member who onboards through the Plan 054 page ends up with a working
router holding their own OpenRouter key that they never see, never paste and
never store anywhere themselves, and that IT can re-budget or revoke in one
call. Anyone whose router has no usable key gets a window on their first
request instead of an error.

First observable proof: onboarding one test user creates an OpenRouter key
named for their verified work email with a per-person budget attached, the
installer writes it `0600`, the router serves one real completion, and deleting
that key stops only that user's spend on their next request.

## Owner decisions this plan builds to

| Decision | Source |
|---|---|
| Provision centrally and write the key to the machine at `0600`, never displayed; do not proxy inference through our own service | Owner, 2026-09-09 |
| Anthropic models come through OpenRouter; no separate Anthropic plan | Owner, 2026-09-09. Claude subscription OAuth may not be intermediated by third-party tools, so OpenRouter is also the compliant route |
| Supersedes Plan 048's "IT issues one OpenRouter key per portco user, pasted once into the setup window" | Owner, 2026-09-09 |
| Identity anchor is the onboarding-verified work email, not the Codex login email | Worked out 2026-09-09 from the verified constraint below |
| Per-user OpenRouter keys, one per install | Plan 048, retained |

## Verified current state (2026-09-09, read-only)

| Check | Observed |
|---|---|
| Machine-side key lookup | `codex_router/credentials.py` already resolves `OPENROUTER_API_KEY`, then `<home>/openrouter.key`, then `opencode_auth`; read at request time so rotation needs no restart; raises `PermissionError` unless the file is owner-only, and `LookupError` when nothing is found. The owner-decided design is already the implemented one |
| Setup page | `codex_router/setup.py` serves a nonce-protected loopback page that validates the key against OpenRouter (`check_key`, showing label, limit and usage) and writes `<home>/openrouter.key` with `O_EXCL` and mode `0o600`. On `FileExistsError` it claims and truncates an *empty* placeholder, and returns 409 ("delete it to rotate keys") only when the existing file holds a real key |
| Window trigger today | Installer-side only: `do_install` mints a nonce whenever `--setup` is passed and opens `setup_url` whenever it is set, tolerating `SystemExit(3)` from the key probe rather than being triggered by it (`packaging/install.py:314-328`, `434-438`). Nothing opens a window from the request path |
| Key placeholder | `ensure_credentials` (`packaging/install.py:143-155`) returns early when a key is already present, and otherwise pre-creates an *empty* `openrouter.key` with `O_EXCL` and `0o600`, prints a paste instruction and raises `SystemExit(3)`. Any later writer must expect that placeholder to exist |
| Repository hygiene | `openrouter.key` is in `.gitignore`; `AGENTS.md` §4 forbids committing or logging keys and bearer tokens |
| Codex identity, owner Mac | `~/.codex/auth.json` carries `tokens.id_token.email = sc.codex.r@gmail.com` and `chatgpt_plan_type = pro`: a provisioned account, not a personal work address |
| OpenRouter capability | Management API keys call `/api/v1/keys` and cannot call completions. `POST /api/v1/keys/` accepts `limit` and `limit_reset` (`daily`/`weekly`/`monthly`). Guardrails at `/api/v1/guardrails` give budgets that follow a person rather than a key and are assignable through the same API (checked 2026-09-09) |
| Plan 054 | Supplies the email-gated onboarding and the per-install token this plan reuses as machine identity |
| AWS | Account `651116729473`; SES production access with `softwarecombined.com` and `softwarecombined.com.au` verified and DKIM-signed; GitHub OIDC provider present |

## Why the Codex login email cannot be the anchor

The owner asked whether the key could be keyed to the email used for the Codex
login. On the owner Mac that email is a provisioned account shared by naming
convention, not a personal work address, so several people could resolve to one
identity and one budget. Separately, a value read from a local file is a claim
about identity, not proof of it; trusting it remotely would mean verifying an
OpenAI-issued token against its JWKS, which is new machinery for an identity
Plan 054 has already verified by email.

The anchor is therefore the onboarding-verified work email. The router may
still read the Codex account email locally and report it once at provisioning
time, stored for reconciliation only. Its one real use is detecting two people
sharing a Codex seat.

## Design

### 1. Where the Management key lives

One OpenRouter Management API key in AWS Secrets Manager in `ap-southeast-2`,
readable only by the provisioning role. Never on a laptop, never in the
repository, never in GitHub secrets, never in the Plan 054 bucket. It cannot
call completions, so its blast radius is key and guardrail administration, not
inference spend. CloudTrail records every read.

### 2. Provisioning at onboarding

After Plan 054 verifies the work email (operator-run script in Stage 1, the
self-serve page later):

For users onboarded through the Plan 054 Stage A page, the Entra `mail`
value (tenant member or B2B guest) is the verified work email: the operator
reads it from the portco subgroup membership rather than re-verifying it.

1. `POST /api/v1/keys/` with a `name` carrying the verified email and a machine
   label, a `limit`, and `limit_reset` monthly.
2. Assign that person's Guardrail through `/api/v1/guardrails` so the budget
   follows the person across every key they hold.
3. Record in DynamoDB: verified email, OpenRouter key id, issued-at, the Plan
   054 install token id, and the Codex account email when reported. Store the
   key id, never the secret.
4. Return the key secret once, over TLS, to the installer that asked for it.

### 3. Delivery to the machine

Key issuance must be authenticated by a **per-install** credential, which
exists only once Plan 054 Stage 4 issues one per verified email. Plan 054's
Stage A token is a single value shared by the whole group and republished in
every `latest.json`, so it must never authorise issuance: anyone holding it
could mint billable keys and be handed another person's secret, and the audit
row could not tell two installs apart.

Until Stage 4 exists, delivery is the interim operator path: the Stage 1
script writes the file directly on the machine through the shared writer.
Exporting `OPENROUTER_API_KEY` is not a delivery channel and must not be used
as one: `ensure_credentials` returns early when it is set, so nothing is
written, the LaunchAgent carries only `ROUTER_HOME`, and the installed service
therefore starts with no credential while the operator's foreground run
passes. An export also lands the secret in shell history, which this section
forbids. Bootstrap-carried delivery is Stage 4 work, not Stage 2 work.

Whichever path writes it, the installer writes `<home>/openrouter.key` at
`0600`, so `credentials.openrouter_key()` needs no change. The key is never
printed, never echoed into a shell, never logged, and never passed as a
command-line argument.

It must reuse `setup.py`'s existing carve-out rather than a plain `O_EXCL`
create. `ensure_credentials` pre-creates an empty placeholder on any earlier
key-less install, so a plain `O_EXCL` write fails with `FileExistsError` on the
installer's own placeholder: claim an empty file, refuse a non-empty one. The
single shared writer belongs in one helper both callers use, not duplicated.

Rotation therefore needs an explicit step, because a file holding a real key is
refused: confirm the new key works, replace the file under the same mode, then
delete the old key by id. The runbook owns that order.

### 4. The first-use key window

New behaviour. It is not the only router-side change: `runtime.load_state`
already refuses to boot keyless unless `setup_pending(state)` finds a nonce
younger than `SETUP_TTL_S` (15 minutes), so today a keyless machine dies at
boot and never reaches a request path. That gate must widen to let a keyless
router boot with the request-path window as the gate; every billable call still
fails closed per request until a key resolves.

Trigger. A request whose `credentials.openrouter_key()` raises `LookupError`,
or a 401 from the OpenRouter provider specifically (`provider.name ==
'openrouter'`) confirmed against the stored key with `check_key`. Scoping
matters: `openai-subscription` and `anthropic-subscription` also return 401 on
ordinary auth expiry, and `relay()` already handles those, so an unscoped
status check would pop a key window for an unrelated provider. Confirming with
`check_key` also stops a transient or hostile upstream 401 inducing a window.

Then the router:

1. Returns one clear message to the client saying a key is needed, so Codex
   shows a cause rather than a bare failure.
2. Mints a setup nonce **once, under `server.lock`**, persisting it the way
   `_finish_setup` already does: re-read the file, write a temp file, then
   `os.replace`. It must not use the installer's `_write_state`, which
   truncates in place with no temp file; from a request thread in a
   `ThreadingHTTPServer` that races the updater and the `/shutdown` route's
   `os._exit(0)`, and can leave a state file that neither the router nor the
   updater can parse.
3. Opens the existing loopback page through `webbrowser`, as `do_install` does.
4. Suppresses further windows while `setup.setup_pending(state)` is true rather
   than with a one-shot per-process flag. That gives one window per live nonce,
   and re-arms after the 15-minute TTL, so a user who steps away is not left
   with a dead URL and no way back.
5. Never prints the URL to a non-interactive stream. It carries the per-install
   path token, and the router's stdout is redirected to
   `<home>/logs/launchd.log` on macOS and to the journal under systemd, so
   printing it would write a bearer token to a persistent log, which
   `AGENTS.md` §4 and Plan 050 both forbid. Print it only when stdout is a TTY;
   otherwise emit a token-free lifecycle event naming the port and the
   `/setup/` path.

Replacing a revoked key. The page cannot currently store one: `setup.py`
returns 409 whenever the existing key file is non-empty, and a revoked key is
still a non-empty file, so the window would open and then refuse the new key on
submit. The shared writer therefore needs one narrow carve-out beyond the empty
placeholder: it may truncate a non-empty file only when `check_key` shows the
**stored** key is itself rejected. Without that, every central revocation
strands a machine until someone deletes the file by hand, which is what
federation exists to avoid.

Reachability is already bounded: `router.py` rejects tokenless and
Origin-bearing requests, so only a holder of the per-install path token can
trigger any of this.

The window is the fallback for a machine the provisioning service does not
know, or whose key was revoked. In the federated path a user never sees it.

### 5. What this plan does not do

It does not proxy inference through our own service. That would put every
completion, including streaming, through our infrastructure: latency on each
token, a single point of failure for everyone's work, and bandwidth cost, while
adding nothing to the control that matters, because revocation and budgets live
at OpenRouter in either design. Holding the key in memory only was also
rejected: it shares the same revocation story, but anyone who can read an
owner-only file in that user's home can equally run the router and read the key
from memory, so it buys a startup dependency and no security.

## Stages, proofs and gates

| Stage | Work | Proof | Gate |
|---|---|---|---|
| 1 | Management key into Secrets Manager; operator-run provisioning script (create key, assign guardrail, write the audit row) | one test user's key exists with its guardrail attached and an audit row written; the secret appears in no log or terminal transcript | AWS resource creation and OpenRouter organisation write (owner) |
| 2 | Installer accepts a provisioned key and writes it through the shared writer; no router change needed | a clean install serves one real completion from a key the operator provisioned, with nothing pasted by the user; bootstrap-carried delivery is explicitly out of this stage | staff-machine action and paid probe (Plans 049, 052) |
| 3 | Keyless-boot gate, first-use key window and the revoked-key carve-out (§4) | a router with no key file boots, and the first request opens the page once, returns a clear message and recovers once a key is saved; a router restarted with no key still boots and still opens it; a non-empty but revoked key completes the window end to end with no manual file deletion; concurrent requests produce exactly one window and one still-valid nonce; a subscription-provider 401 opens none | staff-machine action (owner) |
| 4 | Wire provisioning into the Plan 054 self-serve page, which is also what first issues the per-install credential that authorises issuance (§3) | a portfolio company user onboards end to end with no operator step; revoking their key stops only their spend | account and domain approval (owner); depends on Plan 054 Stage 4 |

Stage 3 is independent of Stages 1, 2 and 4 and can land first; it is the
fallback that makes every other path recoverable.

## Verification

- Unit, no network per `AGENTS.md`: a fake OpenRouter and a fake browser opener.
  `LookupError` and a provider-scoped 401 each produce one window per live
  nonce and one clear client message, and a window re-arms once the nonce
  passes `SETUP_TTL_S`; a saved key ends the window state without a restart; a
  `webbrowser` failure emits the token-free lifecycle event off a TTY and does
  not raise into the request path; truncation of a non-empty key file happens
  only on a 401 or 403 rejection of the stored key and is refused on any other
  status, transport error or unparseable response;
  the key never appears in any log record (log field allowlist) or in an
  exception message; a group-readable key file still raises `PermissionError`
  on POSIX, and the Windows path is asserted separately because
  `credentials.py` skips the mode check when `os.name == 'nt'`.
- Provisioning script: against a fake Management API, a created key carries the
  verified email in its name, a `limit`, monthly `limit_reset` and an assigned
  guardrail; the audit row stores the key id and never the secret; a failed
  guardrail assignment does not leave an unbudgeted key behind.
- Live, gated: one test user end to end, then delete the key and confirm the
  next request from that machine fails closed and opens the window, while
  another user's requests are unaffected.

## Risks

| Risk | Handling |
|---|---|
| A per-key `limit` caps the key, not the person, so several keys sum | assign a per-person Guardrail at provisioning; the plan does not rely on `limit` alone |
| Management key compromise can mint or delete keys | Secrets Manager, least-privilege role, no laptop copy, CloudTrail; it cannot call completions so it cannot spend directly |
| The key sits on a machine the user already controls (owner-accepted) | never displayed, `0600` enforced by `credentials.py`, revocable centrally in one call, per-person budget caps the damage |
| A revoked key looks like a broken router | the provider-scoped 401 path opens the window, and the §4 carve-out lets the page replace a key proven dead, so recovery needs no manual file deletion |
| `check_key` cannot prove a key dead: it raises `ValueError` on any `HTTPError` and on an unparseable body, so a 429, a 5xx or a captive portal would report a live key as rejected, and the local file is the only copy of a provisioned secret | the §4 carve-out truncates only on a 401 or 403 rejection of the stored key and refuses on any other status, transport error or unparseable response, so `check_key` must surface the status; the replacement key must already have validated in the same request |
| Rotation blocked by the existing `O_EXCL` writer | one shared writer: claim an empty placeholder, truncate only a key proven dead by `check_key`, refuse a live one. Runbook order for planned rotation: confirm the new key, replace the file, then delete the old key by id |
| Codex account email is not per-user | never used as the anchor; stored for reconciliation only, which is also how a shared Codex seat is detected |

## Out of scope

Proxying inference; a separate Anthropic plan (OpenRouter already carries those
models); Plan 048's portfolio-company billing arrangement; changing the
subscription-mode choices the setup page already collects; Codex or Claude
client configuration (Plan 051).
