# Codex routing incident, 2026-09-13

## Root cause

At 09:16:21 Australia/Sydney, an unreleased installer-Python compatibility
checker imported `tools/disable.py` while checking the installer surface.
The remover executed its module body: it removed the managed routing block
from Codex's configuration and unloaded the router service. The original
Codex task's command output confirms the removal. A scratch reproduction
against `develop` reproduces both effects without changing the live machine.

The OpenCode recovery task restarted the service at 09:37 but left the
Codex configuration detached. The service was healthy on 0.6.43.57 when
this investigation began, while both `openai_base_url` and
`model_catalog_json` were absent from Codex's configuration. The 09:10
installer backup contains both settings. A new DeepSeek task at 10:55
therefore reached ChatGPT directly and failed before doing any work.
Existing processes can retain the old picker, so seeing a model in the
picker does not establish that new tasks use the router.

This was a local development check with a destructive import side effect,
not evidence of an OpenRouter outage or a changed DeepSeek entitlement.

## Bounded delivery plan

1. Reuse the import-safety fix from commit `8742d1f`: guard the remover's
   entry point, separate compile-only scripts from imported library files,
   and run imports in a child with scratch home directories and command shims.
2. Demonstrate the old failure in a temporary fixture, then run the regression
   tests, the Python 3.9 compatibility check and all required repository checks.
3. Review and merge the focused fix into `develop`, then publish beta 0.6.45.
   Version 0.6.44 is left to the concurrent CI work; that work is outside this fix.
4. Run the published installer's normal install path on the existing router
   home. Unlike an up-to-date version check, this reattaches the missing Codex
   block using the existing state and receipt, preserving unrelated settings.
5. Read back the installed version, service health and effective Codex settings.
   Run one bounded real Codex tool round trip on DeepSeek and one on the
   subscription route, without overriding the routing settings in the probe.

The installer owns activation in `packaging/codex_config.py`; the remover is
the matching explicit detach entry point. No request routing or provider
credential contract changes. Command shims and scratch directories protect
this known check path; they are not a sandbox for arbitrary untrusted code.

## Verification boundaries

The regression fixture reproduced configuration removal and a service-stop
attempt before the fix. The targeted 27-test suite passed with the fix.
Codex is `0.154.0-alpha.6.2` and Claude Code is `2.1.223`, unchanged from
the four-route compatibility evidence already recorded in `docs/compatibility.md`.
Release, local installation and live recovery remain separate acceptance gates;
the release task reports their results after deployment.
