# Plan 156: Targeted CI and test hardening

## Status and scope

Priority P1; TODO. The owner requested a minimal Actions setup on 2026-09-12.
Keep the existing Ubuntu `Test` job as the required PR check for both `main`
and `develop`. Protected branches receive tested PRs; their push runs retain
static checks. Do not duplicate the full suite across three OSes on every
push. This replaces the earlier blanket matrix proposal.

First proof: an installer-changing PR exercises the relevant native platform
paths and real installer Python compatibility, while a router-only PR keeps
the single Ubuntu check. Required-check naming must remain `Test`.

Read current workflows, tests and `docs/compatibility.md` before implementing.
Plan 146 owns ingress behavior; this plan adds coverage only. Release authority
and repository settings belong to plan 144 and are outside this plan.

## Remaining work

1. Add targeted macOS and Windows checks for PRs changing installer code,
   platform backends, shared installer leaves, or their tests. Use native
   platform tests on those runners, with no network or real router home.
   Run these checks for releases as well. Keep ordinary router PRs on Ubuntu.
   Reuse `.github/actions/setup`; do not add a second Python-version pin.
2. Keep one gate named `Test`. If other jobs are added, it must wait for all
   required jobs and fail on their failure or cancellation. Only a deliberately
   unselected platform job may be skipped. Prove the gate fails for a failing
   platform test, not merely that the YAML parses.
3. Run the installer surface under real Python 3.9. Parameterize the existing
   setup composite with a default of 3.14 if a second version is needed.
   Import only the modules the installer loads; explicitly account for runtime
   modules that require 3.14. Do not run the installer or add a skip that hides
   a compatibility failure. Use a short check with no new runtime dependency.
4. Make the source-limits baseline reject nonexistent files, incorrect counts,
   and entries now below their soft cap. Reconcile against current source and
   add one failing-baseline regression check.
5. Add deterministic seeded ingress input-shape coverage for malformed paths,
   authorization, body sizes and encodings. Assert the existing rejection
   contract, without adding a guard owned by plan 146.
6. Add router-level SSE cases for split frames, CRLF, comments, missing data,
   and end-of-stream framing. Reuse existing fixtures and avoid duplicate cases.

## Verification and acceptance

- Required local suite, compile, source limits and policy scans pass.
- Installer-changing PRs execute the selected native checks; unrelated PRs do
  not spend macOS or Windows minutes.
- A failed selected platform or Python 3.9 check makes `Test` fail.
- Native and compatibility failures remain visible; do not weaken assertions
  or add skips to obtain a green result.
- Record measured CI time, platform and client versions. CI success does not
  replace the real client probes required by `AGENTS.md` before publication.
- Update this plan and its row in `plans/README.md` when implemented.

Stop for owner direction if an installer actually needs a newer Python floor,
a platform failure cannot be fixed in this scope, or a generated ingress case
reveals a missing guard. Do not expand this plan into runtime changes.
