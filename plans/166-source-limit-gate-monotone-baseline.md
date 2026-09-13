# Plan 166: Make the source-limit baseline a ceiling, not an exact count

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report; do not improvise.
> When done, update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat c068368..HEAD -- tools/check_source_limits.py config/source-limits-baseline.json AGENTS.md tests/test_source_limits.py plans/156-ci-and-test-hardening-for-a-public-repo.md`
> If any in-scope file changed, compare the "Current state" excerpts against
> the live code before proceeding; on a mismatch, STOP.

## Status

- **Priority**: P1 (it removes friction from every other plan)
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none; reconcile with plan 156 step 4 (see Step 4)
- **Category**: dx
- **Planned at**: commit `c068368` (`origin/develop`), 2026-09-13
- **Source**: `plans/2026-09-13-router-four-lane-audit.md`, finding F6

## Why this matters

`tools/check_source_limits.py` fails a file above its soft cap unless the
baseline records its exact current line count. Any edit that changes the
length of a baselined file, including deleting dead code or a comment, fails
the gate until `config/source-limits-baseline.json` is re-synced. The result
is visible in history: the baseline is the most frequently changed file in
the repository (57 of the last 200 commits on `main`), and 44 files carry an
entry. The gate also never validates the entries it holds: `ai_router/router.py`
is recorded at 204, below the 250 soft cap, so the entry is inert, and the
2026-09-12 review found two stale entries. Meanwhile the three largest
modules (`compaction.py` 395, `tool_adapter.py` 394, `catalogue.py` 393) sit
within six lines of the 400 hard cap, so the gate is about to force a split
of each on the next small edit whether or not a responsibility boundary
exists there. The intent of the cap (keep modules small, stop growth) is
right; the mechanism should reward shrinking and forbid growth.

## Current state (verified at c068368)

- `tools/check_source_limits.py:8-9`: `SOFT = {'ai_router': 250, 'tools': 400, 'tests': 300, 'packaging': 400}`; `HARD = {'ai_router': 400, 'tools': 700, 'tests': 500, 'packaging': 700}`.
- `tools/check_source_limits.py:20-25`:

```python
            if count > HARD[area]:
                print(f'HARD {rel}: {count} lines')
                failures += 1
            elif count > SOFT[area] and baseline.get(rel) != count:
                print(f'SOFT {rel}: {count} lines (not in baseline)')
                failures += 1
```

- `config/source-limits-baseline.json`: 44 entries; 11 under `ai_router/`
  including `"ai_router/router.py": 204` (below the soft cap, inert);
  entries for `tests/` and `packaging/` files as well.
- `AGENTS.md` section 3: "Modules 250 lines soft / 400 hard, entrypoints and
  tools 400/700, tests 300/500. Checked by `python3.14 tools/check_source_limits.py`."
- `plans/156-ci-and-test-hardening-for-a-public-repo.md`, remaining work
  item 4: "Make the source-limits baseline reject nonexistent files,
  incorrect counts, and entries now below their soft cap. Reconcile against
  current source and add one failing-baseline regression check."
- There is no `tests/test_source_limits.py`; the tool has no test.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| The gate | `python3.14 tools/check_source_limits.py` | `source-limits: checked=N failures=0` |
| New test | `python3.14 -B -m unittest tests.test_source_limits` | pass |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Lint | `python3.14 -m ruff check --select F401,F811 ai_router packaging tools tests` | pass |
| Policy scans | `python3.14 tools/check_policy_scans.py` | pass |

## Scope

**In scope**: `tools/check_source_limits.py`, `config/source-limits-baseline.json`,
`tests/test_source_limits.py` (create), `AGENTS.md` section 3 (two
sentences), `plans/156-ci-and-test-hardening-for-a-public-repo.md` (one
sentence in item 4), `plans/README.md` (status rows).

**Out of scope**: the cap values themselves; splitting any module; the CI
workflow (it already runs the tool, `.github/workflows/check.yml:72`).

## Git workflow

- Worktree based on `develop`; branch like `<you>/166-source-limit-gate-20260913`.
- One commit: `chore: make the source-limit baseline a ceiling and prune it`.
  Run `pre-commit-review`. No push or PR unless instructed.

## Steps

### Step 1: Ceiling semantics

Replace the `elif` at `tools/check_source_limits.py:23-25` with:

```python
            elif count > SOFT[area]:
                ceiling = baseline.get(rel)
                if ceiling is None or count > ceiling:
                    print(f'SOFT {rel}: {count} lines (baseline {ceiling})')
                    failures += 1
```

A baselined file may shrink or hold its size; growth above its recorded
count fails; a file above the soft cap with no entry fails as before.

### Step 2: Validate the baseline itself

After the walk, add checks over every baseline entry:

- the path exists under the repository root (else print `STALE <rel>: file missing`, count a failure);
- the file's actual line count is above `SOFT[area]` (else print `STALE <rel>: below the soft cap, remove the entry`, count a failure) — check the file, not the recorded number: `ai_router/upstream.py` is recorded at 281 but is 250 lines today, so a recorded-count test would keep the inert entry this step exists to remove;
- the recorded count is at most `HARD[area]` (else print `STALE <rel>: above the hard cap`) — report only, do not count a failure: the walk's own `HARD` branch already fails that file, and Step 4 expects exactly one failure for it.

Derive `area` from the first path segment; an entry outside the four areas
is stale.

### Step 3: Prune and re-sync the baseline

Run the tool; remove every entry it reports as stale (at the planning commit
that includes `ai_router/router.py`), and lower no other entry. Do not raise
any entry: the recorded counts become ceilings. Re-run until `failures=0`.
An entry may stay above its file's current length and still be correct:
`ai_router/upstream.py` is 250 lines but stays recorded at 281, which is fine
under the monotone rule (the file may shrink freely and its ceiling still
forbids growth past 281), but it is not a statement of the file's size.

**Verify**: `python3.14 tools/check_source_limits.py` → `failures=0`; `python3.14 -c "import json; d=json.load(open('config/source-limits-baseline.json')); print(len(d))"` → fewer entries than 44.

### Step 4: Test the gate

Create `tests/test_source_limits.py`. Import the tool by path with
`importlib.util.spec_from_file_location` (it is a script, not a package
module) or refactor `main()` to accept `root` and `baseline` arguments and
return `(checked, failures)`; the second is cleaner, but the `__main__` guard
at `tools/check_source_limits.py:29-30` must then turn the pair into an exit
status (`sys.exit(1 if main()[1] else 0)`) or CI fails on the tuple
(`.github/workflows/check.yml:72` runs the script). Cases, each built in a
`tempfile.TemporaryDirectory` with an
`ai_router/` file of a chosen length and a baseline dict:

- 260 lines, no entry → 1 failure; 260 lines, entry 260 → 0; 259 lines, entry 260 → 0 (shrinking passes); 261 lines, entry 260 → 1 (growth fails);
- 401 lines, entry 401 → 1 (hard cap wins);
- entry for a missing file → 1; entry 240 (below soft) → 1;
- entry whose first path segment is outside the four areas → 1 stale failure, no exception;
- a 249-line file with no entry → 0.

Also add one assertion that the live `config/source-limits-baseline.json`
has no entry whose file is at or below its area's soft cap — compare the
file's actual line count, not the recorded number (the regression check plan
156 item 4 asked for).

**Verify**: `python3.14 -B -m unittest tests.test_source_limits` → pass.

### Step 5: Words

- `AGENTS.md` section 3: after "Checked by `python3.14 tools/check_source_limits.py`."
  add: "A file above the soft cap needs a baseline entry, which is a ceiling:
  the file may shrink freely and may not grow past the recorded count.
  Remove the entry once the file is back under the cap."
- `plans/156-ci-and-test-hardening-for-a-public-repo.md` item 4: append
  "(landed by plan 166; the 'incorrect counts' check is 'counts above the
  recorded ceiling')".

**Verify**: policy scans and lint pass; full suite passes.

## Test plan

- New `tests/test_source_limits.py` with the nine cases in Step 4.
- Existing: none affected (the tool has no other tests).

## Done criteria

- [ ] `grep -n "baseline.get(rel) != count" tools/check_source_limits.py` returns no matches.
- [ ] `python3.14 tools/check_source_limits.py` → `failures=0` with the pruned baseline.
- [ ] `tests/test_source_limits.py` passes, including the live-baseline assertion.
- [ ] Full suite, compile, lint and policy scans pass; only in-scope files changed.
- [ ] `plans/README.md` status rows for 166 (DONE) and 156 (item 4 note) updated.

## STOP conditions

- The pruned baseline leaves a file above its hard cap: that is a real
  violation the old exact-match rule was hiding; report it, do not raise the
  hard cap.
- Plan 156's executor has already changed the tool: reconcile against their
  version rather than this excerpt.

## Maintenance notes

- Lower an entry whenever a file shrinks, so the ceiling keeps tightening;
  a reviewer should question a raised entry the way they would question a
  raised cap.
- The three modules within six lines of the hard cap (`compaction.py`,
  `tool_adapter.py`, `catalogue.py`) still need a responsibility-led split
  before they grow; this plan buys time, it does not remove the cap.
