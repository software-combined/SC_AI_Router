# SC_Codex_openRouter_adapter Agent Instructions

## Boundaries

- `codex-model-router/` owns the adapter: router, tool protocol adapter,
  capabilities single-source, transparent compaction, catalogue writers,
  probes, tests, and packaging stubs.
- The live runtime directory (`~/.codex/mixed-model-router/`) owns private
  state: bearer tokens, activation receipts, backups, logs, and the generated
  catalogue. Never commit those here. Never print them.
- OpenAI requests keep ChatGPT subscription authentication. Only the six
  configured OpenRouter models use the federated OpenRouter key, read at
  request time. Subscription headers never accompany OpenRouter requests.

## Git Worktree Discipline

- The primary checkout is read-only for agent sessions: never run `git reset`,
  `git stash`, `git pull`, branch switches, or edits here. One writable,
  uniquely named worktree per session (`git worktree add`); remove it when the
  work is merged. Rationale: a concurrent session once hard-reset a shared
  `main` checkout; do not repeat that here.
- At most one owned writable worktree per agent session, reused for every
  follow-up and phase, cleaned up as work integrates.
- Preserve unrelated dirty/untracked work. Never revert another session's
  changes or delete another session's worktree.

## Source Limits

Production modules target 250 physical lines, hard cap 400. Entrypoints
400/700, tests 300/500, governance and config 500/1000. A stricter local
rule always wins. Generated files, fixtures, and vendored code do not count.
Keep each staged commit within 800 meaningful changed lines, targeting fewer
than 500 for complex logic.

## Verification And Review

- Run the module tests before every commit: from `codex-model-router/`,
  `python3 -m unittest` over the `test_*.py` files with
  `PYTHONDONTWRITEBYTECODE=1`.
- Before committing, run the installed `pre-commit-review` skill: one
  simplification pass, secret scan, and three read-only review lanes on the
  exact staged tree. Never fabricate receipts or substitute models to pass
  the hook. Reviewer model and effort follow the owner routing table in
  `~/.codex/AGENTS.md` (currently Muse at xhigh for this repo's lanes).
- Commit subjects use `<type>: <short summary>` with type `feat`, `fix`,
  `refactor`, `test`, `chore`, or `docs`. Do not bypass Git hooks with
  `--no-verify` unless Cyril explicitly approves.

## Safety And Deployment

- Default production work to read-only. Never commit secrets, API keys,
  tokens, or credential exports.
- Runtime changes deploy only with a current backup of the live directory, an
  idle service boundary (no in-flight requests), and a readback proving
  exactly the intended delta landed. Never restart the router while requests
  are active unless Cyril explicitly approves.
- No staff-wide rollout without explicit release authority.
