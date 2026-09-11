# Plan 139: Private feed publication so releases stop needing the GitHub repo

> Renumbered from 122 on 2026-09-11: the refactor wave took 122-134, the
> new-model prompt plan took 135, and the security wave took 136-138 before
> this plan landed on `develop`.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH (the feed is the fleet's code-execution path; contained by
  a tag-only publisher, an edge token gate, immutable bundles and the
  client's serial/version/trusted-origin checks)
- **Depends on**: nothing in source. Consumes Plan 054 T's client slices
  (`packaging/feed.py`) and 055's no-network tool conventions.
- **Supersedes**: Plan 106's push-to-main publication trigger, its
  feed-only-after-transition variant, and the removal of the `gh` fallback;
  also Plan 109's push-to-`main` release trigger (its restart and live
  evidence work stands). The owner chose tag-driven publication, GitHub
  Releases kept beside the feed, and the fallback route retained.
- **Category**: distribution / release engineering
- **Planned at**: commit `3deced4` (develop), 2026-09-11
- **Implemented**: source landed on `develop` (infra stacks, publisher tool,
  workflow wiring, tests, docs). The live steps below stay owner-gated: no
  AWS resource, no token, no tag and no release is created by this plan's
  source work.

## Outcome

Every tagged release publishes to the token-gated feed at
`https://dist.softwarecombined.com` as well as to GitHub Releases, so an
installed router updates with no GitHub account, no `gh` and no repository
access. Existing hosts migrate unattended, because the transition release
carries the feed token in `latest.json` over the route they already use.

First observable proof (rollout step 3): tagging `v<version>-beta` from
`develop` puts the bundle and `beta/latest.json` on the feed, the owner Mac
migrates on its next poll and `logs/update.log` records `"source": "github"`
for that migration install (`"source": "cloudfront"` appears on the first
install after that migration), and the feed answers 403 without the token
header.

## Interfaces and contracts

- Trigger unchanged: tag `v<version>` publishes stable, `v<version>-beta`
  publishes beta, the tag must equal `packaging/VERSION`, and the version is
  `VERSION.<GITHUB_RUN_NUMBER>`.
- Feed keys: `<channel>/latest.json` (`max-age=60`, ETag preserved for the
  updater's 304 path) and `bundles/ai-router-<version>.tar.gz`
  (`max-age=31536000, immutable`). `runtimes.json`, `runtimes/*` and
  `bootstrap/*` are published by `tools/publish_first_install.py` (the
  pinned runtimes and the two wrapper scripts).
- The feed copy of `latest.json` carries `feed_token` and a `url` under the
  feed origin; the GitHub copy keeps the release-asset URL and carries
  `feed_token` only while the transition variable is set.
- Gate: a CloudFront viewer-request function serves the request only when
  `X-SCG-Feed-Token` is a KeyValueStore key whose value is `active`; every
  other path, including a lookup error, returns 403.
- Token stores: the KeyValueStore holds the active token set (overlap for
  rotation); the SecureString `/scg/router-feed/current-token` holds the
  value the workflow embeds. The publisher role reads the parameter and
  writes neither store.
- Fixed names: account `651116729473`, bucket
  `scg-router-feed-651116729473-apse2`, stacks `scg-router-feed-cert`
  (us-east-1) and `scg-router-feed` (ap-southeast-2), role
  `scg-router-feed-publisher`.

## Implementation

1. **Infrastructure** (`infra/feed-cert.yaml`, `infra/feed.yaml`): the
   certificate stack for CloudFront's us-east-1 viewer requirement, then the
   feed stack holding the private versioned bucket (Block Public Access,
   OAC-only reads, Retain), the distribution with the KVS-backed token gate,
   the Route 53 A/AAAA alias, and the publisher role trusted only for
   `repo:software-combined/SC_OpenRouter_adapter:ref:refs/tags/v*`.
2. **Publication** (`tools/publish_feed.py`): reads the token from SSM,
   writes `dist/feed-latest.json` and `dist/release-latest.json`, uploads the
   bundle once (same sha skipped, different sha refused), uploads the channel
   feed, invalidates it, and prints a redacted summary. `.github/workflows/release.yml`
   assumes the role over OIDC, resolves the distribution id from the stack
   output, publishes, and only then creates the GitHub Release.
3. **Client**: no request-path change. A token-bearing host already resolves
   the feed, sends the header, and persists a rotated token after the serial
   check; a host without a token keeps the `gh` route.
4. **Docs and guards**: operations runbook for deploy, seeding, rotation and
   rollback; README and Linux-upgrade notes on when `gh` is still needed;
   `infra/` ownership in `docs/architecture.md`; `cfn-lint` pinned in
   `.github/workflows/check.yml`.

## Rollout (owner-gated)

1. Deploy `scg-router-feed-cert` in us-east-1, then `scg-router-feed` in
   ap-southeast-2. Confirm 403 without the header.
2. Seed the token: `cloudfront-keyvaluestore put-key` (`value=active`) plus
   the matching SecureString.
3. Set repository variable `ROUTER_FEED_EMBED_TOKEN=true` and tag the
   transition release from `develop` (beta), then from `main` (stable).
   Verify the feed, the migration, `/health`, and `gh`-free polling.
4. Unset the variable, rotate the token once so the value that appeared in a
   release asset is dead, and record the evidence.

## Test plan

- `tests/test_publish_feed.py` (offline, fake `aws` runner): feed and release
  document construction and URL rewrite, stale-token stripping, incomplete
  document and bundle-name refusal, immutable-bundle skip and conflict,
  channel feed upload and invalidation target, the transition switch, token
  absent from argv and stdout, `--dry-run` writing nothing, unknown channel,
  checksum mismatch, missing dist directory, missing CLI and one-line AWS
  failure reporting.
- Existing feed tests stay green: a token-bearing host never invokes `gh`,
  and off-origin feed or bundle URLs are refused.
- Templates: `cfn-lint` (pinned) on every PR; `aws cloudformation
  validate-template` before each deploy.
- Live acceptance: gated versus ungated feed URLs, beta and stable
  migration proofs, a scheduled poll with `gh` absent, roll-forward recovery
  after a bad publish, host rollback via `install.py --version`, and a
  rotation that ends with the retired key deleted.

## Assumptions

- Signatures stay off; checksum, serial, version and trusted-origin checks
  remain the client controls.
- Scope is the update path and the feed side of first install:
  `tools/publish_first_install.py` publishes the pinned runtimes and both
  bootstrap wrappers. The identity-gated library page and per-install
  tokens stay with Plan 106's remaining stages and Plans 112/117.
- One poll cycle plus jitter (about 20 minutes) is the rotation overlap.
- CloudFront default price class; published volume is a few MB per release.

## Accepted residual risk

Re-running an old tag's release workflow re-publishes that release's
`latest.json`, including its lower serial, to the channel feed: the
publisher guards bundle bytes but not feed-document monotonicity, so
hosts already on a newer release refuse the replayed document and stay
put, and hosts below it install the older release until the next legitimate
tag. Accepted rather than fixed in this change: it needs a deliberate
operator action, it cannot roll a host backwards, and recovery is a new
tag. A monotonicity guard (compare the served document's serial before
upload, the same rule the client applies) is the obvious follow-up if the
workflow is ever re-run in anger.
