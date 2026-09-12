# Plan 144: Public-repository controls and the visibility flip

> Planning only. Settings are owner-applied; do not change repository
> visibility or protections without an explicit owner instruction.
> Drift check: `git diff --stat 28a1af4..HEAD -- .github/workflows/check.yml .github/workflows/release.yml .github/workflows/refresh.yml .github/CODEOWNERS infra/feed.yaml tests/test_feed_infra.py docs/operations.md README.md`
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
settings, secret scanning and the release authority gate - plus the
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

The owner selected admin-created tags on 2026-09-12. Only Cyril (`SC-Cyril`)
and Brent (`BrentJMaxwell`) may merge PRs, create tags, and deploy or rerun
releases. Keep both as repository admins and all other users and teams at
read or triage. GitHub write access includes workflow reruns, so granting
write or maintain would widen release authority.

- Protect `main` and `develop` with the `Test` check, pull requests, deletion
  and force-push restrictions. Restrict updates to admins through PRs only.
- Protect every tag, with no build-number exception. The workflow publishes
  assets on the existing tag with `gh release create --verify-tag`; bundle
  versions still include the run number. Both the initiating and rerunning
  actor must be Cyril or Brent. Serialize publication against the shared feed.
- Keep the existing tag-scoped AWS OIDC trust. No approval environment or AWS
  trust migration is needed for this selected approach.
- Enable immutable releases only after retiring the inert `v0.6.25.42`
  token-bearing asset. This cleanup does not create a release or tag.

**Verify**: read back both branch rulesets, the all-tag ruleset and effective
collaborator permissions. Confirm the current workflow uses the existing tag
and its download URL. The next authorised beta release must prove role
assumption, feed publication and GitHub asset download end to end.

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

- [ ] Branch and all-tag protections plus effective collaborator permissions read back.
- [ ] Existing-tag workflow integrated; next authorised beta release verifies
      tag-scoped role assumption, feed publication and GitHub asset download.
- [ ] Immutable releases enabled after the legacy asset is retired.
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
- Any non-maintainer can merge, create tags, or run/rerun publishing: do not
  flip or widen access. Recheck effective access, not just direct grants.

## Applied 2026-09-12: selected release control

Owner instruction: only Cyril and Brent merge, tag and deploy. Live GitHub
readback after the cleanup shows:

- `Protect main` (23034914) and `Protect develop` (23034916): deletion,
  non-fast-forward, update restriction, pull request (0 approvals), and
  required `Test` check. Admin bypass is available through PRs only.
- `Protect tags and releases` (23035086): creation, update and deletion
  restrictions on every tag, with no exclusions; admin bypass only.
- Cyril and Brent are the only effective users with write, maintain or admin
  rights. Other direct collaborators retain triage. Repository-specific team
  grants were removed after GitHub did not retain API permission downgrades;
  GraphQL readback confirms no team grants remain. Organisation base access
  remains read.
- Actions remains read-only by default. The organisation rejected enabling
  Actions-created PRs; the broken refresh workflow is removed from source.
  Maintainers use the existing CLI and normal PR process in `CONTRIBUTING.md`.
- The repository remains private. No tag, release, visibility flip, rename,
  AWS deployment, or change to publisher trust was performed by this cleanup.

The workflow source lands on `develop`; `main` receives it through the next
release PR. Do not cut a tag from the older workflow: all-tag protection will
reject its attempt to create a second tag. The next beta publication remains
an explicit acceptance gate. Recheck effective permissions after any team or
organisation ownership change; adding an admin widens tag-rule bypass.

Secret scanning and push protection were enabled earlier. Immutable releases,
Gitleaks in CI, the `cfn-lint` hash pin, required CODEOWNERS review, the public
text audit (plan 160), and the visibility flip remain open.

## Repository name selected, 2026-09-12

The owner selected **SC Unlimited AI** as the display name and
`SC_Unlimited_ai` as the future repository URL slug, and asked for the README
to use them now. Its title uses the display name; GitHub links and clone
commands use the slug in preparation; those links will resolve after the GitHub rename.
The live repository is still `software-combined/SC_OpenRouter_adapter`.
Coordinate the rename with the repository-name references and publisher OIDC
trust in `infra/feed.yaml`, then redeploy and verify the trust before the
next release. The name selection does not apply the GitHub rename or change
the installed dialog title, which remains a separate product-naming decision.
