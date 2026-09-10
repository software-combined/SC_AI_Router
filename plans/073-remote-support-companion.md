# Plan 073: Secure single-helper remote support companion

> **STATUS: PARKED / NOT APPROVED.** Planning deliverable only. This document
> authorises **no** implementation, no source or test edits, no
> `CHANGELOG.md` / `packaging/VERSION` change, no packaging or service
> changes, no paid probes, no relay or hosted infrastructure, and no change to
> any staff, portco, or recipient machine. Nothing here has been built or
> verified live. Planned against `develop` at `e043920`, 2026-09-10.
> Next action is an owner decision on Slice 0, not code.

## Status and first proof

- PARKED, not approved; P3; effort M (Slices 0-1) then M-L; security risk
  HIGH; confidence HIGH in the trust/consent shape, UNVERIFIED in the OS
  signing primitive and per-platform consent-prompt behaviour.
- Independent of Plans 068-072; must not serialize behind them, and must never
  touch `codex_router/router.py` or any file under `codex_router/`.
- Sole authorised helper is Cyril Allart. No second helper, group, role, or
  delegation exists in this design, by construction (see Consent below).
- First proof (Slice 1): on one consenting test machine, a request signed by
  Cyril's pinned key produces a read-only audit bundle only after a human
  accepts an OS/TTY prompt; an unsigned request, a second signer's request,
  and a replayed request are each dropped before any prompt is shown, each
  leaving one token-free audit line.

## Problem statement

A recipient hits a laptop problem involving the router, their client, or their
machine state. Today the only paths are screen-share narration or asking the
recipient to run commands they cannot evaluate. Cyril needs to investigate the
actual machine state and drive a support session through the recipient's own
Codex/Claude, without inheriting standing remote access to a fleet of laptops
and without weakening the router's loopback-only posture.

The router is the wrong vehicle: it is a loopback relay that never executes
tools, and `docs/architecture.md` gives `router.py` ownership of loopback auth
and body limits only. Remote help is therefore a separate, opt-in, separately
installed companion that shares the repo's conventions and nothing else.

## Non-goals

- No remote control of the machine, no screen sharing, no keystroke injection,
  no reverse shell, no arbitrary command execution from the helper side.
- No second helper, no group, no role hierarchy, no delegation. Exactly one
  pinned principal, by construction.
- No new inbound listener anywhere, and no new route on the router.
- No change to router request handling, provider selection, credentials,
  model policy, or the picker.
- No unattended or standing-consent mode, no remember-my-choice, no model
  granting or renewing consent.
- No public relay in this plan (Slice 5 is deferred and undesigned).
- No transport of the per-install loopback token, the OpenRouter key, or any
  request/response content off the machine.
- Not an incident-response tool: CODE RED keeps its own runbook and authority.

## Threat model

Assets: recipient machine state and files; the OpenRouter key and router
loopback token; router state and receipts; Cyril's helper signing key; the
audit trail's integrity; the recipient's trust that consent is real.

Actors: (1) Cyril, the sole authorised helper. (2) The recipient and machine
owner, who owns consent. (3) A network attacker or compromised relay. (4) An
insider or ex-staff member with repo or read access attempting to impersonate
the helper. (5) The recipient's own local agent (Codex/Claude), which already
holds local execution authority.

Trust boundary on the local agent: the recipient's local model can already run
commands on that machine, so the consent gate cannot protect the owner from
their own agent. What consent must protect is remote initiation and remote
disclosure. A local model-driven self-approval therefore grants the local
agent nothing new, but non-interactive approvals are still refused and every
accept is recorded, so an owner reading the log can see an approval they did
not make.

Abuse cases and required controls:

1. Someone other than Cyril sends a request. Verify an Ed25519 signature
   against a pinned single-entry allowed-signers file, with a fixed
   namespace, before any prompt or execution; drop otherwise.
2. Tampered allowlist adds a second signer. The file must contain exactly one
   principal whose key fingerprint equals the fingerprint constant shipped in
   the signed release bundle; a mismatch or a second line fails closed and
   logs `helper_allowlist_rejected`.
3. Replay of an old signed request, or reuse across machines. The signed
   payload binds request id, machine install id, scope, issued-at, and
   expiry; a seen-id ledger rejects replays; clock skew beyond a bounded
   window is refused.
4. Prompt-injection of the receiver's model to accept on the owner's behalf.
   Acceptance is never a chat turn or a model-callable tool; it is an OS
   dialog or a foreground-TTY CLI confirmation requiring a displayed code to
   be typed. The companion refuses to accept when stdin is not a TTY and no
   GUI prompt is available.
5. Prompt fatigue and consent spam. Rate-limited pending requests (one at a
   time, small daily cap), decline-by-default timeout, and a permanent local
   off switch that needs no network.
6. Scope escalation from audit to fix. Separate scope in the signed envelope,
   a second explicit accept, and per-action approval for anything classified
   destructive.
7. Secret exfiltration through audit output. Checks are a fixed argv
   catalogue with no helper-supplied arguments; an explicit deny list covers
   the key file, router token, `~/.ssh`, keychains, browser profiles, and
   shell history; outputs are size-capped and pattern-redacted before release,
   and the owner sees the bundle before it leaves.
8. Compromised relay or network observer. The relay is untrusted by design
   and holds no authority; authenticity comes from the signature. Until a
   reviewed confidentiality design exists, transport is restricted to a
   channel the recipient already trusts (Slice 2), not a public relay.
9. Stolen helper key. Single-file revocation on the receiver, fleet rotation
   through the normal release channel, short session expiry, and per-action
   approval limiting blast radius while a rotation propagates.
10. Session left open after help ends. Hard per-session expiry, idle expiry,
    one-command revoke, revoke on companion stop, and no persistence of grants
    across restarts.
11. Supply-chain change to the companion. It ships in the same signed release
    bundle with the pinned fingerprint; enabling it stays a separate explicit
    installer opt-in that defaults off.

## Architecture

```text
remote_help/                  (new top-level package; stdlib only)
  identity.py    pinned single-signer verification (ssh-keygen -Y verify)
  envelope.py    signed request/response schema, replay ledger, expiry
  consent.py     OS dialog / foreground-TTY accept, decline-by-default
  checks.py      fixed argv catalogue, deny list, caps, redaction
  session.py     lifecycle: grant, scope, expiry, revoke, heartbeat
  audit.py       token-free JSONL audit + owner-visible transcript
  transport.py   outbound long-poll only (Slice 2)
  __main__.py    receiver companion entrypoint

tools/remote_help_console.py  helper-side CLI (Cyril's machine only)
```

Dependency direction: `remote_help/` imports stdlib only. It must never import
`codex_router` (so it can never reach credentials, state, or the loopback
token), and `codex_router/` must never import `remote_help` (so the router's
request path is unchanged whether the companion exists or not). Both
directions become rules in `tests/test_domain_boundaries.py`, whose
synthetic-violation test already proves the detector is not vacuous.

Receiver companion: a separate process with its own home
(`<router-home>/remote-help/`, `0700`) and its own service unit, disabled by
default. No listener: it polls outbound. It executes only named checks from
`checks.py`; there is no shell, no interpolation, and no helper-supplied path.

Helper console: `tools/remote_help_console.py` composes a request, signs it
with Cyril's key, posts it, and renders the returned bundle. It holds no
authority beyond the signature.

Trust and identity: `remote-help/allowed_signers`, `0600`, exactly one line,
verified with `ssh-keygen -Y verify` under a fixed namespace and cross-checked
against the release's fingerprint constant. Loader mirrors
`codex_router/model_policy.py`: absent means disabled, malformed or
wrong-permission means fail closed to no helper, every rejection logs a reason
and no content. Python 3.14 stdlib has no asymmetric signature primitives, so
the OS mechanism is used rather than hand-rolled crypto.

Consent flow: verify signature and freshness, resolve requested scope, show the
owner the helper principal, scope, expiry, and the exact check names, require
an interactive accept, mint a session, execute checks, show the bundle, owner
releases it. Timeout declines. A fix scope repeats the accept, and each
destructive action prompts again with the exact argv.

Session lifecycle and scopes: `audit` (default, read-only, fixed catalogue),
`fix` (second accept, non-destructive allowlisted remediation), and
`fix+destructive` (per-action accept with typed confirmation). Sessions carry
an id, scope, absolute expiry (default 30 minutes, cap 2 hours), idle expiry,
and revocation state. `remote-help revoke` ends everything immediately and is
the documented one-command stop.

## Networking choice and rationale

Slice 1 uses no network at all: the owner hands the signed request to the
companion and returns the bundle out of band. This proves identity, consent,
audit, and redaction with zero attack surface, and it is the honest thinnest
vertical slice.

Slice 2 adds outbound long-poll only, over a channel the recipient already
trusts: Tailscale or SSH to a Cyril-controlled host where present, else HTTPS
to one small mailbox endpoint on that host. No inbound port, no NAT
traversal, no change to `router.py`, and the mailbox stores opaque blobs with
no authority. Registration uses a per-install remote-help token generated for
this purpose, never the router's loopback token.

A public multi-tenant relay is rejected for now: with stdlib-only Python there
is no vetted way to keep payload confidentiality from the relay operator, and
building extra crypto plumbing over `openssl` CLI calls would be speculative
machinery this plan avoids. That decision is Slice 5's gate.

## Logging and audit

Two separate artefacts, per `SECURITY.md`:

- `remote-help/audit.jsonl` (`0600`, rotated): timestamp, helper principal,
  request id, session id, decision (`accepted` / `declined` / `timeout` /
  `dropped` with a fixed reason), check name, exit code, output byte count,
  and output SHA-256. No command content beyond the catalogue name, no output
  text, no keys, no tokens, no request bodies. Never committed; `.gitignore`d
  alongside existing state artefacts.
- `remote-help/sessions/<id>/transcript` (`0600`): the redacted check output
  the owner reviews and releases. Deleted on revoke or expiry plus a short
  retention window. Never written to the router's `logs/router.jsonl`.

## Acceptance gates (distinct, per docs/architecture.md)

1. Source: `python3.14 -m unittest discover -s tests -t .`,
   `python3.14 -m compileall -q` over `codex_router tools tests packaging`
   plus `remote_help`, `python3.14 tools/check_source_limits.py` after adding
   `remote_help` to its SOFT/HARD tables at the module budget (250/400), plus
   `pre-commit-review`.
2. Packaged imports: the companion imports cleanly from a built bundle and the
   router still starts and serves with the companion absent, present, and
   present-but-disabled.
3. Native lifecycle: separate launchd/systemd user unit installs only with the
   explicit opt-in flag, starts, stops, revokes on stop, and uninstalls
   without touching router units or the Codex config block. Windows: explicit
   refusal, consistent with the current installer stance.
4. Real-client session: one end-to-end audit-only session on a consenting test
   machine through the recipient's actual Codex, with the drop cases proven
   pre-prompt.
5. Billing: out of scope here. The companion makes no model calls; any model
   tokens spent belong to the recipient's own client session. No paid probe is
   authorised by this plan.
6. Release: `CHANGELOG.md` + `packaging/VERSION` only when a user-visible
   slice actually lands, released by tag through the normal channel, beta
   channel first on Cyril's machine.

## Staged slices

- Slice 0, decision and primitive spike (no install). Confirm
  `ssh-keygen -Y verify` behaviour, namespace handling, and availability on
  the supported macOS/Linux baselines; confirm the consent-prompt mechanism
  per platform (`osascript`, `zenity`/`kdialog`, TTY fallback). Record
  findings and the key-custody/rotation decision. Proof: written evidence with
  exact commands and versions; explicit NO-GO if the primitive is not
  dependable.
- Slice 1, audit-only, offline, thinnest end-to-end. `identity`, `envelope`,
  `consent`, `checks`, `audit`, `session` (local only), plus the helper
  console's sign/render path. Proof: the first proof above.
- Slice 2, outbound transport and lifecycle. Long-poll, expiry, idle timeout,
  revoke, heartbeat, rate limits. Still audit-only. Proof: a real session
  completes over the trusted channel with no inbound port opened, and revoke
  terminates it within one poll interval.
- Slice 3, assisted fix. Second accept, non-destructive remediation allowlist,
  destructive classification with per-action typed confirmation. Proof: a fix
  runs only after two accepts, and a destructive action is refused when its
  per-action prompt times out.
- Slice 4, packaging, docs, release. Opt-in installer flag, service unit,
  `docs/remote-help.md`, `SECURITY.md` note, architecture-map entry,
  `CHANGELOG.md`/`VERSION`, beta-then-stable release.
- Slice 5, deferred, undesigned. Public relay and any second helper. Blocked
  on an owner-approved confidentiality design; not started by this plan.

## Test plan

- `tests/test_remote_help_identity.py`: valid single signer accepted; unsigned,
  wrong-namespace, second-signer, empty, two-line, wrong-fingerprint, and
  wrong-permission allowlists all rejected with fixed reasons.
- `tests/test_remote_help_consent.py`: timeout declines; non-TTY with no GUI
  refuses; wrong typed code refuses; accept mints a session with the exact
  requested scope and no more.
- `tests/test_remote_help_envelope.py`: expiry, clock-skew bounds, replayed
  id, and machine-id mismatch all rejected before consent is invoked.
- `tests/test_remote_help_checks.py`: only catalogue names resolve;
  helper-supplied argv or paths are impossible; deny-listed paths refused;
  output caps and redaction applied; non-zero exit recorded, not raised.
- `tests/test_remote_help_session.py`: absolute and idle expiry, revoke,
  revoke-on-stop, no grant survives restart.
- `tests/test_remote_help_audit.py`: audit lines carry digests and categories
  only; a seeded secret in check output never reaches audit or transcript in
  the clear.
- `tests/test_domain_boundaries.py`: both new no-import rules.
- `tests/test_install_lifecycle.py`: default install enables nothing; opt-in
  install and uninstall leave router units and the Codex block untouched.

Every case above names a specific defect it would catch; no coverage-only
tests.

## Rollout and rollback

Opt-in per machine, one machine at a time, Cyril's own machine first on the
beta channel. No fleet enablement. Rollback is layered and each layer is
independently sufficient: `remote-help revoke` ends live sessions; deleting
`allowed_signers` disables the helper permanently with no network; stopping or
uninstalling the unit removes the poller; a release revert removes the code.
Because the feature is off unless explicitly enabled, a router rollback never
needs to reason about remote-help state.

## Open questions

1. Where does Cyril's signing key live, and is a hardware-backed or
   passphrase-protected key required? This drives Slice 0's NO-GO criteria.
2. Is the recipient population's consent surface a GUI dialog or a terminal?
   Recipients without a reliable GUI prompt path change the consent design.
3. Does the recipient set already have Tailscale or SSH to a Cyril-controlled
   host? None is present on this machine today, so Slice 2's channel is
   unresolved.
4. Should the fixed check catalogue be router-scoped only (state, health,
   logs, service status, client config) or extend to general machine state?
   Narrower is safer and probably sufficient for the real support cases.
5. Rotation and expiry policy for the pinned fingerprint, given it ships in
   the release bundle and propagates on the normal update cadence.
6. Retention period for session transcripts, and whether the owner may keep
   them at all after a session closes.
7. What obligations apply if a session incidentally reveals personal data on a
   staff or portco laptop?

## Provenance

Planned 2026-09-10 from an Opus-high read-only planning agent over `develop`;
the runtime accepted the requested model but returned no served-model
identity, so treat the served identity as unverified. The planner wrote no
files and created no worktree; this file is the parent's faithful write-up of
that plan, parked here at Cyril's direction. Two items were deliberately left
as gates rather than assumptions: the `ssh-keygen -Y verify` primitive is
untested here, and no Tailscale is installed on this machine, so the Slice 2
channel is genuinely open. If Slice 0 is approved, the natural next step is
the primitive spike and the key-custody decision, both cheap, either of which
would validate or kill the trust design before any code exists.
