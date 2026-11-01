# Router CI: lower runner time

The two-worker layout recorded **9.4%** lower median
aggregate job execution and **29.7%** lower median workflow elapsed.
The comparison used three successful runs per arm with the same source and tests.

This extends the [earlier job-graph benchmark](worked-example.md).
That cohort used different source and tests. Its percentages must remain separate.

## Frozen comparison

Both arms checked out `88a01c658fcbb75b16e4a85c6e529fb89aeaffac`, tree `127f9171c0f99e156391dc78fc4f92fd366e6b12`.
The [diagnostic workflow](https://github.com/software-combined/SC_AI_Router-archive/blob/e77d02ebbfacaee9a14f58478bc8fd1549ad4fde/.github/workflows/router-ci-worker-benchmark.yml) used immutable harness
`e77d02ebbfacaee9a14f58478bc8fd1549ad4fde` for every run.
Branch prefixes selected one or two unit workers. The inspected application,
tests, tools, dependencies and canonical CI definition stayed identical.

Both arms retained the parallel job graph, all 15 jobs, five desktop targets,
the full installer scope and the existing 15-minute unit-job budget.
Python was pinned to 3.14.9, with 3.9.25 for installer compatibility.
Actual Python builds, platform, architecture, logical CPU counts, compiler
identities and installed-package versions matched within each job role.
The macOS certificate package was pinned to 2026.10.23 in both arms.
Before tests, both verified the effective default certificate bundle.
OpenSSL versions, bundle hashes and loaded certificate-set hashes matched.
Hosted image build identifiers varied; the record lists them per sample.
Each arm included the same result observer, environment capture and artifact uploads.
No project dependency cache or artificial prewarming was added.
The separate diagnostic check could not satisfy release acceptance.

The unit runner splits canonical discovery once at a module boundary.
Each process keeps its contiguous case order and fixtures. Duplicate test
occurrences remain present. Failed workers, cancellation, missing reports and
unexplained absent cases fail the job. Legitimate fixture skips are accounted
for separately from cases that started.

## Measurements

Runs followed the declared order: control, candidate, candidate, control, control, candidate.
They ran sequentially on 24 October 2026 AEDT. Every run succeeded on its first attempt.
The last candidate received five macOS installer CPUs instead of the required three.
That [successful run](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/40046083962) was excluded before its timing totals were inspected.
Independent review confirmed that the declared infrastructure allowance permitted
one complete replacement with the same frozen source, harness, labels and inputs.
The replacement satisfied every original eligibility rule and occupies candidate-3's
paired slot. All seven attempts remain recorded; exactly six enter the results.
No second replacement or relaxed predicate was allowed.

An earlier control/candidate pair was excluded before this cohort started.
It had different macOS certificate packages without effective bundle hashes.
The [control](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/40032698483) and
[candidate](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/40033866987) remain linked in the record.
Both passed the same tests. Their timings do not enter these results.

A second cohort stopped after its fourth run failed an unchanged Windows
lifecycle fixture. The production recovery timer could restart the disposable
task during a stopped-state assertion. That failure was not an infrastructure
replacement. All four attempts remain linked in the machine-readable record.
The fixture now starts only on demand; every original assertion remains.
Production scheduling and companion native migration/XML contracts are unchanged.
A [separate real-Windows proof](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/40041814923) compared both fixtures across a real timer interval.
The original reproduced the failure; the corrected fixture passed and both
verified cleanup. That proof used a 65-second idle window and 180-second
children in both variants. The benchmark retains the original 40-second
children. Both final arms use this same correction. No samples from
the interrupted cohort enter these results.

| Sample | Workflow elapsed | Aggregate job execution | Offline suite step |
| --- | ---: | ---: | ---: |
| [control-1](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/40042296437) | 9m 22s | 29m 09s | 8m 25s |
| [candidate-1](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/40043179669) | 6m 08s | 24m 12s | 5m 05s |
| [candidate-2](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/40043756582) | 6m 50s | 23m 50s | 5m 06s |
| [control-2](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/40044371490) | 9m 22s | 25m 33s | 8m 30s |
| [control-3](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/40045200166) | 9m 40s | 26m 20s | 8m 40s |
| [candidate-3-replacement-1](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/40047211909) | 6m 35s | 23m 52s | 4m 52s |

| Measure | One-worker median | Two-worker median | Reduction | One-worker range | Two-worker range |
| --- | ---: | ---: | ---: | ---: | ---: |
| Workflow elapsed | 9m 22s | 6m 35s | 29.7% | 9m 22s–9m 40s | 6m 08s–6m 50s |
| Aggregate job execution | 26m 20s | 23m 52s | 9.4% | 25m 33s–29m 09s | 23m 50s–24m 12s |

Across three runs, aggregate execution totalled
**81m 02s** for control and
**71m 54s** for candidate.
All three paired aggregate differences improved.

The offline unit step median changed from
**8m 30s** to
**5m 05s**.
The complete unit job median changed from
**8m 43s** to
**5m 23s**.
The sum of all other job durations had medians of
**17m 26s** and
**18m 45s** respectively.
Aggregate differences include this other-job and setup variation. They do not
attribute every saved second to worker concurrency. Component medians need
not add to the median total.

Elapsed time runs from workflow creation through the last relevant job completion.
It includes queues, dependency waiting, setup and cleanup.
Aggregate execution sums job start-to-completion durations and excludes queues.
Both measures include diagnostic overhead. Runner duration is allocated wall
time; it does not measure CPU use or establish a billing saving.

## Same verification workload

Every full suite reported **3625 cases and 25 skips**.
Both arms included the same eight new runner regressions.
Discovery retained 3625 occurrences and 3614 unique identifiers.
The sorted inventory fingerprint was identical in all six runs:
`3e58ee0d1312f8467d3f64353f81a55b175f408e7059e1fbaea55d6bdc14eb1f`.
The observed case-outcome fingerprint was also identical:
`3c32bc318ff603dc37b006b17a1c4cc040e21accf0025f0078b21f6be5816a09`.

Actual case IDs, duplicate multiplicities, outcomes and skip reasons matched
within every instrumented phase and platform. Each worker retained its
contiguous discovery order; the combined report matched the control's case
sequence. This is execution evidence,
in addition to discovery. Fixture skips remain distinct from started cases.
Successful subtest display fingerprints varied in some phases. Their callback counts matched, as did all parent-case outcomes and skip identities. The record preserves each fingerprint; it does not claim identical textual parameter displays.

| Phase and platform | Discovered occurrences | Started cases | Reported skips |
| --- | ---: | ---: | ---: |
| Full offline suite (Ubuntu) | 3625 | 3625 | 25 |
| Hook adapter (Linux) | 35 | 35 | 2 |
| Hook adapter (Windows) | 35 | 35 | 5 |
| Linux Router recovery | 1 | 1 | 0 |
| Plugin scheduler (Linux) | 2 | 2 | 0 |
| Plugin scheduler (Windows) | 2 | 2 | 1 |
| Windows ACL contract | 1 | 1 | 0 |
| Windows installer | 874 | 874 | 174 |
| Windows packaging contracts | 31 | 31 | 2 |
| macOS installer | 1031 | 1031 | 10 |

The desktop matrix retained macOS ARM64 and x86_64, Windows x86_64,
and Linux ARM64 and x86_64. Native build/test commands and observed Rust test
identities matched. Python 3.9 imports, shell and PowerShell parsing,
compilation, lint, model, catalogue and policy checks also passed in every run.
No configured verification workload was removed. This does not measure line
or branch coverage.

## Evidence and limits

[The machine-readable record](router-worker-benchmark.json) contains every run,
job timestamp, runner-class total, execution fingerprint, skip record and
resolved environment. It also retains artifact identifiers and digests.
Raw reports are available in run artifacts for their 30-day retention period.

The sampling rule was declared before measurement: lower median aggregate
execution, improvement in all three paired aggregate comparisons, no increase
in median elapsed, and matching verification evidence and relevant environments.
All conditions passed. Hosted image builds, load and tool-cache conditions remain uncontrolled.
Three samples per arm describe this cohort; they do not establish typical
latency or long-term reliability.

The reusable lesson is to measure worker counts within an existing runner
when tests support safe isolation. Preserve fixture semantics and observed
test outcomes before accepting shorter duration.

The faster feedback and lower runner time were useful, but proving the modest
runner saving took substantial effort. This benchmark's harness and repeated
cohorts are not a default proof requirement for other repositories.
Estimate the likely benefit first and expand measurement only when uncertainty
could change the decision. Required tests, checks and reviews still apply.
