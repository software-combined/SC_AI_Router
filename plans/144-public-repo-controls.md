# Plan 144: Public-repository controls and the visibility flip

> Planning only. Settings are owner-applied; do not change repository
> visibility or protections without an explicit owner instruction.
> Drift check: `git diff --stat 28a1af4..HEAD -- .github/workflows/check.yml .github/workflows/release.yml .github/workflows/refresh.yml .github/CODEOWNERS docs/operations.md README.md`
> Verify each live setting below again before acting; this plan records what
> was true on 2026-09-11, and GitHub settings can change outside the repo.

## Status and first proof

- Priority P1; effort S; risk MED (deployment/supply chain); category
  infra/security; depends on plan 142 (licence) completing first. The plan
  143 token rotation is gone (owner decision 2026-09-12: the feed is public
  and token-free); only retiring the inert `v0.6.25.42` token-bearing asset
  below remains.
- Planned at `28a1af4`, 2026-09-11.
- First proof: the repository can be made public without granting any new
  path to secrets, releases or the feed, and every control below reads back
  as configured.

## Why this matters

The repository is private today, so several settings are effectively
unexercised: no branch protection, no tag protection, no environments, no
secret scanning, immutable releases disabled. Going public turns the forks,
issues and pull requests into untrusted input, and makes every published
release asset world-readable. The workflows themselves are already
well-shaped (read-only default token, no `pull_request_target` or
`workflow_run`, SHA-pinned actions), so the work is mostly protection
settings, secret scanning and the release-environment gate - plus the
pre-flip cleanup owned by plans 142 and 143.

## Current live state (verified 2026-09-11)

- No branch protection or rulesets on `main` / `develop`; no tag protection;
  no environments; immutable releases disabled.
- `allowed_actions: all`; `sha_pinning_required: false`; default workflow
  permissions `read`; `can_approve_pull_request_reviews: false`;
  `allow_forking: false` (recheck after the flip); secret scanning and push
  protection disabled; no repository secrets.
- `.github/workflows`: no `pull_request_target`, `workflow_run`, artifact or
  cache steps; all `uses:` SHA-pinned; `cfn-lint==1.56.3` is not
  hash-pinned and the hashed lint requirements are read from the PR tree.
- `release.yml` has no `environment:` gate; the feed publisher OIDC trust is
  tag-scoped in `infra/feed.yaml`.

## Steps (owner-applied, then verified in-repo where possible)

### Step 1: branch, tag and release protections

- Protect `main` and `develop`: require a pull request, at least one
  approving review, dismissal of stale approvals, the CI checks from
  `.github/workflows/check.yml` to pass, linear history if the team agrees,
  and block force pushes and branch deletion.
- Protect tags `v*`: only the release workflow or an owner may create or move
  them.
- Add a `release` environment with required reviewers (owner: `SC-Cyril`)
  and a tag-only deployment rule; attach it to `release.yml`'s publish job.
- Enable immutable releases only after the `v0.6.25.42` token-bearing asset
  has been removed or superseded (retired as hygiene; there is no token to
  rotate).

**Verify**: `gh api repos/software-combined/SC_OpenRouter_adapter/branches/main/protection`,
the tag ruleset, the environment, and the immutable-releases setting each
read back as configured.

### Step 2: secret scanning and supply chain

- Enable secret scanning with push protection for the repository.
- Add the Gitleaks scan used locally to CI's required checks (the existing
  regex scan is a weak net).
- SHA-pin `cfn-lint` or install it from a hash-checked lock that CI itself
  owns; add `CODEOWNERS` for `.github/` and require its review for workflow
  changes.
- Workflows triggered by fork PRs keep read-only tokens and never receive
  secrets or the OIDC role; confirm after the visibility flip.

**Verify**: `gh api .../secret-scanning` and `.../actions/permissions`
readbacks; a test PR from a fork sees no secrets and a read-only token.

### Step 3: text audit for public consumption

Walk the items plan 142 Step 6 lists: internal plan detail, private links,
SSM parameter names, feed URLs, bucket/account identifiers in `infra/` and
docs. Keep what the owner accepts as public; genericise or remove the rest
(the source is public; the operational detail does not have to be).

**Verify**: a redacted scan for `ssm`, account IDs and bucket names lists only
accepted items, recorded in the plan status.

### Step 4: the flip and post-flip checks

Only after plan 142 is complete and the owner approves:
1. Flip the repository visibility to public.
2. Re-check `allow_forking`, fork-PR approval settings, secret scanning on
   the first public push, and that Actions are still read-only by default.
3. Run one full release dry-run path: `publish_feed.py --dry-run` and a
   token-free `latest.json` asset check.
4. Confirm the public repository contains no feed token, no SSM value and no
   private-repository links.

**Verify**: a fresh clone from the public URL passes `python3.14 -m
unittest discover -s tests -t .`, and a second machine installs from the
public feed and updates itself automatically.

## Done criteria

- [ ] Branch, tag, environment and immutable-release protections read back.
- [ ] Secret scanning + push protection enabled; Gitleaks in required checks.
- [ ] Workflow inputs hash-pinned; CODEOWNERS review required for `.github/`.
- [ ] Public text audit recorded.
- [ ] Flip performed only after plan 142; post-flip checks recorded.

## STOP conditions

- Any plan 142 gate is unfinished: do not flip.
- A public scan finds a live credential or the unretired token-bearing
  release asset: STOP, remove it first, then repeat the scan.
- A control cannot be enabled without paying for a GitHub plan the owner has
  not approved: STOP and record the gap (this is an owner decision, not a
  code workaround).
- The publish job has no `release` environment gate and the workflow still
  creates its own tags: do not flip and do not widen push access. Any
  push-capable account can otherwise publish to the public feed (see the
  applied section below).

## Maintenance notes

- Re-run the settings readback after any GitHub plan or organisation policy
  change; protections can be silently overridden by upper-level rulesets.
- Keep the release environment's reviewers current; it is the only gate
  between a tag push and a published feed document.

## Applied 2026-09-12 (owner instruction, readback recorded)

On the owner's instruction that only the two repository admins (Cyril and
Brent) may update `main`, create tags and cut releases, these settings were
applied through the GitHub API and read back:

- Repository ruleset `Protect main` (id 23034914, active): `deletion`,
  `non_fast_forward`, `update`, `pull_request` (0 approvals),
  `required_status_checks` (`Test` from `check.yml`); bypass: repository
  admins, always. Non-admins cannot push to or merge into `main`.
- Repository ruleset `Protect develop` (id 23034916, active): `deletion`,
  `non_fast_forward`; bypass: repository admins.
- Repository ruleset `Protect tags and releases` (id 23035086, active):
  `creation`, `update`, `deletion` on every tag except `refs/tags/v*.*.*.*`;
  bypass: repository admins. The exclusion keeps the release workflow's
  build-numbered tags (`gh release create v<version>.<build>`) working, because
  GitHub refused the Actions integration as a repository-level bypass actor.
  That exclusion leaves a gap: any account with push access can still create
  a four-part tag, and the workflow's `packaging/VERSION` comparison reads the
  file from the tagged tree that pusher controls, so it does not constrain
  them. Until the `release` environment below gates the publish job, a
  push-capable account can publish to the public feed by tagging its own
  commit. The maintenance note above already names that environment as the
  only gate between a tag push and a published feed document.
- Secret scanning and push protection enabled (readback: both `enabled`).
- Description, homepage, topics and delete-branch-on-merge set.

Deviations from Step 1 as planned: zero required approvals instead of one, so
the two admins can merge each other's release pull requests without a second
reviewer; `develop` is not pull-request gated because the working branches
integrate into it directly.

STOP before the flip, and before any widening of push access: attach a
`release` environment with required reviewers (the two admins) to
`release.yml`'s publish job, or change the workflow to publish only from a
tag an admin created (no build-numbered tag creation by the workflow, so the
tag rule can cover every tag). Either closes the gap above; neither is in
place. Also not yet applied: immutable releases, Gitleaks in CI, the
`cfn-lint` hash pin, `CODEOWNERS` review for `.github/` (the file now lives
at `.github/CODEOWNERS`), the Step 3 text audit (plan 160 owns the
identifiers in source), and the flip itself.
