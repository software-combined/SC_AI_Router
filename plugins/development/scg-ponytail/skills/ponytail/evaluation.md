# Ponytail maintenance

For people and agents changing `SKILL.md`. Not runtime instructions, so
`SKILL.md` does not link here.

## Why the rules exist

Keep a rule only while evaluation shows it changes behavior: test simplicity
rules against a no-skill baseline, and guardrails against the skill without
that guardrail. The evidence below is upstream Ponytail 4.10.0 benchmarks on
Claude and older GPT models with small samples, not measurements of this setup.

| Rule | Evidence |
| --- | --- |
| Find every caller; fix the shared function once, framed as the smaller diff | With this framing, root-cause fixes rose from 1/6 (no skill) to 6/6 on Sonnet 4.6 and Opus 4.8; a prose "trace the flow" version scored 0/3 on Opus. One seeded Python task; Haiku did not improve (upstream #245). |
| Explicit safety floor | On security tasks, a bare "YAGNI + one-liners" prompt was unsafe in 1 of 20 runs (path traversal, Haiku 4.5); Ponytail, which names trust-boundary validation, was 20/20. Dropping the "one line" rung is an inference from that failure: the tested Ponytail still had it. |
| A rung must meet the required behavior; a parser is not a validator | Under stdlib-first pressure, models used `email.utils.parseaddr` as a validator: email correctness fell from 100% to 79% on gpt-4.1 and from 98% to 94% on gpt-5.5. |
| Short skill; quick ladder | In single-shot tests (5 tasks, 10 reps, full ruleset sent each call), Ponytail cost 38.7% more on gpt-5.5 and 26.2% more on gpt-5.4-mini. Upstream attributes this to ruleset size and reasoning spent deliberating the rungs; deliberation was not measured separately. |
| One line per skip, no essays | In version 1 (n=1), essays defending skipped work left Ponytail about 4% above a terse-prose control on tokens, though about 11% below no skill. |
| Process rules (ask, reproduce, verify, stop, report) left to the host | `GLOBAL-AGENTS.md` loads in every runtime and owns them; restating them creates two owners. |

## Cases

Cases assume the global contract is loaded, as in real use.

| Case | Expected behavior | Failure signal |
| --- | --- | --- |
| A neutral coding prompt that never mentions Ponytail | The skill loads | Skill not loaded |
| A prose request such as "simplify this paragraph" | Skill not loaded | Skill loaded or coding rules applied |
| Add a date field; the project has no date component | Native `<input type="date">` | New picker library or custom component |
| Add a date field; a shared date picker exists | Reuse it | Native input or a new library |
| Export data in the one format requested | One function | Interface, factory, or registry for one exporter |
| A constant limit, with nobody asking for configuration | Keep the constant | New config option, flag, or environment variable |
| Extend an existing function for a new case | Change the existing path | Add `fooV2` or a parallel copy |
| Retry an HTTP call; the installed client supports retries | Configure the client's retry | Hand-rolled loop or a new dependency |
| Verify signatures or parse time zones with nothing installed | A maintained library | Hand-rolled crypto or parsing |
| Add one small helper | Put it beside related code | New module or file for one function |
| Fix a CSV import; an existing reader handles quoted commas | Reuse the reader; verify a quoted-comma row | Replace it with string splitting |
| Validate an email address | An explicit check that rejects malformed input | A parser such as `parseaddr` used as a validator |
| A cache with a required 60-second expiry | Deliver expiry, reusing a suitable implementation | Indefinite memoization, or refusing for lack of a profiler |
| Join an untrusted filename to a base directory | Keep the path-traversal check | Shortest join without it |
| A shared lookup accepts blank input; one form requires a value | Enforce the rule at the form; other callers unchanged | A shared rejection that breaks valid callers |
| Two entry points violate one shared invariant | Fix the shared logic; verify both paths | Patch only the reported path or duplicate the guard |
| One-line payment change with existing gates | Run the money path's checks | Skip or cap tests because the diff is small |
| An existing one-implementation interface isolates a service in tests | Keep it | Delete it for having one implementation |
| A complete feature with success, retry, and failure behavior | Deliver all of it | Ship part and ask whether the rest is wanted |
| Something a reader might assume exists was deliberately left out | One line: `Skipped X; add when Y.` | A paragraph defending it, or silence |
| Checks pass and no material defect remains | Stop and report | Extra hardening or features |
| Read-only review for over-engineering | Report evidenced simplifications and tradeoffs | Edit files or flag every abstraction |
| A detailed explanation is requested | Give it in full | Trim it to skip lines |

## Method

- Run each case in the target agent on a small fixture. Judge tool actions,
  diffs, checks, and the final answer; matching phrases in `SKILL.md` is not
  evidence.
- Isolate arms so each run loads only the version under test. The skill is
  installed globally and `GLOBAL-AGENTS.md` tells Codex to read it, so an
  unisolated baseline silently runs Ponytail; upstream hit the same
  contamination.
- Record per run: agent, model, skill version, case, result, diff lines,
  tokens, wall time, and whether the skill loaded.
- Compare the same cases before and after a change. One passing run is not
  reliability.
- Upstream's agentic harness (`benchmarks/agentic/`: tasks with good and bad
  references, runner, judge) is in
  `~/.codex/backups/ponytail/2026-10-01-2aeyl3eh/ponytail-4.10.0-original.tar.gz`.
  Codex's previous rewrite is in `~/.codex/backups/ponytail/2026-10-01-codex-rewrite/`.

Adapted from Ponytail 4.10.0 by Dietrich Gebert (MIT; see `LICENSE`).
