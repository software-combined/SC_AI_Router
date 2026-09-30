# Router operations

## How to ship

Work lands on `develop` via `fix/*`/`feat/*` branches, then `develop`
merges to `main` via PR. Release tags use the full `v<VERSION>` label
matching `packaging/VERSION`: `0.6.117` becomes `v0.6.117`.
Add `-beta` for a pre-release, `-express` for an urgent stable release, or
`-beta-express` for an urgent beta. The release workflow runs on `v*` tags
only. A beta tag needs a commit that `develop` or `main` moved to, such as a
PR merge commit, not a commit inside a merged branch. A
stable tag needs a commit merged into `main` with a successful `Check` run for
that exact commit, so tag the `main` merge commit after that run passes. The
workflow then validates the exact version, builds the bundle, publishes the
release to the public feed and creates the GitHub Release with
`latest.json` as a public mirror for humans. The semantic version remains in
the public tag, bundle and feed, where the updater uses it for ordering.
Every router on the stable channel installs a stable release within about four
hours. Never push to `main` directly for a release; a direct push runs
checks but publishes nothing.

Develop PRs and branch pushes run fast static checks. The full offline suite,
scoped native installer checks, plugin scheduler checks and hook-adapter
portability checks run for main PRs and pushes to `main`. A beta tag does not
wait for them: `develop` accepts commits only through pull requests that pass
the required `Test` check, and local tests and review run before every commit.
A stable tag reuses the exact-commit `main` acceptance instead of repeating it.
Both channels then run packaging, runtime-pin verification, signing and
publication. A tag runs the copy of the release workflow saved in the tagged
commit, so a tag on a commit made before this acceptance check existed can
still publish without it. Stopping those older copies from publishing is a
separate step.

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
    BucketName="$FEED_BUCKET" SigningSeedArn="$FEED_SIGNING_SEED_ARN"
```

No subscription confirmation step is left for the reader route. The per-write
email is retired; the reader now sits on the central SCG AWS notification
service, which watches the same `bundles/` prefix with its own EventBridge
rule and reports each write as a branded publication. That route belongs to
`SC_Infrastructure`, so its subscription list and source-stack alarms are the
delivery checks.

The local formatter, topic, queue and narrow failure alarm stay as the rollback
path. They monitor only that local formatter rule, not central delivery.
`tests/test_feed_infra.py` compiles the inline function, drives it with a
hostile key and pins the grants.

To restore the direct route, deploy the pre-retirement `infra/feed.yaml` that
contains `FeedPublishSubscription`, passing `NotificationEmail="$EMAIL"` with
the deploy. The recipient must confirm the new SNS subscription, and the
rollback is incomplete until
`aws sns list-subscriptions-by-topic --topic-arn <topic>` no longer reports
`PendingConfirmation`. Do that same readback after an automatic stack rollback
that re-creates the subscription.

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
skips the flag can still replace a key: the central publication notification
reports it (one message per `bundles/*` write, so a second message for an
existing key is the signal), and bucket versioning recovers the replaced bytes
afterwards. When that second message arrives, recover deliberately: the
notification names the object and the version it wrote, so list that key's
versions (`aws s3api
list-object-versions --bucket "$FEED_BUCKET" --prefix bundles/<name>`),
match the notified `VersionId`, compare each version's `Metadata.sha256`
against the feed document that names the bundle, copy the matching version
back over the key with `aws s3api copy-object --copy-source
<bucket>/<key>?versionId=...`, then find out what held the publisher role.
The feed and its bundles are public: readers need no credential.

### When publication reporting fails

The central SCG AWS notification service owns replacement delivery and
reports both stages through its independent plain-text fallback.
`PublicationRuleFailures` alarms when EventBridge cannot send a bundle event
to the publication topic. `PublicationDeliveryFailures` alarms when that topic
cannot reach the shared notification intake. Both alarms sit in the
`AwsNotificationSources-*` source stack and must be checked before assuming a
publication was lost. The daily digest or notification state then confirms
whether the event was processed.

This stack's `FeedAlertFailureAlarm` is narrower: it covers only the retained
local formatter rule used by rollback. Its queue and function logs explain a
local invocation failure, but it does not establish that the central route
failed or that a reader missed a publication.

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

## Experimental compaction

`jev-compaction` beside the router home's `channel` file controls the opt-in
Jev consumer. `ROUTER_HOME` overrides `~/.codex/mixed-model-router`; use the
home the service actually runs with. The router reads the file at every
external V1 or V2 compaction, without a restart. Trimmed lowercase `shadow`
and `on` are the only enabled values. Missing, empty, unreadable and all other
values, including `ON` and `1`, mean off.

Both enabled modes send selected history text to TypeSafe and bill the
external provider key. Confirm that this data sharing is permitted before
enabling either mode. Subscription threads and ordinary turns never call Jev.
`shadow` is the recommended first step: it logs proposed counts but leaves
the existing summary and input unchanged. `on` uses kept evidence as the
summary text inside the existing V1/V2 envelopes. There is no new capsule or
history store. Disabling the flag affects future compactions, not summaries
already produced.

Choose one mode command after selecting the home. macOS/Linux:

```sh
RH="${ROUTER_HOME:-$HOME/.codex/mixed-model-router}"
printf 'shadow\n' > "$RH/jev-compaction"  # Measure only, recommended first
printf 'on\n' > "$RH/jev-compaction"      # Replace the summary
rm -f "$RH/jev-compaction"                # Disable
```

PowerShell:

```powershell
$rh = if ($env:ROUTER_HOME) { $env:ROUTER_HOME } else { Join-Path $HOME '.codex/mixed-model-router' }
Set-Content "$rh/jev-compaction" shadow -Encoding ascii # Measure only
Set-Content "$rh/jev-compaction" on -Encoding ascii     # Replace the summary
Remove-Item "$rh/jev-compaction" -ErrorAction SilentlyContinue # Disable
```

One batch considers at most 16 complete pairs, largest outputs first. The
first item, latest user message and everything after it, newest six items,
prior compactions, discovery results, agent messages and system/developer
messages stay pinned. The rest stay verbatim. A pair is dropped only when the
judge says its facts are already covered (0.90 or above) *and* that knowing
the call happened no longer matters (below 0.90); covered evidence whose call
still matters keeps the call with a shortened output, and everything else
stays whole. This conservative experimental threshold needs
calibration from shadow data, not assumed safety: a previous trial scored a
plainly true fact at 0.69, so the scores are not a calibrated guarantee.

Wide windows keep their newest evidence and report how many older entries
were left out as `retained_omitted`; both questions tell the judge not to
infer coverage from that absence. When the facts
count as covered but the call still matters, the output keeps
its first 300 characters plus the number removed; the router never advises
re-running a tool, because it cannot know whether that tool is idempotent.
Ambiguous pairs, invalid or partial answers, decision failures,
a state that cannot fit the 32 KiB request budget, or retained text over 40%
of the selected model's compaction limit (its context window when the row sets
no limit) all use the existing summarizer.
There are no decision retries, fallback models, per-turn calls or decision
cache. `compact_jev` logs only mode, counts, byte sizes, elapsed milliseconds
and a closed-set error code; never content, tool names or keys.

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
downloads each pinned CPython build (macOS arm64/x86_64, Linux x86_64 and
arm64 on glibc, Windows x64), verifies its sha256 before anything is
uploaded, and publishes the wrappers only after the runtimes and the
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
updater never imports the runtime) and shows one native restart dialog. The
dialog names up to three new models the way the picker does
(`<Vendor>: <Model>`, without the `· OpenRouter` route suffix). No browser
page or separate desktop notification opens. The dialog appears only when the
router names at least one model that no earlier dialog has listed. An update
or check with no new model stays silent, and so does one that cannot reach
the running router, so a stopped service never delays an update. Once a
dialog is on screen, the router is told to mark every model it covers as
seen (the dialog names three and counts the rest as `+2 more`), through the
same Later action the old approval page used, so no later update lists them
again. Dialogs never stack: a model that arrives while an earlier dialog is
still open waits, and a later pass names it once that dialog has closed.
`Later` leaves the client running; `Quit and reopen` quits
and reopens Codex on macOS. The offer is skipped on installs whose state
records no Codex attachment (`--clients claude`, `--client none`; a `clients`
value recorded by an earlier run can lag the current attachment) and whenever
`ROUTER_NO_NOTICE=1` silences the update notice. If no native dialog tool is
available, the notice stays pending for a later GUI run, and its models stay
waiting until a dialog actually shows them. The first run seeds
the snapshot without announcing the catalogue, so the first landing after
this feature ships only seeds it and later landings announce; removals and
version-only updates stay silent, and an unverified or out-of-policy row is
never announced.

## How to test first

Merge the release candidate into `develop` through its PR, then tag the
resulting `develop` commit `v<VERSION>-beta`. A beta waits only for that PR's
checks, not the long `main` checks. The workflow publishes a pre-release to the
public beta document (`beta/latest.json`). Cyril's machine follows the
`beta` channel (`beta`
in the `channel` file beside the state directory), so it updates first;
watch its `/health` version and `logs/update.log` before promoting `develop`
to `main` through its PR. Promote only what the beta ran: before merging the
release PR, confirm its head is still the beta commit; if `develop` has moved,
tag and watch a new beta on the new `develop` commit first. Once the `Check`
run for the push to `main` passes on the merge commit, tag that merge commit
`v<VERSION>` for stable.

## How to roll back

Revert through `develop` to `main` and tag (the next release supersedes
the bad one), or pin one machine with
`python3 packaging/install.py --rollback --to X`. The installer itself
restores the old pointer automatically when the new release fails its
health check. Scheduled updates keep running after a rollback, so the
channel offers the newer release again at the next pass; stop the scheduled
update job if the rollback has to persist until a fix ships.

A rollback does not rewrite the picker catalogue. Rows the newer release
added stay listed in the picker even though the restored release cannot
route them, and selecting one ends the turn with "That model is not
available on this machine". Re-run the installer, or refresh the picker
with `python3.14 -m ai_router.catalogue --merge <home>/mixed-models.json`
from the restored release, after rolling back across a release that added
or renamed a row.

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

Capture what the new client sends before anything else:

```sh
python3.14 tools/capture_codex_shapes.py
```

It drives the installed app-server through a dynamic-tool turn, a model
switch and a V2 compaction against an in-process router and a fake
upstream, so it is free, makes no network call and reads no credential.
The sanitised request bodies land in
`tests/fixtures/replay/captured/<codex version>/`, and the drift report
lists the item types, top-level request fields and developer-message
openings added or removed since the newest earlier capture. Read that
report first and check the new files for personal paths or text (the
report compares only names), then commit the new directory;
`tests/test_switch_marker.py`
checks that the router still finds the switch marker in every capture.

Next, run the suite, then the base probe against the installed router and
confirm discovery, one exact callback, and the marker in the final
answer. If the app-server protocol changed, probes fail before any
user task does; do not ship model changes until the base probe passes.

`tests/test_replay_golden.py` pins the exact body each route sends for a
set of synthetic histories. Regenerating those goldens with
`REPLAY_GOLDEN_UPDATE=1` changes behaviour on purpose: explain the golden
diff in the PR, and in `CHANGELOG.md` when users see the change.

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

`request_started` and the request's final record carry the same
`request_id`, a random 32-character hex id. Use it to join the two lines
for one request, including a helper turn answered by the fallback twin. It
is not derived from anything the client sent.

## Failed streams (why the provider ended it)

`request_failed` records a terminal event the upstream sent inside a `200`
stream. `code` is `context_length_exceeded` for a context-limit refusal,
`UPSTREAM_INCOMPLETE` when the provider reported an incomplete response,
`UPSTREAM_INVALID_PROMPT` when OpenRouter refused the converted request after
the stream opened, and `UPSTREAM_STREAM_FAILED` for any other terminal error.
Six fields say why:

| Field | Meaning |
|---|---|
| `terminal_event` | `response.failed`, `response.incomplete`, `error`, or `message_error` |
| `upstream_reason` | the `incomplete_details.reason` enum, when reported |
| `upstream_code` | the error envelope's `code` or `error_type`, when present |
| `upstream_error_type` | the canonical top-level `error_type`, when reported |
| `upstream_provider_code` | the `error.metadata.provider_code`, when reported |
| `serving_endpoint` | the OpenRouter endpoint that answered; absent when the router or an edge validation answered |
| `failure_class` | `context`, `final`, `transient` or `unknown`; the stream replay runs only on a recognised `transient` failure |

Every detail must be code-shaped (letters, digits, dot, dash, underscore,
slash for endpoint slugs) and
at most 64 characters; anything else, including message text, is dropped
rather than recorded, because provider prose can quote prompt content. A
missing detail means the provider did not say why, or said it in a form this
rule refuses to record.

Each routed request ends with one `attempt_ledger` record containing ids, route,
send reasons, decisions, commitment, terminal writer and outcome. It contains
fixed codes and counts; terminal request records repeat those outcome fields.

## Agent handoff failures

`handoff_observed` joins a native Responses handoff to `request_id`, the ledger's
`attempt`, and a response-local `call_ordinal`. It records the tool, declaration
location, alias advertisement, namespace category, encryption-marker state and
argument JSON kind before restoration, after restoration and after the guard.
`envelope_changed` identifies a namespace or marker change between envelopes;
`identity_consistent` reports whether their identifiers agree. Raw identifiers,
assignments, recipients, ciphertext and results are never logged.

An upstream native call with a nonempty or absent plaintext marker and
`guard_rejected=true` was refused by the existing encrypted-handoff rule. A
plaintext alias that becomes native with an empty marker and an object argument
passed that rule. `restoration_rejected` identifies an invalid alias envelope.
These facts locate the failure without inferring readable text from ciphertext.

`frame_end_offset` is the end of the adapted frame in that attempt's outgoing
body. Compare it with `forwarded_delta_bytes` for the same request and attempt:
the router confirmed the complete write only when that counter reaches the
offset. A failed or partial write remains unconfirmed; a successful socket write
does not prove the child ran. `handoff_observation_finished` lists missing
envelopes. Each response retains at most 32 call identities and emits at most 96
observations, 32 summaries and one limit record. A limit or logging failure
marks observation incomplete while forwarding continues unchanged.

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

Every request has a local 96 MiB ceiling on its wire, decoded and prepared
bytes, on all four routes and for identity and zstd bodies alike. A turn past
it answers 400 `BODY_TOO_LARGE` with no upstream call, and the transport checks
the same ceiling again on every send. The ceiling bounds what one turn makes
this machine hold; it does not mean a provider or subscription accepts a body
that size. Native history, images, signatures and headers are forwarded whole.

16 MiB is the ordinary request threshold, not a limit. A turn past it on the
wire, on decode or once prepared takes the single large-request slot, before
the rest of a compressed body is expanded, and keeps it until relay, any
repair retry or subscription fallback, and cleanup finish. A second large turn
arriving meanwhile answers 503 `OVERSIZE_BUSY` with `Retry-After: 2` and no
upstream call; smaller turns proceed within the 32-request in-flight limit. A
repair or fallback body is sized together with the body still held, and one
that does not fit is never sent (a fallback keeps the refusal answer).

An external Responses turn still over the 16 MiB prepared budget is reduced
with visible notes before it is sent: repeated released-tool listings collapse
to the newest copy per tool, the oldest images past the newest four (or 4 MiB)
become a note, and long old tool outputs are truncated head and tail. Tool
call/output pairing and the newest items are never touched, and a turn with
nothing reducible left is sent as it is, within the ceiling. Native routes are
never trimmed. Upstream answers keep their own caps: 16 MiB for a response
body or one SSE frame, 1 MiB for an error body.

A refused subscription turn (an upstream 429 on a login the client owns)
answers 503 `UPSTREAM_RATE_LIMITED` whose message names the model and the
subscription that refused it and says the turn was not served, to retry
shortly or to select a routed model. An external route's transient 429
keeps the neutral text, and neither answer carries upstream prose.

Every refusal, retryable or final, leaves one `request_rejected` line with
`status`, `code` and `path`, plus `retry_after` when a retry hint went out and
a bounded, path-redacted `detail` when the plain message left a technical
reason behind (a credential problem's OS text). An upstream rejection keeps
its own line (`upstream_rejected`: `status`, `code`, `parameter`,
`serving_endpoint`, and the bounded `tool`), so the status, codes, field and
tool names a person no longer reads stay searchable in the log.

| Event | Meaning |
|---|---|
| `request_rejected` | one per refusal, retryable or final: `status`, `code`, `path`, `retry_after`, bounded `detail` |
| `upstream_unavailable` | an upstream 5xx or 408 on a Responses turn, answered 503 |
| `client_disconnected` | the client hung up mid-stream; previously counted as `transport_error` |
| `upstream_rate_limited` | an upstream 429, with `category` `quota`, `auth` or `transient`; on Responses a quota 429 answers 400 `PROVIDER_REJECTED` and an auth 429 opens the key window; a subscription turn's `transient` 429 answers 503 naming the model and the subscription |
| `turn_refused` | a turn refused before any upstream call for its size (`BODY_TOO_LARGE`, `INVALID_REQUEST_SIZE`), with compressed, decoded, limit and prepared bytes plus counts and byte weight per carried class and images; no content |
| `turn_trimmed` | an oversized routed turn was reduced with visible notes; names the bytes dropped and how many images and tool outputs were replaced |
| `usage_reported` | a routed Codex turn carrying tools had its reported input tokens raised to what the thread carries (never lowered); names the provider's figure and the reported one |
| `wire_contract` | observe only: a prepared Responses body broke a rule learnt from an earlier upstream refusal (the check never changes or blocks the request); names each rule under `violations` or `warnings` with a count, plus up to eight unknown top-level field names (`error_type` instead when the check itself failed); refusal lines carry the same rules, pairing under `pair_problems` and the rest as `contract_violations` and `contract_warnings`; no content |

## Request identity and failure evidence

Resolve the installed release from its `current` pointer, then run the command
(macOS/Linux shown; use the corresponding router home on Windows):

```sh
router_home="$HOME/.codex/mixed-model-router"
cd "$router_home/releases/$(basename "$(cat "$router_home/current")")"
python3.14 -m ai_router.inspect_requests --minutes 60
python3.14 -m ai_router.inspect_requests --request-id <request-id> --json
python3.14 -m ai_router.inspect_requests --model <model-id> --identity mismatch
```

The command reads completed request chains from the existing four rotated
logs. It makes no model call and loads no credentials. `--minutes 0` includes
all retained records; `--limit` accepts 1–100. Identity filters also accept
`unverified` and `contradictory`. Logs from earlier versions may lack evidence.

Each send records the requested, resolved and upstream IDs separately from
provider reports, including their header or response-field source. Reports
survive later read errors, and a retry starts fresh. Missing or unreadable
identity stays unverified. A mismatch means the reported ID differs literally;
native aliases or snapshot names may explain it. A provider report is not
independent proof of the weights executed. `/health served_models` remains a
last-observed cache and never attests the selected request.

Attempt outcomes describe the observed upstream or transport ending. The
request outcome also reflects delivery and recovery, which can preserve the
first terminal after a later attempt fails. Timings name connect, send, headers
and actual read calls; read wait includes response consumption and must not be
presented as provider compute time. Age, time since the last upstream data,
socket timeout, commitment and retry decisions help distinguish failures.
Write failures are identified separately; a broken client connection is a
cancellation, while an upstream read failure remains a transport failure.
Service restart remains separately recorded by `draining`, `exit` and
`router_started`; an abruptly terminated request may have no final chain.
Prompts, tool data, credentials and raw error bodies are excluded.

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

The attachment also manages Codex settings beyond the connection lines. A
fresh install seeds `model = "deepseek/deepseek-v4.1-flash"` and
`model_reasoning_effort = "max"` inside the managed block; Codex writes the
owner's later pick into those same lines, and an update carries it forward
instead of resetting it. In the config's `[desktop]` table it sets
`followUpQueueMode = "steer"`, so a message sent while a turn runs steers it
instead of queueing, and `enabled-reasoning-efforts`, the client's own list
with `max` added and `ultra` removed. Ultra is Codex's automatic-delegation
level and the served catalogue never offers it, so the picker cannot show it
even if a client default reintroduces it. The managed block also carries
`approvals_reviewer = "user"` in both modes, so installs never fall back to
the background reviewer. An owner root line that sets any key the block
sets (`approvals_reviewer`, or `model_provider` in no-subscription mode) is
set aside on attach, recorded in the activation receipt's `reviewer`
record, and restored on detach, one line per key; a key inside an owner
table, such as a profile's own `model_provider`, is never touched. Detach,
`--client none` and uninstall put the desktop values back as the attach
found them, and a value the owner changed afterwards is left alone. A `[desktop]` table or value the
installer cannot rewrite safely skips that edit with one line of output
rather than risk a second definition or a mangled value.

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
or `thread_title_reconsideration`. Client 0.154 also puts the read-only app
tool allowlist it derives from the installed apps and MCP servers on those
turns, so a helper turn carries tools; they do not make it ineligible.
When the ChatGPT allowance is exhausted upstream refuses those turns, and
the client stores a slice of the prompt as the title instead. The fallback
is on unless `openai_helper_fallback` is explicitly false in
`mixed-router-state.json` (restart the service to load a change): a 429 on
such a turn is answered from the OpenRouter twin row `openai/<slug>`, or
from the Luna twin `openai/gpt-6-luna` when the requesting slug has no
twin of its own, and logged as `subscription_fallback`, or as
`subscription_fallback_unavailable` when the twin cannot be prepared (no
OpenRouter key, for example), which keeps the existing 503. An exhausted
subscription also answers helper turns 401; those take the same twin path,
while ordinary turns keep the raw upstream answer so a sign-in problem
stays visible. Every other
turn keeps that 503 unchanged. A provisioned portco list still gates the
twin: an excluded twin row is never used, so the helper path stays inside
the same allowlist as a directly requested OpenRouter row.
The twin answers the client's own payload, tools included, so the helper
thread keeps the tools its client granted it. The fallback means the
helper prompt reaches OpenRouter and bills that key, and the helper marker
is a client header: any local process holding the loopback path token can
present a helper-shaped turn and have its prompt answered - and billed - by
an allowed twin. It grants no other rerouting.

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
is spawned without a window; on every platform, a file under `logs/` is
deleted 30 days after its last write, at each service start and scheduled
update, apart from the live files, which keep their caps.

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
Subscription picker gate removed (Plan 178): the twin swap left an
OpenRouter-billed row wearing the subscription row's name, and the picker
only reloads when the client starts. Every subscription row is listed
again, with its twin beside it, and an exhausted row answers the refusal
message instead of moving.

## One-time cleanup after 0.4.0

Delete from the state directory on the author's machine:
`compatibility-release.json`, the `before-*` folders,
`config-before-*.toml`, `stdout.log`, `stderr.log`, and `retired/` after
one week. Keep `mixed-router-state.json`, `activation.json`,
`openrouter.key`, `current`, `releases/`, and `logs/`.
