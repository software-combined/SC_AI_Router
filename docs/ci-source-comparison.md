# Complete CI source and layout comparison

The shortcut absence fix and Windows job partitioning reduced complete
continuous integration (CI) elapsed time by **271 seconds (40.45%)** in one eligible pair.
The conservative model retained **257.00 seconds (39.00%)** of improvement.
Both passed the declared thresholds, including the limit on added runner allocation.
This supports promoting the combined change. Final-candidate production acceptance
and integration remain separate gates.

The [qualifying run](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/41194918049)
completed on 31 October 2026 AEDT. All 37 allocated jobs passed.
Five expected layout branches were skipped without runners or executed steps;
they were not missing verification. Both independent paths retained every required check.

| Complete-path measure | Before | After | Change |
| --- | ---: | ---: | ---: |
| Actual elapsed | 670 s | 399 s | 271 s lower (40.45%) |
| Modelled elapsed | 658.998 s | 402 s | 256.998 s lower (39.00%) |
| Actual allocated runner time | 2,518 s | 2,554 s | 36 s higher (1.43%) |
| Modelled allocated runner time | 2,433.998 s | 2,638.002 s | 204.003 s higher (8.38%) |

Elapsed starts at the shared workflow creation, 21:58:43 AEDT.
The after static gate completed at 22:05:22 AEDT; before completed at 22:09:53 AEDT.
The experiment allocated 5,072 runner-seconds across 37 jobs and lasted 670 seconds.
These concurrent paths can share provider capacity and contention.
Allocation measures occupied runner wall time, not CPU use or billing.
One pair does not establish typical speed, reliability or separate component effects.

## Earlier results and retained attempts

The previous [source-only pair](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/41184590089)
passed all 34 allocations and its declared input and execution checks.
Its after source was `905bd5d60bc22e48ec5dbd2d59af7fd52cc0dade`.
It improved elapsed time, but missed both the 90-second and 20% thresholds:

| Measure | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| Observed complete elapsed | 556 s | 475 s | 81 s (14.57%) |
| Conservative elapsed | 542.88 s | 480.12 s | 62.76 s (11.56%) |
| Observed allocated runner time | 2,411 s | 2,409 s | 2 s (0.08%) |

The after core and native jobs took 438 and 435 seconds. Both held up acceptance;
the macOS installer took 348 seconds. These measurements motivated partitioning
both Windows roles. They did not prove the new layout was faster.
Keep that valid below-threshold result. All earlier failed cohorts remain
failed, with their totals unopened.

The [first partitioned pair](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/41190256996)
passed all 37 allocations and workload checks. It failed eligibility because
the candidate native-runtime image and loaded certificates differed from control.
Its [permitted replacement](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/41191265012)
failed environment capture in `After / Desktop menu (darwin/x86_64)`.
After cold Python setup, the Swift version command exceeded its 15-second limit;
the compile step did not run. Both runs' comparison totals remain unopened.
The instrumentation correction below started a new source/controller cohort.
Its [initial pair](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/41193931156)
passed all 37 allocations but failed strict image and loaded-certificate checks
for candidate core-first, native-runtime and native-shortcuts.
Its totals remain unopened. The one allowed replacement was run `41194918049`;
its sources, controller and declared analysis remained identical, and it qualified.

Earlier work used different protocols or isolated safety probes.
It does not contribute samples to this result:

| Attempts | Recorded outcome |
| --- | --- |
| Sequential [control 41162085687](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/41162085687) and [candidate 41162971063](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/41162971063) | Both passed functional checks. Three unchanged Windows roles had different PowerShell versions and loaded certificates, violating that cohort's stricter policy. Rejected; totals unopened. |
| Shared pair [41169081010](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/41169081010) | All 21 jobs passed. Native-shortcuts used PowerShell 7.6.7 and 417 loaded certificates; peers used 7.6.9 and 414. Rejected; totals unopened. |
| Outer-launcher probe [41173656798](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/41173656798) | Windows PowerShell 5.1 startup failed before evidence. This was not a benchmark sample. |
| Pinned-launcher probe [41175735438](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/41175735438) | PowerShell 7.6.9 passed 14 launcher tests with zero skips. This was safety evidence only. |
| Shared pair [41176025819](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/41176025819) | Control passed. Candidate shortcut reads timed out at 30 seconds with every shortcut absent. Candidate gates failed correctly: 18 successful jobs and three failures. Totals unopened. |
| Corrected-source probe [41180734298](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/41180734298) | Fourteen launcher tests passed. Fixture shortcut creation exceeded its new 30-second bound; the original fixture was unbounded. No complete-comparison result. |
| Cold-fixture probe [41184223164](https://github.com/software-combined/SC_AI_Router-archive/actions/runs/41184223164) | The fixture's 60-second bound passed 12 tests with zero skips. This was safety evidence only. |

The [shared-work protocol](ci-partition-experiment.md) remains historical.
The [failed offline fixture comparison](../plugins/development/scg-optimise-ci/skills/optimise-ci/references/offline-fixture-benchmark.md)
also remains failed. Its focused saving is not a complete-CI result.

## Sources and required work

The before source is `b815fe5262168f536f06f627714112a5bfbe6ab0`, tree
`132aa998f6b407c2ea6246cad6ce93dd766628f3`. The after source and controller are
`7e07ff2bea9c9a2c163d75589f2e2a110afbb094`, tree
`db4fe0b929ef8f70bc5625c9bb2ac86b12f0a9fc`.
Both trees, the harness and complete diff were frozen before dispatch.
The last correction added bounded macOS preparation, its workflow contract
and a separate cohort trigger. It retained core selections, diagnostic layout
routing and the reviewed shortcut fix. This CI-only correction did not change
the Router version.

The caller invokes the same reusable diagnostic definition twice:

| Path | Layout | Windows core | Windows native | Allocations |
| --- | --- | --- | --- | ---: |
| Before | `combined` | `core` | `native` | 17 |
| After | `partitioned` | `core-first`, `core-second` | `native-runtime`, `native-shortcuts` | 20 |

Both paths independently run scope, three installers, full offline verification,
five desktop targets, both scheduler targets, both hook targets and final
acceptance with every static check. After also requires the native aggregate.
Only the selected path's final gate and native jobs apply to each call.
Every applicable allocation must succeed. Failed, cancelled, skipped, missing
or unexpected prerequisites fail the gate. No results are shared between calls.
The legacy `windows-ci-bench-*` experiment keeps its original default layout.

Both paths retain suite order, real native assertions, standard accounts,
cleanup, installer opt-in, two offline workers and existing job timeouts.
Each Windows partition has a separate runner and disposable standard account.
Core partitions reuse the existing unittest module boundary split. They retain
full discovery in both reports and record each partition's selected occurrences.
Require equal full inventories and ordered `first.selected + second.selected`
equal to full discovery, including duplicates. Each selected occurrence must
execute or have an exact declared fixture skip. Native groups permit no skips.
Unittest invocations without reports use the existing single-worker observer
with the exact original arguments. Compare each invocation separately, including
duplicate cases, outcomes, subtest callbacks and fixture suppression.
Retain complete reports, failed reports and cache-state logs.

Shortcut creation emits fixed phase markers before each native operation.
A timeout reports only the last recognised marker, or `script-entry-unobserved`.
Markers distinguish script entry, object creation, property assignments and saving.
Fixture construction has a 60-second limit; the original source had no limit.
Production shortcut operations retain their 30-second limits.
The markers do not establish an underlying timeout cause.

The frozen source comparison declared 21 added test identifiers from parsed
Python source before dispatch. They include six shortcut regressions, two
shortcut diagnostic contracts, core partition tests and workflow contracts.
Every original invocation retained its arguments, ordered cases, duplicate
occurrences, outcomes, callback counts, skip reasons and fixture suppression.
New test loops use new methods so existing callback multiplicity stays unchanged.
The original 17 native cases remain an ordered subset of 23, all executed with zero skips.

| Observed invocation | Before cases | After cases | Added |
| --- | ---: | ---: | ---: |
| Full offline verification | 3,805 | 3,826 | 21 |
| Windows core, combined partitions | 2,672 | 2,685 | 13 |
| Windows native, combined partitions | 17 | 23 | 6 |
| macOS installer | 1,103 | 1,111 | 8 |
| Windows installer | 946 | 954 | 8 |

Eight other logical invocations retained their counts and observed outcomes:
both hook adapters (35 each), Windows packaging (31), launcher failure cleanup (2),
Windows access control (1), both schedulers (3 each) and Linux recovery (1).
The frozen policy allowed three added Windows-core capability skips with exact
reasons, and required those cases to pass in Linux offline verification.
Optional shortcut-script skips required a recorded non-Windows environment
without PowerShell. No unexplained missing execution or fixture suppression was accepted.
These records establish executed work and outcomes, not line or branch coverage.

## Inputs and acceptance authority

Both calls use Python 3.14.9, with 3.9.25 for its installer surface, and the
existing action, dependency and Rust pins. Every Windows verification role
uses the hash-verified PowerShell 7.6.9 archive. A post-selection assertion
checks the executing step host's path, version and binary hash. Native helpers
retain Windows PowerShell 5.1. Record actual source commits and trees, operating
system, architecture, CPU count, compilers, dependencies, shells and certificates.

Both source paths prepare Swift before recording the environment in every macOS
role: the installer and both desktop targets. One shared step runs
`xcrun swiftc --version` once, requires a successful exit and allows 60 seconds.
The metadata observer keeps its 15-second limit. Build, test and account limits
stay unchanged. Complete job and setup durations include this preparation in
both paths. No Windows preparation or separate warm-up run is added.

Before opening timing totals, require matching effective inputs for paired roles.
The control core and both candidate core jobs must match their actual image,
certificates, CPU count, architecture, Python, shells and dependencies.
Apply the same requirement to control native and both candidate native jobs.
Static tails must match final dependencies and certificates. Other common-role
image or certificate differences remain visible and enter the conservative
whole-job model below; that model does not prove equal environments.
Unchanged macOS roles may use the recorded three- or five-CPU runner profiles.
Disclose that difference and retain the whole-job minimum/maximum penalties.

In the qualifying pair, all changed core/native roles and both static tails
passed their strict input checks. Paired macOS CPU counts also matched.
Three unchanged Windows roles had the prospectively permitted differences below.
Their complete jobs received the declared before-minimum and after-maximum penalties.

| Unchanged role | Before image / loaded certificates | After image / loaded certificates |
| --- | --- | --- |
| Windows installer | 20261030.294.1 / 414 | 20261021.278.1 / 417 |
| Windows desktop menu | 20261021.278.1 / 417 | 20261030.294.1 / 414 |
| Windows hook adapter | 20261030.294.1 / 414 | 20261021.278.1 / 417 |

Loaded certificate-set hashes differed in those roles. The model measures
sensitivity to observed variation; it neither proves environment equivalence
nor bounds unobserved noise. No strict changed-role input rule was waived.

The new trigger is `cyril/ci-finish-ready-bench-*`, separate from prior cohort prefixes.
Both calls have read-only permissions and diagnostic acceptance names.
They cannot emit the required `Test` check or authorise publication.
Targeted `windows-ci-safety-shortcut-only-*-proof` refs run the isolated
shortcut diagnostic. They reuse unchanged passing launcher contracts; normal
proof refs and both complete source paths retain those contracts.
The [reusable-workflow rules](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)
bind the local called definition to the caller's commit; checkout readback
separately establishes the deliberately different application sources.

## Complete endpoints and conservative calculation

Observed elapsed starts at parent workflow creation and ends at each path's
final static-job completion. Allocation sums every complete job in that path,
including setup, reports and cleanup. Report runner classes separately.
Allocation is neither CPU time nor a bill. Count both paths once in experiment
totals; they are concurrent observations, not typical production measurements.

For unchanged roles, give before the minimum observed complete job duration,
and after the maximum. Keep each changed core job's own complete actual duration.
For native work, separate original runtime cases `R`, original shortcut cases `S`,
new cases `E` and residual job work `O`. Compute runtime minima and maxima
for each matched original occurrence across control and candidate runtime:

```text
b[native] = sum(R_min) + S_before + min(O_before, O_runtime, O_shortcuts)
a[native-runtime] = sum(R_max) + E_runtime + max(O_before, O_runtime)
a[native-shortcuts] = S_after + E_shortcuts + max(O_before, O_shortcuts)
```

Residual work includes setup, imports, fixtures, account work, reports and cleanup.
Require complete case-duration records, with finite nonnegative values and
residuals. Keep each source's changed shortcut durations; treating their
intended difference as noise would erase the optimisation under test.

Expand matrices into the actual dependency graph. Let `P[j]` be each role's
parents, `s[j]` and `e[j]` its timestamps, and `t0` workflow creation:

```text
q_after[j] = s_after[j] - max(t0, e_after[p] for p in P[j])
F_before[j] = max(0, F_before[p] for p in P[j]) + b[j]
F_after[j] = max(0, F_after[p] for p in P[j]) + q_after[j] + a[j]
```

Before receives immediate dispatch. After retains its actual dependency queues,
including the native aggregate's execution and waiting. Sum complete modelled
durations for allocation, with runner classes separate. Assert before estimates
never exceed observed before values and after estimates never fall below after.
Accept only when actual and modelled endpoints both save at least 90 seconds
and 20%, while both allocation increases remain at most 15%.

Both elapsed reductions exceeded 90 seconds and 20%. Actual allocation grew
1.43%; modelled allocation grew 8.38%. Both stayed below 15%.
The complete core job changed from 411 seconds to partitions of 217 and 236 seconds.
Native work changed from 627 seconds to partitions of 260 and 254 seconds.
These are components of the bundled observation, not separate causal estimates.

Allocated time by runner label is retained below. The changing Windows image
builds above remain relevant even where labels match. Model values are rounded
to three decimal places; acceptance used unrounded values.

| Runner label | Actual before (s) | Actual after (s) | Model before (s) | Model after (s) |
| --- | ---: | ---: | ---: | ---: |
| macos-15 | 40 | 55 | 40 | 55 |
| macos-15-intel | 117 | 126 | 117 | 126 |
| macos-latest | 332 | 336 | 332 | 336 |
| ubuntu-24.04 | 121 | 106 | 105 | 122 |
| ubuntu-24.04-arm | 136 | 116 | 116 | 136 |
| ubuntu-26.04 | 30 | 28 | 28 | 30 |
| ubuntu-latest | 302 | 336 | 297 | 341 |
| windows-2025 | 654 | 577 | 653.998 | 577.002 |
| windows-latest | 786 | 874 | 745 | 915 |

## Evidence acquisition

The original provider archive omitted the per-step post-checkout log for
`Before / Desktop menu (darwin/x86_64)`. Its aggregate job log retained the
complete 1,727-byte segment. Recovery matched eight unique, ordered surrounding
step payloads after validating timestamp prefixes. It copied the original gap
bytes into a separately labelled derived archive.

All 456 original archive members remained byte-identical; the derived archive
added one recovered member. An independent check verified the extraction and hashes.
This was acquisition repair, with no invented payload, parser waiver or eligibility change.
The frozen collection, assessment, metrics and plan inputs stayed unchanged.
Input eligibility was decided before timing totals were opened.

| Evidence | SHA-256 |
| --- | --- |
| Original provider archive | `68aa51715b463685edb2a911e7a08403d04fa698d8da99bd55fcdccb205a56ec` |
| Derived archive | `3b19c12219c834193261be5c7dd9b42b0a01c919cc2ac02929de2f45d5b28437` |
| Recovered segment | `2bcf6ee24f830d501f147f8d5e711e2cf24f8d1ba20a40807c8b3146a46fcd99` |

Raw logs and private operational metadata stay outside the public repository.

## Budget and correction

The final cohort allowed one paired workflow, with one replacement only for input
drift found before totals were opened and only when both paths otherwise passed.
Keep identical sources and orchestration for that replacement. Retain every
attempt. Do not add Windows warm-ups. A functional failure or disappointing
timing is not a replacement.
If a required check fails, diagnose and fix it; corrected source starts a new
cohort. This stops the invalid comparison, not the authorised correctness work.

The qualifying replacement exhausted that allowance and passed unchanged criteria.
One successful pair supports one observed bundled source/layout result and
measured sensitivity. It cannot isolate source-fix, core-partition or
native-partition effects, or prove typical savings, reliability or unobserved variation.

## Production promotion and remaining acceptance

The production matrix now selects `core-first`, `core-second`, `native-runtime`
and `native-shortcuts` through the existing launcher. The required `Test` job
depends on the whole matrix, so production needs no extra native aggregate.
Full-scope production has 19 allocations; the measured diagnostic candidate had 20.
Event filters, installer scope, platform coverage, permissions, timeouts and
release rules remain unchanged.

Production keeps its existing toolchain setup. Diagnostic pins, Swift
preparation and evidence collection are not copied into production by this change.
Those differences, and later integration changes, mean this measurement does
not establish the final production candidate's timing or acceptance.
Required checks and production acceptance must cover that final combined candidate.
The successful bounded comparison supports the shared skill example; it does
not establish plugin installation or fresh-client delivery.
