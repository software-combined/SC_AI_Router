# Plan 085: Delete dead code and add a lint gate that keeps it deleted

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat a985197..HEAD -- ai_router/ packaging/ tools/ pyproject.toml .github/workflows/check.yml config/source-limits-baseline.json`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P2; effort S; risk LOW; confidence HIGH; category tech-debt/dx; depends on none (run
  before 086/087 so their refactors see a smaller tree).
- Planned at `a985197`, 2026-09-10.
- First proof: `ruff check --select F401,F811` over `ai_router packaging tools tests` exits 0 in CI,
  and the deleted names are absent.

## Why this matters

Eight verified dead symbols/imports exist, including a dead duplicate of the Claude ingress path
allowlist (`CLAUDE_PATHS`) that invites a future editor to update the wrong constant, and a dead
signed-feed helper (`load_signed_feed`) that looks like a live verification path. No lint gate
catches this class, so it keeps reproducing. A minimal ruff F-rule gate ends the cycle.

## Current state (verified at a985197; line refs refreshed at 12c834b)

Dead code (no references outside plans/docs):
- `ai_router/claude.py:25` — `CLAUDE_PATHS = frozenset({'/v1/messages', '/v1/messages/count_tokens'})`
  (`CLAUDE_POST_PATHS` at `:26` is the live one, used at `:104`; adjust the comment at `:23-24`).
- `ai_router/setup.py:23` — `SETUP_PREFIX = '/setup/'` (router.py uses literals at `:110`, `:148`, `:185`).
- `ai_router/feed_verify.py:150-159` — `load_signed_feed` (plan 054 records feed signatures out by owner decision).
- `ai_router/errors.py:165-169` — `subscription_auth_required` (no callers).
- Unused imports: `ai_router/models.py:15` `CODEX_MODALITIES`; `ai_router/claude.py:16` `providers`;
  `ai_router/providers.py:17` `relay_headers` (keep `HOP_HEADERS`, `Prepared`, `passthrough`);
  `packaging/install.py:19` `urllib.error`.
- Additional findings from an AST scan to confirm with ruff: `packaging/feed_token.py:8-9`,
  `packaging/platforms/linux.py:6`, and several test-file imports.

## Scope

**In scope**: the symbols/imports above, any additional `F401`/`F811` findings in `ai_router/`,
`packaging/`, `tools/`, `tests/`; `pyproject.toml`; `.github/workflows/check.yml`;
`config/source-limits-baseline.json` (count updates only); `plans/README.md` (status row only).
**Out of scope**: unused non-import names not caught by F401/F811, style rules (E/W), renaming,
`# noqa` cleanup for intentional suppressions (`ai_router/transport.py:6` keeps its `# noqa`).

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Ruff survey | `python3.14 -m pip install --user ruff` then `ruff check --select F401,F811 ai_router packaging tools tests` | list of findings to fix; record `ruff --version` for the CI pin |
| Ruff after | same command | exit 0 |
| Focused | `python3.14 -m unittest tests.test_feed_verify tests.test_claude_ingress tests.test_packaging tests.test_setup` | pass |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0 after baseline count updates |

## Steps

### Step 1: delete the verified dead code (commit 1)

Remove the four symbols and four imports listed above. For `claude.py`, keep `CLAUDE_POST_PATHS` and
rewrite the comment so it still explains why GET/POST names are separate (or simplify it to the POST
fact if the GET-only intent is gone). For `feed_verify.py`, delete only `load_signed_feed`; keep
`checked_feed` and `trusted_key`.

**Verify**: `rg -n "CLAUDE_PATHS|SETUP_PREFIX|load_signed_feed|subscription_auth_required" ai_router tools packaging tests` → no matches; focused tests pass.

### Step 2: run ruff and fix the full F401/F811 wave (commit 2)

Run the survey command; fix every finding in the four trees (test imports included). Typical wave:
`packaging/feed_token.py` unused `urllib.*`, `packaging/platforms/linux.py` unused `sys`, plus
`tests/test_model_refresh.py`, `tests/test_setup.py`, `tests/test_mixed_router.py`,
`tests/test_model_policy.py`, `tests/test_claude_desktop_config.py`, `tests/test_windows_portability.py`.
Do not remove names that are used only by `mock.patch` strings or plan-owned contracts; for those,
add a targeted `# noqa: F401` with a one-line reason.

### Step 3: add the gate (commit 2)

- `pyproject.toml`: add
  ```toml
  [tool.ruff]
  target-version = "py39"

  [tool.ruff.lint]
  select = ["F401", "F811"]
  ```
- `.github/workflows/check.yml`: add a step after the compile step that installs a **pinned** ruff
  version and runs `ruff check --select F401,F811 ai_router packaging tools tests`. Pin the version
  explicitly (repo convention: pinned actions).

### Step 4: update the size baseline (commit 1)

`tools/check_source_limits.py` requires any file over its soft limit to match the baseline exactly.
Run it after Step 1 and update `config/source-limits-baseline.json` entries to the new counts for the
files that changed and remain over soft (`errors.py`, `providers.py`, `setup.py`, `install.py`).
Do not let `install.py` exceed 700.

**Verify**: checker exits 0; `git diff --stat` shows only intended files.

## Done criteria

- [ ] `rg` for the four dead names returns no matches.
- [ ] `ruff check --select F401,F811 ai_router packaging tools tests` exits 0.
- [ ] `check.yml` runs the pinned ruff step; `pyproject.toml` carries the config.
- [ ] Baseline counts updated; full suite, compile and limit gates pass.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- A "dead" symbol turns out to be referenced by a plan-owned contract or an installed-bundle path:
  stop for that symbol only and report; delete the rest.
- Ruff's version/availability in CI cannot be pinned in the workflow: stop and report; a floating
  linter is worse than no gate.
- The ruff wave reveals findings beyond F401/F811 classes: keep the gate narrow; do not widen scope.

## Maintenance notes

- New intentional unused imports require a reasoned `# noqa: F401`.
- The gate is deliberately two rules; expand only with a dedicated decision.
- Reviewers: confirm the baseline diff only changes line counts and no new exclusions were added.
