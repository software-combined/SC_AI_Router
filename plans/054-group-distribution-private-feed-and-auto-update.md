# Plan 054: Group distribution, private feed and push-to-main auto-update

> Planning only. No AWS resource creation, DNS or certificate change, GitHub
> organisation plan change, workflow publication, live updater change,
> staff-machine install or release is authorised by this document. Each is a separate owner gate listed below.

Priority P1; effort L; risk HIGH (fleet-wide code execution path).
Planned 2026-09-09 at `1327da3f369eb1af82a3b29c6544f51f3d1049cd`.

## Outcome

Any staff member at Software Combined or a portfolio company opens one
identity-gated page, downloads one file for their OS, runs it, and from then on
their router updates itself from a private feed every time `main` changes. No
GitHub account, no `gh`, no manual Python install, nothing publicly reachable.

First observable proof (Stage 1): a merge to `main` produces a new version on
the owner's Mac within 15 minutes; `update.log` shows the install came from the
CloudFront feed with a token and without `gh`; `/health` reports the new
version; `launchctl print` shows the loaded updater job running the launcher.

## Owner decisions this plan builds to

Recorded before or during planning; this plan does not reopen them.

| Decision | Source |
|---|---|
| Feed in AWS `651116729473`, `ap-southeast-2`: private S3 origin behind CloudFront HTTPS, stable/beta feeds, immutable versioned bundles | Plan 049 §2; `plans/README.md` 047 row (owner 2026-09-09) |
| Feed signatures not enforced; checksum, serial, manifest and version-identity checks retained; access to feed publication is the trust boundary | Plan 049 §2; `CHANGELOG.md` |
| Native pinned CPython 3.14 from `python-build-standalone`, one checked-in runtime lock; no package manager, no `curl \| sh`, no system Python or PATH change, no execution-policy bypass, no quarantine removal | Plan 049 §2 |
| macOS LaunchAgents, Windows per-user Task Scheduler, Linux systemd user units; no root, no stored Windows password, no lingering | Plan 049 target table |
| `main` publishes straight to `stable` on every push | Owner, 2026-09-09 (this plan) |
| Runtime downloads are not publicly reachable: reads are token-gated | Owner, 2026-09-09; supersedes the publicly reachable HTTPS runtime downloads that Plan 053 attributes to 049 |
| Per-user OpenRouter keys, provisioned centrally and delivered by this plan's bootstrap, never displayed | Plan 055 (owner 2026-09-09), superseding Plan 048's paste-once decision |

## Verified current state (2026-09-09, read-only)

| Check | Observed |
|---|---|
| Live updater, owner Mac | Router runs `0.6.7.19` (local install 2026-09-09 10:24 AEST) and is healthy. `com.local.codex-mixed-model-router.update` is loaded but its plist still executes the `0.6.6.18` installer, so it exits 1 every 900 s; no `feed-serial` file exists |
| Failure | `HTTP 404` raised at `service.py:234` in `fetch_feed`: anonymous `urlopen` of a private GitHub Releases URL. `0.6.6.18` predates the authenticated path |
| Fix status | `github_asset()` and `fetch_feed` routing shipped in release `0.6.7.19` (release tag `v0.6.7.19`, trigger tag `v0.6.7`, published 2026-09-09T00:22Z from `origin/main` `83ef008`). The owner Mac's scheduled updater has not picked it up because the old updater cannot fetch anything: the fix is in the fetch path |
| `gh`, owner Mac | 2.91.0, signed in with `repo` scope; reads the private release assets |
| Signature code | `feed_verify.load_signed_feed` and `checked_feed` have no callers outside tests; `FEED_PUBLIC_KEY` empty; `release.yml` never signs. Consistent with the owner decision |
| `release.py` | Accepts `--url-base`; version is `packaging/VERSION` plus run number; `serial` is the run number |
| GitHub | Org plan `free`, 6 seats; repository private; branch protection and rulesets return 403 "Upgrade to GitHub Pro" |
| Repository write access | `SC-Cyril`, `BrentJMaxwell`, `JackSoftcom` (admin); `gbane-softcom` (write); `puja-sc` (read) |
| AWS | GitHub OIDC provider `token.actions.githubusercontent.com` exists; Route 53 zone `softwarecombined.com` (`Z0272966357LH6IEJY0NV`) plus `.com.au`, `.au`, `.co.nz`, `.nl`, `.eu`; no feed bucket yet; SES production access enabled, `softwarecombined.com` and `softwarecombined.com.au` verified with DKIM |
| Windows | No updater or service manager; `install.ps1` is a thin wrapper; `systemd_manager` returns `None` off Linux and the fallback calls `launchctl` |
| Linux | systemd user units integrated (PR 3); staff-machine acceptance pending |
| Python | `MIN_PYTHON = (3, 14)`; `find_python` probes `compression.zstd`; a fresh Mac ships 3.9 |

## Trust boundary, stated plainly

With signatures out by decision, the only publisher authentication is who can
write the feed. Publication is triggered by a push to `main`, and on the free
plan `main` cannot be protected. The effective trust boundary is therefore the
four GitHub accounts with write access plus the AWS principals allowed to write
the bucket. Controls that keep it tight:

- OIDC role trust names exactly this repository (name and repository ID) and
  `ref:refs/heads/main` for stable and `ref:refs/heads/develop` for beta. No
  wildcard subjects. Verify the current claim format before writing the policy
  (Plan 049 §2).
- Bucket policy allows `s3:PutObject` only from the publish role and grants no
  delete permission; bundles are immutable and `latest.json` is overwritten,
  never deleted. No human write principals. Block Public Access on. Versioning
  on so a bad publish is recoverable. CloudTrail data events on the bucket.
- Publish only after the full unit-test suite passes (already in `release.yml`).
- Convention: `main` receives PR merges only. The workflow may soft-check that
  the head commit is a PR merge; a direct pusher can also edit the workflow, so
  this is hygiene, not a control.
- The read token is a confidentiality control only. Leaking it discloses the
  bundle; it cannot inject code. It must never authorise anything else: in
  particular Plan 055 key issuance requires a per-install credential from
  Stage 4, never this shared value.

Resolved 2026-09-09 on owner delegation, in two parts, both to be recorded in
the `docs/operations.md` decision log:

1. **Move the organisation to GitHub Team before Stage 1 publishes to
   `stable`.** Branch rules cannot be applied to private repositories on the
   free organisation plan, and rulesets need Pro, Team or Enterprise, which is
   why this repository's protection and ruleset endpoints both answer 403.
   Team is the cheapest plan that makes a pushed commit reviewable before it
   executes on every machine in the group, at roughly USD 4 per user per month
   for 6 seats; confirm the current figure on GitHub's pricing page, as the
   published rate has moved before. Then require a pull request and the
   existing `Test` check on `main`, **with an empty bypass list and enforcement
   for administrators**. Without that, the rule closes nothing here: after part
   2 the three remaining writers are all admins, and admins bypass branch
   protection by default and can edit or delete a repository ruleset, so the
   direct-push path stays open. Apply the same to tags if the fallback below is
   used, since `push tag v*` remains a publish trigger. With the bypass closed,
   this is what makes the owner's `main`-publishes-`stable` decision defensible
   rather than merely accepted; if the owner declines the plan change, the
   fleet-wide unreviewed-push risk stays open and accepted.
2. **Reduce the writer set now, at no cost.** `gbane-softcom` holds write
   without admin; drop that to read or triage unless there is a current reason
   to push, leaving three admins. Least privilege applies whether or not the
   plan changes.

If the owner declines the plan change, the fallback that preserves the same
safety is to publish `stable` from a tag and leave `main` publishing `beta`
only; that contradicts the recorded decision, so it stays a fallback, not the
design.

## Design

### 1. Feed layout

One bucket in `ap-southeast-2`, name fixed at provisioning, versioning on,
Block Public Access on, reads only through CloudFront Origin Access Control.

| Key | Cache | Notes |
|---|---|---|
| `stable/latest.json`, `beta/latest.json` | `max-age=60`, ETag preserved | existing `fetch_feed` 304 revalidation keeps 15-minute polls cheap |
| `bundles/codex-model-router-<version>.tar.gz` | `immutable, max-age=31536000` | never overwritten; `release.py` output unchanged |
| `runtime/<os>-<arch>/<pbs-filename>` | immutable | mirrored `python-build-standalone` install-only CPython 3.14, pinned by URL and SHA-256 in `packaging/runtime.lock` (Plan 049 §2); licences retained |
| `bootstrap/install.sh`, `bootstrap/install.ps1` | `max-age=300` | download-then-run entry points (§5) |

Hostname `dist.softwarecombined.com`, decided 2026-09-09 on owner
delegation: one host serves the feed, bundles, pinned runtimes and bootstrap
scripts, so one ACM certificate, one distribution, one function and one DNS
record cover the lot, and a later public `/install` path can share it rather
than needing a second name. ACM certificate in `us-east-1`, DNS-validated in
the existing `softwarecombined.com` zone (`Z0272966357LH6IEJY0NV`).
`feed_verify.beta_feed_url` derives `<origin>/beta/latest.json`, which is
correct on a dedicated origin and removes today's `https://github.com/beta/`
mis-derivation.

### 2. Read access: token header checked at the edge

A viewer-request CloudFront Function looks the header `X-SCG-Feed-Token` up in
a CloudFront KeyValueStore and returns 403 otherwise. No AWS credentials, IP
allowlists or AWS CLI on hosts. Tokens are random 32-byte values, stored as
KVS *keys* so a lookup is one operation and retiring one token is a single key
deletion; the store holds one or more active tokens so rotation overlaps.

The function must fail closed. `kvs.get()` raises when a key is absent, so the
handler returns 403 on a missing header, an absent key and any lookup error,
and never falls through to the origin. Constraints that shape it, verified
2026-09-09: JavaScript runtime 2.0 is required, one key value store may be
associated per function, keys are capped at 512 bytes and values at 1 KB, and
an updated store propagates to edge locations within seconds, which is what
makes revocation immediate.

Hosts keep the token at `<home>/feed-token` (mode 0600), written by the
bootstrap at first install. `latest.json` carries the current value as
`feed_token`; the updater refreshes the file on every successfully read feed,
not only on install, keeps the previous value beside it and retries a 403 once
with that previous value (§4). Rotation: add the new value to the store,
publish `latest.json` carrying it, wait at least one full poll cycle for the
fleet plus the overlap you choose, then retire the old value. A host offline
for the whole overlap re-runs the bootstrap. Rotation is a security-event
action, not routine.

The token never appears in the repository or in GitHub secrets. The publish
workflow reads it from the KeyValueStore through the OIDC role at build time and
passes it to `release.py` for `latest.json`. Never log it (Plan 050 rule).

### 3. Publish on push: GitHub Actions, no stored keys

`release.yml` becomes branch-driven:

| Trigger | Channel | Notes |
|---|---|---|
| `push` to `main` | `stable` | owner decision; every merge publishes |
| `push` to `develop` | `beta` | early channel for the owner without changing the stable rule; hosts opt in through the existing `channel` file |
| `push` tag `v*` | optional | tags remain available for provenance; the tag-equals-VERSION check applies to tags only |

Steps: checkout, Python 3.14, `unittest`, `aws-actions/configure-aws-credentials`
(OIDC `role-to-assume`), read token from the store, `release.py --out dist
--build $GITHUB_RUN_NUMBER --sha $GITHUB_SHA --channel <c> --url-base
https://dist.softwarecombined.com/bundles --feed-token-file <tmp>`, upload
the bundle (immutable), upload `latest.json` (short cache), invalidate
`/<channel>/latest.json`. Runtime archives upload only when `runtime.lock`
changes, so updates never re-download an unchanged interpreter.
`GITHUB_RUN_NUMBER` remains the monotonic `serial` for `check_serial`; both
channels live in one workflow so the counter is global. Moving a host from
`beta` back to `stable` requires clearing `<home>/feed-serial` first, because
`check_serial` refuses the lower stable serial with a hard error on every poll
until stable overtakes it; the runbook records this step.

### 4. Updater changes (`packaging/service.py`, `packaging/install.py`)

- `FEED_URL` becomes `https://dist.softwarecombined.com/stable/latest.json`.
- `TRUSTED_ORIGINS` replaces the `RELEASES_PREFIX` gate: any feed or bundle URL
  off the trusted origin (or `file://` in tests) is refused before fetch.
- One shared request builder adds `X-SCG-Feed-Token` from `<home>/feed-token`
  to every trusted-origin request, in both `fetch()` and `fetch_feed`, which
  otherwise builds its own conditional request; `fetch_feed` keeps ETag
  revalidation.
- Persist `latest['feed_token']` after every successfully read and
  serial-checked feed, before the version comparison, keeping the previous
  value in `<home>/feed-token.previous`; on a 403 retry once with the previous
  value and restore it when it works. A host that is already current therefore
  still picks up a rotated token.
- The updater job launches through the release-independent launcher that
  already serves the router agent (`router_launch.py` resolves `<home>/current`
  at exec time), given a `--check-update` entry point, instead of a
  release-specific `install.py` path. Today `render_update_plist` bakes in
  `current_release_dir(home)`, and launchd keeps that loaded definition after
  an upgrade: `restart_service` bootstraps the updater only when it is missing
  and `reload_main_service` reloads the router agent only (`service.py:5-6`,
  `277-306`), so a host keeps running the previous release's poller until its
  next login. Reloading from inside the child installer is not an option: a
  `bootout` of the update job would terminate the running poller and the
  installer with it. With the launcher, the loaded job never goes stale on any
  of the three supervisors.
- Keep `github_asset()` for exactly one transitional release, then remove it.

Migration for installed hosts: Stage 0 restores updates over `gh`. After Stage 1
infrastructure exists, one transitional release T is published to both the
GitHub Releases feed (the last GitHub release) and the CloudFront feed. T keeps
`FEED_URL` on GitHub Releases, sends the token header, persists `feed_token`
from any successfully read feed, and resolves the CloudFront feed in
`channel_feed` only once `<home>/feed-token` exists. On a host: the old updater
fetches the GitHub `latest.json` (which carries `feed_token`) over `gh` and
installs T; T's child installer also resolves the GitHub feed, so no token is
needed yet; T's first poll reads the GitHub feed once more, persists the token,
and every later poll resolves CloudFront. T also carries the launcher-based
updater job; an existing macOS host runs T's poller only after its next login,
or after one more `bootout`/`bootstrap` of the update label (the Stage 0
runbook entry, re-run once T has installed), because launchd keeps the pre-T
job definition until then. Late migrators still find T on GitHub. `github_asset()` is removed in a later release after the owner confirms
the known hosts have migrated; a rotation before that point also re-publishes
T's GitHub `latest.json` with the new value. No reinstall.

### 5. First install: download a file, run it

Plan 049 §2 already requires the shell and PowerShell wrappers to run without
Python. This plan gives them a home and a source. `install.sh` (macOS, Linux)
and `install.ps1` (Windows):

1. Take the feed token from an environment variable or the value embedded by
   the download page; write `<home>/feed-token`.
2. Download the matching CPython 3.14 archive from the feed using pin data
   generated from `packaging/runtime.lock`; verify SHA-256 with `shasum`,
   `sha256sum` or `Get-FileHash`; install under `<home>/runtime/<sha>/`; verify
   `compression.zstd`. Reuse a verified suitable Python when present.
3. Download `stable/latest.json`, then the bundle; verify the checksum; run
   `packaging/install.py` from the verified bundle with that interpreter.

The user downloads the file and runs it (`sh install.sh`; Windows see below).
Nothing is piped from the network into a shell, no execution policy is bypassed
and no quarantine attribute is removed. A downloaded `install.sh` runs under
`sh` without Gatekeeper interaction.

Windows open item: a downloaded `.ps1` will not run under the default
`Restricted` policy or under `RemoteSigned` while it carries the download mark,
and 049 forbids bypassing either. On Windows the plugin lane (§7) is therefore
the primary entry; `install.ps1` serves users whose machines already permit
local scripts. A signed script would remove the friction and needs the deferred
code-signing decision. Resolve before Stage 3 acceptance.

### 6. Three operating systems

| OS | Router service | Updater | Status |
|---|---|---|---|
| macOS | LaunchAgent via `router_launch.py` (exists) | LaunchAgent, 900 s (exists, release-specific path) | router works; the loaded updater job goes stale after an upgrade until next login (§4 fix), which is the live state on the owner Mac |
| Linux | systemd user units (PR 3) | systemd user timer (PR 3) | integrated; staff acceptance pending (Plan 049) |
| Windows 11 x64 | per-user Task Scheduler task at logon | per-user Task Scheduler task, 15 min | new: `packaging/windows.py` `Manager` mirroring `systemd.Manager`; `install.py` selects by platform; no admin, no stored password; both tasks run the stable launcher so upgrades never re-register them |

### 7. Onboarding surface

Stage A, no new authentication code: an identity-gated page in the wider-team
SharePoint (`~/TechnologyIT`, the authoritative IT document location) hosts
`install.sh`, `install.ps1` and the three-OS instructions with the current
token embedded. Microsoft 365 sign-in is the email and domain gate. Portfolio
company staff outside the tenant join as guests or receive the page through
their own channel.

Stage B, optional and later: self-serve `dist.softwarecombined.com/install`
(the same host and certificate, an ungated path in front of the token gate)
with an email-domain allowlist and SES one-time codes (production access and
DKIM are in place), issuing per-install tokens into the KeyValueStore with a
DynamoDB audit row. Adds per-user revocation and cross-tenant onboarding
without changing the runtime or the feed.

Plan 049's plugin lane (`scg-openrouter`, `manage-router`) stays a parallel
entry point that calls the same bootstrap and the same feed.

## Stages, proofs and gates

| Stage | Work | Proof | Gate |
|---|---|---|---|
| 0 | Re-point the owner Mac's updater LaunchAgent at the `0.6.7.19` installer: while the update job is not running, rewrite `ProgramArguments[1]` in `~/Library/LaunchAgents/com.local.codex-mixed-model-router.update.plist` to `<home>/releases/0.6.7.19/packaging/install.py`, then `launchctl bootout gui/<uid>/com.local.codex-mixed-model-router.update` and `launchctl bootstrap gui/<uid> <that plist>`. Touch only the update agent, never the router agent (`docs/operations.md:44`); add these steps to `docs/operations.md` as a runbook entry. A host still on `0.6.6.18` needs one local install of `0.6.7.19` first; its updater cannot pull the fix because the fix is in the fetch path | `launchctl print gui/<uid>/com.local.codex-mixed-model-router.update` names the `0.6.7.19` installer; `update.log` shows `up to date 0.6.7.19` over `gh`, no 404; last exit 0 | staff-machine action (owner) |
| 1 | AWS: bucket, OAC, CloudFront, function and KeyValueStore, publish role, ACM, DNS. Repo: branch-driven `release.yml`, `release.py --feed-token-file`, updater §4 (origins, token, launcher-based job), transitional release; once T has installed on the owner Mac, re-run the Stage 0 runbook entry (bootout and bootstrap the update label while the job is not running) so the launcher-based job loads | a merge to `main` reaches the owner Mac within 15 min via CloudFront with token and without `gh`; `launchctl print` shows the loaded updater job running the launcher, not a release path | AWS creation, DNS and ACM, GitHub organisation plan upgrade (owner, recurring spend), publication cutover (owner) |
| 2 | `runtime.lock`, runtime mirror, real `install.sh` and `install.ps1` (§5), SharePoint page | a clean Mac without Python 3.14 installs from the page and auto-updates; then Linux on the contributor's machine | staff-machine changes (Plan 049) |
| 3 | `packaging/windows.py`, Task Scheduler updater, Windows entry decision (§5) | the designated Windows 11 x64 machine installs and auto-updates | Windows machine designation and entry decision (owner) |
| 4 (optional) | self-serve email-OTP page, per-install tokens, audit | a portfolio company user onboards with no Software Combined account; revoking their token stops their updates | account and domain approval (owner) |

Each stage is its own PR under 500 changed lines of logic. Infrastructure is
applied by CLI with the exact commands added to `docs/operations.md` as each
stage lands, then read back before the repository change that depends on it is merged. Running
cost at this scale is a few dollars a month.

## Verification

- Unit: `TRUSTED_ORIGINS` refuses off-origin feed and bundle URLs; the token
  header is present on the feed request itself (`fetch_feed`) and on bundle
  requests, only for the trusted origin, and never logged; `feed_token` is
  refreshed on a successful feed read with no install, the previous value is
  kept, and a 403 falls back to it once; `release.py` emits `feed_token` only
  when given a file; stale serial, checksum mismatch and manifest mismatch
  leave the working install unchanged. Existing tests extended; no network.
- Workflow: a `develop` push publishes to `beta/` and a `main` push to
  `stable/`; the bundle object is immutable; `latest.json` is invalidated; the
  runtime upload is skipped when the lock is unchanged.
- Edge: no token gives 403; a retired token gives 403; an active token gives 200
  with ETag and 304 on revalidation.
- Host: live readback, because a stale poller prints `up to date` and exits 0
  exactly like a healthy one: `launchctl print` shows the loaded updater job
  running the launcher for the current release; owner Mac `update.log` shows
  the CloudFront read and no `gh` call (the `run` seam in tests; the log field
  allowlist live).
- Recovery: a forward revert (new higher-serial release) reaches a host that
  already installed the bad version; a beta host moved to stable updates again
  after `feed-serial` is cleared; the transitional release T migrates a host
  from the GitHub feed to CloudFront without a reinstall (synthetic feeds).
- Bootstrap: a wrong-platform or wrong-checksum runtime never executes; a second
  run does not re-download the interpreter.

## Risks and accepted trade-offs

| Risk | Handling |
|---|---|
| A bad merge to `main` reaches every host within 15 min (owner-accepted) | tests gate publish; the installer does not activate a release whose `/health` does not come up; `wait_idle` defers busy routers; `develop` to `beta` lets the owner see builds first. Fleet recovery is forward-only: publish a new, higher-serial release that reverts the change. Restoring an older `latest.json` is refused by `check_serial` as stale, and a per-machine `do_rollback` is undone by the next poll, so neither recovers the fleet; S3 versioning only keeps prior artefacts for the forward revert |
| Bucket write compromise or policy mistake publishes unsigned code (owner-accepted by the signature decision) | OIDC-only writes, no human write principals, CloudTrail data events, versioning; revisit if the write boundary widens |
| Token leak | read-only exposure of the bundle; rotate through the store and `latest.json` |
| Four write-access accounts, no branch protection on the free plan | open owner decision above |
| `python-build-standalone` mirror | pinned URL and SHA-256, licences retained, install-only builds; unqualified architectures refused (Plan 049) |
| Windows is new lifecycle code and has the entry-point open item | separate stage, designated machine, no admin or stored credentials |
| The loaded macOS updater job goes stale after an upgrade (pre-existing installer behaviour, live on the owner Mac) | launcher-based updater job (§4) removes the need to reload; existing hosts pick it up at next login or by re-running the Stage 0 runbook entry once T has installed; Stage 0 and Stage 1 proofs read back the loaded job |

## Out of scope

Signing-key ceremony or signature enforcement (owner decision); plugin
marketplace hosting (Plan 053); Codex and Claude client configuration (Plan
051); paid probes (Plan 052); WSL, Windows ARM, musl and headless servers (Plan
049).
