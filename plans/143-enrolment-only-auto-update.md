# Plan 143: Enrolment-only auto-update for SC hosts

> SUPERSEDED 2026-09-12 (owner decision, Cyril): the update feed is fully
> public and token-free. The enrolment-only model below (feed-token file
> required; tokenless hosts make no requests; installer refuses without a
> feed) no longer applies. Every install updates from
> `https://dist.softwarecombined.com/<channel>/latest.json` with no token,
> no enrolment, no GitHub account and no repository access; a leftover
> `feed-token` file is inert. The three SC testers stay on the public beta
> channel with no token. The body below is kept as history; steps marked
> SUPERSEDED must not be implemented.
> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat 28a1af4..HEAD -- packaging/feed.py packaging/updater.py packaging/service.py packaging/diagnostics.py packaging/install.py packaging/bootstrap.sh packaging/bootstrap.ps1 docs/operations.md README.md tests/test_feed_migration.py tests/test_private_updates.py tests/test_install.py tests/test_install_config.py tests/test_preflight.py`
> Reconcile the line references below against the live files before editing.

## Status and first proof (SUPERSEDED 2026-09-12: see the note at the top)

- Priority P1; effort S-M; risk MED-HIGH (update channel); category
  release/security; depends on none for the code change; the cutover depends
  on plan 142 (licence) and precedes plan 144 (visibility flip).
- Planned at `28a1af4`, 2026-09-11.
- First proof: a scheduled update pass on a host with no `feed-token` makes
  zero network calls to GitHub or CloudFront, exits 0, writes one bounded log
  line and does not touch `update_failures`; an enrolled host updates exactly
  as today; `python3.14 -m packaging.updater --feed file:///...` still
  installs a pinned bundle.

## Why this matters

Today `channel_feed()` falls back to the public GitHub Releases route whenever
no feed token is stored. That is invisible while the repository is private
(`gh` needs an authorised account), but the moment the repository is public
any install - including one belonging to someone outside SC - auto-updates
every 15 minutes from the public releases. The requirement is the opposite:
SC-managed hosts update automatically from the gated stable channel; public
users install and update manually. The simplest mechanism is to make the
stored feed token the enrolment fact: no token means no unattended update.
The CloudFront gate, SSM token and bootstrap flow already exist; only the
fallback and the messaging need to change.

## Current state (verified 2026-09-11)

- `packaging/feed.py:147-159` `channel_feed()`: a `feed` file pin wins, then
  `channel`, then tokenless returns `RELEASES_PREFIX +
  'latest/download/latest.json'`, then token -> `FEED_URL` / beta.
- `packaging/feed.py:121-144` `_beta_github_feed()` resolves a beta tag
  through `gh`; `:81-87` `trusted_origin()` trusts GitHub release URLs
  unconditionally; `:194-219` `live_feed()` sends `X-SCG-Feed-Token`, retries
  once with `feed-token.previous`, then exits with the bootstrap remedy.
- `packaging/service.py:98-109` fetches GitHub assets through `gh`, with
  private-repo wording; `:313-331` `fetch_feed`, `:692-696` `check_serial`
  persists any `feed_token` a document carries.
- `packaging/updater.py:83-89` resolves the feed and runs one pass every
  15 minutes (macOS `StartInterval 900`, systemd `OnUnitInactiveSec=15min`,
  Windows `PT15M`); failures never touch `update_failures` unless a bundle
  was fetched.
- `packaging/diagnostics.py:109-118` preflight tells a tokenless host to
  install `gh`.
- Enrolment today: `packaging/bootstrap.sh:30-47` / `bootstrap.ps1:19-29`
  write `feed-token` (0600) from `SCG_FEED_TOKEN`, keeping
  `feed-token.previous` for one rotation of overlap.
- The published stable `v0.6.25.42` release asset `latest.json` still carries
  a `feed_token` field (field counted only, value never read); its
  `check_serial` path would enrol any public reader until the token is
  rotated.

## Scope

**In scope**: `packaging/feed.py`, `packaging/updater.py`,
`packaging/service.py` (route guards and wording only),
`packaging/diagnostics.py`, `packaging/install.py` (pinned `--feed` rule
unchanged), the bootstraps (usage wording only), `docs/operations.md`,
`README.md`, and the listed tests.
**Out of scope**: the CloudFront/KVS/SSM infrastructure itself, per-request
Entra validation, the licence conversion (plan 142), GitHub settings (plan
144).

## Design decisions (locked, then SUPERSEDED 2026-09-12: kept as history)

1. **Enrolled = `<home>/feed-token` exists (0600).** No new marker file.
   `feed-token.previous` stays for one rotation of overlap.
2. **No token = no unattended update.** `channel_feed()` never returns a
   GitHub URL for the scheduled path. The updater returns 0 with one bounded
   line such as `not enrolled for automatic updates; install manually or
   enrol with the SC bootstrap`. No `gh`, no fetch, no failure counter.
3. **Explicit manual paths stay.** `--feed <url|path>` (one-shot installer
   hand-off, including `file://`) and the operator `feed` file pin keep
   working; `trusted_origin()` keeps accepting those pinned sources only.
4. **Stable/beta unchanged for enrolled hosts.** `channel` file selects
   `/stable/latest.json` (default) or the gated beta document; both are
   token-gated.
5. **Provisioning stays simple.** SC hosts enrol with the existing bootstrap
   (`SCG_FEED_TOKEN` from SSM) or an MDM-pushed owner-only `feed-token`. An
   Entra front, if chosen later, gates *issuance* of the same token (device
   code -> Entra-protected endpoint -> token -> bootstrap persists it); the
   edge, header and updater do not change. Store the feed origin next to the
   token so an Entra-fronted origin can move without a code release.

## Steps (SUPERSEDED 2026-09-12: kept as history, do not implement)

### Step 1: make tokenless mean unenrolled in `feed.py`

Add a positive enrolment predicate (`feed_token(home) is not None`, or an
explicit pin/override). Remove the tokenless GitHub return and the
`_beta_github_feed()` lookup from the unattended path. Keep
`github_route_parts()` / `github_command()` reachable only for explicit
pinned runs and tests.

**Verify**: new unit tests (Step 4) fail before and pass after;
`python3.14 -m unittest tests.test_feed_migration` passes.

### Step 2: quiet skip in `updater.py`

After feed resolution, if the host is unenrolled, print one bounded line and
`return 0` before any fetch. Do not increment `update_failures`, do not open
a dialog, do not retry. Leave the enrolled path untouched, including the
304/up-to-date path and the `--feed` one-shot rule.

**Verify**: a scheduled-pass test with no token records zero fetch calls and
exit 0; the enrolled test still installs.

### Step 3: wording and diagnostics

`packaging/service.py` GitHub fetch stays only behind explicit pins; replace
the "Private router updates require GitHub CLI" wording with the enrolment
message. `packaging/diagnostics.py` preflight says "enrol with the SC
bootstrap or pass `--feed`" instead of "install gh". Bootstraps keep the
`SCG_FEED_TOKEN` contract; update their usage text to say the token comes
from the SC-managed source only.

**Verify**: `rg -n "Private router updates" packaging` returns nothing;
preflight tests pass.

### Step 4: tests

- Update `tests/test_feed_migration.py` (`test_no_token_stays_on_github_route`
  and the beta/route expectations), `tests/test_private_updates.py`,
  `tests/test_install.py`, `tests/test_install_config.py`,
  `tests/test_preflight.py`.
- Add: tokenless scheduled pass performs no fetch, exits 0, logs once and adds
  no `update_failures`; enrolled pass unchanged; explicit `--feed file://...`
  still installs; double-403 still names the bootstrap remedy in public-safe
  wording; diagnostics no longer mention `gh` for the unattended path.
- Keep `tests/test_publish_feed.py` (token only in the gated feed copy) and
  `tests/test_release.py` (embed refusal) as the release-side guards.

**Verify**: focused suites pass; each new test fails against the pre-change
tree.

### Step 5: docs

Rewrite the update sections of `README.md` and `docs/operations.md`:
enrolment (bootstrap/MDM), the manual update path for non-enrolled installs,
the stable/beta channel behaviour, and the rotation runbook in public-safe
language (no internal library names).

**Verify**: `rg -n -i "technology library|private router" README.md docs/`
returns nothing public-unsafe.

### Step 6: cutover (SUPERSEDED 2026-09-12: no token rotation happens)

1. Confirm the fleet is enrolled and healthy: `update.log` source
   `cloudfront`, current versions read back.
2. Rotate the feed token in the documented order: add the new value to the
   KVS, write SSM, republish both channel documents, wait one poll plus
   jitter (~4 hours per channel), verify the new token serves the same
   version, then delete the old KVS key.
3. Remove or supersede the token-bearing `latest.json` asset on
   `v0.6.25.42` (delete the asset before enabling immutable releases), or cut
   the next stable release so `latest/download/latest.json` is token-free.
4. Only then proceed to plan 144's visibility flip.

**Verify**: old token returns 403 and new returns 200; a tokenless public
test host performs no update over 24 hours.

## Known fleet (updated 2026-09-12; the 2026-09-11 enrolment text below is history)

Three SC beta testers remain the known fleet. They stay on the public
beta channel with no token: one bootstrap or manual install each reaches
the public-feed version, after which they update themselves. A leftover
`feed-token` file on any of these hosts is inert and can be ignored or
deleted.

2026-09-11 enrolment text (superseded): three SC beta testers are the
known enrolled fleet. They keep
`channel = beta`; migration is one bootstrap (or MDM push) per host writing
`feed-token` 0600, then `--status` must read `feed: cloudfront` and
`channel: beta`, and `feed-serial` must not be ahead of the beta document.
Automatic polls run every 4 hours (macOS `StartInterval` 14400, systemd
`OnUnitInactiveSec=4h`, Windows `PT4H`), with a 5-minute first check after
service start; the installer and updater stay manual-only for unenrolled
hosts. When Entra arrives, an Entra group gates *issuance* of the same
static token (device code -> Entra-protected endpoint -> token ->
bootstrap stores it); removing someone from the group stops new token
fetches, and offboarding also rotates the token. The edge, header and
updater stay unchanged; per-request Entra validation would need
Lambda@Edge or signed URLs and is out of scope.

## Done criteria (SUPERSEDED 2026-09-12: kept as history)

- [ ] Tokenless scheduled passes do zero network calls and exit 0 quietly.
- [ ] Enrolled hosts update unchanged; explicit `--feed` still works.
- [ ] Tests and docs updated; the double-403 remedy is public-safe.
- [ ] Fleet enrolment and token rotation recorded before the visibility flip.
- [ ] `plans/README.md` index row added when the plan is committed.

## STOP conditions (SUPERSEDED 2026-09-12: kept as history)

- Fleet enrolment cannot be verified: STOP before the token rotation and the
  visibility flip.
- Removing the GitHub fallback breaks a documented SC workflow that has no
  enrolled alternative: STOP and record the workflow.
- Two rotations inside one poll window: STOP; hosts keep one previous token
  only and would need the bootstrap.

## Maintenance notes (SUPERSEDED 2026-09-12: kept as history)

- The feed token is a shared bearer secret: enrolment is out-of-band and
  eviction requires a full re-key; per-device or Entra-issued credentials are
  the upgrade path if per-host revocation ever becomes a requirement.
- Keep the release workflow publishing the feed before the GitHub release so
  a token-free `latest.json` is the public artifact.
