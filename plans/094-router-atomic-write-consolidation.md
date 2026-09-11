# Plan 094: One atomic writer for installer-side state and config files

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat a985197..HEAD -- packaging/service.py packaging/codex_config.py packaging/release.py packaging/install.py tests/test_packaging.py tests/test_install_state.py tests/test_release.py`
> Read changed code and preserve current behavior before edits. (`packaging/atomic_write.py`
> is new in this plan, so it has no baseline diff; `packaging/install.py` and
> `tests/test_release.py` joined the path list under plan 123.)

## Status and first proof

- Priority P1; effort S-M; risk MED; confidence HIGH; category tech-debt/data-safety; depends on none.
- Planned at `a985197`, 2026-09-10.
- First proof: a crash between write and replace leaves the previous `mixed-router-state.json` and
  `~/.codex/config.toml` intact; the temp file is unique per writer.

## Why this matters

The same logical files have different durability classes depending on which code path writes them:

- `packaging/service.py:616-619` `_write_state` truncates in place (`O_TRUNC`); `ensure_state`
  migrations use `path.write_text` (`:628`, `:632`). The router writes the same file atomically via
  `ai_router/setup.py:302-320` `_atomic_replace`.
- `packaging/codex_config.py:78-80` rewrites `~/.codex/config.toml` with `O_TRUNC`, while
  `packaging/claude_config.py:70-92`, `packaging/claude_desktop_config.py:105-127` and
  `tools/disable.py:19-26` already use temp-file + `os.replace`.

A crash mid-write can strand the service (the state file holds port/token) or leave a truncated
codex config. The installer holds `install_lock` (`service.py:340-370`) but the router does not
participate, so atomic replacement fixes torn files; it does **not** fix lost updates from
concurrent read-modify-write, which is explicitly out of scope here.

## Current state (verified at a985197; line refs re-verified 2026-09-11 at f72fc7e)

- `packaging/service.py:616-619`:
  ```python
  def _write_state(home, state):
      fd = os.open(home / 'mixed-router-state.json', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
      with os.fdopen(fd, 'w') as stream:
          stream.write(json.dumps(state, indent=2) + '\n')
  ```
- `packaging/service.py:622-650` — `ensure_state` writes with `path.write_text` for the
  `openai_models` seed (`:628`) and the `gpt-reserve` prune (`:632`); fresh-state creation
  (`:645-647`) already uses `O_EXCL` + `os.replace` and stays as is.
- `packaging/codex_config.py:63-89` — `replace_config_block` reads, rewrites, and truncates in place
  (`:78-80`), then chmods 0600.
- `ai_router/setup.py:302-320` is the house exemplar: `O_EXCL` tmp + stale-tmp retry + `os.replace`.
  Note its deterministic tmp name is safe there (router-only writer) but two processes using the
  same deterministic name would unlink each other's in-flight temp.
- Packaging modules load through `service.load()` (Plan 123's single 3.9 loader at
  `packaging/service.py:38-50`); only the `service` bootstrap in `packaging/install.py:24-30`
  keeps a `spec_from_file_location` copy. Modules run on Python 3.9; no package-relative imports.

## Scope

**In scope**: new `packaging/atomic_write.py`; `packaging/service.py` (`_write_state`,
`ensure_state`); `packaging/codex_config.py` (`replace_config_block` only); release/bundle file
lists and their tests; `tests/test_install_state.py` or a new `tests/test_atomic_write.py`.
**Out of scope**: `claude_config.write_settings` / `claude_desktop_config.write_json` (their
stale-tmp refusal is test-visible; do not change their semantics), `ai_router/setup.py`,
`packaging/feed.py`, snapshot/rollback features, cross-process lost-update handling,
`install_lock` semantics.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -m unittest tests.test_install_state tests.test_install_config tests.test_claude_config tests.test_install` | pass before and after |
| New module | `python3.14 -m unittest tests.test_atomic_write` | pass |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; update baseline where counts change (`service.py` 684, `codex_config.py` 156, `install.py` 690 at f72fc7e) |
| 3.9 grammar | run the repo's installer-surface test | pass |

## Steps

### Step 1: add `packaging/atomic_write.py` (commit 1)

Python 3.9-safe, stdlib only. One public function:
```python
def replace_text(path, text, mode=0o600):
    """Atomically replace path with text; unique tmp, fsync-free."""
```
Use `tempfile.mkstemp(dir=path.parent, prefix=path.name + '.', suffix='.tmp')` (unique per writer,
0600 from mkstemp), `os.fdopen(fd, 'w')` + write, `os.chmod(tmp, mode)`, `os.replace(tmp, path)`;
on any exception unlink the tmp best-effort and re-raise. Create the parent directory first if a
caller needs it (state home already exists).

### Step 2: route the three writers (commit 2)

- `service._write_state` → `atomic_write.replace_text(home / 'mixed-router-state.json', json.dumps(state, indent=2) + '\n')`.
- `service.ensure_state` → same helper for both `write_text` sites. Keep the return value and the
  `gpt-reserve` prune behavior identical.
- `codex_config.replace_config_block` → `atomic_write.replace_text(config_path, after)`, keeping the
  existing read/exists/mkdir/chmod flow (chmod on the final path remains for the pre-existing-file case).

Load the helper with `service.load()` (Plan 123's single 3.9 loader) so no new `spec_from_file_location` copy is added.
`service.py` loads it at module scope (`_atomic_write`); `codex_config.py` keeps no loader copy —
`install.py` injects the loaded helper (`_codex_config._atomic_write = _svc.load(...)`) right after
its own `service` bootstrap, the same seam `diagnostics.py` already uses for `_codex_config`.

### Step 3: bundle wiring (same commit as Step 1)

Add `packaging/atomic_write.py` to `packaging/release.py`'s `PACKAGING_FILES` inventory, to
`REQUIRED_PACKAGING` and the 3.9 installer-surface list in `tests/test_packaging.py`, and to the
closure dep list in `tests/test_release.py`. A missing entry means the installed release cannot
import the helper and the service fails to start.

Semantics the helper chooses (recorded 2026-09-11 after review): a symlinked target is replaced
by a regular file rather than written through (the old `O_TRUNC` followed the link; the new
behaviour also closes a planted-symlink redirect), a read-only target no longer blocks the write
(rename needs only directory permission), and the helper is fsync-free: it fixes torn reads, not
power-loss durability, so recovery from the latter is re-running the installer.

### Step 4: tests (commit 2)

New `tests/test_atomic_write.py`: replace creates/overwrites; mode is 0600; a pre-existing target
survives a failed write (patch `os.replace` to raise); no tmp remains after success or failure.
Keep/extend `tests/test_install_state.py` coverage for `ensure_state` prune and seed paths.

**Verify**: focused tests pass; simulate a crash by patching `os.replace` to raise and asserting the
original file bytes are unchanged.

## Done criteria

- [ ] `rg -n "O_TRUNC" packaging/service.py packaging/codex_config.py` → no matches, and the three targeted writers (`_write_state`, both `ensure_state` sites, `replace_config_block`) go through the atomic helper. Remaining `write_text` calls (receipts at `codex_config.py:125,150`, feed token at `feed.py:60-62`, `swap_current`'s tmp write at `service.py:227`) are deliberately out of scope here: receipts move in plan 095, and the tmp write is already atomic.
- [ ] Bundle list, release-bundle test, and 3.9 surface list include `packaging/atomic_write.py`.
- [ ] Crash-simulation test proves the original survives; tmp files are cleaned.
- [ ] Full suite, compile, limit and surface gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- The bundle lists cannot take the new file (release closure test fails structurally): stop and
  report; shipping without bundle wiring breaks installed releases.
- Any test depends on the exact tmp filename of `_write_state`/`replace_config_block`: stop and
  report before changing the naming scheme.
- The 3.9 surface parser rejects the new module: stop; rewrite with 3.9 syntax rather than moving
  the helper into the 3.14 runtime tree.

## Maintenance notes

- Lost updates between router and installer remain possible by design; the plan does not claim to
  fix them. If that becomes real, the fix is a shared lock the router also takes.
- Do not route `claude_config`/`claude_desktop_config` through this helper in this plan: their
  deterministic-tmp refusal is deliberate and tested.
- Reviewers: check that `ensure_state` still pins the exact same JSON shape (`indent=2` + newline).
