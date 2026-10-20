---
name: manage-router
description: >
  Set up, check, repair, update or remove SCG Router when the user requests it.
  Open the permanent SCG Router app, or guide the user through the approved
  staff download page. Never changes client settings or handles model keys.
---

# Manage Router

The router is one local service per operating-system user. This plugin is an
optional shortcut to the same installer staff use. It does not own installation
files, provider keys, subscription sign-in or assistant configuration.

## Setup or maintenance

1. Use the user's requested assistant and installation target. Ask only for a
   missing choice that changes the action. An explicit setup request supplies
   authority; do not add another generic approval question.
2. If the permanent **SCG Router** app is installed, open it through the active
   runtime's available application tools. The app offers setup, repair, status,
   another assistant, key replacement, download sign-in and removal.
3. Otherwise direct the user to the approved staff route at
   `https://hub.softwarecombined.com/router`. If private publication is still
   pending, ask the maintainer for the existing setup script. Never substitute
   an unverified package or a plugin-cache install.
4. Let the user enter the IT-issued personal key in the secure window.
   Never ask for the key, subscription credentials or a setup URL in chat.
5. Keep unfinished setup pending until a fresh assistant session produces a
   routed reply and its enabled SC tools work. Installation health alone does
   not prove this. Never restart an assistant without the user's explicit action.

The new packages are unsigned. A device can block them under company policy.
Contact IT when that happens. Never disable a device control to finish setup.

## Diagnostics

Use the installed release's `docs/troubleshooting.md` and the canonical installer
for authorised technical checks. Native installations keep their own Python.
The source entry point is `packaging/install.py`; use its retained installed copy.
The current serving release is selected by `<home>/current`; update control is
selected independently by `<home>/control-version`. Do not change either by hand.

`install.py --status --json --home <home>` and `--doctor` provide redacted checks.
Use the retained interpreter and installer, not system Python or this plugin's
cache path. Send IT only the redacted status. Never print tokens, keys, setup
URLs, download cookies or raw configuration bodies.

Reopening setup preserves the existing release channel, key, instructions,
company policy and disabled plugins. Attaching another assistant is additive.
Native subscription sign-in stays with its original client. A missing or
expired download sign-in keeps the router and last good model list available.
