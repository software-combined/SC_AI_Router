# Plan 142: Relicense the repository to Apache-2.0 only

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat 28a1af4..HEAD -- LICENSE COMMERCIAL_LICENSE.md THIRD_PARTY_NOTICES.md pyproject.toml README.md docs/PROVENANCE.md .codex-plugin/plugin.json .claude-plugin/plugin.json packaging/release.py tests/test_packaging.py CHANGELOG.md packaging/VERSION`
> Read the changed files and reconcile the line references below before editing.

## Status and first proof

- Priority P1; effort S-M; risk MED (legal/publication); category docs/release;
  depends on owner approval (Cyril) recorded before merge, and on plan
  143's cutover before the repository visibility flip (plan 144).
- Planned at `28a1af4`, 2026-09-11.
- First proof: `rg -n -i "polyform|licenseref-|commercial_license|unlicensed"`
  over the tree returns nothing except historical `CHANGELOG.md` entries, and
  the release bundle contains `LICENSE` (Apache-2.0), `NOTICE` and
  `THIRD_PARTY_NOTICES.md` with no `COMMERCIAL_LICENSE.md`.

## Why this matters

The repository is published today under PolyForm Shield plus a separate
commercial licence pointer. The owner has decided the public repository must
be Apache-2.0 only. That is a plain-language change in what others may do
(commercial and competing use becomes permitted, no separate agreement), so
it needs a deliberate, complete swap of licence text, metadata, notices,
bundle contents and documentation - not just a `LICENSE` file edit.

## Current state (verified 2026-09-11)

- `LICENSE:1` - `# PolyForm Shield License 1.0.0` (verbatim Shield text,
  including the Required Notice mechanism at the end).
- `COMMERCIAL_LICENSE.md:1-25` - source-available statement and the
  separate commercial-licence pointer.
- `pyproject.toml:6` - `license = "LicenseRef-PolyForm-Shield-1.0.0"`;
  `:7` `license-files = ["LICENSE", "THIRD_PARTY_NOTICES.md"]`.
- `.codex-plugin/plugin.json:10` and `.claude-plugin/plugin.json:9` -
  `"license": "LicenseRef-PolyForm-Shield-1.0.0"`.
- `packaging/release.py:42-44` - bundle inventory comment naming PolyForm and
  shipping `LICENSE`, `COMMERCIAL_LICENSE.md`, `THIRD_PARTY_NOTICES.md`.
- `tests/test_packaging.py:82` - the same three-file expectation.
- `THIRD_PARTY_NOTICES.md:3-6` - PolyForm distribution statement.
- `README.md:299-316` - source-available explanation, competition
  restriction, commercial pointer, PolyForm link.
- `docs/PROVENANCE.md:20-24` - PolyForm/SPDX record; `:25-36` - visibility
  and prompt-file provenance notes.
- `CHANGELOG.md:93-99` - the historical PolyForm groundwork entry (history
  stays; a new entry is added).

## Owner gates (blocking)

Record in the plan's status when complete; do not merge without them:
1. Owner (Cyril) approves Apache-2.0 only, including the patent grant and
   termination terms, and the removal of the competition restriction.
2. Owner approves the `NOTICE` wording and accepts trademark/logo use terms
   for `packaging/assets/router-icon.png` and `docs/assets/sc-logo-wide.png`.
3. Provenance decision for `ai_router/openrouter_base_instructions.txt`
   (shipped in every bundle via the `*.txt` glob): it "closely follows the
   Codex desktop application's own agent instructions" and the desktop
   application's terms are not established (`docs/PROVENANCE.md:30-36`).
   Default choice: rewrite it as original Software Combined wording; the
   alternative is to drop it from the bundle. It must not be relicensed as
   Apache-2.0 by implication.

## Scope

**In scope**: `LICENSE`, `COMMERCIAL_LICENSE.md` (delete), new `NOTICE`,
`THIRD_PARTY_NOTICES.md`, `pyproject.toml`, `README.md`,
`docs/PROVENANCE.md`, both plugin manifests, `packaging/release.py`,
`tests/test_packaging.py`, `CHANGELOG.md`, `packaging/VERSION`, and the
prompt-file/question above if the owner chooses to rewrite it.
**Out of scope**: the visibility flip and GitHub settings (plan 144), the
update/enrolment mechanics (plan 143), edits in the private
`SC_Agent_plugins` repository (external dependency, recorded here).

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -m unittest tests.test_packaging tests.test_release tests.test_notice` | pass |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0 |
| Licence gate | `rg -n -i "polyform\|licenseref-\|commercial_license\|unlicensed"` | only historical CHANGELOG lines |

## Steps

### Step 1: resolve the provenance blockers (STOP gate)

Owner decision recorded for the prompt file, icon and logo. If the decision
is only "confirm original", record who confirmed it in `docs/PROVENANCE.md`.

**Verify**: the three items have a recorded decision; otherwise STOP.

### Step 2: swap the licence text and files

Replace `LICENSE` with the verbatim Apache License 2.0 text and put
`Copyright 2026 Software Combined Pty Ltd` in the appendix. Delete
`COMMERCIAL_LICENSE.md`. Add a root `NOTICE` containing the copyright line and
the owner-approved attributions (the opencodex MIT text stays in
`THIRD_PARTY_NOTICES.md`, not duplicated here).

**Verify**: `head -3 LICENSE` shows Apache-2.0; `test -f NOTICE` passes;
`test ! -f COMMERCIAL_LICENSE.md` passes.

### Step 3: metadata and bundle

`pyproject.toml`: `license = "Apache-2.0"`, `license-files =
["LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"]`.
Both plugin manifests: `"license": "Apache-2.0"`.
`packaging/release.py`: replace the three-file tuple and its comment with
`'LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md'`.
`tests/test_packaging.py:82`: mirror the same tuple.

**Verify**: focused packaging/release tests pass; a built bundle lists the
three files and no commercial file.

### Step 4: documentation and changelog

Rewrite the `README.md` licensing section to the Apache-2.0 grant summary
(official text link `https://www.apache.org/licenses/LICENSE-2.0`), remove the
commercial bullet. Rewrite the `THIRD_PARTY_NOTICES.md` header. Record the
conversion in `docs/PROVENANCE.md` (date, Apache-2.0, commercial file removed,
NOTICE added; leave the import history intact). Add a `CHANGELOG.md`
`Unreleased` entry; leave the historical PolyForm entry untouched.

**Verify**: `rg -n -i "polyform" README.md docs/ THIRD_PARTY_NOTICES.md`
returns nothing.

### Step 5: version and licence-gate test

Bump `packaging/VERSION` and both plugin `version` fields per repository rule;
note `pyproject.toml`'s diverged version (`0.6.9`) in the changelog entry or
align it in this change. Add one test (extend `tests/test_packaging.py`) that
fails if any of `PolyForm`, `LicenseRef-PolyForm`, `COMMERCIAL_LICENSE` or
`UNLICENSED` reappears in `LICENSE`, `pyproject.toml`, both manifests,
`README.md` or `packaging/release.py`, and that asserts `NOTICE` exists and is
in the bundle inventory.

**Verify**: the new test fails on the pre-change tree and passes after;
focused and full suites pass; limits pass.

### Step 6: pre-publish scrub (with plan 144)

Audit repository text that is safe while private but not for a public
repository: internal `plans/` feed/account detail, the private-repository link
in `model-allocation-suggestion.md`, token-gated feed URLs and SSM parameter
names in `README.md` / `docs/operations.md` / `docs/linux-upgrade.md`, and the
infra identifiers in `infra/feed.yaml`. Decide per item: keep, genericise, or
move to an internal-only document.

**Verify**: a redacted `rg` scan for `ssm`, account IDs, bucket names and feed
URLs lists only the items the owner accepted as public.

## Done criteria

- [ ] Owner gates recorded; provenance blockers resolved.
- [ ] Apache-2.0 text in `LICENSE`; `COMMERCIAL_LICENSE.md` gone; `NOTICE` added.
- [ ] Metadata, bundle inventory, tests, README, PROVENANCE and changelog updated.
- [ ] Licence-gate test exists and fails without the change.
- [ ] Full suite, compile and limits gates pass; the pre-publish scrub is recorded.

## STOP conditions

- No recorded owner approval for Apache-2.0-only, the NOTICE wording, or the
  logo/trademark use: STOP.
- The prompt-file provenance cannot be resolved: STOP and ship nothing public.
- Any test or bundle still ships `COMMERCIAL_LICENSE.md` or a PolyForm string.

## Maintenance notes

- When the visibility flip happens (plan 144), update
  `docs/PROVENANCE.md`'s private/public notes and the plugin marketplace entry
  in the private `SC_Agent_plugins` repository.
- Keep `CHANGELOG.md` history intact; only add entries.
