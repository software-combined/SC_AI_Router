# Plan 059: Enforce packaging size limits and per-domain test rules

> REJECTED RETRY DRAFT. Do not execute. See this folder's README and the active parent plan index.

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 6840312..HEAD -- packaging tools tests config AGENTS.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plans/057-service-backend-interface.md
- **Category**: dx
- **Planned at**: commit `6840312`, 2026-09-09

## Why this matters

Two guardrails are missing exactly where growth will hurt. First,
`packaging/install.py` sits at 699/700 lines with `packaging/service.py`
at 601 lines, and the only thing stopping the next OS or client from
pushing both over the hard limit is reviewer memory — the checker
(`tools/check_source_limits.py`, 30 lines) enforces router/test limits
from `config/source-limits-baseline.json` but packaging has no recorded
rule beyond the AGENTS.md prose. Second, test placement is conventional
but unwritten: 47 test files mirror module names, fakes live in
`tests/fakes.py` with platform selection in `tests/_platform.py`, yet
nothing tells the next contributor where a Windows-backend test or a
Kiro-adapter test belongs, or that installer tests must fake `run` and
never shell out. After this plan both rules are machine-checked: the
size gate fails the build on growth, and a short testing-rules note
plus one meta-test keeps new tests in their domain homes.

## Current state

The relevant files, each with one line on its role:

- `tools/check_source_limits.py` (30 lines) — enforces module/entrypoint/test limits against baselines
- `config/source-limits-baseline.json` — per-file baselines (covers `codex_router/*`, installer, and large tests)
- `packaging/install.py` (699 lines) — at the entrypoint hard limit; Plan 057 must shrink it
- `packaging/service.py` (601 lines) — shared service helpers, over the 400-line module hard limit by prose exception ("Split out of packaging/install.py")
- `tests/_platform.py` — platform selection helper for tests
- `tests/fakes.py` — shared fakes (fake `run`, fake router home)
- `AGENTS.md` — project-doc §3 states the limits prose (250/400, 400/700, 300/500)

The limits prose today (`AGENTS.md` §3): "Modules 250 lines soft / 400
hard, entrypoints and tools 400/700, tests 300/500." `service.py`
(601) exceeds the module hard limit with only a code-comment
justification; after Plans 056-057 split it, each piece must fit the
stated limits with no exceptions file.

## Commands you will need

| Purpose   | Command                                             | Expected on success |
|-----------|-----------------------------------------------------|---------------------|
| Tests     | `python3.14 -m unittest discover -s tests -t .`     | `OK`                |
| Compile   | `python3.14 -m compileall -q codex_router tools tests packaging` | exit 0   |
| Limits    | `python3.14 tools/check_source_limits.py`           | `failures=0`        |

## Scope

**In scope** (the only files you should modify):

- `tools/check_source_limits.py` — extend to packaging-size + test-placement rules ONLY (no redesign of the checker)
- `config/source-limits-baseline.json` — re-baseline moved files after Plans 056-057
- `tests/test_repo_rules.py` (create) — one meta-test asserting the domain rules below
- `AGENTS.md` — append the two-sentence test-placement rule to §3 (docs-only edit, no behavior)

**Out of scope** (do NOT touch, even though they look related):

- Splitting any module yourself — Plans 056-057 do the splits; this plan only gates the result
- Router or installer behavior — zero functional change
- `docs/`, `README.md`, `CHANGELOG.md`, `packaging/VERSION` — no user-visible change

## Git workflow

- Branch: `advisor/059-packaging-size-and-test-rules` off `develop`
- Commit per step; message style `<type>: <short summary>` (`feat`/`fix`/`refactor`/`test`/`chore`/`docs`)
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Re-baseline moved files, gate packaging pieces as modules

After Plans 056-057 land, update `config/source-limits-baseline.json`
so every moved path has an entry at its moved line count. Then extend
`tools/check_source_limits.py` minimally: every file under
`packaging/` except `install.py` is checked as a module (250 soft /
400 hard); `install.py` keeps the entrypoint rule (400/700). No other
checker behavior changes. If `service.py` still exists at 601 lines at
this point, the checker must FAIL on it — that failure is the forcing
function for completing the Plan 057 split, not something to
grandfather with a new exception.

**Verify**: `python3.14 tools/check_source_limits.py` → `failures=0` (or exactly the service.py failure that Plan 057 must clear — record which)

### Step 2: Write the test-placement rule and its meta-test

Append to `AGENTS.md` §3 (two sentences, no other AGENTS.md edits):

"Tests mirror their domain: `test_service_backend.py`/`test_systemd.py`/
`test_launchd.py` for service backends, `test_client_adapter.py`/
`test_claude_ingress.py`/`test_catalogue.py` for client adapters,
`test_mixed_router.py`/`test_providers.py`/`test_handler.py` for the
request path. Installer and backend tests fake the `run` callable
(`tests/fakes.py`) and never shell out, touch the network, or write
outside a temp home."

Create `tests/test_repo_rules.py` asserting:

- every `packaging/*.py` file except `install.py` is ≤400 lines;
  `install.py` is ≤700 lines (read the files, count lines — no imports needed).
- every test file asserting on `schtasks`/`systemctl`/`launchctl` argv
  patches `run` (source assertion: the test file imports from
  `tests.fakes` or defines a local fake — grep the test source).
- no test file imports `urllib.request.urlopen` without going through a
  fake (same source-assertion technique).

Keep the meta-test under 100 lines; it reads source text, never executes backends.

**Verify**: `python3.14 -m unittest discover -s tests -t .` → `OK`

### Step 3: Full gate

Run the trio. Update `plans/README.md` status row for this plan.

**Verify**: suite `OK`, compileall exit 0, limits `failures=0`

## Test plan

- New `tests/test_repo_rules.py` (3 assertions above), self-testing the
  repo's own rules; pattern: plain unittest reading file text, no fakes needed.
- Full suite green; checker green with no new exceptions.

## Maintenance note

When the fourth OS or fourth client lands, its author adds no config:
the meta-test picks up the new files by directory convention
(`packaging/*`, `tests/*`). Reviewers: a size failure is a split
signal, not a baseline-bump signal — bump baselines only for moves,
never for growth.

## STOP conditions

- If the drift check shows in-scope files changed since `6840312`, stop and reconcile.
- If enforcing the packaging rule requires splitting a module inside
  THIS plan, stop: splits belong to Plans 056-057; record the failure
  and hand back instead of expanding scope.
- If the suite drops below its incoming pass count, stop and report.

## Done criteria

- [ ] Packaging pieces gated as modules (250/400), `install.py` as entrypoint (400/700), no exceptions
- [ ] Test-placement rule in AGENTS.md §3 + enforcing meta-test
- [ ] `python3.14 -m unittest discover -s tests -t .` → `OK`
- [ ] `python3.14 tools/check_source_limits.py` → `failures=0`
- [ ] Status row for this plan updated in `plans/README.md`
