# Plan 156: CI and test hardening for a public repository

> **Executor instructions**: Follow this plan step by step. If a STOP condition
> occurs, stop and report. When done, update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 0024a42..HEAD -- .github/workflows/check.yml .github/actions/setup/action.yml tools/check_source_limits.py tools/check_policy_scans.py tests/test_packaging.py tests/test_ingress_guards.py tests/_platform.py config/source-limits-baseline.json`
> Plan 146 owns ingress hardening behaviour: this plan adds coverage and
> runners only and must not add or change a guard. Plan 134 owns the setup
> composite action: reuse it, never bypass it. Reconcile every cited line
> before editing.

## Status and first proof

- Priority P1; effort S-M; risk LOW; confidence HIGH; category ci/quality.
- Depends on nothing. Serialize with plan 146 on
  `tests/test_ingress_guards.py` if 146 is in flight.
- Source: `plans/2026-09-12-architecture-scalability-review.md`, rows
  "CI runs the suite on one OS and only for pull requests", "macOS dialog paths
  never execute in CI", "Python 3.9 compatibility is grammar-only", and "The
  source-limits baseline drifts silently".
- First proof: a push to `develop` runs the full suite on Ubuntu, macOS and
  Windows; a separate short job imports every `packaging/` module under a real
  Python 3.9 and fails on a 3.10+ stdlib call; and
  `tools/check_source_limits.py` fails on a stale baseline entry.

## Why this matters

`.github/workflows/check.yml:32-33` runs the unit suite only when
`github.event_name == 'pull_request'`, so a direct push to `develop` or `main`
never executes a test. The job runs on `ubuntu-latest` (`:23`), so the six
darwin-gated tests (`tests/test_key_prompt.py:341`, `:351`, `:365`;
`tests/test_notice.py:199`, `:213`; `tests/test_notice_delivery.py:214`) never
run anywhere except the owner's Mac, and the Windows backend is exercised only
through Python fakes. The suite takes 137 seconds locally, so a three-OS matrix
is cheap.

Python 3.9 compatibility is asserted by parsing, not running:
`tests/test_packaging.py:219-246` uses `ast.parse(..., feature_version=(3, 9))`
and its own comment says "No 3.9 interpreter exists in CI, so pin the grammar
instead". A 3.10-or-later stdlib call in `packaging/` passes that gate and
breaks on a recipient's machine, which is exactly the population the installer
targets.

`tools/check_source_limits.py:23` reads the baseline only when a file is over
its soft cap, so an entry that no longer matches is never validated. Measured
at `0024a42`: `ai_router/router.py` is recorded as 204 lines and is 207, and
`tests/test_history_portability.py` is recorded at 164 and is now under the
soft cap entirely.

## Scope

**In scope**: the files named in the drift check, plus new tests.
**Out of scope**: any new ingress guard or runtime behaviour (plan 146), the
release workflow (plan 144 owns its environment gate), GitHub repository
settings of any kind, the refresh workflow, and installing anything beyond the
already-pinned CI inputs.

## Steps

1. **Run the suite on every event.** In `.github/workflows/check.yml`, delete
   the `if: github.event_name == 'pull_request'` condition at `:32` so the
   suite runs on pushes to `main` and `develop` as well. Update the comment at
   `:29-31`, which currently explains the opposite policy.

2. **Add the OS matrix.** Turn the `test` job into a matrix over
   `ubuntu-latest`, `macos-latest` and `windows-latest` for the unit suite,
   compile and source-limits steps only. Keep the single-runner steps that
   genuinely need one host on Ubuntu in a second job: the CloudFormation lint
   (`:69-75`), the ruff install (`:57-67`), the shell and PowerShell parse
   gates (`:34-55`), the model registry check (`:76-79`), the catalogue merge
   check (`:80-83`) and the policy scans (`:84-89`). Both jobs reach Python
   through `./.github/actions/setup` (plan 134's single owner). Run the matrix
   `fail-fast: false` so one platform's failure still reports the others.
   A matrix renames the check runs to `Test (ubuntu-latest)` and so on, and
   the `Protect main` ruleset (plan 144, id 23034914) requires a check named
   exactly `Test`: keep a non-matrix gate job named `Test` that `needs` the
   matrix legs so the required name keeps reporting, or hand the owner the
   ruleset update to land in the same change. Never leave `main` waiting on a
   check that no longer reports.

3. **Run the installer half on a real Python 3.9.** Add a third job,
   `installer-py39`, on `ubuntu-latest`, using `actions/setup-python` pinned to
   the same SHA the composite uses but with `python-version: "3.9"`. Because
   the composite pins 3.14, this job needs its own step; add a comment saying
   why it is the one deliberate exception to plan 134's rule.
   `tools/check_policy_scans.py` fails any workflow that carries its own
   `actions/setup-python` pin, so either reach 3.9 through the composite with a
   version input (preferred, no second pin), or add an explicit allowlist in
   `check_setup_single_owner` naming this one job and its pinned SHA, with a
   test proving any other workflow-local pin still fails. A blanket relaxation
   of that scan is a STOP condition. The job runs a
   new `tools/check_installer_py39.py` that imports every module under
   `packaging/` that the installer surface loads, through the same
   `spec_from_file_location` pattern `packaging/service.py:40` uses, and exits
   non-zero on any `ImportError`, `AttributeError` or `SyntaxError`. It must
   not run the installer, touch the filesystem outside a temp directory, or
   make a network call.

4. **Cover the modules the 3.9 job cannot import.** Some `packaging/` modules
   import `ai_router` leaves at load time. For those, the new script imports
   the leaf directly (`ai_router/provider_defs.py` and
   `ai_router/atomic_write.py` are both documented as 3.9-parseable) and
   records the rest in an explicit skip list with a one-line reason each. A
   module that is neither imported nor listed fails the script, so the list
   cannot rot silently.

5. **Make the source-limits baseline self-checking.** In
   `tools/check_source_limits.py`, after the existing walk, validate the
   baseline itself: every key must name an existing file, its recorded count
   must equal the current count, and the file must still exceed its area's soft
   cap. Report each stale entry on its own line and count it as a failure. Fix
   the two entries this review measured as part of the same change.

6. **Add ingress input-shape coverage.** Add to `tests/test_ingress_guards.py`
   a deterministic, seeded generator over `ai_router/ingress.py`'s
   `authorized_path` and `read_body`: random byte sequences in the path
   segment (including bytes 0x80 to 0xFF, which plan 136 fixed), random
   `Authorization` values, absent and negative and oversized
   `Content-Length`, an unexpected `Transfer-Encoding`, and malformed zstd
   bodies. Assert the invariant only: every input returns a response or raises
   `InvalidSize`, never an unhandled exception, and an unauthenticated input
   always yields the uniform 403. Use a fixed seed and print it on failure.
   This adds no guard; it proves the guards plans 136 and 146 own.

7. **Add SSE edge coverage.** Add to `tests/test_stream_containment.py` cases
   for a frame split across reads, a `data:` line with no trailing blank line
   at end of stream (already `ValueError` at `ai_router/sse.py:24-25`, so pin
   it), CRLF framing, a comment-only frame, an `event:` line with no `data:`,
   and a zero-length frame. Assert the router's downstream behaviour, not just
   `sse.blocks`.

## Verification

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_ingress_guards tests.test_stream_containment tests.test_packaging` | pass |
| Installer 3.9 gate | `python3.9 tools/check_installer_py39.py` if a 3.9 interpreter is available locally, otherwise rely on the CI job | exit 0 |
| Limits self-check | `python3.14 tools/check_source_limits.py` | `failures=0` after the two stale entries are fixed |
| Stale-entry proof | temporarily edit one baseline count, re-run the limits check, restore it | the check fails and names the entry |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Policy scans | `python3.14 tools/check_policy_scans.py` | exit 0 |
| Workflow parse | `python3.14 -c "import json,sys;print('yaml parse is a CI concern')"` and push the branch to let the Check workflow run | all matrix legs green |

## STOP conditions

- The suite does not pass on macOS or Windows: stop and report the failures
  with their platform. Do not add a skip to make a runner green; a real
  platform failure is the finding this plan exists to surface.
- The 3.9 job fails on a module the installer genuinely needs: stop and report
  the module and the 3.10-or-later API it uses. Whether to fix the call or
  raise the installer floor is an owner decision.
- The matrix would exceed the owner's accepted CI minutes: stop and report the
  measured duration per leg; running the matrix on push only is the fallback.
- A generated ingress input reveals an unhandled exception: stop and report it
  rather than fixing it here. The fix belongs to plan 146.
- The 3.9 job cannot pass `tools/check_policy_scans.py` without loosening the
  single-owner rule for every workflow: stop and report; the allowlist form
  above is the only accepted exception.

## Acceptance checklist

- [ ] The unit suite runs on push and pull request, on Ubuntu, macOS and
      Windows, with `fail-fast: false`.
- [ ] Single-host checks still run exactly once, on Ubuntu, through the setup
      composite.
- [ ] A real Python 3.9 job imports the installer surface and fails on a
      3.10-or-later call, with an explicit and non-rotting skip list.
- [ ] `tools/check_source_limits.py` fails on a stale baseline entry, and the
      two current stale entries are corrected.
- [ ] Seeded ingress input coverage asserts the no-unhandled-exception and
      uniform-403 invariants without adding a guard.
- [ ] SSE edge cases are covered at the router level.
- [ ] Full suite, compile and policy scans pass; `plans/README.md` row updated.

## Maintenance notes

- `.github/workflows/check.yml` already records the single-runner cost decision
  in a comment (`:18-22`). Replace that comment with the new one rather than
  leaving both.
- If the owner later raises the installer floor above 3.9, the `installer-py39`
  job and its skip list are deleted together with the grammar gate at
  `tests/test_packaging.py:219-246`.
