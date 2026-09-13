# Plan 167: Scope the feed publisher role and make bundle publication create-only

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report; do not improvise.
> When done, update this plan's status row in `plans/README.md`. The deploy
> step is owner-gated: stop at it and report unless the owner has said to
> deploy.
>
> **Drift check (run first)**: `git diff --stat c068368..HEAD -- infra/feed.yaml tools/publish_feed.py tests/test_publish_feed.py docs/operations.md .github/workflows/release.yml`
> If any in-scope file changed, compare the "Current state" excerpts against
> the live code before proceeding; on a mismatch, STOP.

## Status

- **Priority**: P2 (owner-gated deploy)
- **Effort**: M
- **Risk**: MED (an over-tight policy breaks the next release; stage with a dry run)
- **Depends on**: none; complements 144 (repository controls) and 160 (identifiers out of source)
- **Category**: security
- **Planned at**: commit `c068368` (`origin/develop`), 2026-09-13
- **Source**: `plans/2026-09-13-router-four-lane-audit.md`, finding F7

## Why this matters

The feed bucket holds the trust root for every first install and every
update: `stable/latest.json`, `beta/latest.json`, `bundles/*`, `runtimes.json`,
`runtimes/*` and `bootstrap/*`. The publisher role that the release workflow
assumes may `PutObject` on every key in the bucket, and the only thing that
stops a published bundle from being replaced is a `head-object` comparison
inside the publishing script, which is a check-then-put race and which a
caller holding the role can simply skip. Versioning is enabled, so a
replacement is recoverable after the fact, but nothing prevents it and
nothing alerts on it. The compensating controls are real and were verified on
2026-09-13: tag creation is Admin-only by ruleset, and the release workflow
runs only for two named actors and re-checks the tag SHA. This plan narrows
what the role can do, makes the bundle upload create-only inside the
publisher, and adds a notification when a bundle key is written. The
precondition is an upload request option, not a bucket control: a role
holder who skips it can still replace a bundle, so the immutability promise
becomes "refused on the supported path, visible when someone steps off it,
and recoverable afterwards from versioning", not server-enforced
immutability.

Object Lock is deliberately not used: CloudFormation can only enable it at
bucket creation (`ObjectLockEnabled` requires replacement), and a lock on
object versions would not stop a new current version from being served.

## Current state (verified at c068368)

- `infra/feed.yaml:140-160`, the `PublisherRole` inline policy: `s3:PutObject`
  and `s3:GetObject` on `${FeedBucket.Arn}/*` (no prefix condition),
  `s3:ListBucket` on the bucket, `cloudfront:CreateInvalidation` on the
  distribution, `cloudformation:DescribeStacks` on the stack. No `Deny`
  statements. `:41-42` `VersioningConfiguration: Status: Enabled`; `:43-47`
  public access fully blocked; `:53-68` the bucket policy allows only
  CloudFront reads.
- `tools/publish_feed.py:70-103`: `bundle_state` reads `Metadata.sha256` via
  `aws s3api head-object` and treats a 404 as absent; `publish_bundle`
  uploads with `aws s3 cp ... --metadata sha256=...` only when absent, and
  refuses when a different digest is recorded. `:106-109` `publish_document`
  uploads the channel document with `aws s3 cp`. `:20` `BUNDLE_PREFIX = 'bundles/'`.
- `.github/workflows/release.yml:56-80`: configure AWS credentials and the
  publish step call
  `tools/publish_feed.py --dist dist --channel "$CHANNEL" --bucket ... --distribution-id ...`
  after `aws-actions/configure-aws-credentials` assumes `FEED_ROLE`.
- `tools/publish_first_install.py` writes `runtimes.json`, `runtimes/*` and
  `bootstrap/*`, but with the operator's own credentials rather than
  `FEED_ROLE` (`tools/publish_first_install.py:16-18`), and no workflow
  assumes the release role for it. The release path therefore needs only the
  bundle and channel-document prefixes, and the role must not keep write
  access to the mutable `bootstrap/*` entry point.
- CI lints the template: `.github/workflows/check.yml:73-79` runs
  `cfn-lint infra/*.yaml` (pinned 1.56.3).
- `docs/operations.md`, "Feed infrastructure and publishing", documents the
  role as "It can read and write objects in the feed bucket, list the bucket,
  invalidate the feed, and read the stack outputs. It cannot delete objects
  or touch any other resource."
- Test conventions: `tests/test_publish_feed.py` replaces
  `publish_feed.run` with a recorder and asserts the exact `aws` argv.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Template lint | `python3.14 -m pip install --disable-pip-version-check cfn-lint==1.56.3 && cfn-lint infra/*.yaml` | no findings |
| Publisher tests | `python3.14 -B -m unittest tests.test_publish_feed tests.test_publish_first_install` | pass |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Policy scans | `python3.14 tools/check_policy_scans.py` | pass |
| Dry run (owner) | `python3.14 tools/publish_feed.py --dist dist --channel beta --dry-run` | prints the plan, no AWS call |
| Stack diff (owner, read-only) | `aws cloudformation deploy --stack-name scg-router-feed --region ap-southeast-2 --template-file infra/feed.yaml --capabilities CAPABILITY_NAMED_IAM --parameter-overrides CertificateArn="$CERT" NotificationEmail="$EMAIL" --no-execute-changeset` | a change set to review |

## Scope

**In scope**: `infra/feed.yaml`, `tools/publish_feed.py`,
`tests/test_publish_feed.py`, `tests/test_feed_infra.py`,
`docs/operations.md`.

**Out of scope**: `infra/feed-cert.yaml`; the bucket name, account id and
role name (plan 160 moves them); `.github/workflows/release.yml` (plan 144
owns release authority); enabling Object Lock; any change to what the feed
document contains.

## Git workflow

- Worktree based on `develop`; branch like `<you>/167-feed-write-scope-20260913`.
- Commits: `chore: scope the feed publisher role to its prefixes` and
  `fix: publish bundles create-only`. Run `pre-commit-review`. No push, PR
  or deploy unless instructed.

## Steps

### Step 1: Prefix-scope the role

In `infra/feed.yaml`, replace the first statement of `publish-router-feed`
(`:145-149`) with two:

```yaml
              - Effect: Allow
                Action: s3:GetObject
                Resource: !Sub ${FeedBucket.Arn}/*
              - Effect: Allow
                Action: s3:PutObject
                Resource:
                  - !Sub ${FeedBucket.Arn}/bundles/*
                  - !Sub ${FeedBucket.Arn}/stable/latest.json
                  - !Sub ${FeedBucket.Arn}/beta/latest.json
```

and add an explicit deny so a later widening of the Allow cannot reach the
bucket configuration or delete anything:

```yaml
              - Effect: Deny
                Action:
                  - s3:DeleteObject
                  - s3:DeleteObjectVersion
                  - s3:PutBucketPolicy
                  - s3:PutBucketAcl
                  - s3:PutLifecycleConfiguration
                  - s3:PutBucketVersioning
                  - s3:PutObjectAcl
                Resource:
                  - !GetAtt FeedBucket.Arn
                  - !Sub ${FeedBucket.Arn}/*
```

Confirm the prefix list against every key `tools/publish_feed.py` writes
(grep for `s3://`): `bundles/*` and the two channel documents. The
first-install keys stay out on purpose — that tool uploads with the
operator's own credentials, and the tag-scoped release role has no reason to
write the `bootstrap/*` entry point every recipient downloads and executes.

`tests/test_feed_infra.py:82-89` asserts the template text never contains
`s3:DeleteObject`, which this Deny now must. Update that assertion to keep
its intent: no `Allow` statement grants a delete action, while the `Deny`
lists them. The published-token assertion in the same test stays as it is.

**Verify**: `cfn-lint infra/*.yaml` → no findings.

### Step 2: Create-only bundle uploads

In `tools/publish_feed.py`, change `publish_bundle` to upload with
`aws s3api put-object --bucket B --key K --body PATH --if-none-match '*'
--cache-control ... --content-type application/gzip --metadata sha256=...`
instead of `aws s3 cp`. S3 rejects the write with HTTP 412
(`PreconditionFailed`) when the key already exists, atomically at the
server. Keep the existing `head-object` pre-check so the friendly
"already published" and "bundles are immutable" messages stay, and map a
precondition failure from `put-object` to the same immutability refusal,
matching the CLI's stderr text (`PreconditionFailed`) rather than the bare
"412"; record that real text in the new test. Bundle files are
small (well under the 5 GB single-put limit), so multipart is not needed.
Leave `publish_document` on `aws s3 cp` (documents are meant to be
replaced).

Update `tests/test_publish_feed.py` where it asserts the bundle `aws s3 cp`
argv: it must now assert `s3api put-object` with `--if-none-match '*'`, and
add one case that the recorded precondition-failure stderr produces the
immutability refusal.

**Verify**: `python3.14 -B -m unittest tests.test_publish_feed` → pass.

### Step 3: Notify on every bundle write

In `infra/feed.yaml`, add an `AWS::SNS::Topic` (`FeedPublishTopic`) with an
email subscription parameter (`NotificationEmail`, no default), an
`AWS::Events::Rule` on `aws.s3` `Object Created` events for the bucket with a
`key` prefix filter of `bundles/`, targeting the topic, and
`EventBridgeConfiguration: EventBridgeEnabled: true` under the bucket's
`NotificationConfiguration`. Add an `AWS::SNS::TopicPolicy` letting
`events.amazonaws.com` publish to the topic with `aws:SourceArn` pinned to
the rule: CloudFormation grants that for a Lambda target only, `cfn-lint`
cannot see the missing permission, and without it the rule deploys clean and
never delivers an email. One email per release is the expected volume; a
second email for an existing key is the signal this plan exists to give.

**Verify**: `cfn-lint infra/*.yaml` → no findings.

### Step 4: Documentation

`docs/operations.md`: update the role description to name the writable
prefixes (`bundles/*` and the two channel documents), state that the
publisher's bundle upload is create-only while a role holder that skips the
precondition can still replace a key (the publish email reports it and
versioning recovers it), describe the publish email, and add
`NotificationEmail="$EMAIL"` to the deploy snippet at `:30-32`. Keep the
roll-forward recovery guidance unchanged.

**Verify**: `python3.14 tools/check_policy_scans.py` → pass.

### Step 5: Deploy (owner-gated)

Stop here and report unless the owner has authorised the deploy. When
authorised: run the read-only change set command from the table, review
that it changes only the role policy, the notification resources and the
bucket's notification configuration (no bucket replacement), then execute
it, subscribe the email, and run `tools/publish_feed.py --dry-run`. Before
executing, confirm the bucket carries no out-of-band notification
configuration: `PutBucketNotificationConfiguration` replaces the whole
configuration, so anything set outside this template would be dropped.
Record the deploy date and the change-set summary in this plan's status row.

## Test plan

- `tests/test_publish_feed.py`: bundle upload argv uses create-only
  semantics; the recorded precondition-failure stderr maps to the
  immutability refusal; documents still use `s3 cp`; dry run unchanged.
- Template: `cfn-lint` clean; change set reviewed before execution.

## Done criteria

- [ ] `grep -n "Resource: !Sub \${FeedBucket.Arn}/\*" infra/feed.yaml` shows the wildcard only on `s3:GetObject` and the Deny statement.
- [ ] `grep -n "if-none-match" tools/publish_feed.py` shows the create-only flag on the bundle upload.
- [ ] `cfn-lint infra/*.yaml` exits 0; publisher tests and full suite pass.
- [ ] `docs/operations.md` describes the scoped role and the publish email.
- [ ] Deploy recorded (owner) or the plan row says "source landed; deploy pending owner".

## STOP conditions

- The change set proposes replacing the bucket or the distribution: stop;
  do not execute.
- The runner's AWS CLI does not support `--if-none-match` on `put-object`
  (check `aws --version`; support arrived in CLI v2 during 2024): keep
  `aws s3 cp` plus the pre-check and report the version.
- `tools/publish_first_install.py` writes a key outside the six prefixes:
  add that prefix to Step 1, do not widen back to `/*`.

## Maintenance notes

- Any new object family the publisher writes needs a prefix in the role
  policy; the release will fail loudly (AccessDenied) if it is forgotten,
  which is the intended direction.
- Plan 160 will move the bucket and role identifiers to workflow inputs;
  this plan's policy shape is unaffected by that move.
- Land this plan before 160 on the same branch: the prefix list hardcodes
  `FeedBucket`, which 160 removes from tracked source.
