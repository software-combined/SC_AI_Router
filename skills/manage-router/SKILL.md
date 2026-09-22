---
name: manage-router
description: >
  Set up, check, update, or remove the local SCG mixed-model router through
  the canonical installer. Use when the user asks to install, set up, or
  connect OpenRouter models on this computer, check router health, update
  the router, or detach it from a client. Never runs automatically on
  plugin enable or refresh; every mutation follows an explicit user request.
---

# Manage Router

The router is one local service per OS user, shared by Codex and Claude
Code. All work goes through the canonical installer in this repository;
this skill never edits client settings or router state by hand.

## Before any mutation

1. Report the exact proposed target first: which clients, which home,
   which feed. Wait for confirmation on first setup.
2. Run the read-only probes and show their redacted summary:
   `python3 packaging/install.py --preflight --home <home>`,
   `python3 packaging/install.py --status --home <home>` and
   `python3 packaging/install.py --doctor --home <home>` (the doctor names a
   fix per failing row).
3. Respect the host approval policy. Do not demand a second generic
   confirmation and do not grant new tool permissions.

## Actions

- Setup: `python3 packaging/install.py --home <home>` for the
  invoking client; add `--clients both` only when both were requested.
  The key window opens by itself when the installed service has no key;
  pass `--setup` only to force it (for example when no window appeared).
  Collect subscription modes first (`--openai-mode`, `--claude-mode`);
  the key window collects the key and a Dev/General starter choice; it installs
  the starter only when no global instructions file exists and never changes routing.
  The installed service does not receive the invoking shell's environment,
  so an exported `OPENROUTER_API_KEY` does not count as configured: the
  window still opens. `--setup` on an up-to-date home restarts the current
  release with a fresh setup link, without re-extracting it.
- Status: `python3 packaging/install.py --status --json --home <home>`.
  Health alone is not successful setup; a model round trip proves it.
- Update: `python3 packaging/install.py --update --home <home>` applies what
  the channel offers; `--check-update` only reports the installed and
  available versions.
- Detach Claude: uninstall detaches every client; `--client none`
  drops to service-only and restores Claude settings too. A plain
  `--clients codex` reinstall never silently detaches Claude.
- Key recovery: a missing or revoked key opens the native key popup (or the
  loopback setup page when the host has no dialog tool) on
  next request. Never ask for the key in chat, arguments, or environment.

## Rules

- The service runs from its private installation directory, never a
  plugin-cache path. Removing or upgrading this plugin must not strand it.
- Restarting a client is a separate user-visible step, never automatic.
- Never print tokens, keys, setup URLs, or config bodies.
- Native client sign-in is preserved; conflicting overrides block with a
  redacted explanation instead of silent overwrite.

## When something is wrong

Work from `docs/troubleshooting.md` in the installed release. Run
`python3 packaging/install.py --doctor` first: it names the component that is
WARN or FAIL and the fix. The common staff cases and their first check:

- No OpenRouter models in the Codex picker: Codex reads its catalogue only at
  startup, so quit and reopen it before investigating anything else.
- An update that stopped: the updater parks a version after three failed
  attempts and says so; `logs/update.log` lists activated installs, and a
  failed attempt's output is there on macOS or in the update service's journal
  on Linux.
- Claude Code stopped routing: `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_API_KEY`
  must stay unset. The installer owns four settings in the client's `env`
  block (`ANTHROPIC_BASE_URL`, `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY`,
  `ENABLE_TOOL_SEARCH` and `_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL`); the
  first must point at the loopback URL, and the other three must keep the
  installer's values or the attach refuses.

Send IT `--status --json` output only; it carries no tokens, keys or URLs.
