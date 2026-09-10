# Plan 074: Rename `codex_router` package to `ai_router`

> Implementation plan. No AWS, Entra, staff-machine, release or publication
> authority. Branch `codex/ai-router-rename-20260910`, target `develop`.

## Why

The package serves Codex, Claude Code, and OpenRouter side by side; the
`codex_` prefix misleads new readers into treating the Codex client adapter
as the whole router. New name: `ai_router`.

## Compatibility contract (do not break installed machines)

- Installed home stays `~/.codex/mixed-model-router`; `--home` default unchanged.
- Launchd label `com.local.codex-mixed-model-router` and systemd units unchanged.
- State/catalogue filenames unchanged (`mixed-router-state.json`, `mixed-models.json`).
- Logger name stays `codex_router` (tests and log filters match on it).
- Thin `codex_router` alias package re-exports `ai_router` so old releases,
  probes, and user scripts keep importing. It is removed only by a later plan.
- `probe_codex_runtime.py` filename stays (paid-probe history references it);
  internal imports move to `ai_router` with a fallback import.
- Client-specific names stay: `clients/codex.py`, `claude.py`,
  `codex_config.py`, `claude_config.py`.

## Steps

1. `git mv codex_router ai_router`; write `codex_router/__init__.py` alias
   (`from ai_router.<name> import *` per public module; keep `MODELS`,
   `Router`, `LOG` importable).
2. Mechanical rewrite `codex_router` -> `ai_router` in source, tools,
   packaging, tests, `.github/`, docs, README, AGENTS.md, SOURCES.txt,
   `config/source-limits-baseline.json`, `pyproject.toml` name `ai-router`.
3. Revert the rewrite inside the alias package, history quotes, and the
   compatibility notes themselves.
4. Release bundle: `bundle_files` reads `ai_router/`; tarball becomes
   `ai-router-<version>.tar.gz`. Feed/`latest.json` shape unchanged.
5. Router launcher accepts both `ai_router` and legacy `codex_router`
   release dirs during the transition window.
6. Gates: `python3.14 -m unittest discover -s tests -t .`,
   `python3.14 -m compileall -q ai_router tools tests packaging`,
   `python3.14 tools/check_source_limits.py`, fresh-`--home` install +
   `--status` in temp dir, `pre-commit-review`.
7. Docs: CHANGELOG Unreleased entry + `packaging/VERSION` bump per repo
   release rule; README runtime file list regenerated; architecture note.
