# Security policy

## Reporting a vulnerability

Email **cyril@softwarecombined.com**. Include the router version
(`python3.14 packaging/install.py --status` prints it without secrets), your
operating system and client, and the steps to reproduce.

Please do not open a public issue for a suspected vulnerability, and do not
attach state files, logs or configuration: they can carry the loopback token.

A confirmed vulnerability has a fix target of 30 days. Fixes ship as a normal
release, and installs on the `stable` channel pick them up automatically
within about four hours.

## Scope

In scope: the router service (`ai_router/`), the installer, updater and
service definitions (`packaging/`), the bootstrap scripts, the update feed
templates (`infra/`) and the release workflow.

Out of scope: the upstream providers and clients themselves (OpenAI,
Anthropic, OpenRouter, Codex, Claude Code), and findings that require code
already running as the installing user, who holds the key by design.

## What the router does to protect you

- Listens on `127.0.0.1` only; every request needs the per-install path token.
- Keeps the provider key in an owner-only file (mode 600 on macOS and Linux,
  an `icacls` grant to the installing user on Windows) and refuses a key file
  whose permissions have been widened.
- Never sends subscription headers with a request billed to OpenRouter.
- Logs request metadata only: never request content, keys or tokens.
- Verifies every update bundle by SHA-256 with version and identity checks;
  unattended updates come only from the HTTPS feed origin, where a serial
  replay guard also applies.

## Rules for contributors

Never commit state files, activation receipts, catalogues, logs, API keys or
bearer tokens. `tools/check_policy_scans.py` runs the secrets scan locally and
in CI, and GitHub secret scanning with push protection is enabled on this
repository.
