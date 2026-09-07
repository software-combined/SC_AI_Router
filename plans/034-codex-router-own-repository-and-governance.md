# Plan 034: Move the Codex model router into its own product repository with governance and CI

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 749a6b8d..HEAD -- domains/ai-platform/codex-model-router`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (source-only move; the deployed router on any machine is untouched until Plan 041 installs from the new repo)
- **Depends on**: none
- **Category**: tech-debt / direction
- **Planned at**: commit `749a6b8d` on branch `codex/codex-adapter-20260907` of `software-combined/SC_Infrastructure`, 2026-09-07

## Why this matters

The router is becoming a product that staff install and that auto-updates, but it currently lives as a directory inside the SC_Infrastructure monorepo on an unmerged branch. That home is wrong for three reasons. The monorepo's rules (Fargate defaults, CloudFormation under `reference/`, `npm run check` running synth and template validation) do not apply to a stdlib Python client tool, and its own `domains/ai-platform/README.md` says the domain does not own provider contracts. An auto-updater needs a narrow, stable release feed; giving every staff machine read access to the infrastructure monorepo to fetch a router bundle is a needless exposure. And the product needs its own version tags, changelog, compatibility matrix and CI that runs the Python tests on every change, which the monorepo CI does not do today (it is Node only). This plan creates the dedicated repository, moves the code into a package layout, and gives it the same governance quality the monorepo has, so every later plan lands in the right place.

## Current state

- Source directory in SC_Infrastructure: `domains/ai-platform/codex-model-router/` (20 files, present only on branch `codex/codex-adapter-20260907`, pushed to origin, no pull request open, not on `main`).
- Runtime modules (flat, sibling imports): `mixed_router.py` (HTTP server and handler), `tool_adapter.py`, `capabilities.py`, `compaction.py`, `apply_catalogue.py`, `update_reasoning_catalog.py`.
- Operator tools: `probe_codex_runtime.py` (paid live probe through the Codex desktop app-server), `disable.py` (removes the config block and stops the LaunchAgent).
- Tests: `test_mixed_router.py`, `test_tool_adapter.py`, `test_capabilities.py`, `test_compaction.py`, `test_apply_catalogue.py`, `test_packaging.py` (unittest, no dependencies).
- Packaging: `packaging/VERSION` (`0.3.0`), `packaging/install.sh`, `packaging/install.ps1`, `packaging/SOURCES.txt`.
- `.gitignore` in that directory excludes runtime state: `mixed-router-state.json`, `activation.json`, `mixed-models.json`, `config-before.toml`, `compatibility-release.json`, `before-*/`, `*.log`.
- Imports are sibling imports, for example `mixed_router.py:11-13`:

```python
from tool_adapter import prepare_tools, stream_events, ToolEvents
from capabilities import OPENROUTER_HOST, OPENROUTER_MODELS
import compaction as comp
```

- Entry point is `mixed_router.py:231-233`:

```python
if __name__ == '__main__':
    state = json.loads(STATE.read_text())
    Router(state).serve_forever()
```

- The monorepo CI to mirror is `.github/workflows/check.yml` (top-level `permissions: contents: read`, `concurrency` group with `cancel-in-progress: true`, job `timeout-minutes: 15`, every action pinned to a full commit SHA). The policy is enforced by `scripts/validate-github-actions.mjs` (must declare permissions, concurrency group, timeout, pinned SHAs, no `write-all`/`read-all`).
- Monorepo source limits (`AGENTS.md`, enforced by `scripts/check-source-limits.mjs`): modules 250 lines soft / 400 hard, entrypoints 400/700, tests 300/500. Keep the same numbers in the new repo.
- Commit message convention: `<type>: <summary>` with type in `feat|fix|refactor|test|chore|docs` (shared commit-msg hook at `~/.config/scg-agent-git-hooks/`).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Router tests (monorepo) | `/opt/homebrew/bin/python3 -m unittest discover -s domains/ai-platform/codex-model-router -p 'test_*.py'` | last line `OK` |
| Router tests (new repo) | `python3.14 -m unittest discover -s tests -t .` | last line `OK` |
| Byte-compile check | `python3.14 -m compileall -q codex_router tools tests` | exit 0, no output |
| Workflow policy (monorepo copy) | `node scripts/validate-github-actions.mjs` | exit 0 |
| Resolve an action SHA | `gh api repos/actions/checkout/git/ref/tags/v4 --jq .object.sha` | 40-hex SHA |

Python 3.14 is required at runtime because `mixed_router.py:8` imports `compression.zstd` (Codex compresses request bodies with zstd). On this machine it is `/opt/homebrew/bin/python3` (3.14.4). Use whichever 3.14 interpreter exists; do not lower the version.

## Scope

**In scope**:
- New repository `software-combined/codex-model-router` (name is a recommendation; see Step 1).
- All files under `domains/ai-platform/codex-model-router/` are copied and restructured into the new repository.
- New repository files: `AGENTS.md`, `README.md` (short pointer; Plan 042 writes the full one), `SECURITY.md`, `CODEOWNERS`, `.gitignore`, `.github/workflows/check.yml`, `tools/check_source_limits.py`, `docs/PROVENANCE.md`, `pyproject.toml` (metadata only, no dependencies), `plans/` (copy of plans 034 to 042 from this folder).

**Out of scope**:
- Do not delete `domains/ai-platform/codex-model-router/` from SC_Infrastructure in this plan. Removal is Step 9 and is gated on the new repository's CI being green and Plan 041's first release existing.
- Do not touch `~/.codex/mixed-model-router/` (deployed runtime) or `~/.codex/config.toml` on any machine.
- Do not change router behaviour. Only imports, file locations and the entry point move.
- Do not add third-party Python dependencies. Stdlib only is a product rule.

## Git workflow

- SC_Infrastructure: read-only for this plan except Step 9 later. Work from a dedicated worktree if you must edit it; never edit the primary checkout.
- New repository: default branch `main`, first commits directly on `main` until branch protection is enabled in Step 7, then feature branches `codex/<slug>-<yyyymmdd>` and pull requests.
- Commit messages `<type>: <summary>`. Example from the monorepo log: `fix: tolerate predated router state without request cap key`.
- Do NOT push to SC_Infrastructure or open pull requests there unless the operator instructs it.

## Steps

### Step 1: Record the two operator decisions, then create the repository

Two decisions belong to Cyril, not the executor. Confirm both before running anything:

1. Repository name and visibility. Recommended: `software-combined/codex-model-router`, **public**. Rationale: the code contains no secrets by design, and a public repository lets Plan 041's updater fetch GitHub Releases without distributing any token to staff machines. If Cyril prefers private, record that the release feed must then be an S3 plus CloudFront bucket provisioned from SC_Infrastructure, and Plan 041 uses that feed instead.
2. CODEOWNERS: recommended `* @cyrilallart` plus the second steward Cyril names.

With approval recorded in your report, create the repository:

```sh
gh repo create software-combined/codex-model-router --public --description "Local Codex model router: ChatGPT subscription plus OpenRouter models, one picker" --disable-wiki
```

(Use `--private` if that was the decision.)

**Verify**: `gh repo view software-combined/codex-model-router --json name,visibility --jq '.name+" "+.visibility'` prints the name and the chosen visibility.

### Step 2: Clone and lay out the package

```sh
git clone git@github.com:software-combined/codex-model-router.git ~/Documents/Github/codex-model-router
cd ~/Documents/Github/codex-model-router
mkdir -p codex_router tools tests packaging plans docs .github/workflows
```

Copy from the SC_Infrastructure worktree `domains/ai-platform/codex-model-router/` (path `SRC` below):

| From `SRC` | To |
|---|---|
| `mixed_router.py` | `codex_router/router.py` |
| `tool_adapter.py`, `capabilities.py`, `compaction.py`, `apply_catalogue.py`, `update_reasoning_catalog.py` | `codex_router/` (same names) |
| `probe_codex_runtime.py`, `disable.py` | `tools/` |
| `test_*.py` | `tests/` |
| `packaging/*` | `packaging/` |
| `README.md` | `docs/legacy-readme.md` (Plan 042 replaces it) |
| `plans/034-*.md` to `plans/042-*.md` from SC_Infrastructure `plans/` | `plans/` |

Create `codex_router/__init__.py` (empty) and `codex_router/__main__.py`:

```python
"""Run the router: python3.14 -m codex_router"""
import json
from .router import STATE, Router

state = json.loads(STATE.read_text())
Router(state).serve_forever()
```

Remove the `if __name__ == '__main__':` block from `codex_router/router.py` (the three lines quoted in Current state).

**Verify**: `find codex_router tools tests packaging -type f | sort | wc -l` prints `21` (6 modules + `__init__` + `__main__` + 2 tools + 6 tests + 4 packaging + `docs/legacy-readme.md` is outside these dirs). If the count differs, list the files and reconcile against the table.

### Step 3: Rewrite imports to package-relative form

In `codex_router/router.py` change lines 11 to 13 to:

```python
from .tool_adapter import prepare_tools, stream_events, ToolEvents
from .capabilities import OPENROUTER_HOST, OPENROUTER_MODELS
from . import compaction as comp
```

Apply the same pattern in `codex_router/apply_catalogue.py` (`from .capabilities import ...`) and `codex_router/update_reasoning_catalog.py` (`from .apply_catalogue import write_guarded`, `from .capabilities import ...`).

In every test under `tests/`, replace bare module imports with package imports, for example `import mixed_router` becomes `from codex_router import router as mixed_router`, `from mixed_router import Router, route, prepare_openrouter` becomes `from codex_router.router import Router, route, prepare_openrouter`, `from tool_adapter import ...` becomes `from codex_router.tool_adapter import ...`, and so on for `capabilities`, `compaction`, `apply_catalogue`, `update_reasoning_catalog`.

`tests/test_packaging.py` resolves `packaging/` relative to its own file (`Path(__file__).resolve().parent / 'packaging'`). Change that to `Path(__file__).resolve().parents[1] / 'packaging'` in both tests.

`tools/disable.py` reads `activation.json` from `Path(__file__).resolve().parent`. Change `root` to `Path(os.environ.get('ROUTER_HOME', Path.home() / '.codex' / 'mixed-model-router'))` so it keeps working when the tool no longer sits beside the state file. Plan 035 introduces the same `ROUTER_HOME` convention in the router.

**Verify**: `python3.14 -m compileall -q codex_router tools tests` exits 0, then `python3.14 -m unittest discover -s tests -t .` ends with `OK`. The two packaging tests must pass, not error.

### Step 4: Add repository rules

Create `AGENTS.md` with exactly these sections (write them out in full, adapting nothing from the monorepo that is about AWS):

1. Purpose: local loopback router that keeps ChatGPT subscription traffic on OpenAI and routes approved OpenRouter models with a separate key; runtime Python 3.14+, stdlib only, no third-party dependencies, no network calls in tests.
2. Worktree discipline: one writable worktree per agent session, never edit the primary checkout, never `git reset --hard` or `git checkout --` without explicit approval (copy the wording from SC_Infrastructure `AGENTS.md` "Git worktree discipline").
3. Source limits: modules 250 soft / 400 hard, entrypoints 400/700, tests 300/500, checked by `python3.14 tools/check_source_limits.py`.
4. Security: never commit state, activation receipts, catalogues, logs, keys or bearer tokens; never log request or tool content; loopback only; the path token is per-install.
5. Verification before commit: `python3.14 -m unittest discover -s tests -t .`, `python3.14 -m compileall -q codex_router tools tests`, `python3.14 tools/check_source_limits.py`, then the shared `pre-commit-review` skill.
6. Release rule: every user-visible change updates `CHANGELOG.md` and `packaging/VERSION` (semver); releases are cut by tag `v<VERSION>` and the release workflow (Plan 041).
7. Compatibility rule: after any Codex desktop upgrade, run the paid probe from `tools/probe_codex_runtime.py` on one OpenRouter model and one OpenAI model before publishing a release; record the Codex version in `docs/compatibility.md`.

Create `tools/check_source_limits.py` (under 60 lines): walk `codex_router`, `tools`, `tests`; count physical lines; apply the limits above by directory (`tests/` 300/500, `tools/` and `__main__.py` 400/700, else 250/400); print `source-limits: checked=N failures=M` and exit 1 if any file exceeds its hard limit or if a file exceeds its soft limit and is not listed in `config/source-limits-baseline.json` at its exact current count. Create that baseline file with any file currently over soft (expected: none).

Create `SECURITY.md` (report channel: Cyril's email; no secrets in issues; 30-day fix target), `CODEOWNERS` per Step 1, `.gitignore` copying the router's existing seven ignore lines plus `__pycache__/`, `*.pyc`, `dist/`, `.DS_Store`.

Create `pyproject.toml` with `[project] name = "codex-model-router"`, `version` read from `packaging/VERSION` by hand for now, `requires-python = ">=3.14"`, `dependencies = []`. No build backend configuration is needed; this file is metadata for humans and tools.

**Verify**: `python3.14 tools/check_source_limits.py` prints `failures=0` and exits 0.

### Step 5: Add CI

Create `.github/workflows/check.yml`:

```yaml
name: Check

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    name: Test
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@<FULL_SHA_OF_v4>
      - uses: actions/setup-python@<FULL_SHA_OF_v5>
        with:
          python-version: "3.14"
      - run: python -m compileall -q codex_router tools tests
      - run: python tools/check_source_limits.py
      - run: python -m unittest discover -s tests -t . -v
      - name: Secrets scan
        run: |
          if grep -rEn "sk-or-v1-[A-Za-z0-9]{20,}|Bearer [A-Za-z0-9._-]{30,}" --include='*.py' --include='*.md' --include='*.json' --include='*.toml' . ; then echo "possible secret committed"; exit 1; fi
```

Resolve both SHAs with `gh api repos/actions/checkout/git/ref/tags/v4 --jq .object.sha` and `gh api repos/actions/setup-python/git/ref/tags/v5 --jq .object.sha` and paste the 40-character values. Never leave a tag reference.

**Verify**: copy the workflow file into a scratch copy of the monorepo and run `node scripts/validate-github-actions.mjs` there, or check by eye against the five rules in Current state. Then push to `main` and confirm `gh run list --limit 1 --json conclusion --jq '.[0].conclusion'` prints `success`.

### Step 6: Record provenance

Create `docs/PROVENANCE.md` stating: imported from `software-combined/SC_Infrastructure` path `domains/ai-platform/codex-model-router` at commit `749a6b8d` on 2026-09-07; earlier history lived only in the deployed directory `~/.codex/mixed-model-router` and is not recoverable; compatibility release 2 was verified against `codex-cli 0.153.4` on 2026-09-07.

**Verify**: `test -s docs/PROVENANCE.md && echo ok` prints `ok`.

### Step 7: Protect `main`

```sh
gh api -X PUT repos/software-combined/codex-model-router/branches/main/protection \
  -f required_status_checks.strict=true -f 'required_status_checks.contexts[]=Test' \
  -f enforce_admins=false -f required_pull_request_reviews.required_approving_review_count=1 \
  -F restrictions=
```

If the API call fails on the JSON shape, set the same three rules in the GitHub UI (require the `Test` check, require one review, block force pushes) and record that you did.

**Verify**: `gh api repos/software-combined/codex-model-router/branches/main/protection --jq .required_status_checks.contexts` prints `["Test"]`.

### Step 8: Install shared hooks locally

Follow `~/.config/scg-agent-git-hooks/README.md` to point `core.hooksPath` at the shared hooks for this clone so the commit-msg format and pre-commit review receipt apply here as in every SC repository.

**Verify**: `git -C ~/Documents/Github/codex-model-router config core.hooksPath` prints the shared hooks path.

### Step 9 (later, gated): Remove the directory from SC_Infrastructure

Only after the new repository CI is green and Plan 041 has published release `v0.4.0` or later: on a new SC_Infrastructure worktree from `codex/codex-adapter-20260907`, delete `domains/ai-platform/codex-model-router/`, add one line to `domains/ai-platform/README.md` pointing at the new repository, run `npm run check`, and open a pull request. Record the removal in the new repository's `docs/PROVENANCE.md`.

**Verify**: `npm run check` in that worktree exits 0.

## Fallback if extraction is rejected

If Cyril decides to keep the router inside SC_Infrastructure, skip Steps 1 to 3 and 6 to 9 and instead add this job to `.github/workflows/check.yml` in the monorepo (SHAs resolved as in Step 5), then execute Plans 035 to 042 with `ROUTER_ROOT = domains/ai-platform/codex-model-router`:

```yaml
  router-tests:
    name: Router tests
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@<FULL_SHA_OF_v4>
      - uses: actions/setup-python@<FULL_SHA_OF_v5>
        with:
          python-version: "3.14"
      - run: python -m unittest discover -s domains/ai-platform/codex-model-router -p 'test_*.py' -v
```

Verify with `node scripts/validate-github-actions.mjs` (exit 0) and `npm run check` (exit 0).

## Test plan

- No new behaviour, so no new unit tests beyond the relocated suite.
- The relocated suite must pass unchanged in count: run `python3.14 -m unittest discover -s tests -t . -v 2>&1 | tail -3` and confirm the same number of tests as `/opt/homebrew/bin/python3 -m unittest discover -s domains/ai-platform/codex-model-router -p 'test_*.py' 2>&1 | tail -3` reported in the monorepo before the move.

## Done criteria

- [ ] Repository exists with the decided name and visibility; `gh repo view` confirms.
- [ ] `python3.14 -m unittest discover -s tests -t .` ends with `OK` and the test count equals the pre-move count.
- [ ] `python3.14 -m compileall -q codex_router tools tests` exits 0.
- [ ] `python3.14 tools/check_source_limits.py` prints `failures=0`.
- [ ] `gh run list --limit 1` shows the `Check` workflow succeeded on `main`.
- [ ] Branch protection requires the `Test` check.
- [ ] `docs/PROVENANCE.md`, `AGENTS.md`, `SECURITY.md`, `CODEOWNERS`, `.gitignore`, `pyproject.toml` exist.
- [ ] `grep -rn "^from tool_adapter\|^from capabilities\|^import compaction\|^from mixed_router" codex_router tests tools` returns nothing.
- [ ] No file in SC_Infrastructure modified (Step 9 excluded).
- [ ] `plans/README.md` status row updated in both repositories.

## STOP conditions

- Cyril has not confirmed repository name and visibility (Step 1). Do not create an organisation repository on your own authority.
- The relocated test suite reports a different test count or any failure after the import rewrite; report the failing test rather than editing its assertions.
- `gh repo create` reports insufficient permission on the `software-combined` organisation.
- A file in `codex_router/` exceeds 400 lines after the move (it should not; `router.py` is about 230 lines).
- Step 9 is reached while Plan 041 has not published a release: stop, the monorepo copy remains the source until then.

## Maintenance notes

- After this plan, the SC_Infrastructure copy is frozen. Any fix made there by another session must be ported to the new repository before Step 9; check `git log -- domains/ai-platform/codex-model-router` on the adapter branch before Step 9.
- Reviewers should check that no runtime state files (`mixed-router-state.json`, `activation.json`, `mixed-models.json`, logs) were committed; the `.gitignore` guards this, the CI grep is a backstop.
- Deferred on purpose: a `release.yml` workflow and signed release bundles belong to Plan 041; Windows CI belongs to Plan 041 phase 2.
