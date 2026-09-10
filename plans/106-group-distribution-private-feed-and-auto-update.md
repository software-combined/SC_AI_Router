# Plan 106: Group distribution, private feed and push-to-main auto-update

> **Consolidation 2026-09-09 at `96db57f`:** the owner-Mac recovery described in
> Stage 0 is historical. Current readback is healthy `0.6.9.22`, both jobs
> loaded, router/update jobs using stable launchers, updater interval 900.
> Reconcile and skip an already satisfied repair; never re-point to `0.6.7.19`
> just to replay the old procedure. Feed-token/CloudFront and branch-publishing
> work remain pending; current source is still tag-driven/private GitHub.
>
> Execution ownership: 067 extracts the updater, 056 supplies platform
> backends, 116 supplies `packaging/platforms/windows.py`, 105 supplies the
> single runtime lock/native bootstrap, 117 supplies recipient preflight/docs,
> and 063 supplies shared client activation. Reuse these pieces in Stages 1-3.
> Source/synthetic checks do not wait for cloud publication. Stage 4 identity
> and per-install authority must precede 107 Stage 4 automated key issuance.
> Stable-launcher work is already implemented; verify it rather than duplicate.

> Planning only. No AWS resource creation, DNS or certificate change, GitHub
> organisation plan change, workflow publication, live updater change,
> staff-machine install or release is authorised by this document. Each is a separate owner gate listed below.

Priority P1; effort L; risk HIGH (fleet-wide code execution path).
Planned 2026-09-09 at `1327da3f369eb1af82a3b29c6544f51f3d1049cd`.
Updated 2026-09-09: Entra group download gate, B2B guest path, and canonical AWS endpoints recorded (owner discussion).

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
| Feed in AWS `651116729473`, `ap-southeast-2`: private S3 origin behind CloudFront HTTPS, stable/beta feeds, immutable versioned bundles | Plan 112 §2; `plans/README.md` removal log, 047 (owner 2026-09-09) |
| Feed signatures not enforced; checksum, serial, manifest and version-identity checks retained; access to feed publication is the trust boundary | Plan 112 §2; `CHANGELOG.md` |
| Native pinned CPython 3.14 from `python-build-standalone`, one checked-in runtime lock; no package manager, no `curl \| sh`, no system Python or PATH change, no execution-policy bypass, no quarantine removal | Plan 112 §2 |
| macOS LaunchAgents, Windows per-user Task Scheduler, Linux systemd user units; no root, no stored Windows password, no lingering | Plan 112 target table |
| `main` publishes straight to `stable` on every push | Owner, 2026-09-09 (this plan) |
| Runtime downloads are not publicly reachable: reads are token-gated | Owner, 2026-09-09; supersedes the publicly reachable HTTPS runtime downloads that Plan 114 attributes to 112 |
| Per-user OpenRouter keys, provisioned centrally and delivered by this plan's bootstrap, never displayed | Plan 107 (owner 2026-09-09), superseding Plan 048's paste-once decision |

## Historical planning snapshot (2026-09-09, read-only)

The owner-Mac rows below predate the `96db57f` consolidation readback. Use
the current evidence at the top of this plan; do not execute an old repair.

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
  (Plan 112 §2).
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
  particular Plan 107 key issuance requires a per-install credential from
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
| `runtime/<os>-<arch>/<pbs-filename>` | immutable | mirrored `python-build-standalone` install-only CPython 3.14, pinned by URL and SHA-256 in `packaging/runtime.lock` (Plan 112 §2); licences retained |
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
passes it to `release.py` for `latest.json`. Never log it (Plan 108 rule).

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
- Preserve the implemented `update_launch.py` contract: resolve the active
  release at each invocation, then run its installer with `--check-update`.
  It is distinct from `router_launch.py`; do not merge their roles. Older
  loaded jobs may still need one external reload, but the owner Mac already
  uses the stable updater launcher. Never boot out a running update job from
  its child installer. Plans 067/056/116 preserve this across supervisors.
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

Plan 112 §2 already requires the shell and PowerShell wrappers to run without
Python. This plan gives them a home and a source. `install.sh` (macOS, Linux)
and `install.ps1` (Windows):

1. Run 117's native no-Python prerequisite and platform preflight before
   changing disk state. Take the feed token from the authorized delivery
   surface; write it through the shared protected-file contract.
2. Download the matching CPython 3.14 archive from the feed using pin data
   generated from `packaging/runtime.lock`; verify SHA-256 with `shasum`,
   `sha256sum` or `Get-FileHash`; install under `<home>/runtime/<sha>/`; verify
   `compression.zstd`. Reuse the verified managed runtime when present; a
   system interpreter is only an explicit qualified override under 105.
3. Download `stable/latest.json`, then the bundle; verify the checksum; run
   `packaging/install.py` from the verified bundle with that interpreter.

The canonical download endpoints, served from the Stage 1 feed and
republished on every push to `main` (section 3):

- `https://dist.softwarecombined.com/stable/latest.json`
- `https://dist.softwarecombined.com/bundles/codex-model-router-<version>.tar.gz`
- `https://dist.softwarecombined.com/runtime/<os>-<arch>/<pbs-filename>`
- `https://dist.softwarecombined.com/bootstrap/install.sh`
- `https://dist.softwarecombined.com/bootstrap/install.ps1`

Every endpoint above is token-gated (section 2): the installer sends
`X-SCG-Feed-Token` on each request, so an AWS link alone never authorises
a download. Entra groups (section 7) decide who receives the page that
carries the token, not the bytes.

The user downloads the file and runs it (`sh install.sh`; Windows see below).
Nothing is piped from the network into a shell, no execution policy is bypassed
and no quarantine attribute is removed. A downloaded `install.sh` runs under
`sh` without Gatekeeper interaction.

Windows entry remains an acceptance gate: inspect the designated machine's
actual policy and download marking. A plugin invoking the same refused script
does not establish a usable entry. Reuse 116's policy-compliant entry decision;
do not bypass policy or remove the mark. If the permitted unsigned path is
insufficient, prepare the exact alternative for the owner before Stage 3
acceptance, without silently reopening the code-signing decision.

### 6. Three operating systems

| OS | Router service | Updater | Status |
|---|---|---|---|
| macOS | LaunchAgent via `router_launch.py` | LaunchAgent via `update_launch.py`, 900 s | both stable launchers observed loaded; private-feed update acceptance remains |
| Linux | systemd user units (PR 3) | systemd user timer (PR 3) | integrated; staff acceptance pending (Plan 112) |
| Windows 11 x64 | per-user Task Scheduler task at logon | per-user Task Scheduler task, 15 min | consume 116's `packaging/platforms/windows.py` behind 056's manager contract; no admin/stored password; stable launcher contracts |

### 7. Onboarding surface

Stage A, no new authentication code: the joiner flow is add-to-Entra,
send-link, install. One parent Entra security group (for example
`sg-SCG-Router-Users`) plus one subgroup per portfolio company (for example
`sg-SCG-Router-<Portco>`) controls access to an identity-gated download page in the
wider-team SharePoint (`~/TechnologyIT`, the authoritative IT document
location). The page links the AWS bootstrap endpoints (section 5) with the
current feed token embedded. The downloaded installer pulls the runtime and
the bundle from CloudFront, and every later update polls the same feed.
Microsoft 365 sign-in is the email and domain gate.

Guests: portfolio company staff whose mailboxes live outside Microsoft 365
(for example on Google Workspace) are invited as Entra B2B guests on their
work address and redeem with email one-time passcode. Neither Google federation
nor adding a non-Microsoft domain to Entra is needed. Grant each portco
subgroup directly to the download site rather than relying only on nesting.
When the TechnologyIT page must stay staff-only, host the portco download
on a separate site collection with guest sharing on, or route that portco
through its own channel.

Offboarding boundary: removing a user from the Entra group stops future
downloads only. It does not stop their updater while the shared Stage A feed
token is valid, and it does not stop their spend. The leaver path is remove
from the subgroup, rotate the feed token when warranted, and delete that
user's OpenRouter key by id (Plan 107). Per-install tokens and central key
revocation remain the real offboarding control in Stage 4.

Stage B, optional and later: self-serve `dist.softwarecombined.com/install`
(the same host and certificate, an ungated path in front of the token gate)
with an email-domain allowlist and SES one-time codes (production access and
DKIM are in place), issuing per-install tokens into the KeyValueStore with a
DynamoDB audit row. Adds per-user revocation and cross-tenant onboarding
without changing the runtime or the feed.

Plan 112's plugin lane (`scg-openrouter`, `manage-router`) stays a parallel
entry point that calls the same bootstrap and the same feed.

## Stages, proofs and gates

| Stage | Work | Proof | Gate |
|---|---|---|---|
| 0 | Read back current service/updater with 108; skip already satisfied repairs. Only a genuinely old loaded job receives a prepared, separately authorized external reload, never a re-point to a historical version | correct active version, healthy service, stable loaded launchers; no mutation from a stale snapshot | read-only first; actual repair is owner-gated |
| 1 | AWS bucket/OAC/CloudFront/KVS/publish role/ACM/DNS; branch workflow, release token input, origin/token updater, transitional migration. Reuse existing stable launchers; reload only a verified old host from outside its job | merge to main reaches owner Mac within 15 min through token-gated CloudFront, without gh; loaded updater uses update_launch.py | AWS/DNS/ACM, Team recurring spend and publication/cutover authority |
| 2 | `runtime.lock`, runtime mirror, real `install.sh` and `install.ps1` (§5), Entra parent plus per-portco subgroups, SharePoint page (§7) | a joiner added to a portco subgroup installs a clean Mac without Python 3.14 from the page and auto-updates; then Linux on the contributor's machine | staff-machine changes (Plan 112) |
| 3 | Consume 116's Windows manager and 105's bootstrap; validate actual entry policy | designated Windows 11 x64 machine installs and auto-updates | Windows target and entry authority |
| 4 (later, required for complete 107) | self-serve email-OTP page, per-install tokens, audit | portfolio user onboards; per-install revocation stops updates; identity can authorize 107 issuance | account/domain authority; not a Stage 1 prerequisite |

Split stages into coherent PRs under the applicable commit limits. Source and
synthetic/infrastructure validation may integrate before production resources
exist; do not activate a workflow against an absent target. Prepare exact
commands and rollback in `docs/operations.md`, obtain missing authority, apply
to the verified target, then read back before enabling dependent publication
or host cutover. Estimate current costs for approval rather than reusing the
historical monthly estimate.

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
| `python-build-standalone` mirror | pinned URL and SHA-256, licences retained, install-only builds; unqualified architectures refused (Plan 112) |
| Windows is new lifecycle code and has the entry-point open item | separate stage, designated machine, no admin or stored credentials |
| A legacy host still has a release-specific loaded updater job | read back each host; preserve the stable launcher already implemented; externally reload only a proven legacy job under authorized recovery |

## Out of scope

Signing-key ceremony or signature enforcement (owner decision); plugin
marketplace hosting (Plan 114); Codex and Claude client configuration (Plan
113); paid probes (Plan 115); WSL, Windows ARM, musl and headless servers (Plan
112).
