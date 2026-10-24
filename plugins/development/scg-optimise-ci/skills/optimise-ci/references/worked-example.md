# Router CI benchmark

SC AI Router starts its full offline suite alongside independent native checks.
The earlier layout waited for those checks before starting the suite.
The required `Test` gate still waits for every applicable result.
The graph change shipped in [PR 488](https://github.com/software-combined/SC_AI_Router/pull/488)
and reached `main` through [PR 494](https://github.com/software-combined/SC_AI_Router/pull/494).

This controlled comparison measures both layouts against identical source and tests.
It replaces the earlier comparison between different source revisions.
Median elapsed time fell **38.3%** across three successful samples per layout.
Median aggregate job execution changed **+2.4%**. This does not establish compute savings.

The [worker-count follow-up](runner-time-benchmark.md) measures lower runner time
within the parallel graph. It uses a different frozen workload; do not combine
the two cohorts' percentages.

## Controlled workload

Every executed job checked out commit `bc2920a6688cceb9eed3caf40847fef4dc031f39`,
tree `2b6076c122282b315b3ef724bcf0cc673745589a`.
The [diagnostic harness](https://github.com/software-combined/SC_AI_Router/blob/a79f21a92a32f6eaed49ed79cc8ea825017fc930/.github/workflows/router-ci-benchmark.yml)
used one commit for both layouts: `a79f21a92a32f6eaed49ed79cc8ea825017fc930`.
Its branch name selected serial or parallel scheduling.
The checked-out application, tests, tools, dependencies and CI definitions stayed identical.
Keeping the inspected workflow unchanged also kept its regression tests identical.

Both layouts used CPython 3.14.8, serial unittest execution,
`SCG_RUN_INSTALLER_TESTS=1` and `python -m unittest discover -s tests -t .`.
The compatibility job used CPython 3.9.25.
Installer scope was forced on in both layouts, retaining every native acceptance job.
Matrices, verification commands, action revisions and permissions matched.
Native job budgets stayed unchanged. The parallel suite had its own 15-minute budget.
The diagnostic workflow used a separate check name and could not satisfy release acceptance.

## Measurements

All runs completed on 23 October 2026, on their first attempt.
The declared order was serial, parallel, parallel, serial, serial, parallel.
Runs were sequential. No primary run failed or needed replacement.

| Sample | Workflow elapsed | Aggregate job execution | Offline suite step |
| --- | ---: | ---: | ---: |
| [serial-1](https://github.com/software-combined/SC_AI_Router/actions/runs/39931873584) | 14m 17s | 29m 09s | 8m 09s |
| [parallel-1](https://github.com/software-combined/SC_AI_Router/actions/runs/39933647660) | 8m 10s | 28m 58s | 7m 31s |
| [parallel-2](https://github.com/software-combined/SC_AI_Router/actions/runs/39934670492) | 8m 50s | 28m 11s | 8m 09s |
| [serial-2](https://github.com/software-combined/SC_AI_Router/actions/runs/39935769534) | 13m 40s | 28m 09s | 7m 44s |
| [serial-3](https://github.com/software-combined/SC_AI_Router/actions/runs/39937474035) | 13m 45s | 27m 14s | 8m 05s |
| [parallel-3](https://github.com/software-combined/SC_AI_Router/actions/runs/39939149481) | 8m 29s | 28m 50s | 7m 41s |

| Measure | Serial median | Parallel median | Serial range | Parallel range |
| --- | ---: | ---: | ---: | ---: |
| Workflow elapsed | 13m 45s | 8m 29s | 13m 40s–14m 17s | 8m 10s–8m 50s |
| Aggregate job execution | 28m 09s | 28m 50s | 27m 14s–29m 09s | 28m 11s–28m 58s |
| Offline suite step | 8m 05s | 7m 41s | 7m 44s–8m 09s | 7m 31s–8m 09s |

Workflow elapsed runs from workflow creation through the last executed job's completion.
It includes queues, dependency waiting, setup and cleanup.
Aggregate job execution sums each executed job's start-to-completion duration.
It excludes queues and does not weight runner classes or billing rates.
The extra Ubuntu job adds setup while allowing the suite and native checks to overlap.
Unit-step durations varied while the unit code and command stayed fixed.

## Verification coverage

Every full suite reported **3492 tests and 21 skips**.
Post-run discovery found 3492 entries with 3481 unique test identifiers in each run.
The sorted identifiers, retaining duplicates, had the same SHA-256 digest in all six runs:
`ff65d6d1d606551ab406d5b774c5e9ee8ba874ba79e5440380348aadce760554`.
Inventory collection ran after the suite, avoiding pre-test import warming.
This discovery hash is not an execution trace and does not identify the skipped cases.

Native selections and reported test/skip totals also matched:

| Check | Reported tests | Skips |
| --- | ---: | ---: |
| macOS installer, 92 selected modules | 905 | 6 |
| Windows installer, 74 selected modules | 748 | 174 |
| Windows packaging contracts | 31 | 2 |
| Windows ACL contract | 1 | 0 |
| Linux plugin scheduler | 2 | 0 |
| Windows plugin scheduler | 2 | 1 |
| Linux Router recovery | 1 | 0 |
| Linux hook adapter | 35 | 2 |
| Windows hook adapter | 35 | 5 |

Desktop menu builds retained macOS ARM64 and x86_64, Windows x86_64,
and Linux ARM64 and x86_64.

Python 3.9 imports, shell and PowerShell parsing, compilation, lint, registry,
catalogue and policy checks also passed in every run.
Serial runs completed 14 jobs; parallel runs completed 15.
No configured verification workload was removed. These records establish matching discovery,
reported test/skip totals, selections and platform checks. They do not establish identical
skipped-test identities or measure line or branch coverage.

## Limits and retained evidence

[The benchmark record](router-benchmark.json) contains run links, exact revisions,
test and module digests, platform execution totals, setup costs and observed toolchains.
All diagnostic instrumentation and setup costs remain included in both layouts.
No project dependency cache was added. Hosted runtime downloads and tool-cache state varied.
Hosted images and machine load were not controlled. The record lists all observed image variants.
Actual Python versions and recorded desktop menu compiler identities matched across the primary cohort.
This is a descriptive six-run result, not a guarantee of typical latency, billing savings or reliability.

Three preliminary runs used floating Python selectors.
They resolved to different patch versions and were excluded as a separate cohort.
Their run identifiers, measurements and exclusion reason remain in the benchmark record.
The primary cohort pinned all runtime setup calls before its first run.
No sample was rerun to improve its result.

Failure and event wiring were checked in source and workflow tests.
The diagnostic harness also rejected missing, failed, cancelled and unexpected prerequisites in local guard checks.
Remote failure injection was not performed; these measurements exercised successful full acceptance workloads.

The portable lesson is to measure the dependency graph before narrowing verification.
Freeze source and test inputs, inspect actual runtimes, retain every attempt and report elapsed time separately from runner use.
Another repository must derive its own commands, dependencies, platform requirements and release gates.
