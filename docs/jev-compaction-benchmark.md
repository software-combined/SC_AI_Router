# Jev compaction benchmark, 2026-09-18

First measured pass over real archived Codex threads, replaying them through
the shipped `ai_router/jev_compaction.py` with `tools/bench_jev_compaction.py`.
The harness reads the archive read-only, uses a throwaway home for the flag,
and spends nothing unless `--live` is passed. Everything below came from the
30 largest rollouts in `~/.codex/archived_sessions`, tail window of 160 items,
unless a row says otherwise. Live spend for the scoring pass: **US$0.0041**.
The scoring pass was then repeated after a review lane corrected the sweep
(truncations now count only where the shipped rule really shortens, over 300
characters): **US$0.0082 across both passes**, and the two runs agreed to two
decimals on every summary statistic.

## What the sample looks like

| Measure | Value |
|---|---|
| Sessions replayed | 30 |
| Sessions that reached Jev | 25 |
| Candidate pairs judged | 378 (756 `noul` values) |
| Median request state | 16.4 KB |
| Median rendered result | 137 KB |
| Median decision latency | 426 ms |
| Estimated cost per compaction | US$0.00016 |

## The defect this benchmark exposed: an inverted decision

The measured scores did not fit the shipped rule's behaviour, and following
that thread found the most serious defect in the feature. Both questions are
positive propositions — "the pair's facts are already covered by retained",
and "knowing the call happened still matters" — so a *high* coverage value
means the evidence survives elsewhere and the pair may go. The rule compared
both values against the threshold backwards: it dropped a pair when both fell
*below* 0.90, which is exactly when the judge had said the facts were **not**
covered. At the shipped setting, with every measured score below 0.83, that
meant deleting **every judged pair** — 243 of them carrying failure or
mutation markers in this sample — while the documentation promised the
opposite.

Fixed in the same release: a pair is dropped only when its facts count as
covered and the call no longer matters; covered evidence whose call still
matters keeps the call with a shortened output; an uncovered pair stays
verbatim. With that rule the shipped 0.90 drops nothing at all on this
sample, which is the safe behaviour the report below describes.

## Coverage: two defects the archive exposed

**Fixed — global pair closure refused most real windows.** The shipped rule
required every tool call in the window to have its output and refused the
whole compaction otherwise. Real windows routinely hold an output whose call
scrolled out of the window: at a 600-item window **40 of 60 sessions refused**
(median 3 unmatched outputs, 0 unmatched calls), and at 160 items 34 of 60
refused. Refusing protected nothing — an item with no partner is never a
candidate, so it is kept either way. Closure is now local: only complete,
ordered, unpinned pairs are eligible, duplicated ids protect every member,
and anything unpairable is left verbatim. After the fix: **0 pair-closure
refusals in both windows**, 749 pairs judgeable at 600 items and 795 at 160,
against 209 and 376 before. (Sessions still decline for other reasons: at 600
items 59 of 60 cannot fit the state budget below.)

**Open — the 32 KiB state budget declines wide windows.** The state ladder
shrinks each item (2000, then 500, then 120 characters) but never the number
of items, so a wide window cannot fit: at 600 items **59 of 60 sessions**
decline with `request_too_large` before any call is made. Real Codex
compactions see windows that large, so this is the next thing to fix; the
conservative direction is to thin `retained` (newest first) with an explicit
omitted count, because less evidence biases the judge toward keeping.

## Score distribution (756 values, live)

| min | p25 | median | p75 | max | values >= 0.90 |
|---|---|---|---|---|---|
| 0.16 | 0.44 | 0.54 | 0.61 | 0.83 | **0** |

Run twice on the same windows with independent calls, the distribution moved
by at most 0.01 at every point and neither run produced a single value at or
above 0.90.

With the corrected rule, the shipped threshold of 0.90 **drops and truncates
nothing** on this sample: coverage never reaches 0.90. In `on` mode that
means paying for a call and returning the window rendered verbatim (median
137 KB) instead of a summary — a no-op at best, and a refusal when the result
exceeds 40% of the context window. The feature is safe at its default and
useless at its default, which is the honest description.

## Threshold sweep

| threshold | dropped (valuable) | dropped (unknown) | truncated (valuable) |
|---|---|---|---|
| 0.50 | 28 (15) | 13 | 147 (86) |
| 0.60 | 57 (30) | 27 | 52 (29) |
| 0.70 | 28 (12) | 16 | 6 (3) |
| 0.80 | 2 (1) | 1 | 0 |
| 0.85 and above | 0 | 0 | 0 |

The table was recomputed from the same stored answers after the polarity fix,
so it costs nothing to reproduce. Drop counts peak at 0.60 and fall away
above it, because raising the threshold makes "covered" harder to reach; the
truncation column peaks at 0.50, where most pairs count as covered but their
calls still matter.

So at 0.50, 101 of the 175 pairs the setting touches carry a failure or
mutation marker; at 0.60 it is 59 of 109. The sweep is read against heuristic
labels, not ground truth: a pair is
`redundant` when an identical call and identical output appear elsewhere in
the same window, `valuable` when the output or arguments carry a failure,
test, or mutation marker, and `unknown` otherwise. **No pair in this sample
was labelled redundant** — real redundancy is semantic (re-reads, superseded
listings), so the positive class is missing and the label column can only
show risk, not correctness. That is why the columns report marker hits rather
than false positives.

## Recommendation, and what it waits on

1. **Keep 0.90 for now.** Nothing is dropped, so nothing is lost, and the
   sweep gives no evidence that any lower setting is safe: at 0.50 alone,
   101 of the 175 pairs it touches carry failure or mutation markers, and the
   label set cannot yet tell a true positive from a false one. Lowering the
   threshold on this evidence would trade real
   information for unmeasured savings.
2. **Do not treat `on` as useful until the state budget is fixed** and a
   labelled set exists to choose a threshold against. The score scale here
   is compressed and does not separate redundant from valuable on its own.
3. **Add score-level shadow logging** so real compactions accumulate the
   distribution instead of only counts, then adjudicate a sample by hand
   (about 50 pairs is enough to start) to build the missing positive class.
4. **Re-measure against the pinned snapshot** whenever
   `provider_defs.OPENROUTER.decisions_model` changes.

## Limits

The sample is 30 of 2,450 archived rollouts, weighted to the largest files;
windows are tail slices of 160 or 600 items rather than Codex's own
compaction boundary; labels are heuristics; one model snapshot
(`typesafe/jev-1.13-20260917`) at one point in time; and the harness measures
one batch per session, not a whole thread's compaction history.
