# Plan 157: Source reference hygiene - every plan pointer resolves

> **Executor instructions**: Follow this plan step by step. If a STOP condition
> occurs, stop and report. When done, update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 0024a42..HEAD -- ai_router/ packaging/ tools/ tests/ plans/README.md docs/architecture.md`
> This plan edits comments and docstrings across four trees, so it conflicts
> with almost anything in flight. Run it in one session on a quiet tree, after
> plans 152 to 156 have landed or before any of them starts. Plan 159 renames
> two plan files: land 159 first if it is in flight.

## Status and first proof

- Priority P2; effort S-M; risk LOW; confidence HIGH; category docs/tech-debt.
- Depends on plan 159 if 159 is in flight (it changes two plan filenames).
  Otherwise independent.
- Source: `plans/2026-09-12-architecture-scalability-review.md`, row
  "Source carries 212 plan references on 123 lines; 84 of those lines name 23
  plan numbers with no file".
- First proof: a new test walks every `Plan NNN` reference in `ai_router/`,
  `packaging/`, `tools/` and `tests/` and fails when one does not resolve to a
  plan file, a parked plan, the renumbering map or a recorded removal; and the
  84 currently dangling lines all resolve.

## Why this matters

The repository uses plan numbers as the provenance mechanism in comments, which
is a good habit and is worth keeping. Measured at `0024a42`: 212 references on
123 source lines. Of those, 84 lines name 23 numbers with no file anywhere in
`plans/`: 036, 037, 041, 044, 045, 046, 047, 049, 054, 055, 056, 057, 058,
059, 060, 061, 062, 063, 064, 066, 067, 068, 069. Some were renumbered
(`plans/README.md` carries the map: 041 to 110, 044 to 118, 045 to 109, 046 to
099, 049 to 112, 054 to 106, 055 to 107, 057 to 116, 058 to 117, 059 to 105,
066 to 119) and some were removed after completion (the removal log in the same
file). A reader who follows `packaging/codex_config.py:1` to `plans/063-*.md`
finds nothing, and that reader is about to be a member of the public.

Nothing enforces this today, so the count only grows.

## Scope

**In scope**: comments and docstrings under `ai_router/`, `packaging/`,
`tools/` and `tests/`; one new test; a short convention note in
`plans/README.md`.
**Out of scope**: any behaviour change, any code change beyond comment text,
renaming or deleting any plan file (plan 159), the `codex_router/` shim removal
(its condition is recorded in `plans/README.md` and stays there), and the
`CHANGELOG.md` plan references in version headings (plan 158).

## Steps

1. **Build the resolver.** Add `tests/test_plan_references.py` with a helper
   that, for a number `NNN`, resolves in this order: a file matching
   `plans/NNN-*.md`; a file matching `plans/parked/NNN-*.md`; an entry in the
   renumbering map parsed from `plans/README.md`; an entry in the removal log
   parsed from the same file. Anything else is unresolved. Derive the
   dangling set from the merged tree at execution time, not from this plan's
   snapshot: the 2026-09-12 prune removed more completed plan files after
   this plan was written, and every one of them is in the removal log, so
   their citations resolve.

2. **Prove the resolver is not vacuous.** In the same test, assert that a
   fabricated number such as `Plan 999` resolves to nothing, following the
   pattern at `tests/test_domain_boundaries.py:84-102`.

3. **Rewrite the renumbered references.** For each of the 11 numbers in the
   renumbering map, replace the reference with the current number and keep the
   sentence. For example `packaging/claude_config.py:1` "(Plan 049)" becomes
   "(Plan 112)". Do not restate the plan's content; the point is that the
   pointer resolves.

4. **Rewrite the unresolved references.** Take the set that step 1's resolver
   reports as unresolved on the merged tree; it may be empty, because the
   removal log already covers the completed plans removed on 2026-09-10 and
   2026-09-12. For each remaining number, the plan text is gone and only git
   history holds it: drop the number and keep the reason in plain words.
   Where the number is the only thing the comment says, delete the comment.
   Where the sentence carries a real invariant, keep the sentence and drop
   the number. A number the removal log records is never stripped here.

5. **Keep resolving references as they are.** A reference to a plan that
   still has a file after the 2026-09-12 prune, to one of the two parked
   numbers, or to a number the removal log records stays untouched. The test
   proves it resolves; that is the whole contract.

6. **Add the convention.** Add three lines to `plans/README.md` under the
   executor rules: a source comment may cite a plan number only while it
   resolves through a plan file, a parked file, the renumbering map or the
   removal log; a completed plan leaves the tree only together with its
   removal-log entry, so its citations keep resolving;
   `tests/test_plan_references.py` enforces it.

7. **Record the shim decision without acting on it.** `codex_router/__init__.py`
   documents its own removal condition and `plans/README.md` carries the owner.
   Add nothing and remove nothing; confirm in the plan status row that the
   condition is unchanged, so a future reader does not re-litigate it.

## Verification

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_plan_references` | pass; zero unresolved references |
| Count before and after | `grep -rhoE "Plan [0-9]{3}" --include="*.py" ai_router packaging tools tests \| sort -u \| wc -l` | the distinct set shrinks from 54 to the live set only |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Lint | `python3.14 -m ruff check --select F401,F811 ai_router packaging tools tests` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | `failures=0` |

## STOP conditions

- Dropping a plan number would remove the only record of why a line exists:
  stop on that line, keep the sentence, and report it. Provenance beats
  tidiness.
- The renumbering map in `plans/README.md` is ambiguous for a number: stop and
  report the number rather than guessing which plan it meant.
- The edits would touch a line that carries executable behaviour: stop. This
  plan changes comment text only.

## Acceptance checklist

- [ ] `tests/test_plan_references.py` exists, resolves through files, parked
      files, the renumbering map and the removal log, and is proven non-vacuous.
- [ ] Zero unresolved plan references in `ai_router/`, `packaging/`, `tools/`
      and `tests/`.
- [ ] Renumbered references point at their current number; unresolved
      references keep their reason and drop the number.
- [ ] `plans/README.md` states the convention and names the enforcing test.
- [ ] No behaviour change: the diff is comments and one new test file.
- [ ] Full suite, compile, lint and limits pass; `plans/README.md` row updated.

## Maintenance notes

- The test is the point. Without it the count returns, because every future
  plan adds references and some future plan removes a file.
- `CHANGELOG.md` also carries plan numbers in version headings; plan 158 owns
  that file and should apply the same rule when it archives.
