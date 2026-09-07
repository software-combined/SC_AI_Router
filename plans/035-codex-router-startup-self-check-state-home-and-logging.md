# Plan 035: Make the router fail loudly at startup, separate code from state, and give logs timestamps and rotation

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 749a6b8d..HEAD -- <ROUTER_ROOT>`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (additive validation and logging; routing logic untouched)
- **Depends on**: none (Plan 034 changes file locations; the path table below covers both layouts)
- **Category**: bug / dx
- **Planned at**: commit `749a6b8d`, 2026-09-07

## Path convention

`ROUTER_ROOT` is `domains/ai-platform/codex-model-router` in SC_Infrastructure before Plan 034, or the repository root after it. In the table, "pre-034" names come first and "post-034" names second.

| Role | pre-034 | post-034 |
|---|---|---|
| Router module | `mixed_router.py` | `codex_router/router.py` |
| Router tests | `test_mixed_router.py` | `tests/test_mixed_router.py` |
| Disable tool | `disable.py` | `tools/disable.py` |

## Why this matters

On 7 September 2026 a deploy shipped router code that read a state key the state file did not contain. Every OpenRouter request then failed with a generic 400 until the operator noticed. The unit tests passed because the test fixture supplied the missing key. Nothing at startup checked that the code and the state agreed, and the 400 path logs nothing, so the failure was invisible in the logs. Separately, the logs have no timestamps and no rotation (the current `stdout.log` is 2.4 MB and growing under launchd), and state, code, backups and logs all live in one directory, so the running version cannot be told from the files on disk. This plan adds a startup self-check that refuses to serve with a clear message, introduces one `ROUTER_HOME` location for state and logs that is independent of where the code lives (Plan 041's installer relies on this), adds timestamps and rotation, and makes the health endpoint report the version.

## Current state

- `mixed_router.py:17-20`:

```python
STATE = Path(__file__).with_name('mixed-router-state.json')
MAX_BODY = 16 * 1024 * 1024
# Fallback when a state file predates the cap key; explicit key wins when present.
DEFAULT_REQUEST_CAP = 1000
```

- State is loaded without validation at `mixed_router.py:231-233` (`state = json.loads(STATE.read_text())`). Keys used by the code: `port` (`:73`), `token` (`:95-97`), `openai_models` (in `do_POST`, passed to `route`), `opencode_auth` (`:151`), optional `request_cap` (`:147`).
- The live state file on the author's machine has exactly `port`, `token`, `openai_models`, `opencode_auth`. Never print `token`.
- Logging is `print(json.dumps({...}), flush=True)` at `mixed_router.py:189` (`request_started`), and two more prints for `request_completed` and `transport_error` later in `do_POST`. There is no timestamp field. Error responses from `Handler.error` (`:83-91`) log nothing.
- `Handler.log_message` (`:81-82`) is intentionally a no-op so request URLs (which carry the token) never reach access logs. Keep that.
- Health at `mixed_router.py:106-107` reuses the error envelope: `return self.error(200, 'Router ready')`, so a 200 body reads `{"error": {...}}`.
- Request cap at `:146-150`: an in-memory counter that returns 429 after `request_cap` (default 1000) OpenRouter requests until the process restarts. The deployed copy on the author's machine has this block removed; the committed copy has it with a default of 1000. The 2026-09-07 release note in the deployed `compatibility-release.json` says the cap was removed on purpose. Treat the cap as a decision point (Step 5).
- `disable.py:7-8` resolves `activation.json` beside the script: `root = Path(__file__).resolve().parent`.
- Existing test fixture `test_mixed_router.py:68-70`:

```python
def _test_state(auth_path):
    return {'port': 0, 'token': 'test-token', 'request_cap': 1000,
            'openai_models': [], 'opencode_auth': auth_path}
```

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Tests (pre-034) | `/opt/homebrew/bin/python3 -m unittest discover -s domains/ai-platform/codex-model-router -p 'test_*.py'` | `OK` |
| Tests (post-034) | `python3.14 -m unittest discover -s tests -t .` | `OK` |
| Source limits (pre-034) | `node scripts/check-source-limits.mjs` | `failures=0` |
| Source limits (post-034) | `python3.14 tools/check_source_limits.py` | `failures=0` |
| Manual start (post-034, does not bind the live port) | `ROUTER_HOME=/tmp/rh python3.14 -m codex_router` | exits 1 with a message naming the missing state file |

## Scope

**In scope**: the router module, its test file, `disable.py`, `README.md` (one paragraph on `ROUTER_HOME`).

**Out of scope**: `tool_adapter.py`, `compaction.py`, `capabilities.py`, catalogue scripts, the installer (Plan 041), any change to routing or provider behaviour, the LaunchAgent plist on any machine.

## Git workflow

- Branch `codex/router-self-check-<yyyymmdd>` from the current router branch (or `main` post-034).
- One commit per step is fine; messages `fix:`/`feat:`/`test:` per the shared hook. Do not push or open a PR unless instructed.

## Steps

### Step 1: Add `ROUTER_HOME` and a validating `load_state`

In the router module replace the `STATE` constant with:

```python
ROUTER_HOME = Path(os.environ.get('ROUTER_HOME', Path.home() / '.codex' / 'mixed-model-router'))
STATE = ROUTER_HOME / 'mixed-router-state.json'
REQUIRED_STATE = {'port': int, 'token': str, 'openai_models': list, 'opencode_auth': str}

def load_state(path=STATE):
    """Fail closed with a precise message; never echo the token."""
    try:
        state = json.loads(path.read_text())
    except FileNotFoundError:
        raise SystemExit(f'Router state file missing: {path}')
    except ValueError as exc:
        raise SystemExit(f'Router state file is not valid JSON: {path} ({exc.__class__.__name__})')
    missing = [k for k, t in REQUIRED_STATE.items() if not isinstance(state.get(k), t)]
    if missing:
        raise SystemExit('Router state file is missing or mistyped keys: ' + ', '.join(missing))
    if not Path(state['opencode_auth']).exists():
        raise SystemExit('OpenRouter credential file not found at the configured opencode_auth path')
    return state
```

Add `import os` at the top. Note the default of `ROUTER_HOME` is the directory the router already uses today, so nothing moves on existing machines.

Update the entry point (`__main__.py` post-034, or the `if __name__` block pre-034) to `Router(load_state()).serve_forever()`.

**Verify**: `ROUTER_HOME=/tmp/rh-empty python3.14 -m codex_router; echo "exit=$?"` prints `Router state file missing: /tmp/rh-empty/mixed-router-state.json` and `exit=1` (pre-034: run the module file directly with the same env var).

### Step 2: Structured log events with timestamps and rotation

Add near the top of the router module:

```python
import logging, logging.handlers
from datetime import datetime, timezone

LOG = logging.getLogger('codex_router')

def configure_logging(home=ROUTER_HOME):
    (home / 'logs').mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(home / 'logs' / 'router.jsonl',
                                                   maxBytes=5 * 1024 * 1024, backupCount=3)
    handler.setFormatter(logging.Formatter('%(message)s'))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)

def log_event(event, **fields):
    LOG.info(json.dumps({'ts': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                         'event': event, **fields}))
```

Replace the three `print(json.dumps({**metrics, 'event': ...}), flush=True)` calls in `do_POST` with `log_event('request_started', **metrics)`, `log_event('request_completed', **metrics, status=..., total_ms=...)` and `log_event('transport_error', ...)` keeping the exact same field names. Add `log_event('request_rejected', status=status, reason=message, path=<sanitised path>)` inside `Handler.error` for statuses 400 to 599, where the sanitised path is the routed path after the token prefix has been removed (never `self.path`). Call `configure_logging()` from the entry point before `serve_forever`.

Keep `log_message` as a no-op. Do not log headers, bodies, tool content or the token.

**Verify**: start the router with `ROUTER_HOME=/tmp/rh` containing a valid test state on port 0? Not possible from the CLI, so verify through the unit test in the Test plan (`test_rejections_are_logged_with_timestamp`). `grep -n "print(json.dumps" <router module>` returns nothing.

### Step 3: Health endpoint reports version

Read the version once: `VERSION = (Path(__file__).resolve().parents[1] / 'packaging' / 'VERSION').read_text().strip()` post-034, or `Path(__file__).with_name('packaging').joinpath('VERSION')` pre-034, falling back to `'unknown'` if the file is absent (the deployed copy today has no `packaging/`). Replace the health branch with a proper 200 JSON body `{"status": "ok", "version": VERSION, "inflight": self.server.inflight}` using the same header sequence as `error()` but without the error envelope. Add `self.inflight = 0` to `Router.__init__` and increment/decrement it around the upstream relay in `do_POST` under `self.server.lock` (Plan 041's updater waits for `inflight == 0` before restarting).

**Verify**: unit test `test_health_reports_version_and_inflight` (Test plan) passes; `curl -s http://127.0.0.1:<port>/<token>/health` on a locally started test instance prints `{"status": "ok", ...}`.

### Step 4: `disable.py` resolves `ROUTER_HOME`

Change `root = Path(__file__).resolve().parent` to the same `ROUTER_HOME` expression as Step 1 (duplicate the one-liner; do not import the router module from the tool, so the tool keeps working when the package is not importable).

**Verify**: `python3.14 -c "import ast,sys; ast.parse(open('tools/disable.py').read())"` exits 0 (pre-034: `disable.py`).

### Step 5: Decide the request cap

Ask the operator: keep or remove the in-memory OpenRouter request cap? Recommended: **remove** it. It is a trial artefact, it resets only on restart, the default of 1000 will trip for a heavy user within a day, and OpenRouter credit limits are the real spend control. If removed: delete `DEFAULT_REQUEST_CAP`, the `with self.server.lock:` cap block at `:146-150`, `self.requests`, the `request_cap` key from the test fixture and the test `test_compact_counts_against_request_cap`. If kept: make it a required state key with a documented meaning and a daily reset, and record the decision in `README.md`.

**Verify**: tests pass; `grep -n request_cap <router module> <test file>` returns nothing (if removed).

### Step 6: README paragraph

Add to `README.md` under Operation: `ROUTER_HOME` (default `~/.codex/mixed-model-router`) holds `mixed-router-state.json`, `activation.json`, and `logs/router.jsonl` (5 MB, three rotations). The code may live anywhere. Startup refuses to serve if the state file is missing or mistyped and prints which keys are wrong.

**Verify**: `grep -n ROUTER_HOME README.md` shows the paragraph.

## Test plan

Add to the router test file, modelled on `LoopbackBoundaryTests` (which starts a real `Router` on port 0):

- `test_load_state_reports_missing_keys`: write `{"port": 1}` to a temp file; `load_state(path)` raises `SystemExit` whose message contains `token, openai_models, opencode_auth`.
- `test_load_state_rejects_missing_credential_file`: valid keys but `opencode_auth` pointing at a non-existent path raises `SystemExit` mentioning `credential file`.
- `test_load_state_accepts_valid_file`: returns the dict.
- `test_rejections_are_logged_with_timestamp`: point `LOG` at a `logging.handlers.MemoryHandler` or a temp `RotatingFileHandler`; GET `/wrong-token/health` (403) then assert one JSON line with `event == 'request_rejected'`, `status == 403`, and `ts` parseable by `datetime.fromisoformat`. Assert the token does not appear in the log text.
- `test_health_reports_version_and_inflight`: GET `/test-token/health` returns 200, JSON has `status == 'ok'`, `version` is a string, `inflight == 0`.
- Adjust `_test_state` and the cap test per Step 5.

Verification: full suite ends `OK` with the new tests present.

## Done criteria

- [ ] Test suite `OK`; new tests listed above exist and pass.
- [ ] `grep -n "print(json.dumps" <router module>` returns nothing.
- [ ] `ROUTER_HOME=/tmp/rh-empty python3.14 -m codex_router` exits 1 with the missing-file message (pre-034: run the module file).
- [ ] Source limits check passes (`router.py` stays under 250 lines; if it does not, move `load_state`, `configure_logging`, `log_event` into `codex_router/runtime.py` and import them).
- [ ] No file outside the in-scope list modified.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- The router module at the cited lines does not match the excerpts (another session may still be editing it; on 2026-09-07 the deployed copy and the committed copy differed).
- Adding logging pushes the module over 400 lines and the split into `runtime.py` is not possible without touching out-of-scope files.
- The operator has not decided Step 5 and you cannot reach them: implement removal (the recommended default) and flag it in the report.

## Maintenance notes

- Plan 041's installer writes state into `ROUTER_HOME` and points the LaunchAgent's `StandardOutPath`/`StandardErrorPath` at `ROUTER_HOME/logs/`. Only tracebacks and startup refusals should appear there after this plan.
- Plan 040 replaces the `opencode_auth` existence check with the ordered credential lookup; keep `load_state` as the single place that validates state so that plan edits one function.
- Reviewers: confirm no log line can contain the token or a bearer header; search the diff for `self.path` and `headers` near `log_event`.
