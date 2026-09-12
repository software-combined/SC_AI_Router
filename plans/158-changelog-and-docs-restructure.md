# Plan 158: Changelog and docs restructure for a first-time reader

> **Executor instructions**: Follow this plan step by step. If a STOP condition
> occurs, stop and report. When done, update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 0024a42..HEAD -- CHANGELOG.md docs/ README.md AGENTS.md packaging/release.py tests/test_bundle_docs.py tests/test_packaging.py tests/test_release.py`
> The public-readiness task is editing `README.md`, `docs/README.md`,
> `docs/PROVENANCE.md` and moving the model-allocation pages into `plans/model-allocation/`.
> Land this plan after that work is merged and re-read those files first.

## Status and first proof

- Priority P2; effort S; risk LOW; confidence HIGH; category docs.
- Depends on the public-readiness documentation pass being merged. Independent
  of plans 152 to 157.
- Source: `plans/2026-09-12-architecture-scalability-review.md`, row "The
  changelog is one 1125-line file with 22 version headings".
- First proof: `CHANGELOG.md` opens on an `Unreleased` section followed by the
  current minor series and nothing else; every older entry survives verbatim in
  an archive page; the release bundle still ships the docs it shipped before;
  and `docs/README.md` indexes every page under `docs/`.

## Why this matters

Measured at `0024a42`: `CHANGELOG.md` is 1125 lines with 22 version headings,
running from `0.6.36` back to `0.4.0`. The oldest headings name plan numbers
that no longer resolve, for example `## 0.4.2 (Plan 047)`. A first-time public
reader opens it to find out what the current release does and has to scroll
past a year of internal detail. `AGENTS.md` section 6 makes updating it
mandatory for every user-visible change, so it only grows.

The docs tree is in better shape: `docs/README.md` indexes eleven pages and
`packaging/release.py:59` ships every `docs/**/*.md` to installed hosts. Two
things are worth fixing while the changelog is open: the index must stay
complete after the public-readiness move, and the dated review and audit
reports currently sitting at the top of `plans/` are historical documents that
a reader looking for the backlog has to step over.

## Scope

**In scope**: `CHANGELOG.md`, a new `docs/changelog-archive.md`, the docs index,
moving the dated report files within `plans/`, and the tests that pin the
shipped document set.
**Out of scope**: editing the content of any historical entry or report (they
are evidence), the licence and provenance work (plan 142), repository settings
(plan 144), the backlog tables themselves (plan 159), and `AGENTS.md` beyond
the one sentence step 4 changes.

## Steps

1. **Split the changelog.** Create `docs/changelog-archive.md` and move every
   heading below the current minor series into it verbatim, oldest last, under
   a one-paragraph preamble saying what it is and that entries are unedited.
   Keep the current minor series in `CHANGELOG.md` and add a link to the
   archive at the bottom. Do not reword a single historical entry.

2. **Add an `Unreleased` section.** `CHANGELOG.md` gains an `## Unreleased`
   heading above the newest version. Plans 147 and others already assume one
   exists (`plans/147-...md` maintenance note says "it belongs in
   `CHANGELOG.md` under Unreleased"), so this makes an existing convention
   real.

3. **Drop unresolvable plan numbers from headings.** In the archive, rewrite
   headings of the form `## 0.4.2 (Plan 047)` to `## 0.4.2`, applying the same
   rule plan 157 applies to source comments. Body text is untouched.

4. **Record the convention.** Add one sentence to `AGENTS.md` section 6: new
   entries go under `Unreleased` and move under the version heading when the
   tag is cut; entries older than the current minor series move to the archive.

5. **Keep the shipped document set correct.** `packaging/release.py:59` globs
   `docs/**/*.md`, so the archive ships to hosts automatically. Confirm that is
   wanted: if the owner prefers a smaller bundle, exclude the archive
   explicitly in `release.py` and record the exclusion in
   `docs/runtime-files.md`. Either way, update `tests/test_bundle_docs.py` so
   the expected set is asserted rather than inferred.

6. **Move the dated reports.** Create `plans/reviews/` and move the dated
   top-level files there (`2026-09-09-*`, `2026-09-10-*`, `2026-09-11-*`,
   `2026-09-12-*`), keeping their names. Update every reference to them:
   `plans/README.md` cites several, and so does every plan file that names its
   source report. Use `grep -rn "2026-09-[0-9][0-9]-" plans/ docs/ *.md` to
   find them all.

7. **Complete the docs index.** After the public-readiness move,
   `docs/README.md` must list every `.md` under `docs/`. Add a test to
   `tests/test_bundle_docs.py` that the index names every shipped page, so a
   new page cannot be added without an index row.

## Verification

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_bundle_docs tests.test_packaging tests.test_release` | pass |
| No content lost | `git show 0024a42:CHANGELOG.md \| wc -l` against `cat CHANGELOG.md docs/changelog-archive.md \| wc -l` | the second is the first plus the archive preamble and the link lines, and no other difference |
| Reference sweep | `grep -rn "plans/2026-09-" . --include="*.md" \| grep -v "plans/reviews/"` | no hits outside the moved files themselves |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | `failures=0` |

## STOP conditions

- A historical entry would have to be reworded to fit the archive: stop and
  keep it verbatim. The entries are the record of what shipped.
- Moving the dated reports would break a citation this plan cannot find: stop
  and report the citation.
- The public-readiness documentation pass has not merged yet: stop. Running
  this plan on top of an in-flight `README.md` and `docs/README.md` rewrite
  will conflict.

## Acceptance checklist

- [ ] `CHANGELOG.md` opens on `Unreleased` and holds the current minor series
      only.
- [ ] `docs/changelog-archive.md` holds every older entry verbatim.
- [ ] No changelog heading names an unresolvable plan number.
- [ ] `AGENTS.md` section 6 records the convention.
- [ ] The dated reports live under `plans/reviews/` and every citation follows.
- [ ] `docs/README.md` indexes every shipped page, enforced by a test.
- [ ] The shipped document set is asserted, not inferred.
- [ ] Full suite, compile and limits pass; `plans/README.md` row updated.

## Maintenance notes

- The archive is append-only: at each minor bump, the previous series moves
  down. Say so in the archive preamble so the next agent does not invent a
  different rule.
