# Plan 144: Public-repository controls and the visibility flip

> Planning only. Settings are owner-applied; do not change repository
> visibility or protections without an explicit owner instruction.
> Drift check: `git diff --stat 28a1af4..HEAD -- .github/workflows/check.yml .github/workflows/release.yml .github/workflows/refresh.yml CODEOWNERS docs/operations.md README.md`
> Verify each live setting below again before acting; this plan records what
> was true on 2026-09-11, and GitHub settings can change outside the repo.

## Status and first proof

- Priority P1; effort S; risk MED (deployment/supply chain); category
  infra/security; depends on plan 142 (licence) and plan 143 (cutover +
  rotation) completing first.
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
  has been removed or superseded (plan 143, Step 6).

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

Only after plans 142 and 143 are complete and the owner approves:
1. Flip the repository visibility to public.
2. Re-check `allow_forking`, fork-PR approval settings, secret scanning on
   the first public push, and that Actions are still read-only by default.
3. Run one full release dry-run path: `publish_feed.py --dry-run` and a
   token-free `latest.json` asset check.
4. Confirm the public repository contains no feed token, no SSM value and no
   private-repository links.

**Verify**: a fresh clone from the public URL passes `python3.14 -m
unittest discover -s tests -t .`, and a tokenless second machine installs
manually while performing no automatic updates.

## Done criteria

- [ ] Branch, tag, environment and immutable-release protections read back.
- [ ] Secret scanning + push protection enabled; Gitleaks in required checks.
- [ ] Workflow inputs hash-pinned; CODEOWNERS review required for `.github/`.
- [ ] Public text audit recorded.
- [ ] Flip performed only after plans 142 and 143; post-flip checks recorded.

## STOP conditions

- Any plan 142 or 143 gate is unfinished: do not flip.
- A public scan finds a live credential or token-bearing release asset: STOP,
  rotate/remove first, then repeat the scan.
- A control cannot be enabled without paying for a GitHub plan the owner has
  not approved: STOP and record the gap (this is an owner decision, not a
  code workaround).

## Maintenance notes

- Re-run the settings readback after any GitHub plan or organisation policy
  change; protections can be silently overridden by upper-level rulesets.
- Keep the release environment's reviewers current; it is the only gate
  between a tag push and a published feed document.
