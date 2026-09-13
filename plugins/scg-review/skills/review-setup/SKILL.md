---
name: review-setup
description: Check or explicitly provision the local dependencies for SCG pre-commit review, including its Git hooks and owner-approved Gitleaks pin. Use before the first review or when its setup check fails.
---

# Review setup

Resolve the plugin root from this skill's location. Read the repository README
when working from source, and the bundled [setup guide](../../references/setup.md)
in either source or installed form.

Run `python3 <plugin-root>/scripts/setup.py check --repo <absolute-repo-path>`.
This is read-only. Report local prerequisites separately from provider access,
actual review completion, and client update delivery.

If installation is requested, inspect the target repo and its effective
`core.hooksPath` first. The explicit install command in the setup guide adds
the shared adapter and sets `core.hooksPath` for that repository only. It
requires a reviewed scanner configuration and refuses to replace existing
hook files or configuration. Do not remove, overwrite or repin existing
configuration to make it pass. Preserve user-managed hooks and resolve an
incompatibility with the owner.

Read the bundled reviewer model policy and any applicable host/project policy.
Report missing provider/model access; do not install credentials, modify
provider settings, or bypass exact model requirements during setup. Actual review
calls may use the bundled policy's eligible availability fallbacks.

If host instructions hard-code an older standalone skill path, explain that
they still select that copy. Migrate only the relevant references when
authorised, preserving the user's other instructions. Do not delete personal
skills or automatically rewrite AGENTS.md during plugin installation.

When installing, pulling or updating this plugin for use, complete the bundled
[updater guide](../../references/updates.md): configure the native schedule,
run the shared updater and verify schedule status and installed versions.
Automatic updates are part of installation on macOS, Linux and Windows, not an
optional follow-up. Respect explicit read-only scope; preserve custom schedules
and report a setup blocker rather than claiming that a pull enabled updates.
The shared updater refreshes all installed, enabled SCG plugins without changing
hooks or pins. An already verified working schedule does not need reinstalling
for every ordinary review.
