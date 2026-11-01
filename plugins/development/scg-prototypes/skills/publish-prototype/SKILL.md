---
name: publish-prototype
description: Publish a built frontend prototype to the SCG prototype channel and return a shareable URL. Use when the user asks to publish, share, host or send a link for a prototype, demo, mockup or static site produced in this session.
metadata:
  short-description: "Publish a prototype and return its shareable URL."
---

# Publish Prototype

Publish a static directory to `https://prototypes.softwarecombined.com/<slug>/`.
Each link is public but unlisted, uses `noindex`, and expires 30 days after
publication. The configured archive keeps the published files reproducible.

Everything runs through `<skill-dir>/scripts/prototypes.py`, where `<skill-dir>`
is the directory containing this SKILL.md. It uses the Amazon Web Services
(AWS) command-line interface, Git, and the gitleaks binary pinned by the SCG
review hooks. It verifies the scanner's SHA-256 hash before each scan.

The bundled [channel template](references/channel.json) is blank and cannot
publish. Store the completed config outside the repository and installed
plugin. Select it with `--config` or `PROTOTYPE_CHANNEL_CONFIG`. See
[channel configuration](references/channel.md) for the fields and failure
guidance.

## Steps

1. Decide the slug before building, because the build base path must match:
   propose `<readable-name>-<4 random characters>` unless the user names one.
2. Build the prototype with that slug as the base path, for example
   `npm run build -- --base=/<slug>/` for Vite, or `base: '/<slug>/'` in the
   framework config. Plain HTML with relative asset paths needs no change.
3. Confirm the output directory contains `index.html` at its root.
4. Run:

   ```sh
   python3 <skill-dir>/scripts/prototypes.py --config <private-config> publish <output-dir> --slug <slug> --title "<title>"
   ```

   Add `--source <project-dir>` when the published directory is a build output.
   Use `--dry-run` to validate and see the plan without writing anything, and
   `--update` only to replace a slug that is already published.
5. If the command reports an expired AWS sign-in, sign in to the profile named
   in the private config and retry once.
6. Report the URL and its expiry date exactly as the script printed them.

Other commands: `list` shows every published prototype with its status, and
`unpublish <slug>` removes one from the channel while keeping its archive.

## Rules

- Never publish real customer data, credentials or `.env` files. The script runs
  gitleaks and fails closed; do not bypass, silence or re-run around a finding.
- Never claim a prototype is published unless the script printed its URL.
- Never invent a channel value. If configuration is missing, ask the channel
  owner for the approved private config.
- Keep one slug per prototype; a different slug means a different URL and a new
  30 day expiry.

## Updates

This skill ships with the SCG router, which delivers and refreshes it; see
[automatic updates](references/updates.md). There is no per-plugin updater or
schedule to configure. Respect explicit read-only scope.
