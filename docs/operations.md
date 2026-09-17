# Router operations

## How to ship

Work lands on `develop` via `fix/*`/`feat/*` branches, then `develop`
merges to `main` via PR. Tag the merge `v$(cat packaging/VERSION)` (or
`v*-beta` for pre-releases): the release workflow runs on `v*` tags
only, runs the suite, builds the bundle, publishes the release to the
public feed, and then creates the GitHub Release with `latest.json` as a
public mirror for humans.
Every router on the stable channel installs it within about four hours.
Never push to `main` directly for a release; a direct push runs
checks but publishes nothing.

## Feed infrastructure and publishing

Two stacks, both in this repository, hold the update path. The `infra/`
templates are repository-only: deploy them from a checkout, not from an
installed host (the release bundle carries `README.md` and `docs/*.md` only).
Deploy the certificate first: CloudFront reads viewer certificates from `us-east-1`,
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
  --parameter-overrides CertificateArn="$CERT" \
    BucketName="$FEED_BUCKET" SigningSeedArn="$FEED_SIGNING_SEED_ARN" \
    NotificationEmail="$EMAIL"
```

The subscription needs one click: SNS emails `NotificationEmail` and waits.
Confirm it, then re-check with
`aws sns list-subscriptions-by-topic --topic-arn <topic>` that it no longer
reads `PendingConfirmation`; until it does, the publish email never arrives
and the second-write signal is silently missing.

Each `bundles/` write then mails one short message - subject, object, size,
S3 version id, time and the PutObject actor - instead of the raw S3 event. The
small `FeedAlertFunction` owns that wording. It exists rather than an
EventBridge `InputTemplate` because a template substitutes raw: an object key
carrying a double quote would break the template and stop delivery, letting
the writer this alert watches silence their own alarm. The function also sets
the mail subject. `tests/test_feed_infra.py` compiles the inlined function,
drives it with a hostile key and pins the grants (the rule may invoke only
this function; the function may publish only to this topic).

### Where the feed identifiers live (Plan 160)

The template carries no account-bearing default, and the tree carries no
account id, bucket name or role ARN. The release workflow reads three
**repository variables** (repository settings, not the tree; never written
down here):

| Variable | What it is | What uses it |
|---|---|---|
| `FEED_BUCKET` | the feed bucket the publisher writes to | `tools/publish_feed.py --bucket`, the deploy override above |
| `FEED_ROLE` | the publisher role the release workflow assumes by OIDC | the workflow's AWS credentials step |
| `FEED_SIGNING_SEED_ARN` | the Secrets Manager secret holding the feed signing seed | the workflow's publish step, and the template's `SigningSeedArn` |

`FEED_STACK` stays a literal in the workflow: a stack name carries no account
id. Both publishers now require `--bucket`, so a fork that runs them with no
arguments fails with a message naming the argument instead of publishing to
someone else's bucket.

`infra/feed.yaml` owns the versioned bucket (private to S3, served publicly
through CloudFront), the CloudFront distribution, the DNS alias, and the
publisher role. The role is assumable only by
`token.actions.githubusercontent.com`, and only for this repository's tag
refs: `repo:software-combined/SC_AI_Router:ref:refs/tags/v*` in the
classic subject form, or
`repo:software-combined@200868195/SC_AI_Router@1360169840:ref:refs/tags/v*`
in GitHub's immutable form. It may read any object in the feed bucket and
write only what a release publishes: `bundles/*` and, per channel,
`latest.json`, `latest.json.sig` and `models.json`. It can also list the
bucket, invalidate the feed, read the stack outputs and read the signing
seed. An explicit deny refuses a delete or any change to the bucket's own
configuration, so a later widening of the allow cannot reach them. The
first-install keys (`runtimes*`, `bootstrap/*`) are outside it on purpose:
that tool uploads with the operator's own credentials.

The publisher's bundle upload is create-only (`--if-none-match '*'`), so a
second write of a published key is refused by S3 itself. A role holder that
skips the flag can still replace a key: the publish email reports it (one
message per `bundles/*` write, so a second message for an existing key is
the signal), and bucket versioning recovers the replaced bytes afterwards.
When that second message arrives, recover deliberately: the email names the
object and the version it wrote, so list that key's versions (`aws s3api
list-object-versions --bucket "$FEED_BUCKET" --prefix bundles/<name>`),
match the emailed `VersionId`, compare each version's `Metadata.sha256`
against the feed document that names the bundle, copy the matching version
back over the key with `aws s3api copy-object --copy-source
<bucket>/<key>?versionId=...`, then find out what held the publisher role.
The feed and its bundles are public: readers need no credential.

### When the alert itself fails

A publish email that never arrives is reported too: the rule's target carries
a dead-letter queue (`<stack>-alert-dlq`, 14-day retention) and an alarm on
`FailedInvocations` - one failure in a five-minute period sends an email to
the same topic. So a mail whose body is an alarm, not a bundle, means the
formatter could not deliver the bundle mail; the event it could not format is
in the queue. Read it with `aws sqs receive-message --queue-url <queue url>`
plus `--attribute-names All`, and the failure itself in
`/aws/lambda/<function name>` in CloudWatch Logs. CloudWatch tells the topic
about a state change only, so a long outage sends one alarm mail rather than
one per attempt while the queue keeps every failed event for its 14 days.

Verify the feed before trusting a release. Before the first publish the
channel documents do not exist; run the positive check after the first
release.

```sh
curl -s -o /dev/null -w '%{http_code}\n' https://dist.softwarecombined.com/stable/latest.json
# 200 once a release is published.
```

### Retired: token rotation and the embed-token migration switch (2026-09-12)

There is no feed token to rotate: the feed is public and token-free. The
old token-bearing `latest.json` asset on the `v0.6.25.42` release is inert
but should still be retired before enabling immutable releases. The
repository visibility flip remains its own owner-gated step (plan 144).

Feed bundles are immutable and the updater refuses a feed whose serial is
older than the last accepted one, so recovering from a bad release is
roll-forward: revert the change on the publishing branch, bump
`packaging/VERSION`, and tag again. Re-uploading a different bundle for an
already-published version aborts instead of replacing bytes, and a failed
workflow before the feed upload leaves the previous feed document serving.
A single host rolls back locally with `install.py --rollback --to <version>`
at an idle moment. Moving a host from `beta` back to `stable` needs
`<home>/feed-serial` cleared first, or the lower stable serial is refused
as stale.

## Update feed: public and automatic

Every install polls the public feed at
`https://dist.softwarecombined.com/<channel>/latest.json` with no token,
no enrolment, no GitHub account and no repository access. The `channel`
file in the router home (`~/.codex/mixed-model-router`) selects the
document: `beta` follows the pre-release document, anything else (or a
missing file) follows `stable`. Checks run every 4 hours (macOS
`StartInterval` 14400, systemd `OnUnitInactiveSec=4h`, Windows `PT4H`);
Linux also runs a first check 5 minutes after the timer activates, and
macOS runs one when the job loads. Every channel document carries a
detached Ed25519 signature (`latest.json.sig`); the updater verifies the
exact served bytes before parsing and refuses unsigned or bad-signature
feeds with the `feed_signature` code (Plan 145). `file://` manual installs
stay operator-trusted when no sidecar is present. SHA-256 verification of
every bundle, version and identity checks, and the feed serial replay guard
still apply on top. Feeds and bundles off the trusted origins are
refused. Feeds and bundles never follow a redirect off that
origin, and a feed document without a bundle checksum is refused. A manual install passes `--feed` with a downloaded release
document; `--status` reports the feed source (`cloudfront`) and the
channel. A leftover `feed-token` file on an older host is inert and can
be ignored or deleted. The signing seed lives in Secrets Manager
(`FEED_SIGNING_SEED_ARN` in the release workflow) by name only; the seed
value never appears in logs or docs. `update.log` records each install with its source
(`cloudfront` or `local`).

A host still on a pre-cutover build reaches the public-feed version with
one bootstrap or one manual `--feed` install; after that it updates
itself.

First install uses the two bootstrap wrappers
(`packaging/bootstrap.sh` for macOS/Linux, `packaging/bootstrap.ps1` for
Windows). Each bootstrap downloads the pinned runtime and the release
bundle from the public feed, verifies both checksums, and runs the bundle
installer; `--channel=beta` follows pre-releases. The recipient never
touches GitHub and supplies no token.

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
python3.14 tools/publish_first_install.py --bucket "$FEED_BUCKET" --dry-run  # plan only
python3.14 tools/publish_first_install.py --bucket "$FEED_BUCKET"  # download, verify, upload
```

Hand a recipient the bootstrap URL for their OS:

```sh
curl -fsSL https://dist.softwarecombined.com/bootstrap/bootstrap.sh -o bootstrap.sh
sh bootstrap.sh
```

A machine that cannot use the bootstrap's download path still gets its
first install from a handed-off release directory with
`python3 packaging/install.py --feed file:///path/to/latest.json`, a
one-shot pin that is never persisted.

`docs/agent-install-prompt.md` is the paste-to-agent prompt so the user
asks their own agent to run the bootstrap and verify setup. The prompt
pins the production home, forbids printing secrets, and leaves client
restarts to the user.

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

## New model notifications

When a scheduled update lands a version that adds models for the machine's
policy scope, the updater asks the running router over loopback (the 3.9
updater never imports the runtime) and offers a Codex restart: a desktop
notification names up to three of the new models (macOS always; Linux when
`notify-send` is installed; Windows logs the offer only) and the approval
page opens in the browser on macOS and Linux. The page is reachable only
through its single-use link, which carries the per-install path token plus
a 48 h nonce; both Restart Codex and Later acknowledge, and only the
Restart click quits and reopens Codex, on macOS. The offer is skipped on
installs whose state records no Codex attachment (`--clients claude`,
`--client none`; a `clients` value recorded by an earlier run can lag the
current attachment) and whenever `ROUTER_NO_NOTICE=1` silences the update
notice. The first run
seeds the snapshot without announcing the catalogue, so the first landing
after this feature ships only seeds it and later landings announce;
removals and version-only updates stay silent, and an unverified or
out-of-policy row is never announced.

## How to test first

Tag `v*-beta` from `develop`. The workflow publishes a pre-release to the
public beta document (`beta/latest.json`). Cyril's machine follows the
`beta` channel (`beta`
in the `channel` file beside the state directory), so it updates first;
watch its `/health` version and `logs/update.log` before merging
`develop` to `main` and tagging stable.

## How to roll back

Revert through `develop` to `main` and tag (the next release supersedes
the bad one), or pin one machine with
`python3 packaging/install.py --rollback --to X`. The installer itself
restores the old pointer automatically when the new release fails its
health check. Scheduled updates keep running after a rollback, so the
channel offers the newer release again at the next pass; stop the scheduled
update job if the rollback has to persist until a fix ships.

A release before 0.6.9 recorded a `--feed` install's own build number in
`<home>/feed-serial`, so a local build could leave a number the published
feed has not reached. Every scheduled check then refuses the real feed with
`stale feed serial N is older than M`. Delete `<home>/feed-serial` to clear
it; the next unpinned update records the channel's own serial. Installs from
0.6.9 on leave that file alone.

## Operator surface

Every command is read-only unless it says otherwise, and none prints a
token, key or URL:

```sh
python3 packaging/install.py --doctor    # helper rows, a Fix line per WARN/FAIL
python3 packaging/install.py --status    # version, service, keys, channel, update recency
python3 packaging/install.py --check-update   # installed and available versions only
python3 packaging/install.py --update    # apply what the channel offers (scheduled action)
python3 packaging/install.py --rollback  # list installed releases; --to VERSION restores one
python3 packaging/install.py --support   # 0600 redacted bundle for a support request
```

`--doctor` exits 1 when any row fails. Its rows cover the Python runtime, the
installed release, the serving version, each provider key, the picker
catalogue (one `ai_router.catalogue --check` run), the Claude Code attach
snapshot against the live `GET /v1/models` listing, the scheduled command
carrier and update recency; a host whose launcher or systemd unit still runs
the read-only `--check-update` fails that row until the installer re-renders
it. `--status` reports `last_check_at`, `last_applied_version`, `last_error`
(a code from a closed set) and the per-version failure counts from state, so
a parked release is visible without reading the log. `--support` writes only
booleans, enums, versions, counts and timestamps to
`<home>/logs/support-<UTC>.json` and prints the path.

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
four hours; run the installer by hand to retry. The count lives in the
state file, which is what parks it on the production feed -- that feed is
read from the public feed. Linux uses
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
`activation.json` (config receipt), and one owner-only key file per
external provider (`openrouter.key` by default, mode 600).
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

## Failed streams (why the provider ended it)

`request_failed` records a terminal event the upstream sent inside a `200`
stream. `code` is `context_length_exceeded` for a context-limit refusal,
`UPSTREAM_INCOMPLETE` when the provider reported an incomplete response,
`UPSTREAM_INVALID_PROMPT` when OpenRouter refused the converted request after
the stream opened, and `UPSTREAM_STREAM_FAILED` for any other terminal error.
Six fields say why:

| Field | Meaning |
|---|---|
| `terminal_event` | `response.failed`, `response.incomplete`, or `error` |
| `upstream_reason` | the `incomplete_details.reason` enum, when reported |
| `upstream_code` | the error envelope's `code` or `error_type`, when present |
| `upstream_error_type` | the canonical top-level `error_type`, when reported |
| `upstream_provider_code` | the `error.metadata.provider_code`, when reported |
| `serving_endpoint` | the OpenRouter endpoint that answered; absent when the router or an edge validation answered |
| `failure_class` | `context`, `final` or `transient`; the stream retry runs only on `transient` |

Every detail must be code-shaped (letters, digits, dot, dash, underscore,
slash for endpoint slugs) and
at most 64 characters; anything else, including message text, is dropped
rather than recorded, because provider prose can quote prompt content. A
missing detail means the provider did not say why, or said it in a form this
rule refuses to record.

## Tool alias repair (why a called name changed)

`tool_call_repaired` and `tool_call_unresolved` carry a `cause`: `native`
(the plain tool name), `dotted` (`namespace.tool`), `digest` (a damaged
fallback digest), `near` (a readable alias within two edits; an ambiguous
near miss is never guessed), or `delivered` (a delivered-message name such
as `delivered_message`, which is not a tool). `unknown` means the name
matched nothing repairable.

## Router answer codes (Responses protocol)

The router answers deterministic refusals with HTTP 400 (the client treats
400 as final and shows the message at once) and transient upstream failures
with HTTP 503 plus `Retry-After: 2` (the client retries on its own backoff;
Codex paces itself and does not read the header). The only retryable 409
left on Responses is the compaction summariser's, where a repeat can cure
the failure; an oversized turn answers 400 with guidance instead of 413. The
Anthropic Messages path keeps its existing answers except at that shared
size boundary, where it answers 400 like Responses.

A refused subscription turn (an upstream 429 on a login the client owns)
answers 503 `UPSTREAM_RATE_LIMITED` whose message names the model and the
subscription that refused it and says the turn was not served, to retry
shortly or to select a routed model. An external route's transient 429
keeps the neutral text, and neither answer carries upstream prose.

| Event | Meaning |
|---|---|
| `upstream_unavailable` | an upstream 5xx or 408 on a Responses turn, answered 503 |
| `client_disconnected` | the client hung up mid-stream; previously counted as `transport_error` |
| `upstream_rate_limited` | an upstream 429, with `category` `quota`, `auth` or `transient`; on Responses a quota 429 answers 400 `PROVIDER_REJECTED` and an auth 429 opens the key window; a subscription turn's `transient` 429 answers 503 naming the model and the subscription |

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

One key file per external provider (Plan 139): the installer and the setup
window name the provider whose key they are collecting, and a second
provider's key never overwrites the first. `--status` reports each
provider's key under `providers`, with the legacy `key_present` /
`key_usable` pair still describing the default provider (OpenRouter).

1. IT creates the key in the OpenRouter dashboard with a monthly allowance
   and hands it to the user over an existing trusted channel (never commit
   it, never paste it into chat or email threads beyond that handoff).
2. The user installs and a native window opens by itself to ask for the key,
   the subscription choice for the client(s) being set up (ChatGPT for Codex,
   Claude for Claude Code, both when both are attached) and the starter. It
   validates the key against OpenRouter before storing anything and shows
   remaining credit; the key lands in `openrouter.key` (mode 600), which the
   router reads per request. A host with no dialog tool (headless Linux, SSH)
   opens the loopback page instead, and an interactive terminal prints the
   link so the operator can paste it into a browser. The installed
   service does not receive the invoking shell's environment, so an exported
   `OPENROUTER_API_KEY` does not count as configured and still opens the
   window. Re-run with `--setup` only if no window appears; it restarts the
   current release with a fresh link, without re-extracting it. Scheduled
   `--update` runs and manual `--check-update` runs never pop the window; the
   next request opens it instead.
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

Native service calls (`/alpha/*`, `/guardian*`) pass through to the
ChatGPT backend with the client's own login in subscription mode and answer
404 in `none` mode; the list is a prefix rule on the OpenAI definition, so a
new backend path needs no router change. A dot segment, percent-encoded dot
or backslash in the path is refused before the prefix test.

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

## Subscription picker gate

A ChatGPT subscription slug that upstream refuses is worse than useless in
the picker: it stays selectable and fails the turn. The router therefore
hides one from `mixed-models.json` once it has evidence that this slug
cannot run, and puts it back when it can.

Three kinds of evidence move the gate, all read from turns the client
already makes (`ai_router/subscription_gate.py` owns the state and the
rules; `ai_router/subscription_watch.py` watches and rewrites the picker;
`ai_router/subscription_probe.py` rechecks):

- `x-codex-primary/secondary-used-percent` response headers, when the
  upstream sends them, are authoritative: a window at 100% blocks that slug
  until its reported reset (capped at seven days), and any lower reading
  clears it.
- A refused subscription turn (429) or an auth refusal (401/403) blocks the
  slug for an hour, refreshed by later refusals; a turn that succeeds
  clears it at once.
- While a slug is blocked, the router asks the subscription upstream once
  about that slug - the first attempt on the next tick (up to twenty minutes
  later), then at most once every four hours - one attempt, no retries, a
  short timeout - using the login the client last presented. That login
  lives in the running process only: it is never written to disk, never
  logged, dropped when nothing is blocked, and dropped at once if upstream
  refuses it. Set
  `subscription_probe: false` in `mixed-router-state.json` (restart the
  service) to disable the recheck; with no login seen, the pass sends
  nothing.

State is `subscription-gate.json` beside the router state: one entry per
slug with its source, start and expiry. A missing or malformed document
means no gate, which is the behaviour before this existed. Changes are
silent and log one `subscription_gate_changed` event per change; every probe
that reaches upstream logs one `subscription_probe` event, while a pass with
no login sends nothing and logs nothing. The picker file is rewritten at
once, but Codex reads its catalogue at startup, so a running client shows
the result only after it reopens.

The OpenRouter twin of a subscription model (`openai/<slug>`) is that
model's paid route, and the two never list together: the twin is hidden
while its subscription row is the working route and appears only while that
row is hidden, so the same model still has a selectable paid fallback. An
install that serves no subscription at all (`openai_mode: none`) lists the
twins and no subscription rows, as it always did. The key-filtered
`/models/user` gate is untouched, and the Claude listing is out of scope.

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

Managed installs: the state file may carry `policy_enforced: true`, set
only by the trusted provisioning path (the installer flag, MDM, or the central
grant tool) and never by a user or a routine update. With the flag set, a
missing policy denies external routing instead of granting it, and the router
logs one token-free `model_policy_rejected` event with reason
`enforced_without_policy` (Plan 176). An unreadable or invalid policy denies on
any install, each with its own reason. A personal install never sets the flag,
so an absent policy keeps today's behaviour. A value that is not true or false
stops the boot with `policy_enforced must be true or false`.

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
`logs\launchd.log` and `logs\update.log` (rotated at 1 MB, one backup). Every console child (`schtasks`, `icacls`, `whoami`, `python`)
is spawned without a window.

Restart and update: the task allows one instance (`IgnoreNew`), so a
handover posts the authenticated `/shutdown`, waits for the instance to
leave the Running state (up to 180 seconds), then runs the task again; a
process still alive after that deadline is ended. `schtasks /query /tn
CodexMixedModelRouter /fo list /v` shows status, last run and last result
(`267009` means running). Key protection: the router home carries an
inheritable owner-only grant and the key and state files a plain one; a
widened ACL makes the router refuse the key at read time.

## Incidents

Check `install.py --doctor` first, then `/health`, then `logs/launchd.log`,
then `launchctl print` for the router agent (`schtasks /query` on Windows).
Roll back by re-running the installer with `--rollback --to` naming the
previous release.

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
