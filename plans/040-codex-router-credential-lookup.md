# Plan 040: Read the OpenRouter key from a documented, ordered set of sources instead of OpenCode's private file

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 749a6b8d..HEAD -- <ROUTER_ROOT>`
> On any in-scope change, compare the "Current state" excerpts against the
> live code first; on a mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (additive sources; the existing OpenCode source remains the last fallback)
- **Depends on**: Plan 035 (`ROUTER_HOME`, `load_state`); Plan 037 introduces the `credentials` object this plan fills in (either order works, see Step 1)
- **Category**: security / dx
- **Planned at**: commit `749a6b8d`, 2026-09-07

## Path convention

`ROUTER_ROOT` is the repository root post-Plan 034 (`codex_router/...`), or `domains/ai-platform/codex-model-router` with flat names before it.

## Why this matters

The router reads the OpenRouter key from OpenCode's credential store, `~/.local/share/opencode/auth.json`, through the `opencode_auth` state key. That works on the author's machine and nowhere else: staff who do not use OpenCode have no way to supply a key, and the Windows installer text promises an `OPENROUTER_API_KEY` environment variable that no code reads. A product needs one documented, ordered lookup that works on a fresh machine, keeps the key out of process arguments and logs, and lets a key be rotated without a restart.

## Current state

- Router module (`mixed_router.py:151-154` at the planned commit):

```python
auth = json.loads(Path(self.server.state['opencode_auth']).read_text())['openrouter']
if auth['type'] != 'api':
    raise ValueError('OpenCode credential is not an API key')
key = auth['key']
```

  The read happens per request, so a rotated key in that file takes effect immediately. Keep that property.
- `packaging/install.ps1:2` and `:10` mention `$env:OPENROUTER_API_KEY`; nothing in the Python reads an environment variable (`grep -n "environ\|getenv" *.py` returns nothing).
- The OpenCode file on the author's machine has mode `0600`; the router does not check modes today.
- launchd does not pass the login shell's environment to LaunchAgents, so on macOS an environment variable is only practical for manual runs and CI; a key file under `ROUTER_HOME` is the realistic default for the service.
- Plan 037 defines a `credentials` object with a method `openrouter_key()` used by `OpenRouterProvider.prepare` and `compact`.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Tests | `python3.14 -m unittest discover -s tests -t . -v` | `OK` |
| Source limits | `python3.14 tools/check_source_limits.py` | `failures=0` |

## Scope

**In scope**: new `codex_router/credentials.py`, the router module (replace the four lines above with the lookup; startup check in `load_state`), `packaging/install.ps1` (text only), `README.md` (credential section), new `tests/test_credentials.py`, `tests/test_mixed_router.py` and `tests/test_handler.py` fixtures only if they rely on the OpenCode path.

**Out of scope**: the installer (Plan 041 creates the key file interactively), any secret value anywhere in the repository, keychain integration (deferred; see Maintenance notes).

## Git workflow

- Branch `codex/router-credentials-<yyyymmdd>`; commits `feat:`/`test:`/`docs:`. Do not push unless instructed.

## Steps

### Step 1: Write `credentials.py`

```python
"""Ordered OpenRouter key lookup. Read at request time so rotation needs no restart. Never log the key."""
import json
import os
from pathlib import Path

ENV_VAR = 'OPENROUTER_API_KEY'
KEY_FILE = 'openrouter.key'

class Credentials:
    def __init__(self, state, home, env=None):
        self.state, self.home, self.env = state, Path(home), os.environ if env is None else env

    def openrouter_key(self):
        value = self.env.get(ENV_VAR, '').strip()
        if value:
            return value
        key_file = self.home / KEY_FILE
        if key_file.exists():
            if os.name != 'nt' and key_file.stat().st_mode & 0o077:
                raise PermissionError(f'{key_file} must be readable by the owner only (chmod 600)')
            value = key_file.read_text().strip()
            if value:
                return value
            raise LookupError(f'{key_file} is empty')
        opencode = self.state.get('opencode_auth')
        if opencode:
            auth = json.loads(Path(opencode).read_text())['openrouter']
            if auth.get('type') != 'api':
                raise ValueError('OpenCode credential is not an API key')
            return auth['key']
        raise LookupError(f'No OpenRouter key: set {ENV_VAR}, create {key_file}, or configure opencode_auth')

    def check(self):
        """Startup probe: raises the same errors as openrouter_key without returning the value."""
        self.openrouter_key()
        return True
```

If Plan 037 has not landed yet, construct `Credentials(state, ROUTER_HOME)` once in `Router.__init__` as `self.credentials` and replace the four lines quoted in Current state with `key = self.server.credentials.openrouter_key()`. If Plan 037 has landed, the provider already calls `credentials.openrouter_key()`; only the class body is new.

**Verify**: `python3.14 -m compileall -q codex_router` exits 0.

### Step 2: Fail closed at startup, not on the first request

In `load_state` (Plan 035) replace the check `if not Path(state['opencode_auth']).exists()` with `Credentials(state, ROUTER_HOME).check()` wrapped so that `LookupError`, `PermissionError`, `ValueError`, `OSError` become `SystemExit('OpenRouter credential problem: <message>')`. `opencode_auth` becomes optional in `REQUIRED_STATE` (keep the type check when present).

**Verify**: `ROUTER_HOME=/tmp/rh-nokey python3.14 -m codex_router` (with a valid state file lacking `opencode_auth` and no key file) exits 1 with `OpenRouter credential problem: No OpenRouter key: ...`.

### Step 3: Align the packaging text and README

- `packaging/install.ps1:2` and `:10`: change to say the key is read from `$env:OPENROUTER_API_KEY`, then `%USERPROFILE%\.codex\mixed-model-router\openrouter.key`, then OpenCode, and that the installer (Plan 041) creates the key file.
- `README.md`: add a "Credentials" section listing the order (environment variable, key file with mode 600, OpenCode fallback), that the key is read per request so rotation is "replace the file", and that the key must never be passed on a command line or written into the LaunchAgent plist.

**Verify**: `grep -n "openrouter.key" README.md packaging/install.ps1` shows both.

## Test plan

`tests/test_credentials.py`, modelled on the temp-file pattern in `tests/test_mixed_router.py` (`CompactBranchTests._server`):

- `test_env_var_wins`: env `{ENV_VAR: 'k-env'}` and a key file present; returns `k-env`.
- `test_key_file_600_is_read`: key file mode `0o600` with `k-file\n`; returns `k-file`.
- `test_key_file_group_readable_is_refused`: mode `0o640` raises `PermissionError` (skip on Windows).
- `test_empty_key_file_is_lookup_error`.
- `test_opencode_fallback`: no env, no key file, `opencode_auth` temp JSON with `{"openrouter": {"type": "api", "key": "k-oc"}}`; returns `k-oc`.
- `test_opencode_non_api_type_is_value_error`.
- `test_nothing_configured_is_lookup_error_naming_all_sources`: message contains `OPENROUTER_API_KEY`, `openrouter.key`, `opencode_auth`.
- `test_repr_never_contains_key`: `'k-file' not in repr(Credentials(...))`.

Also adjust the handler fixtures so `Credentials` finds a key: simplest is `ROUTER_HOME` pointing at a temp dir containing `openrouter.key` (mode 600) in `setUp`; leave OpenCode-based fixtures where they still pass.

Verification: full suite `OK`, eight new tests.

## Done criteria

- [ ] `grep -n "opencode_auth" codex_router/router.py codex_router/providers.py` returns nothing (only `credentials.py` knows about it).
- [ ] Full suite `OK`; `tests/test_credentials.py` has eight passing tests.
- [ ] Startup with no key source exits 1 with the `OpenRouter credential problem` message.
- [ ] `README.md` and `install.ps1` describe the same three sources in the same order.
- [ ] No key value appears anywhere in the repository (`git grep -n "sk-or-"` returns nothing).
- [ ] `plans/README.md` status row updated.

## STOP conditions

- The router module no longer reads the key at `:151-154` (Plan 037 may have moved it); locate the single read site and apply the same replacement, but STOP if there is more than one read site.
- A test needs a real key to pass. Tests use fake strings only.

## Maintenance notes

- Deferred: macOS Keychain (`security find-generic-password`) and Windows Credential Manager. Add them as a fourth source only if staff ask; the key file with mode 600 is the same protection level Codex and OpenCode use for their own stores.
- Reviewers: check that no code path formats the key into an exception message or log line. `LookupError` and `PermissionError` messages name paths, never values.
