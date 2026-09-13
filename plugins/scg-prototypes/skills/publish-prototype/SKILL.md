---
name: publish-prototype
description: Publish a built frontend prototype to the SCG prototype channel and return a shareable URL. Use when the user asks to publish, share, host or send a link for a prototype, demo, mockup or static site produced in this session.
metadata:
  short-description: "Publish a prototype and return its shareable URL."
---

# Publish Prototype

Publish a static directory to `https://prototypes.softwarecombined.com/<slug>/`:
public but unlisted, `noindex`, expiring 30 days after each publish, archived in
`software-combined/SC_Prototypes` so the URL is always reproducible from git.

Everything runs through `<skill-dir>/scripts/prototypes.py`, where `<skill-dir>`
is the directory containing this SKILL.md. It uses the AWS CLI
(`scg-prototypes` profile), `git` and the gitleaks binary pinned by the SCG
review hooks (verified by SHA-256 before it runs).
Channel values, identity details and troubleshooting live in
[references/channel.md](references/channel.md); the machine-readable values are in
[references/channel.json](references/channel.json).

## Steps

1. Decide the slug before building, because the build base path must match:
   propose `<readable-name>-<4 random characters>` unless the user names one.
2. Build the prototype with that slug as the base path, for example
   `npm run build -- --base=/<slug>/` for Vite, or `base: '/<slug>/'` in the
   framework config. Plain HTML with relative asset paths needs no change.
3. Confirm the output directory contains `index.html` at its root.
4. Run:

   ```sh
   python3 <skill-dir>/scripts/prototypes.py publish <output-dir> --slug <slug> --title "<title>"
   ```

   Add `--source <project-dir>` when the published directory is a build output.
   Use `--dry-run` to validate and see the plan without writing anything, and
   `--update` only to replace a slug that is already published.
5. If the command fails on an expired SSO session, run
   `aws sso login --profile scg-prototypes` once and retry.
6. Report the URL and its expiry date exactly as the script printed them.

Other commands: `list` shows every published prototype with its status, and
`unpublish <slug>` removes one from the channel while keeping its archive.

## Rules

- Never publish real customer data, credentials or `.env` files. The script runs
  gitleaks and fails closed; do not bypass, silence or re-run around a finding.
- Never claim a prototype is published unless the script printed its URL.
- Never invent a channel value: if `channel.json` has no `distributionId`, the
  foundation is not deployed yet. Say so and point at the `SC_Infrastructure`
  manifest `environments/software-combined/production/web-edge-prototype-channel.yaml`.
- Keep one slug per prototype; a different slug means a different URL and a new
  30 day expiry.

## Updates

When installing, pulling or updating this skill for use, complete
[automatic-update setup](references/updates.md) on macOS, Linux or Windows:
configure the native shared schedule, run it and verify installed versions.
This is part of installation, not an optional follow-up. Respect explicit
read-only scope and preserve custom schedules when reporting setup blockers.
