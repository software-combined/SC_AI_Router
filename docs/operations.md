# Router operations

## How to ship

Work lands on `develop` via `fix/*`/`feat/*` branches, then `develop`
merges to `main` via PR. Tag the merge `v$(cat packaging/VERSION)` (or
`v*-beta` for pre-releases): the release workflow runs on `v*` tags
only, runs the suite, builds the bundle, publishes the release to the
token-gated feed, and then creates the GitHub Release with `latest.json`.
Every router on the stable channel installs it within about fifteen
minutes. Never push to `main` directly for a release; a direct push runs
checks but publishes nothing.

## Feed infrastructure and publishing

Two stacks, both in this repository, hold the update path. Deploy the
certificate first: CloudFront reads viewer certificates from `us-east-1`,
and the deploy stays in progress until ACM validates the DNS record it
creates in the `softwarecombined.com` zone.

```sh
aws cloudformation deploy --stack-name scg-router-feed-cert --region us-east-1 \
  --template-file infra/feed-cert.yaml
CERT="$(aws cloudformation describe-stacks --stack-name scg-router-feed-cert \
  --region us-east-1 \
  --query "Stacks[0].Outputs[?OutputKey=='CertificateArn'].OutputValue" --output text)"
aws cloudformation deploy --stack-name scg-router-feed --region ap-southeast-2 \
  --template-file infra/feed.yaml --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides CertificateArn="$CERT"
```

`infra/feed.yaml` owns the private versioned bucket, the CloudFront
distribution and its viewer-request token gate, the DNS alias, and the
publisher role. The role is assumable only by
`token.actions.githubusercontent.com`, and only for this repository's tag
refs: `repo:software-combined/SC_OpenRouter_adapter:ref:refs/tags/v*` in the
classic subject form, or
`repo:software-combined@200868195/SC_OpenRouter_adapter@1360169840:ref:refs/tags/v*`
in GitHub's immutable form. It can read and write objects in the feed
bucket, list the bucket, invalidate the feed, read the stack outputs and
read the token parameter. It cannot delete objects, write the token stores,
or touch any other resource.

### Feed tokens

The gate is a CloudFront KeyValueStore: a request is served only when
`X-SCG-Feed-Token` is a store key whose value is `active`. Every other
request, including a lookup error, gets 403. The workflow reads the current
value from the SecureString `/scg/router-feed/current-token` and embeds it
in the feed's `latest.json`; the value is never an argv word, never printed
and never logged.

The stack deliberately does not create the parameter, so a stack update
cannot overwrite a live token. Seed both stores once, after the first
deploy:

```sh
TOKEN="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
aws cloudfront-keyvaluestore put-key --kvs-arn "<KeyValueStoreArn>" \
  --key "$TOKEN" --value active --if-match "<etag>"
aws ssm put-parameter --region ap-southeast-2 \
  --name /scg/router-feed/current-token \
  --type SecureString --value "$TOKEN" --overwrite
```

Verify the gate before trusting a release. Before the first publish the
channel documents do not exist, so even a valid token gets 403; run the
positive check after the first release.

```sh
curl -s -o /dev/null -w '%{http_code}\n' https://dist.softwarecombined.com/stable/latest.json
# 403: no header, and also before the first publish. After a release, a
# request with the token header returns the feed document.
```

Rotation keeps the fleet polling. Add the new value to the KeyValueStore as
a second key (`aws cloudfront-keyvaluestore describe-key-value-store`
returns the `--if-match` ETag, and the write fails on a stale one), put the
new value in SSM, then republish the current release: re-run the release
workflow for the latest release tag. A new tag only publishes when its
version equals `packaging/VERSION`, and re-running an older tag replays that
older document, which up-to-date hosts refuse; the release step of a re-run
reports the existing GitHub Release, but the feed publish runs first.

Record the version the channel serves before the republish, wait one poll
cycle plus the updater's bounded jitter (900 s plus up to 120 s, so allow
about 20 minutes), then confirm the edge accepts the new value, the served
document carries it, and the document is still that release before deleting
the retired key:

```sh
# Run this before the republish, while OLD is still active.
BEFORE="$(curl -s -H "X-SCG-Feed-Token: $OLD" \
  https://dist.softwarecombined.com/<channel>/latest.json \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["version"])')"

# OLD = retired token value, NEW = its replacement.
test -n "$NEW" || { echo 'NEW is unset'; exit 1; }
AFTER="$(curl -sf -H "X-SCG-Feed-Token: $NEW" \
  https://dist.softwarecombined.com/<channel>/latest.json \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["version"], d["feed_token"])')"
[ "$AFTER" = "$BEFORE $NEW" ] \
  && echo "the edge accepts the new token and the channel serves it; safe to retire the old key"
```

Before retiring the key, all of these must hold: the edge accepts `$NEW`,
the served document carries `$NEW`, and it is still the release you
recorded. A failed request means the new key is not in the store; a version
that differs means the republish was not that release — an older document
is refused by up-to-date hosts, and a newer one means a release shipped
alongside the rotation, so check against its version instead.

Repeat for every channel in use (`stable` and `beta`) before retiring the
key: a channel you do not republish still serves the old token, and its
hosts lose updates when that key is deleted.

A host keeps the previous value in `feed-token.previous` and retries a 403
once with it, which is what makes the overlap invisible. Never retire the
key before that check passes: a host that has not yet seen the new document
has only the retired value. A host offline for the whole rotation needs the
bootstrap again; a double 403 names the Technology library bootstrap as the
remedy without leaking bytes.

### Migration switch and rollback

`ROUTER_FEED_EMBED_TOKEN` (repository variable) makes the publisher also
carry the token in the GitHub Release copy of `latest.json`. Hosts that
still read the private repository pick the token up on their next poll,
persist it owner-only, and never read the release asset again. Set it for
the transition release, unset it once the fleet has polled, then rotate the
token so the value that appeared in a release asset is dead.

Feed bundles are immutable and the updater refuses a feed whose serial is
older than the last accepted one, so recovering from a bad release is
roll-forward: revert the change on the publishing branch, bump
`packaging/VERSION`, and tag again. Re-uploading a different bundle for an
already-published version aborts instead of replacing bytes, and a failed
workflow before the feed upload leaves the previous feed document serving.
A single host rolls back locally with `install.py --version <version>` at
an idle moment. Moving a host from `beta` back to `stable` needs
`<home>/feed-serial` cleared first, or the lower stable serial is refused
as stale.

## Update feed and repo-free auto-update

Installed routers update themselves with no GitHub account, no repo
access, and no `gh`. Each host resolves its feed through
`packaging/feed.py`: hosts without `<home>/feed-token` poll the private
GitHub Releases feed over `gh` exactly as before; the first feed that
carries `feed_token` is persisted owner-only (previous value kept for
one 403 retry) and every later poll uses
`https://dist.softwarecombined.com/<channel>/latest.json` with the
`X-SCG-Feed-Token` header. Persistence happens after the serial check
but before the version comparison, so an already-current host still
migrates. Feeds and bundles off the trusted origins are refused, and a
double 403 names the Technology library bootstrap as the remedy without
leaking token bytes. `update.log` records each install with its source
(`cloudfront`, `github`, or `local`).

First install for no-repo-access users uses the two bootstrap wrappers
(`packaging/bootstrap.sh` for macOS/Linux, `packaging/bootstrap.ps1` for
Windows) with the feed token. The bootstrap resolves the pinned runtime
from `runtimes.json`, verifies the runtime and bundle checksums, writes
the feed token, and runs the bundle installer; every download comes from
the token-gated feed, so the recipient never touches GitHub.

The first-install assets are published by
`tools/publish_first_install.py`: it reads `packaging/runtime.lock`,
downloads each pinned CPython build, verifies its sha256 before anything
is uploaded, and publishes the wrappers only after the runtimes and the
`runtimes.json` table they read. Re-run it after a runtime-lock change;
identical runtime artifacts are skipped and different bytes under a
runtime key are refused. The two `bootstrap/*` wrappers are the one
mutable entry point: they are replaced when they change and cached for
five minutes, so a wrapper fix can still reach new installers.

```sh
python3.14 tools/publish_first_install.py --dry-run   # plan only
python3.14 tools/publish_first_install.py             # download, verify, upload
```

Hand a recipient the bootstrap URL and the token. Until the gated library
page and per-install tokens land, the shared feed token is the credential,
so rotating it retires every holder at once:

```sh
curl -fsSL -H "X-SCG-Feed-Token: $TOKEN" \
  https://dist.softwarecombined.com/bootstrap/bootstrap.sh -o bootstrap.sh
SCG_FEED_TOKEN="$TOKEN" sh bootstrap.sh
```

The gated Technology site library page remains the self-serve follow-up,
and a machine that cannot use the bootstrap's download path still gets
its first install the old way.

The library page also carries `docs/agent-install-prompt.md`: a
paste-to-agent prompt so the user asks their own agent to run the
bootstrap and verify setup. The prompt pins the production home, forbids
printing secrets, and leaves client restarts to the user.

Never run the installer against a scratch `--home` on a live machine:
service names are machine-wide, so even a /tmp home bootstraps, bootouts,
or TERMs the production jobs. `main()` refuses mutating actions on a
non-production home unless `ROUTER_LIVE_RUN=1` is set; local feed
experiments belong in a disposable session or VM with its own service
manager. Direct `do_install` calls in tests must use the fake `run` seam.

## Global starter instructions

The setup window offers an Everyday help or Coding help starter after the key is stored and
installs the chosen one as the full global `AGENTS.md` (or non-empty
`AGENTS.override.md`) beside `config.toml`, exactly once. An existing file is
never overwritten; updates and uninstall leave global instructions alone, so
the owner's edits always win. Start a fresh Codex task to load the file. It
applies across models without duplicating text in the catalogue and grants no
new permission.

## How to test first

Tag `v*-beta` from `develop`. The workflow publishes a pre-release with
`latest-beta.json`. Cyril's machine follows the `beta` channel (`beta`
in the `channel` file beside the state directory), so it updates first;
watch its `/health` version and `logs/update.log` before merging
`develop` to `main` and tagging stable.

## How to roll back

Revert through `develop` to `main` and tag (the next release supersedes
the bad one), or pin one machine with
`python3 packaging/install.py --version X`. The installer itself
restores the old pointer automatically when the new release fails its
health check.

A release before 0.6.9 recorded a `--feed` install's own build number in
`<home>/feed-serial`, so a local build could leave a number the published
feed has not reached. Every scheduled check then refuses the real feed with
`stale feed serial N is older than M`. Delete `<home>/feed-serial` to clear
it; the next unpinned update records the channel's own serial. Installs from
0.6.9 on leave that file alone.

## Safe update, restart, reinstall

Updates do not wait for idle traffic. Activation swaps the `current`
pointer, then sends one `TERM`: launchd `KeepAlive` restarts the router on
the held socket into the new release, so new connections queue in the
kernel while the outgoing process finishes the requests it already
accepted. An in-flight chat completes on the old release, and on macOS
nothing is refused. Linux has no socket activation (see below): the
outgoing process owns the port and stops accepting for the length of its
drain, so a connection attempted mid-handover fails until the new process
binds. One writer at a time, enforced by an advisory lock on
`install.lock` in the router home, so a scheduled pass and a manual run
cannot interleave.

Prefer `TERM` over `bootout` for a live service: `bootout` unloads the
definition, and if the following `bootstrap` does not take, the machine is
left with no router and no `KeepAlive` to recover it. A reload is only for
a plist launchd has actually loaded differently (a changed interpreter or
port), and it must wait for the label to leave the domain before
bootstrapping: `bootout` returns success while the job is still draining,
and a `bootstrap` issued in that window fails with `Bootstrap failed: 5`.
The installer never boots out the scheduled updater from inside it, since
that job is what runs the installer.

On failed health the installer restores the old pointer, TERMs again, and
then verifies a loaded job is serving the restored version, bootstrapping
it if launchd has none; it says the router is not serving rather than
reporting a clean rollback over a dead machine. A version that fails three
times is parked, so a bad release stops costing a service restart every
fifteen minutes; run the installer by hand to retry. The count lives in the
state file, which is what parks it on the production feed -- that feed is
read through the GitHub CLI and carries no ETag to save. Linux uses
systemd user service restart with a 150-second stop timeout; the launcher
opens the same loopback port after the old process drains. It does not use
launchd socket activation. Failed upgrades restore the prior catalogue too.

Releases are installed only when feed version, manifest version and the
bundled `packaging/VERSION` marker all agree; any mismatch aborts
before any file, pointer or launchd change. `--feed` selects one run's
source and is never pinned, so a local test feed cannot freeze future
updates. Run local feed experiments in a disposable OS user session or VM,
with its own service manager and Codex configuration. A different `--home`
alone does not isolate the fixed user service names or client configuration;
see [Linux upgrade and verification](linux-upgrade.md).

## Layout of the state directory

`~/.codex/mixed-model-router/` holds `current` (pointer to the live
release), `releases/` (current plus two priors for rollback depth), `logs/`,
`mixed-router-state.json` (port, token and feature flags, mode 600),
`activation.json` (config receipt), and `openrouter.key` (mode 600).
The code may live anywhere; only this directory matters at runtime.

## Verification after a Codex upgrade

Run the suite, then the base probe against the installed router and
confirm discovery, one exact callback, and the marker in the final
answer. If the app-server protocol changed, probes fail before any
user task does; do not ship model changes until the base probe passes.

## Latency phase fields (aggregate-only comparison recipe)

`request_completed` carries per-phase durations in milliseconds plus the
long-standing cumulative fields (`local_prepare_ms`,
`upstream_headers_ms`, `first_chunk_ms`, `total_ms`), whose meanings are
unchanged:

| Field | Meaning |
|---|---|
| `read_ms` | Socket read plus body decode |
| `prepare_ms` | Provider selection plus body preparation |
| `connect_ms` | Upstream connection establishment (`connect()`) |
| `send_ms` | Request upload (`request()`) |
| `headers_ms` | Wait for upstream response headers (`getresponse()`) |
| `first_data_ms` | First upstream read-return inside adaptation (not provider TTFB on buffering paths) |
| `first_write_ms` | First successful downstream write (forwarding delay, not network TTFB) |
| `response_kind` | `sse`, `json`, or `other` (fixed values only) |
| `response_encoding` | `identity`, `gzip`, `deflate`, `br`, `zstd`, or `other` (fixed values only) |

`transport_error` carries the phases that completed before the failure;
absent later phases mean the request never got that far. To compare
builds, group by version/provider/model/stream/encoding over approved
existing logs, include failed/aborted counts with sample size and time
window, and use per-request ratios, never ratios of unrelated
percentiles. Paid direct-versus-router comparisons need separate
explicit authority.

## Stream identity observation (last-observed, not proof)

Tool-free responses carry an optional identity observer: bytes forward
immediately while a bounded copy is retained for a post-EOF parse
(JSON, only when the whole body fit in 64 KiB) or complete-frame parse
(SSE, tails over 64 KiB discarded unobserved). Oversized, malformed, or
compressed-without-identity bodies leave the observation unavailable
rather than blocking or fabricating one. `/health served_models` is
therefore last-observed state per alias, never proof of the current
served model; a new observation overwrites, an unobservable response
leaves the prior entry intact.

## Per-user OpenRouter keys (IT issue and revoke)

Owner decision 2026-09-09: IT issues one OpenRouter key per portco user;
there is no self-service provisioning. The flow per user:

1. IT creates the key in the OpenRouter dashboard with a monthly allowance
   and hands it to the user over an existing trusted channel (never commit
   it, never paste it into chat or email threads beyond that handoff).
2. The user installs with `--setup` and a native window asks for the key, the
   subscription choice for the client(s) being set up (ChatGPT for Codex,
   Claude for Claude Code, both when both are attached) and the starter. It
   validates the key against OpenRouter before storing anything and shows
   remaining credit; the key lands in `openrouter.key` (mode 600), which the
   router reads per request. A host with no dialog tool (headless Linux, SSH)
   opens the loopback page instead, and the installer prints the link on its
   own terminal so the operator can paste it into a browser.
3. Rotation: delete `openrouter.key` first (the setup window refuses to
   overwrite a file holding a real key with 409), then re-run the installer
   with `--setup` and paste the replacement. File-level alternative is under
   `Key rotation` below.
4. Revocation is at the OpenRouter dashboard: delete or pause the user's key,
   then confirm fail-closed by asking the user to run any OpenRouter request
   and checking the router log for a `request_completed` entry carrying the
   upstream 401 rather than a completion. Offboarding also removes the seat
   per the portco process; there is no local grant to unwind as long as no
   `OPENROUTER_API_KEY` env or OpenCode-auth fallback is set on that machine,
   because entitlement otherwise lives entirely in the dashboard key state.

## Client activation and subscription policy

`--client codex` (the default) manages the Codex config block, picker
preservation, global guidance, and the activation receipt.
`--client none` installs, updates, rolls back, and uninstalls the router
lifecycle without touching any client file; uninstall needs no receipt.
Switching an active Codex install to `none` restores the exact owned block
first, or refuses when the block was edited. The choice persists in router
state and survives scheduled updates.

Subscription routing is independent per client: `openai_mode` governs
Responses, `anthropic_mode` governs Messages when explicitly set, otherwise
Messages follows the legacy `openai_mode` fallback. Neither mode widens
access on migration; unsets keep prior behavior.

Thread titles, descriptions, summaries and title reconsiderations are the
model calls behind the client's thread metadata. They run as their own
helper threads and are the only turns whose `x-codex-turn-metadata` carries
a `thread_source` of `thread_title`, `thread_description`, `thread_summary`
or `thread_title_reconsideration`. When the ChatGPT allowance is exhausted
upstream refuses those turns, and the client stores a slice of the prompt as
the title instead. With `openai_helper_fallback` true in
`mixed-router-state.json` (default off; restart the service to load it), a
429 on such a turn is answered from the OpenRouter twin row `openai/<slug>`
and logged as `subscription_fallback`, or as
`subscription_fallback_unavailable` when the twin cannot be prepared (no
OpenRouter key, for example), which keeps the existing 503. Every other
turn keeps that 503 unchanged. A provisioned portco list still gates the
twin: an excluded `openai/<slug>` row is never used, so the helper path
stays inside the same allowlist as a directly requested OpenRouter row.
Enabling the flag means the helper prompt reaches OpenRouter and bills
that key, and the helper marker is a client header: any local process
holding the loopback path token can present a helper-shaped turn and have
its prompt answered - and billed - by an allowed twin. It grants no other
rerouting.

## Key rotation

Replace the `openrouter.key` file contents. No restart is needed; the
router reads the key per request.

## Per-portco model policy

Onboarding: add the user to the portco subgroup, resolve the slug subset
centrally against the current `models.json` (a department list must stay
within its portco list), and deliver `<home>/model-policy.json` (`0600`,
atomic write) with `portco`, `department`, `allowed_models`, `version`,
and `updated_at`. The router loads it at startup into
`state['allowed_models']`; both protocol policies gate OpenRouter slugs
on it, subscription rows unaffected. Offboarding: remove the user from
the subgroup and delete their OpenRouter key by id; the policy file goes
with the machine's decommissioning, never as a revocation control.

## Windows (Task Scheduler)

The Windows backend (`packaging/platforms/windows.py`) registers two
per-user tasks, `CodexMixedModelRouter` and `CodexMixedModelRouterUpdate`,
from XML it writes to `logs\*.task.xml`. Facts the design rests on, all
verified on Windows 11 on 2026-09-10: a logon trigger must name the
installing user (an unscoped one needs elevation and fails with "Access is
denied"); a repeating trigger needs a `StartBoundary`; `schtasks /delete`
leaves a running instance alive, so uninstall ends the tasks first;
re-registering a running task keeps its instance, so the updater can refresh
its own definition; and an interactive-token console task shows its window,
so both tasks run `pythonw.exe` through `task_launch.py` in the router home
(rewritten on every install), which appends stdout and stderr to
`logs\launchd.log` and `logs\update.log` (rotated at 1 MB, one backup). Every console child (`schtasks`, `icacls`, `whoami`, `python`,
`gh`) is spawned without a window.

Restart and update: the task allows one instance (`IgnoreNew`), so a
handover posts the authenticated `/shutdown`, waits for the instance to
leave the Running state (up to 180 seconds), then runs the task again; a
process still alive after that deadline is ended. `schtasks /query /tn
CodexMixedModelRouter /fo list /v` shows status, last run and last result
(`267009` means running). Key protection: the router home carries an
inheritable owner-only grant and the key and state files a plain one; a
widened ACL makes the router refuse the key at read time.

## Incidents

Check `/health`, then `logs/launchd.log`, then
`launchctl print` for the router agent (`schtasks /query` on Windows). Roll
back by re-running the installer with `--version` pointing at the previous
release.

## Decision log

Request cap removed. Compaction runs through a billable summariser
call. The catalogue is a generated snapshot from the registry (live
in-router catalogue pending); live model metadata refreshes weekly
into the registry. Model rows are data; new behaviour is always code.

## One-time cleanup after 0.4.0

Delete from the state directory on the author's machine:
`compatibility-release.json`, the `before-*` folders,
`config-before-*.toml`, `stdout.log`, `stderr.log`, and `retired/` after
one week. Keep `mixed-router-state.json`, `activation.json`,
`openrouter.key`, `current`, `releases/`, and `logs/`.
