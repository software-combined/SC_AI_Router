---
name: ponytail
description: >-
  Chooses the simplest complete, correct solution. Use on any coding task
  (writing, designing, fixing, refactoring, or reviewing code, or choosing a
  dependency) and when the user asks to simplify code, cut over-engineering,
  apply YAGNI, or use Ponytail. Works alongside debugging, testing, and review
  skills. Not for prose or other non-code tasks.
license: MIT
---

# Ponytail

This skill ships with the SCG router; see [automatic updates](../../references/updates.md).
There is no per-plugin updater or schedule to configure. Respect explicit
read-only scope.

Build everything the task requires and nothing it does not. Minimize total
complexity: code, dependencies, state, coupling, runtime cost, and operational
burden. Line count is a clue, not the goal.

## Ladder

Before changing a function, find every caller and reference (for example
`rg -nw fnName`; text search can miss Blueprint, reflection, route, and
cross-repo callers). Patching only the reported path leaves sibling callers
broken: fix the shared function once when the corrected rule holds for every
caller, since one guard there is a smaller diff than one per caller; otherwise
fix the caller that owns the rule.

Take the first rung that meets the required behavior on the supported
runtimes. The ladder is a quick check, not an analysis; do not list the rungs
you rejected.

1. **Nothing.** The outcome already holds, or the piece is speculative: not
   requested and not needed by what was requested.
2. **Existing code.** Search the codebase first. Reuse a helper with the same
   semantics, or change the existing path; never add a parallel version of
   existing logic.
3. **Standard library or platform.** `<input type="date">` over a picker
   library, a unique index over check-then-insert, the engine's timer over a
   hand-rolled tick counter.
4. **A dependency.** Use an installed one. Add a new one only when it removes
   more risk than it adds (parsing, crypto, time zones), never for what a few
   lines do.
5. **Minimum new code** for the remaining gap.

Similar names or fewer lines prove nothing: a parser is not a validator, and a
cache with 60-second expiry is not `lru_cache`. Do not force reuse through a
fragile adapter, and do not rewrite working code to reach a higher rung.

If a much simpler option would meet the user's underlying goal, build what was
asked and mention the option once, in one line.

## Rules

- No structure for a single case: no interface, factory, base class, or
  wrapper with one implementation or caller, and no config option or flag for
  a value that never varies, unless it serves a concrete source of change or
  test isolation.
- Put new code where related code already lives; add a file only for a
  distinct responsibility.
- When two changes both meet the requirement, prefer the one that deletes or
  narrows code.
- Boring over clever: a few readable lines beat a dense one-liner.
- Never simplify away input validation at trust boundaries, security, error
  handling that prevents data loss, accessibility, or required reliability.
- Diff size never lowers the verification bar: a one-line change to a money,
  auth, data, or concurrency path gets that path's full checks. Otherwise add
  the smallest set of checks, using the project's existing test tools, that
  would fail if the new logic broke; none only if an existing test already
  covers the changed path.
- Mark a known, acceptable limit that will matter later with a code comment:
  `ponytail: <limit>; <upgrade> when <trigger>.` Never use it to excuse a
  defect.
- Do not defend simplifications in prose. For each thing a reader might assume
  you built but you deliberately left out, write one line:
  `Skipped X; add when Y.`
