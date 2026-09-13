# Plan 165: Split the logging and home leaves out of `runtime.py`, break the only import cycle, and correct the architecture map

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report; do not improvise.
> When done, update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat c068368..HEAD -- ai_router/runtime.py ai_router/state.py ai_router/setup.py ai_router/credentials.py ai_router/discovered.py ai_router/model_policy.py ai_router/tool_aliases.py ai_router/upstream.py ai_router/providers.py ai_router/local_services.py ai_router/activation.py ai_router/subscription_fallback.py ai_router/candidate.py docs/architecture.md tests/test_domain_boundaries.py tests/test_runtime.py packaging/service.py config/source-limits-baseline.json`
> If any in-scope file changed, compare the "Current state" excerpts against
> the live code before proceeding; on a mismatch, STOP. Plan 131's remaining
> scope also names `ai_router/runtime.py`; coordinate so one writer holds it.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW-MED (import order at boot; widely imported constants)
- **Depends on**: none; coordinate with 131 (state readers) and 152/155 (they cite `docs/architecture.md`)
- **Category**: tech-debt
- **Planned at**: commit `c068368` (`origin/develop`), 2026-09-13
- **Source**: `plans/2026-09-13-router-four-lane-audit.md`, finding F5

## Why this matters

`ai_router/runtime.py` owns two unrelated things: the structured event log
(`LOG`, `configure_logging`, `log_event`, which need only `json`, `logging`
and `datetime`) and the boot composition root (`load_state`, which needs
`registry`, `credentials`, `setup` and `model_policy`). Eleven modules import
`runtime`: eight eagerly (`__main__`, `activation`, `ingress`,
`local_services`, `providers`, `router`, `subscription_fallback`,
`upstream`) and three through function-local imports (`model_policy.py:30`,
`setup.py:206`, `tool_aliases.py:209`). Eight of the eleven want only
`log_event`. The import-time graph is acyclic today, but counting the
function-local edges — which Step 4's test does — there is exactly one
strongly connected component, `{runtime, setup, credentials, model_policy}`:
`runtime` eagerly imports `setup` and `credentials`, and `setup`,
`credentials` and `model_policy` load `runtime` back inside functions to
write one log line. Steps 1 to 3 remove that component.
`upstream.py` declares itself "pure policy: no
dispatch, no model data, no credentials" and yet, through `runtime`,
transitively imports `registry`, `credentials`, `setup`, `key_prompt`
(`subprocess`, `webbrowser`) and `model_policy` to write one log line. The
same root cause forces `setup.py` to rebuild state paths by hand and
`discovered.py` to carry its own copy of `default_home`. `docs/architecture.md`
omits `runtime` entirely and draws `transport`/`upstream` below `protocols`,
although `providers` and `claude` import `transport`; the boundary test is a
hand-written denylist that happens to permit exactly those edges.

## Current state (verified at c068368)

- `ai_router/runtime.py:9-11`:

```python
from . import provider_defs, registry, state as state_mod
from .setup import setup_pending
from .credentials import Credentials, default_home
```

  `:20` `LOG = logging.getLogger('codex_router')`; `:95-106` `configure_logging` and `log_event`; `:40-92` `load_state`; `:87` a function-local `from .model_policy import load as _load_policy`.
- Function-local imports that eagerly load `runtime`: `ai_router/setup.py:206`
  (`from .runtime import log_event as _log_event`), `ai_router/model_policy.py:30`
  (`from .runtime import log_event`), `ai_router/tool_aliases.py:209`
  (`from .runtime import log_event`), `ai_router/credentials.py:123` and
  `:127` (`from . import key_store` / `from . import setup` inside
  `key_rejected`, which calls `setup.setup_pending`).
- Eager `runtime` importers that want only `log_event`: `ai_router/upstream.py:18`,
  `ai_router/local_services.py:9`, `ai_router/providers.py:11`,
  `ai_router/activation.py:4`, `ai_router/subscription_fallback.py:23`.
  `ai_router/ingress.py:18` wants `VERSION`; `ai_router/router.py:15` wants
  `MAX_BODY, ROUTER_HOME, log_event`; `ai_router/__main__.py:7` wants
  `VERSION, configure_logging, load_state, log_event`.
- `ai_router/setup.py:29-39` (`setup_pending`) is pure: it reads
  `state['setup']['nonce']` and `['expires']` against `time.time()`.
- `ai_router/credentials.py:20-22` (`default_home`) and
  `ai_router/discovered.py:22-23` (`_home`) are byte-identical:
  `Path(os.environ.get('ROUTER_HOME', Path.home() / '.codex' / 'mixed-model-router'))`.
- `ai_router/state.py` is a Python 3.9-safe leaf spec-loaded by
  `packaging/service.py:59-60`; it owns `STATE_NAME` and `path(home)`.
- `docs/architecture.md:9-30` is the dependency diagram; `:32-46` the
  per-module rules paragraph; `runtime`, `events`, `state`, `atomic_write`,
  `errors`, `credentials`, `setup` are absent from the diagram.
- `tests/test_domain_boundaries.py:57-77` (`RULES`) is a per-file denylist of
  forbidden imports for 13 files; the rule for `ai_router/upstream.py` forbids
  `router`, `claude`, `providers`, `transport` but not `runtime`, `setup`,
  `credentials`, `key_prompt`.
- Tests that patch logging: grep before you start with
  `grep -rn "runtime.log_event\|router.log_event\|patch.object(runtime" tests/`
  and keep every patch target resolving (the handler injects `log_event`
  from `ai_router.router` for that reason, `ai_router/ingress.py:8-10`).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_domain_boundaries tests.test_runtime tests.test_lifecycle tests.test_setup tests.test_credentials tests.test_discovered tests.test_model_policy tests.test_handler tests.test_upstream_failures` | all pass |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Lint | `python3.14 -m ruff check --select F401,F811 ai_router packaging tools tests` | pass |
| Limits | `python3.14 tools/check_source_limits.py` | `failures=0` |
| Policy scans | `python3.14 tools/check_policy_scans.py` | pass |
| 3.9 leaf gate | `python3.14 -B -m unittest tests.test_packaging` | pass (`state.py` stays 3.9-parseable) |
| Router boots | `ROUTER_HOME=$(mktemp -d) python3.14 -c "import ai_router.router, ai_router.__main__"` | exit 0, no ImportError |

## Scope

**In scope**: `ai_router/events.py` (create), `ai_router/runtime.py`,
`ai_router/state.py`, `ai_router/setup.py`, `ai_router/credentials.py`,
`ai_router/discovered.py`, `ai_router/model_policy.py`,
`ai_router/tool_aliases.py`, `ai_router/upstream.py`,
`ai_router/local_services.py`, `ai_router/providers.py`,
`ai_router/activation.py`, `ai_router/subscription_fallback.py`,
`docs/architecture.md`, `tests/test_domain_boundaries.py`,
`tests/test_import_graph.py` (create), `tests/test_packaging.py`,
`docs/runtime-files.md`, `tests/test_setup.py`,
`tests/test_tool_alias_repair.py`, `config/source-limits-baseline.json`.

**Out of scope**: `packaging/` behaviour; the `codex_router` logger name
(kept by the repository's recorded decision); `ai_router/router.py` and
`ai_router/ingress.py` beyond import lines (plans 163/164 own them);
`ai_router/state.py`'s reader contract (plan 131); any behaviour change to
logging, state validation or the key window.

## Git workflow

- Worktree based on `develop`; branch like `<you>/165-runtime-leaves-20260913`.
- Suggested commits, in order: `refactor: move the event log into a leaf`,
  `refactor: move setup_pending and default_home into the state leaf`,
  `docs: redraw the dependency map and derive the boundary test from it`.
  Run `pre-commit-review` before each. No push or PR unless instructed.

## Steps

### Step 1: The events leaf

Do Step 2's two moves into `ai_router/state.py` first: `events` resolves its
default home through `state.default_home`, so the leaf cannot land before it.

Create `ai_router/events.py` holding, verbatim from `runtime.py:20` and
`:95-106`, `LOG`, `configure_logging(home=None)` and
`log_event(event, **fields)`. Module-level imports are `json`, `logging`,
`logging.handlers`, `os`, `datetime`, `timezone` — no `ai_router` import at
module level. `configure_logging` must not bind `runtime.ROUTER_HOME` as a
default (that recreates the cycle); when `home is None` it resolves the path
through one function-local `from .state import default_home`. That single
call-time edge is the only local import `events` is allowed, and Step 4's
leaf rule is written to permit exactly it.

Add `ai_router/events.py` to the `FILES` tuple in `tests/test_packaging.py`
and to the module list in `docs/runtime-files.md` in the same step, or the
suite fails: `tests/test_packaging.py:116-124` asserts the tuple covers every
`ai_router/**/*.py` file and `:149-152` asserts the doc lists exactly the
tuple.

In `runtime.py`, replace the three definitions with
`from .events import LOG, configure_logging, log_event` so every existing
`runtime.log_event` reference keeps resolving.

**Verify**: `python3.14 -B -m unittest tests.test_runtime tests.test_lifecycle tests.test_packaging` → pass.

### Step 2: `setup_pending` and `default_home` into the state leaf

- Move `setup_pending` from `ai_router/setup.py:29-39` into
  `ai_router/state.py` unchanged (it is 3.9-safe); keep
  `setup_pending = state_mod.setup_pending` in `setup.py` so callers and
  tests are unaffected.
- Move `default_home` from `ai_router/credentials.py:20-22` into
  `ai_router/state.py`; keep `from .state import default_home` in
  `credentials.py` for its importers (`runtime.py:11` among them). Replace
  `ai_router/discovered.py:22-23` (`_home`) with `from .state import default_home`
  and update its call site (`ai_router/discovered.py:27`).
- `ai_router/runtime.py:10` becomes `from .state import setup_pending`
  (or a qualified call through `state_mod`); `runtime` must no longer import
  `setup` at all.
- `ai_router/credentials.py:127`: `key_rejected` calls
  `state_mod.setup_pending(self.state)`; drop the lazy `from . import setup`.
  The lazy `from . import key_store` at `:123` can become a top-level import
  (`key_store` imports `provider_defs` and `atomic_write` only).
- `ai_router/state.py` stays 3.9-safe and dependency-free: it gains only
  `os` and `time` beside `json` and `pathlib`, which is what
  `packaging/service.py:59-60` spec-loads.

**Verify**: `python3.14 -B -m unittest tests.test_setup tests.test_credentials tests.test_discovered tests.test_packaging` → pass; the 3.9 grammar gate covers `state.py`.

### Step 3: Point the log writers at the leaf

Replace `from .runtime import log_event` with `from .events import log_event`
in `ai_router/upstream.py:18`, `ai_router/local_services.py:9`,
`ai_router/providers.py:11`, `ai_router/activation.py:4`,
`ai_router/subscription_fallback.py:23`; make the three function-local
imports top-level `from .events import log_event` in `ai_router/setup.py`
(`:206`), `ai_router/model_policy.py` (`:30`) and `ai_router/tool_aliases.py`
(`:209`). Leave `ai_router/router.py`, `ai_router/ingress.py` and
`ai_router/__main__.py` importing from `runtime` (they need its other names
and the handler's injected `log_event` contract stays).

Two committed tests intercept the current lazy path and must be retargeted in
the same step: `tests/test_setup.py:358-366` and
`tests/test_tool_alias_repair.py:246-259` patch
`ai_router.runtime.log_event`, which works only while the import is
function-local. Once the name is bound at import time those patches intercept
nothing, so point them at the consumer module — `ai_router.setup.log_event`
and `ai_router.tool_aliases.log_event` — keeping the call-count and no-token
assertions. Retarget the third patch of the same binding at
`tests/test_tool_alias_repair.py:183` as well: its assertion is
`call_count == 0` on a path that never logs, so it stays green while
observing nothing. Patching `ai_router.events.log_event` would not intercept
a `from .events import log_event` binding either.

**Verify**: `ROUTER_HOME=$(mktemp -d) python3.14 -c "import ai_router.router"` → exit 0; focused tests pass.

### Step 4: An import-graph test that forbids cycles

Create `tests/test_import_graph.py`: walk every `ai_router/**/*.py` with
`ast`, collect `ImportFrom` nodes whose `module` is relative (`level >= 1`)
or starts with `ai_router` (including nodes inside function bodies; record
those as lazy), build the module graph and assert:

- no strongly connected component with more than one module (a plain DFS
  with colours is enough; print the cycle on failure);
- `ai_router/events.py` imports nothing from `ai_router` at module level
  (its one function-local `from .state import default_home` is the permitted
  exception and counts against the lazy ceiling), and `ai_router/state.py`
  imports nothing from `ai_router` at all;
- only `ai_router/router.py`, `ai_router/ingress.py` and
  `ai_router/__main__.py` import `runtime`; a leaf re-importing `runtime`
  creates no cycle by itself, so this row is the rule that catches the
  regression this plan exists to stop;
- the number of function-local `ai_router` imports is at most the count you
  measure after Step 3 (record it in the test with a comment), so the
  workaround cannot silently grow. Legitimate lazies stay: platform-specific
  `winacl`, CLI-only `candidate`/`catalogue`, and the `errors` import inside
  `transport.emit_terminal_failure`.

Model the docstring and the AST walk on `tests/test_domain_boundaries.py:1-55`.

**Verify**: `python3.14 -B -m unittest tests.test_import_graph` → pass; temporarily add `from . import relay` at the top of `ai_router/upstream.py` and confirm the test fails on the `upstream`/`relay` cycle, then remove it. (Adding `from . import setup` to `upstream.py` creates no cycle, so it proves nothing about the SCC rule.)

### Step 5: Redraw the map and derive the boundary rules from it

- `docs/architecture.md:9-30`: redraw the diagram with a leaf band at the top
  (`provider_defs`, `errors`, `sse`, `tool_merge`, `image_items`,
  `atomic_write`, `state`, `events`), then `registry`/`capabilities`, then
  `transport` + `upstream` + `stream_errors` as leaves consumed by the
  adapters, then `providers` + `claude`, then `protocols` (which imports the
  adapters, so it sits above them), then `ingress` + `relay`, then `router`,
  with `runtime` (boot composition: state, credentials, policy) and
  `__main__` beside `router`. Add one sentence: "`events.py` owns the event
  log; only `router.py`, `ingress.py` and `__main__.py` still take
  `log_event` from `runtime`, and nothing else under `ai_router/` imports
  `runtime`."
- `tests/test_domain_boundaries.py`: keep `RULES` (they still hold) and add
  rows: `'ai_router/events.py': ()` plus a module-level "imports nothing
  local" assertion (the one function-local `state` import in
  `configure_logging` is the permitted exception), `'ai_router/upstream.py'` adds `'runtime', 'setup',
  'credentials', 'key_prompt'`, `'ai_router/transport.py'` adds `'runtime'`,
  `'ai_router/stream_errors.py': ('router', 'providers', 'claude', 'runtime', 'setup')`.

**Verify**: `python3.14 -B -m unittest tests.test_domain_boundaries` → pass; `docs/architecture.md` renders (no broken code fence).

### Step 6: Baseline

Re-sync `config/source-limits-baseline.json` for any file whose count moved
across the 250 soft cap (`runtime.py` shrinks; `state.py` grows but stays
small). No CHANGELOG entry: nothing user-visible changes.

## Test plan

- New: `tests/test_import_graph.py` (cycle-free, leaf purity, lazy-import
  ceiling).
- Extended: `tests/test_domain_boundaries.py` rows for `events`, `upstream`,
  `transport`, `stream_errors`.
- Existing: runtime, lifecycle, setup, credentials, discovered, policy and
  handler suites pass unchanged.

## Done criteria

- [ ] `grep -rn "from .runtime import log_event" ai_router/` returns matches only in `ai_router/router.py`, `ai_router/ingress.py`, `ai_router/__main__.py` (or none, if they moved to `events`).
- [ ] `grep -n "^from .setup import\|^from . import.*setup" ai_router/runtime.py` returns no matches.
- [ ] `grep -n "def _home" ai_router/discovered.py` returns no matches.
- [ ] `tests/test_import_graph.py` passes and reports zero cycles.
- [ ] Full suite, compile, lint, limits, policy scans and the 3.9 gate pass; only in-scope files changed.
- [ ] `plans/README.md` status row for 165 updated.

## STOP conditions

- A test patches `ai_router.runtime.LOG` or `ai_router.runtime.configure_logging`
  and stops taking effect because the re-export is a copied name: switch
  the test to `ai_router.events` only if the plan's owner agrees; otherwise
  report.
- Moving `setup_pending` changes any installer behaviour
  (`packaging/service.py` does not use it today; confirm with `grep`).
- The boot import check fails with a circular import you cannot resolve by
  the steps above: report the cycle; do not add a new lazy import.
- Plan 131's writer is active on `runtime.py` or `state.py`.

## Maintenance notes

- New modules log through `events`, read paths through `state`, and never
  import `runtime`; `runtime` is the composition root and may import
  anything.
- `tests/test_import_graph.py` is the enforcement; when a genuinely new
  lazy import is needed, raise the ceiling in the test with a comment
  naming the module and why.
- Plans 152 and 155 cite `docs/architecture.md` line numbers; their drift
  checks will flag this plan's edit, which is expected.
