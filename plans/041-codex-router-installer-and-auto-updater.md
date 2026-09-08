# Plan 041: Ship the router as a versioned release bundle with a stdlib installer, health-checked rollback and a daily auto-updater

> **Deviation recorded 2026-09-08 (installer-core commit):** the bundle
> excludes `tests/*.py`, and `self_test` is an import smoke (`catalogue`
> and `registry` load with non-empty `MODELS`) rather than full discover
> in the bundle. Bundled repo tests reference files outside the bundle
> (`packaging/release.py`, `README.md`, wrappers), so discover in the
> bundle fails deterministically. Verified install still holds via
> manifest check, smoke, health check, and rollback. The bundled
> `packaging/VERSION` is stamped with the composed build version so
> `current_version()` converges after install.

> **Amended 2026-09-07**: Plan 045 supersedes Step 6 (update cadence becomes every 15 minutes with ETag, jitter and a beta channel) and Step 8 (releases are created automatically on every push to `main` or `beta`; `packaging/VERSION` holds `MAJOR.MINOR` and CI appends the run number). Plan 045 also replaces the stop-and-start restart with drain plus launchd socket activation. Plan 043 adds the `--openai-mode none` installer flag. Build the installer core (Steps 1 to 5, 7) exactly as written here, then follow Plan 045 for cadence, release trigger and restart.

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
- **Effort**: L
- **Risk**: MED (writes a LaunchAgent and a config block on staff machines; mitigated by dry-run, health check and rollback)
- **Depends on**: Plan 034 (repository and package layout), Plan 035 (`ROUTER_HOME`, self-check, `/health` with `inflight`), Plan 040 (key file). Plan 039 changes what the config block contains (Step 6 handles both cases).
- **Category**: dx / migration / direction
- **Planned at**: commit `749a6b8d`, 2026-09-07

## Why this matters

Today "deploying" the router means copying eight files beside the private state directory by hand at an idle moment, restarting the LaunchAgent, and hoping. There is no version on disk, no check that the copied code matches the state file, no rollback, and the two installer scripts only run the tests and print instructions. Cyril's goal is to push code and have every staff router update itself. That is safe only if each update is a verified, versioned bundle, is installed next to the previous version, is started only when the router is idle, is health-checked, and is rolled back automatically when the health check fails. This plan builds exactly that with one stdlib Python installer that also serves as the updater, macOS first and Windows as a gated second phase.

## Current state

- `packaging/install.sh` (12 lines) runs six test modules and prints "copy ONLY mixed_router.py ... to $HOME/.codex/mixed-model-router at an idle boundary". `packaging/install.ps1` (10 lines) does the same and mentions an environment variable. `packaging/VERSION` is `0.3.0`. `tests/test_packaging.py` checks that both scripts name the same eight files and that VERSION is semver.
- LaunchAgent on the author's machine, `~/Library/LaunchAgents/com.local.codex-mixed-model-router.plist`: `ProgramArguments` `[/opt/homebrew/bin/python3, /Users/cyrilallart/.codex/mixed-model-router/mixed_router.py]`, `WorkingDirectory` the same directory, `KeepAlive` true, `RunAtLoad` true, `ThrottleInterval` 10, `Umask` 63 (octal 077), `StandardOutPath`/`StandardErrorPath` `stdout.log`/`stderr.log` in that directory.
- Config block contract (`activation.json` `inserted_block`, consumed by `tools/disable.py:8-13`, which refuses to act unless the block occurs exactly once):

```toml
# BEGIN local mixed model picker
openai_base_url = "http://127.0.0.1:18749/<token>/backend-api/codex"
model_catalog_json = "/Users/cyrilallart/.codex/mixed-model-router/mixed-models.json"
# END local mixed model picker
```

  After Plan 039 the `model_catalog_json` line is absent.
- State file contract after Plans 035 and 040: `{"port": int, "token": str}` required; `openai_models` and `opencode_auth` optional. Token is `secrets.token_urlsafe(32)` style (43 characters on the author's machine).
- `/health` (Plan 035) returns `{"status": "ok", "version": "...", "inflight": N}`.
- Runtime needs Python 3.14 (`compression.zstd`). System Python on macOS is 3.9.6; Homebrew provides 3.14 at `/opt/homebrew/bin/python3`. `uv` is not installed on the author's machine.
- Release feed decision from Plan 034 Step 1: public repository with GitHub Releases (default), or S3 plus CloudFront. `latest.json` on GitHub is reachable at `https://github.com/software-combined/codex-model-router/releases/latest/download/latest.json` for a public repository.
- Repository CI conventions (Plan 034 Step 5): top-level `permissions`, `concurrency` group, `timeout-minutes`, actions pinned to full SHAs.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Tests | `python3.14 -m unittest discover -s tests -t . -v` | `OK` |
| Build a bundle locally | `python3.14 packaging/release.py --out dist` | `dist/codex-model-router-<VERSION>.tar.gz`, `dist/latest.json` |
| Dry run install | `python3 packaging/install.py --dry-run --feed file://$PWD/dist/latest.json` | prints the actions it would take, exits 0 |
| Real install (author's machine) | `python3 packaging/install.py --feed file://$PWD/dist/latest.json` | `installed <VERSION>; health ok` |
| Update check | `python3 packaging/install.py --check-update` | `up to date <VERSION>` or `installed <NEW>` or `deferred: router busy` |

`python3` in these commands may be the 3.9 system interpreter; the installer must run on 3.9+ and locate a 3.14 interpreter for the router itself.

## Scope

**In scope**: new `packaging/release.py`, new `packaging/install.py`, new `.github/workflows/release.yml`, `packaging/install.sh` and `packaging/install.ps1` (become two-line wrappers), `tests/test_packaging.py` (rewrite), new `tests/test_install.py`, `packaging/VERSION` (bump to `0.4.0`), `CHANGELOG.md` (entry), `README.md` (install and update sections; Plan 042 polishes).

**Out of scope**: router behaviour; `tools/disable.py` beyond keeping its contract; any AWS resources (if the feed decision is S3, the bucket is provisioned from SC_Infrastructure under its own plan); Windows Task Scheduler beyond Step 9's gated phase.

## Git workflow

- Branch `codex/router-installer-<yyyymmdd>`; commits `feat:`/`test:`/`chore:`; pre-commit review per the shared skill. Do not push unless instructed. Tag creation (Step 8) is an operator action.

## Steps

### Step 1: `packaging/release.py` builds a deterministic bundle

Stdlib only. Reads `packaging/VERSION`. Creates `dist/codex-model-router-<VERSION>.tar.gz` containing exactly: `codex_router/**/*.py` and `codex_router/*.txt`, `tools/*.py`, `tests/*.py`, `packaging/VERSION`, `packaging/install.py`, and a generated `MANIFEST.json` `{"version", "files": {relative path: sha256}, "codex_tested": <value from docs/compatibility.md or "unknown">, "min_python": "3.14"}`. Set fixed `mtime`, `uid`/`gid` 0, `uname`/`gname` empty on every tar member so two builds of the same tree are byte-identical. Writes `dist/latest.json` `{"version", "url": "<release asset URL for the tarball>", "sha256": <tarball sha256>, "min_python": "3.14", "published": <UTC ISO>}` where the URL is `https://github.com/software-combined/codex-model-router/releases/download/v<VERSION>/codex-model-router-<VERSION>.tar.gz` unless `--url-base` is given. Exclude `__pycache__`.

**Verify**: build twice; `shasum -a 256 dist/*.tar.gz` identical both times; `tar tzf dist/*.tar.gz | grep -c __pycache__` prints `0`.

### Step 2: `packaging/install.py` core: fetch, verify, unpack, test

Single file, `#!/usr/bin/env python3`, runs on Python 3.9+. Arguments: `--feed URL` (default the GitHub `latest.json` URL; `file://` accepted), `--version X` (pin), `--home PATH` (default `~/.codex/mixed-model-router`), `--python PATH`, `--install-python` (macOS: run `brew install python@3.14` if no 3.14 is found), `--dry-run`, `--check-update`, `--uninstall`, `--static-catalogue` (writes the `model_catalog_json` line; only for installs before Plan 039). All network access goes through one function `fetch(url) -> bytes` so tests can inject a fake.

Flow for install:

1. Locate a 3.14 interpreter: `--python`, then `python3.14` on `PATH`, then `/opt/homebrew/bin/python3.14`, `/opt/homebrew/bin/python3`, `/usr/local/bin/python3.14`; accept the first whose `-c "import sys;print(sys.version_info[:2])"` is `(3, 14)` or higher and that can `import compression.zstd`. If none: with `--install-python` on macOS run Homebrew, otherwise print the exact `brew install python@3.14` instruction and exit 2.
2. Read `latest.json`; compare `version` with `home/current/packaging/VERSION` if present (tuple of ints).
3. Download the tarball; verify sha256 equals `latest.json['sha256']`, else exit 1 `bundle checksum mismatch`.
4. Extract into `home/releases/<version>.partial/` after checking every member: no absolute paths, no `..`, no symlinks or hardlinks, regular files and directories only. Verify each file against `MANIFEST.json`; any mismatch: delete the partial directory and exit 1. Rename to `home/releases/<version>/`.
5. Run `<python3.14> -m unittest discover -s tests -t . -q` inside the new release directory. Any failure: delete the release directory and exit 1 `bundle self-test failed`.

**Verify**: `python3 packaging/install.py --dry-run --feed file://$PWD/dist/latest.json` prints the interpreter found and the five actions without performing them.

### Step 3: State, key file, `current` swap

6. If `home/mixed-router-state.json` is missing: choose port 18749 unless something already listens on it (try a bind), generate `token = secrets.token_urlsafe(32)`, write `{"port", "token"}` with mode 0600. If present: keep it untouched.
7. Credentials: if `OPENROUTER_API_KEY` is set, or `home/openrouter.key` exists, or the state has `opencode_auth` pointing at an existing file, continue. Otherwise create an empty `home/openrouter.key` with mode 0600, print `Paste your OpenRouter key into <path> (owner-only file) and re-run the installer`, and exit 3. Never accept the key as an argument.
8. Swap: `os.symlink(release_dir, home/current.tmp)`; `os.replace(home/current.tmp, home/current)`. Remember the previous target for rollback.

**Verify**: after a real run, `readlink ~/.codex/mixed-model-router/current` prints the release directory; `stat -f %Lp ~/.codex/mixed-model-router/mixed-router-state.json` prints `600`.

### Step 4: Service on macOS, health check, rollback

9. Write `~/Library/LaunchAgents/com.local.codex-mixed-model-router.plist` from a template: `ProgramArguments` `[<python3.14>, -m, codex_router]`, `WorkingDirectory` `home/current`, `EnvironmentVariables` `{ROUTER_HOME: home}`, `KeepAlive` true, `RunAtLoad` true, `ThrottleInterval` 10, `Umask` 63, `StandardOutPath` and `StandardErrorPath` `home/logs/launchd.log`. Create `home/logs/` first.
10. `launchctl bootout gui/<uid>/com.local.codex-mixed-model-router` (ignore a non-zero exit when the agent is not loaded), then `launchctl bootstrap gui/<uid> <plist>`.
11. Poll `GET http://127.0.0.1:<port>/<token>/health` every 0.5 s for up to 20 s; success is HTTP 200 with JSON `status == 'ok'` and `version == <version>`.
12. On failure: repoint `current` to the previous release (if any), run steps 10 and 11 again for the old version, and exit 1 with `rolled back to <old>: new version failed health check; see home/logs/launchd.log`. If there was no previous release, bootout and exit 1.
13. Prune `home/releases/` to the current and the previous release only.

**Verify**: simulate a failure once on the author's machine by installing a bundle whose `codex_router/__main__.py` has been edited to `raise SystemExit('boom')` (build it into a scratch `dist-bad/`); the installer must print the rollback line and the router must answer `/health` with the previous version afterwards. Then install the good bundle.

### Step 5: Config block

14. Read `~/.codex/config.toml`. If the exact block from `home/activation.json['inserted_block']` occurs once, replace it; if no block markers exist, insert at the top; if markers exist but do not match the receipt, exit 1 `config block was edited by hand; run tools/disable.py first` (never guess). New block: `# BEGIN local mixed model picker`, `openai_base_url = "http://127.0.0.1:<port>/<token>/backend-api/codex"`, plus `model_catalog_json = "<home>/mixed-models.json"` only with `--static-catalogue`, then `# END local mixed model picker`. Write atomically with mode 0600 after saving a copy to `home/config-before-<UTC stamp>.toml` (mode 0600). Update `activation.json` with `config_path`, `inserted_block`, `previous_sha256` (sha256 of the file as it was before this write) so `tools/disable.py` keeps working unchanged.
15. Print `installed <version>; health ok; restart Codex to load the router`.

**Verify**: `python3.14 -c "import json;c=open('$HOME/.codex/config.toml').read();print(c.count(json.load(open('$HOME/.codex/mixed-model-router/activation.json'))['inserted_block']))"` prints `1`.

### Step 6: `--check-update` and the update agent

- `--check-update`: fetch `latest.json`; if not newer than `current`, print `up to date <version>` and exit 0. If newer: poll `/health`; proceed only when `inflight == 0` for three consecutive polls one second apart, waiting up to 10 minutes; otherwise print `deferred: router busy` and exit 0. Then run the install flow (Steps 2 to 5) from the **downloaded** bundle's own `packaging/install.py` (`subprocess.run([python3.14, extracted/packaging/install.py, ...])`) so a newer installer is used for its own version; the current installer only fetches, verifies and hands over. Write a `home/logs/update.log` line per run.
- Second LaunchAgent `com.local.codex-mixed-model-router.update`: `ProgramArguments` `[<python3.14>, <home>/current/packaging/install.py, --check-update]`, `StartCalendarInterval` `{Hour: 10, Minute: 0}`, `RunAtLoad` false, `StandardOutPath`/`StandardErrorPath` `home/logs/update.log`. Written and bootstrapped by the installer in Step 4.
- Channel: read `home/channel` (`stable` default). For `beta`, the feed URL is `latest-beta.json` and Step 8 publishes it for pre-release tags. Keep this to four lines; it lets Cyril test releases on his own machine before staff receive them.

**Verify**: `python3 ~/.codex/mixed-model-router/current/packaging/install.py --check-update --feed file://$PWD/dist/latest.json` prints `up to date <version>`; `launchctl print gui/$(id -u)/com.local.codex-mixed-model-router.update | grep -c StartCalendarInterval` prints at least `1`.

### Step 7: `--uninstall`, wrappers, tests

- `--uninstall`: run `tools/disable.py` from `current` (it removes the config block and boots out the router agent), then bootout and delete the update agent plist and the router plist, and print that `home` was left in place for the operator to delete.
- `packaging/install.sh` becomes: `#!/bin/sh` and `exec python3 "$(dirname "$0")/install.py" "$@"`. `packaging/install.ps1` becomes the PowerShell equivalent calling `python`.
- Rewrite `tests/test_packaging.py`: assert VERSION is semver, assert both wrappers call `install.py`, assert `release.py` bundle from a temp tree contains `MANIFEST.json` whose hashes match the files.

**Verify**: full suite `OK`.

### Step 8: Release workflow and first release

`.github/workflows/release.yml`: trigger `push: tags: ['v*']`; top-level `permissions: contents: read`; `concurrency` group `release-${{ github.ref }}` with `cancel-in-progress: false`; one job with `timeout-minutes: 15` and job-scoped `permissions: contents: write`; steps: checkout (pinned SHA), setup-python 3.14 (pinned SHA), `python -m unittest discover -s tests -t .`, `python packaging/release.py --out dist`, then `gh release create "$GITHUB_REF_NAME" dist/*.tar.gz dist/latest.json --generate-notes` with `GH_TOKEN: ${{ github.token }}`; for tags containing `-beta`, also upload `latest-beta.json` (a copy of `latest.json`) and pass `--prerelease`. Bump `packaging/VERSION` to `0.4.0`, add a `CHANGELOG.md` entry, merge, then the operator tags `v0.4.0`.

**Verify**: `gh release view v0.4.0 --json assets --jq '.assets[].name'` lists the tarball and `latest.json`; `curl -sL https://github.com/software-combined/codex-model-router/releases/latest/download/latest.json | python3 -c "import json,sys;print(json.load(sys.stdin)['version'])"` prints `0.4.0`. Then on the author's machine: `python3 packaging/install.py` with no `--feed` installs from the public feed and `/health` reports `0.4.0`.

### Step 9 (gated phase 2): Windows

Only if Cyril confirms staff run the Codex desktop app on Windows and names one test machine. Then: installer detects `os.name == 'nt'`; config path `%USERPROFILE%\.codex\config.toml`; service via `schtasks /Create /SC ONLOGON /TN CodexModelRouter /TR "<python> -m codex_router" /F` with `ROUTER_HOME` set through a small `.cmd` wrapper in `home`; update task `schtasks /Create /SC DAILY /ST 10:00 /TN CodexModelRouterUpdate ...`; health check identical; rollback identical; key file mode check skipped (documented). Add a `windows-latest` job to `check.yml` running the unit tests.

**Verify**: on the named machine, `python install.py` prints `installed`, and Codex lists the OpenRouter models.

## Test plan

`tests/test_install.py` imports `packaging/install.py` as a module (guard all side effects under `if __name__ == '__main__'`; expose functions `verify_sha256`, `safe_extract`, `newer`, `render_plist`, `swap_current`, `replace_config_block`, `wait_idle`, `install` with injectable `fetch`, `run`, `now`):

- `test_checksum_mismatch_is_rejected`.
- `test_extract_rejects_traversal_and_links`: tar with `../x` and a symlink member raises.
- `test_manifest_mismatch_deletes_partial_dir`.
- `test_newer_compares_tuples`: `newer('0.10.0', '0.9.9')` is True.
- `test_render_plist_contains_label_home_and_python`.
- `test_swap_current_is_atomic_and_rollback_restores_previous` (temp home with two release dirs).
- `test_replace_config_block_preserves_unrelated_lines_and_refuses_double_markers`.
- `test_wait_idle_returns_false_when_inflight_stays_positive` (fake fetch returning `{"inflight": 1}` and a fake clock).
- `test_install_dry_run_performs_no_writes` (temp home stays empty).
- `test_health_failure_triggers_rollback` (fake `run` for launchctl, fake fetch returning 500 for the new version then 200 for the old).

Pattern: temp directories as in `tests/test_apply_catalogue.py`. Verification: full suite `OK`, ten new tests.

## Done criteria

- [x] `python3.14 packaging/release.py --out dist` is deterministic (identical sha256 across two builds). Verified 2026-09-08 on current source: two `--out` builds at 0.6.4.0 produced identical tarballs (`dc8ad87d...`; earlier pair at 0.6.3.0 also identical at `7213d4bd...`).
- [ ] `tests/test_install.py` ten tests pass; full suite `OK`.
- [ ] On the author's machine: `readlink ~/.codex/mixed-model-router/current` points at `releases/0.4.0`, `/health` reports `0.4.0`, both LaunchAgents are loaded, the config block matches `activation.json`, and the simulated bad bundle rolled back.
- [ ] `gh release view v0.4.0` shows the two assets; `latest.json` is reachable from the feed URL.
- [ ] `tools/disable.py` still works against the new block (dry check: count of `inserted_block` in config is 1).
- [ ] No key value or token appears in any log or in the plist (`grep -c <token> ~/Library/LaunchAgents/*.plist` prints `0`; run without printing the token).
- [ ] `plans/README.md` status row updated.

## STOP conditions

- No Python 3.14 can be found or installed on the target machine and `--install-python` is refused; report, do not lower the runtime version.
- The release feed decision (public repository or S3) is not recorded in Plan 034's report.
- The health check fails after rollback too (both versions down): leave the previous plist in place, print the launchd log path, and stop.
- `~/.codex/config.toml` contains the markers but not the receipt's exact block. Do not edit the file.
- Windows phase without a named test machine.

## Maintenance notes

- Every release must bump `packaging/VERSION`; the updater compares that file, nothing else. A tag without a bump publishes a bundle the updater ignores.
- The updater hands over to the new bundle's installer, so installer bugs are fixed by shipping a new release, not by touching machines.
- Deferred on purpose: signed manifests (Ed25519 via `openssl` on macOS) if the feed ever moves off GitHub over HTTPS; `uv`-managed Python instead of Homebrew if staff machines lack Homebrew; a `--port` override for machines where 18749 is taken (the installer already picks a free port on first install).
- Reviewers: check that `safe_extract` is used for every member and that no `subprocess` call includes the token or key.
