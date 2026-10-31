# Router offline fixture comparison

Two diagnostic test classes finished **101.537 seconds sooner** in one local
comparison after their health probes used an existing fixture seam.
The complete required-verification comparison failed. It did not establish
faster successful complete verification or continuous integration (CI).

## Cause and change

Status and doctor tests checked keys, receipts and diagnostic output.
Several cases also reached a real local HTTP health probe with a five-second
retry window. Two control cases failed immediately when an unexpected-HTTP
guard was added, confirming the unintended boundary crossing.

`StatusTests` and `OperatorSurfaceTests` then used their existing health seam
to return an unavailable service by default. Each test retained the HTTP guard
and restored its patches on cleanup. Existing healthy and version-mismatch
overrides, assertions and real integration tests remained.
Runtime code, timeouts, shared fixtures, native tests and CI definitions did not change.

## Bounded local measurement

The comparison ran on 31 October 2026 AEDT with Python 3.14.9,
macOS 26.7.1 ARM64 and 18 logical CPUs. Execution used one worker;
`SCG_RUN_INSTALLER_TESTS` was unset, matching normal local verification.
Both arms used base commit `22fff3124254cdc4af7471031b7cdf224ce1cb3f`.
The measured candidate's trimmed `git diff HEAD` had SHA-256
`a8d09007c1642e9e30aa22f3216eadc4f6412462361113e97c4c80b8faa05d5b`.

The existing result recorder executed both classes:

```sh
python3.14 tools/ci_unittest.py --report "$REPORT_PATH" -- \
  tests.test_status.StatusTests \
  tests.test_operator_surface.OperatorSurfaceTests
```

Each attempt used a separate report path outside the repository.
Timing included command completion and normal cleanup.

| Focused sample | Elapsed | Observed cases | Skips | Result |
| --- | ---: | ---: | ---: | --- |
| Control | 102.754s | 31 | 0 | Passed |
| Candidate | 1.217s | 31 | 0 | Passed |

The observed reduction was **98.8%**. Inventories, selected cases, order,
duplicate multiplicities, observed outcomes, events and fixture-skip records matched.
This is one pair, not evidence of typical speed or reliability.
Natural filesystem and interpreter warming remained uncontrolled.

## Failed complete comparison

The budget allowed four measured attempts, with no replacements for test failures.
Their order was focused control, complete control, focused candidate, complete candidate.
The two guard-only reproductions were separate from these timing samples.

The control passed all four required local commands in **450.047s**.
Its suite reported 2,696 cases and 10 skips.
The candidate suite finished in **349.734s**, also reporting 2,696 cases and 10 skips,
but failed `SourceLimitsBaselineTests.test_the_live_baseline_passes_the_tool`.
The added fixture exceeded one test file's existing 451-line ceiling by five lines.
The remaining three required commands did not run in that attempt.

The complete comparison therefore failed its acceptance criterion.
The failed attempt remains part of the evidence; later corrections and required
verification do not replace it. No successful complete-verification saving is claimed.
The focused result supports the narrow fixture lesson. It does not establish
remote Windows behavior, faster whole CI, or line or branch coverage.
