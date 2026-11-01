# Windows standard-user CI comparison

The split reduced median complete-pipeline time by **31.5%**, from **16m 08s**
to **11m 03.5s**, across two successful samples per layout. Both paired
candidates finished sooner, and their executed Windows verification matched.
Median aggregate job execution increased **6.7%**. This cohort passes the
declared 20% elapsed-time gate; it does not establish typical savings.

## Frozen workload

Every sample uses source and harness commit
`54b4dabd9855e02ce9c05a70b2569cb944772413`, tree
`80b830a4d9dc8629f6a535d3a782e644941db97f`.
The control runs core followed by native under one disposable Windows account.
The candidate runs each suite on a separate runner and disposable account.
Both layouts retain every other acceptance command and all five desktop targets.
Installer scope is forced on; the offline suite always takes full discovery.
The separate diagnostic check cannot satisfy protected `Test` acceptance.

The declared order is control, candidate, candidate, control, with at most four
full runs and no replacement allowance. All four runs finished on their first
attempt; none was excluded or replaced. Runs were sequential. All 66 executed
jobs checked out the frozen revision. Python is pinned to 3.14.9,
with 3.9.25 for installer compatibility. Windows runtime, architecture, logical
CPU counts and OpenSSL reports matched across the four samples.

## Measurements

| Sample | Complete workflow | Aggregate job execution |
| --- | ---: | ---: |
| [Control 1](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/40794286782) | 13m 36s | 39m 41s |
| [Candidate 1](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/40795816439) | 11m 09s | 44m 06s |
| [Candidate 2](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/40797047472) | 10m 58s | 45m 15s |
| [Control 2](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/40798267153) | 18m 40s | 44m 05s |

The first pair reduced workflow elapsed by 18.0%; the second reduced it by 41.3%.
Control elapsed ranged from 13m 36s to 18m 40s; candidate elapsed ranged from
10m 58s to 11m 09s. Median aggregate job execution changed from 41m 53s to
44m 40.5s. Native-suite duration varied substantially, so neither the median
nor a single pair guarantees the result of a future run.

Elapsed time starts at workflow creation and ends at the last relevant job
completion, including queue, setup, reports and cleanup. Aggregate execution
sums each job's start-to-completion time. It excludes queues and does not weight
runner classes or establish billing savings. The split adds a Windows runner.

## Equivalent Windows verification

All four samples executed 2,660 core occurrences with 211 skips, plus 17 native
cases with no skips. The observed verification fingerprints match across all
four samples. They retain case identities, order, duplicate multiplicity,
outcomes, hashed skip reasons and fixture-skip records. Subtest parameter displays
are removed to avoid retaining temporary paths; parent identities and callback
outcomes remain. These observations do not measure line or branch coverage.

The [machine-readable record](https://github.com/software-combined/SC_AI/blob/development/docs/windows-ci-benchmark.json) retains source identity,
run links, timings, per-phase fingerprints, job durations and runner metadata.
Raw diagnostic reports have seven-day artifact retention. Hosted image versions
and machine load vary. Those conditions and unrelated-job variation prevent
attributing the entire aggregate difference to the Windows layout.

The native Windows safety proof passed 11 tests with no skips. Synthetic failures
in either matrix entry failed the diagnostic gate. Cancelling the waiting run
cancelled its gate. These short probes are recorded separately from the four
full performance samples. No router version, tag or runtime release is involved.
