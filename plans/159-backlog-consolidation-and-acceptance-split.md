# Plan 159: Backlog consolidation and the acceptance split

> **Executor instructions**: Follow this plan step by step. If a STOP condition
> occurs, stop and report. When done, update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 0024a42..HEAD -- plans/`
> The public-readiness task is deleting plan files whose status is DONE and
> rewriting `plans/README.md`. Land this plan after that work is merged, then
> re-read `plans/README.md` and `ls plans/` before step 1. Plan 157 depends on
> the filenames this plan settles: land 159 first.

## Status and first proof

- Priority P2; effort S; risk LOW; confidence HIGH; category docs/process.
- Depends on the public-readiness backlog pass being merged. Blocks plan 157.
- Source: `plans/2026-09-12-architecture-scalability-review.md`, rows "Two plan
  numbers are used twice" and the "What does not scale" item on backlog
  hygiene.
- First proof: `ls plans/*.md` shows no number used twice, every remaining plan
  file has exactly one status row in `plans/README.md`, every owner-gated
  billed leg is listed in one acceptance file instead of scattered across
  fourteen plans, and the recommended execution order describes a public
  repository.

## Why this matters

Two numbers are used twice: `plans/139-native-key-popup.md` beside
`plans/139-router-private-feed-publication.md`, and
`plans/145-model-verification-gate.md` beside
`plans/145-router-tool-alias-repair.md`. Worse than the collision,
`139-native-key-popup.md` has no row in `plans/README.md` at all, even though
the modules it created (`ai_router/key_dialog.py`, `ai_router/key_prompt.py`,
`ai_router/setup_page.py`) all exist and its work shipped. A file with no
status row is invisible to the convention that keeps the backlog honest.

Separately, the backlog mixes two different kinds of work. Roughly half of the
open plans are local and executable by one agent in one session. The other half
cannot be finished without the owner's machines, the owner's subscriptions or
billed model calls: 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116,
117, 118, 119, 120, 121 and the probe legs of 150, 151 and the removed 145
pair. A contributor reading the backlog cannot tell which is which without
opening each file, and `plans/README.md`'s recommended order still describes a
private repository whose raw file URLs need a token. Plan 099's own STOP
condition names that as its blocker, so the public flip unblocks it and the
order needs to say so.

## Scope

**In scope**: `plans/README.md`, the plan files' status rows, renaming or
retiring the two collided numbers, and one new `plans/acceptance/README.md`.
**Out of scope**: changing any plan's technical content, deleting a plan whose
status is not DONE, the dated report files (plan 158 moves them), source
comments (plan 157), and any owner-gated setting or approval.

## Steps

1. **Reconcile against the merged tree.** Run `ls plans/*.md` and compare with
   the tables in `plans/README.md`. Produce a three-column list: files with a
   status row, files with no status row, and status rows with no file. Record
   it in the plan status row. Every later step works from that list, not from
   this plan's snapshot.

2. **Settle number 139.** If `139-native-key-popup.md` still exists, its work
   has shipped (the three modules named above are present and
   `tests/test_popup_style.py` pins the style rule it introduced), so give it
   the same treatment the backlog gives other completed plans: record it in the
   removal log in `plans/README.md` with its completion evidence, then delete
   the file. If the public-readiness pass already deleted it, confirm the
   removal log names it and move on. Do not renumber
   `139-router-private-feed-publication.md`: it is cited by
   `plans/README.md`'s publication wave and by plan 106.

3. **Settle number 145.** Both `145-model-verification-gate.md` and
   `145-router-tool-alias-repair.md` are recorded DONE. If either survives,
   record it in the removal log and delete it. If both survive, note that the
   verification gate is the one cited by plans 135, 151 and the external router
   review, so it is the one whose number must appear in the removal log
   unambiguously.

4. **Create the acceptance list.** Add `plans/acceptance/README.md` with one
   table: leg, owning plan, what it costs (owner machine, owner subscription,
   billed model calls), what evidence it must record, and where that evidence
   lands (`docs/compatibility.md` for client and OS versions). Populate it from
   the open plans listed in "Why this matters", plus the billed probe legs of
   150, 151 and the removed 145 pair, plus the new plans 152 to 158 that name
   an owner-gated leg. Move no plan file; the acceptance list points at the
   plans that own each leg.

5. **Mark every backlog row.** Add a column or a suffix to the
   `plans/README.md` tables marking each row `local` or `owner-gated`. A row
   with both a local and an owner-gated half, such as 151, is marked
   `local + gate` with the gate named in the sequencing cell.

6. **Reconcile the superseded and subsumed.** Record in `plans/README.md`,
   without editing the plan files' technical content: 143 is SUPERSEDED and
   stays as history; 106's publication half is owned by 139 and only its
   first-install and group-gating stages remain; 099's hourly refresh becomes
   available once the repository is public, because its own STOP condition
   named the private repository as the blocker; and plans 152 to 160 from the
   2026-09-12 architecture review join the order.

7. **Rewrite the recommended order for the public era.** Replace the phase list
   with one that reflects the flip: a local phase that a contributor can run
   (132, 137, 146, 147, 148, 152, 153, 154, 155, 156, 157, 158, 160, and 151
   stages 1 and 2), then the publication phase (142, 144), then 099's refresh
   wiring once the public feed and public raw URLs are live, then the
   owner-gated acceptance phase, which points at
   `plans/acceptance/README.md` rather than restating it.

8. **Add the numbering rule.** Add two lines to `plans/README.md`: a new plan
   takes the next free number above the highest existing file, and a number is
   never reused even after its file is removed, because the removal log and 212
   source comments resolve through it.

## Verification

| Purpose | Command | Expected |
|---|---|---|
| No duplicate numbers | `ls plans/*.md \| sed -E 's#plans/([0-9]{3}).*#\1#' \| sort \| uniq -d` | no output |
| Every file has a row | `for f in plans/[0-9]*.md; do n=$(basename "$f" \| cut -c1-3); grep -q "\[$n\](" plans/README.md \|\| echo "no row: $f"; done` | no output |
| Every row has a file | `grep -oE '\[[0-9]{3}\]\([0-9]{3}-[a-z0-9-]+\.md\)' plans/README.md \| sed -E 's/.*\((.*)\)/\1/' \| while read p; do test -f "plans/$p" \|\| echo "no file: $p"; done` | no output |
| Acceptance list exists | `test -f plans/acceptance/README.md && echo ok` | `ok` |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 (this plan touches no code, so the suite must be unchanged) |

## STOP conditions

- A plan file's status is not DONE and this plan would delete it: stop. Only
  completed plans leave the tree, and only with a removal-log entry.
- A number appears in a source comment and this plan would make it
  unresolvable: stop and coordinate with plan 157, which owns those comments.
- The public-readiness backlog pass has not merged: stop. Two agents rewriting
  `plans/README.md` at once will lose rows.

## Acceptance checklist

- [ ] No plan number is used twice.
- [ ] Every plan file has exactly one status row and every status row has a
      file.
- [ ] `plans/acceptance/README.md` lists every owner-gated billed or
      machine-bound leg with its owning plan and its evidence destination.
- [ ] Every backlog row is marked `local`, `owner-gated` or `local + gate`.
- [ ] The recommended order describes a public repository and includes 152 to
      160.
- [ ] The numbering rule and the never-reuse rule are written down.
- [ ] The test suite is untouched and still green.
- [ ] `plans/README.md` row for this plan updated.

## Maintenance notes

- The acceptance list is the artefact a contributor needs most: it is the
  honest answer to "why is this plan still open after a year".
- Keep the removal log complete. Plan 157's test resolves source comments
  through it, so an omission there becomes a failing test rather than a silent
  dead link.
