# Plan 160: Move publication identifiers out of tracked source

> **Executor instructions**: Follow this plan step by step. If a STOP condition
> occurs, stop and report. When done, update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 0024a42..HEAD -- .github/workflows/release.yml infra/feed.yaml infra/feed-cert.yaml tools/publish_feed.py tools/publish_first_install.py docs/operations.md tests/test_publish_feed.py tests/test_publish_first_install.py tests/test_feed_infra.py tests/test_policy_scans.py`
> Plan 144 owns the visibility flip and every GitHub setting. This plan is the
> code half of its Step 3 and changes no setting. Reconcile every cited line
> before editing.

## Status and first proof

- Priority P2; effort S; risk MED (release path); confidence HIGH; category
  infra/publication.
- Depends on nothing in code. Feeds plan 144 Step 3, which records the text
  audit and performs the flip.
- Source: `plans/2026-09-12-architecture-scalability-review.md`, row "The AWS
  account id is in four tracked files".
- First proof: no AWS account id, bucket name or publisher role name is left in
  code, CI, infrastructure or `docs/`; a release still publishes to the same
  feed with the same behaviour; and running the publishers without the required
  input fails with a clear message instead of silently defaulting to someone
  else's bucket.

## Why this matters

Measured at `0024a42`, the AWS account id and the derived bucket and role
names appear in four tracked source files:
`.github/workflows/release.yml:17-18`, `infra/feed.yaml:22` (as a parameter
default), `tools/publish_feed.py:17` and `tools/publish_first_install.py:30`
(both as `DEFAULT_BUCKET`). `docs/operations.md:25-30` names the stacks.

None of these is a secret, and the OIDC trust in `infra/feed.yaml:131-135` is
tag-scoped, so the exposure is not a credential leak. It is an identifier
disclosure: an account id plus a bucket name plus a role name is exactly the
input to role and bucket enumeration, and publishing them is a decision the
owner should make deliberately rather than inherit. The code-level fix is small
and it also removes a real footgun: a fork that runs `tools/publish_feed.py`
with no arguments today targets the real bucket by default.

`plans/144-public-repo-controls.md` Step 3 already owns the audit and the
decision. This plan does the code half so that, whichever way the owner
decides, the value lives in one place.

## Scope

**In scope**: the files named in the drift check.
**Out of scope**: any GitHub repository or organisation setting, the visibility
flip, branch and tag protection, secret scanning, the release environment gate
(all plan 144), rotating or changing any AWS resource, and deploying any stack.

## Steps

1. **Make the publishers require their target.** In `tools/publish_feed.py` and
   `tools/publish_first_install.py`, delete the `DEFAULT_BUCKET` constants and
   make `--bucket` a required argument. A missing value must exit non-zero with
   a message naming the argument, not fall back to any default. Update
   `tests/test_publish_feed.py` and `tests/test_publish_first_install.py` to
   pass a fixture bucket and to assert the new refusal.

2. **Move the workflow values to repository variables.** In
   `.github/workflows/release.yml`, replace the literal `FEED_BUCKET` and
   `FEED_ROLE` at `:17-18` with `${{ vars.FEED_BUCKET }}` and
   `${{ vars.FEED_ROLE }}`. Add a guard step before the AWS credential step
   that fails with a clear message when either is empty, so a fork or a
   misconfigured repository fails loudly instead of assuming a role it cannot
   assume. `FEED_STACK` at `:16` is a stack name with no account in it and may
   stay literal; say so in a comment.

3. **Drop the account-bearing parameter default.** In `infra/feed.yaml:22`,
   remove the `Default:` value for the bucket parameter so the stack requires
   it at deploy time. Update the deploy commands in `docs/operations.md:25-30`
   to pass it explicitly, and update `tests/test_feed_infra.py` if it asserts
   the default.

4. **Document where the values live.** Add a short subsection to
   `docs/operations.md` listing the three repository variables the release
   workflow needs, what each is for, and that they are set in repository
   settings rather than in the tree. Do not write any actual value into the
   documentation.

5. **Add a scan that keeps them out.** Extend `tools/check_policy_scans.py`
   with a third scan: a twelve-digit AWS account id pattern
   (`\b\d{12}\b` constrained to the contexts that matter, that is `arn:aws:`
   strings and bucket-shaped names) across the tree, excluding the scan's own
   file as the existing scans do at `tools/check_policy_scans.py:13`. Add the
   case to `tests/test_policy_scans.py`, including a synthetic violation so the
   scan is proven non-vacuous.

6. **Run the dry path.** With the variables set, confirm
   `python3.14 tools/publish_feed.py --help` shows `--bucket` as required, and
   run the publisher's existing dry-run path against a fixture directory. Do
   not publish, do not deploy, and do not assume a role.

## Verification

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_publish_feed tests.test_publish_first_install tests.test_feed_infra tests.test_policy_scans` | pass |
| Required argument | `python3.14 tools/publish_feed.py --dist dist --channel stable` | exits non-zero naming `--bucket` |
| Clean tree | `grep -rn "<the account id>" . --exclude-dir=.git` | hits only the historical plan documents |
| Policy scans | `python3.14 tools/check_policy_scans.py` | exit 0 |
| CloudFormation lint | `python3.14 -m pip install --disable-pip-version-check cfn-lint==1.56.3 && cfn-lint infra/*.yaml` | exit 0 |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | `failures=0` |

## STOP conditions

- The release workflow cannot read repository variables in this repository's
  plan tier: stop and report. Keeping the literals is a legitimate owner
  choice and this plan must not force a paid tier.
- Removing the CloudFormation parameter default would break the deployed
  stack's next update: stop and report. A deployed stack keeps its current
  parameter value on an update that does not pass one, but confirm that for
  this template rather than assuming it.
- Any step would require assuming an AWS role, deploying a stack or publishing
  an asset: stop. This plan is source-only.

## Acceptance checklist

- [ ] No AWS account id, bucket name or publisher role name is left in code,
      CI, infrastructure or `docs/`.
- [ ] Both publishers require `--bucket` and refuse clearly without it.
- [ ] The release workflow reads repository variables and fails loudly when
      they are empty.
- [ ] `infra/feed.yaml` has no account-bearing default and
      `docs/operations.md` passes the value explicitly.
- [ ] A policy scan prevents the identifiers returning, proven non-vacuous.
- [ ] Full suite, compile, limits, policy scans and cfn-lint pass;
      `plans/README.md` row updated.

## Maintenance notes

- Record in plan 144's Step 3 status that the code half is done, so the owner's
  text audit covers only what remains: private links, SSM parameter names and
  feed URLs.
- The refusal in step 1 is worth more than the disclosure fix: after the flip,
  a fork running the publisher with no arguments is a realistic accident.
