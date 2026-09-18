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
against 209 and 376 before. That count is about pairing alone; the state
budget was a second, separate refusal reason, fixed below.

**Fixed — the 32 KiB state budget declined wide windows.** The ladder shrank
each item (2000, then 500, then 120 characters) but never the number of
items, so a wide window could not fit: at 600 items **59 of 60 sessions**
declined with `request_too_large` before any call was made. The state now
also thins the newest evidence (64 entries at 500, 32 at 120, 16 at 60) and
records how many older entries it left out. That is not one-way safe:
thinning lowers the coverage score and the "call still matters" score as
well, which can turn a truncation into a drop, so both questions now name
`retained_omitted` and forbid inferring coverage from absence.
A 20-window replay at the same size: **17 of 20 reach Jev** (was 0 of 20
before the fix), median request 7 KiB, and the remaining three have no
eligible pair at all.

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

## Labelled calibration, 2026-09-18 AEST

`tools/probe_jev_calibration.py` builds windows whose correct action is known
by construction: 24 cases from eight templates at three output sizes. Six
pairs are provably droppable (a retained duplicate, or a read superseded by a
later identical one) and eighteen must be kept (unique failures, mutation
receipts, equal-length contradictory outputs, a verdict past character 300,
and three whose call occurrence is itself the fact); three windows have no
candidate pair at all. The live pass cost about US$0.001 and asked on all 21
pair-bearing windows; the stored report records the pinned `decisions_model`
and a request-bytes floor estimate as `spend_usd`.

The live answers are staged as `docs/jev-compaction-calibration.json`, and
`python3.14 tools/probe_jev_calibration.py --replay` on that file recomputes
the table and the score bands below without another call, so every number in
this section is checkable offline.

| threshold | correct | false drops | truncation harm | missed drops |
|---|---|---|---|---|
| every rung from 0.40 to 0.99 | 18 | **0** | **0** | 6 |

The scores explain that result, and they are the interesting part. On the six
*provably droppable* pairs the coverage answer was 0.23-0.32; on the eighteen
that must be kept it was 0.18-0.23 - the bands touch at 0.23, so no threshold
separates them. The call answer sat between 0.48 and 0.65 for every pair
regardless of kind. A pair drops only when coverage is at or above the
threshold and the call is below it, and here coverage never reaches 0.32
while calls never fall below 0.48: the rule cannot drop anything on this set
at any threshold. A second live run of the same 24 cases reproduced this
table exactly but moved individual scores by up to 0.02 (the droppable band's
floor moved from 0.22 to 0.23), so the bands themselves are run-dependent.

Why coverage answers are so low is the blind spot earlier passes found, now
measured on known cases: candidates carry only `ok|error, N chars (omitted)`,
so the judge is asked whether facts are covered while the facts themselves
are withheld, and it answers about 0.2 even where redundancy is provable by
construction. Letting it answer that question would mean sending candidate
result bodies, which changes what leaves the machine - an owner decision, not
a review fix.

So the labelled evidence says two things at once: the shipped default is safe
(no false drop and no truncation harm at any threshold tested) and it is
inert for the same reason the archived sweep found - the rule never fires.
The useful next change is not a threshold; it is either showing the judge the
candidate's own text under the existing cap ladder, or replacing the coverage
question with one the state can actually settle.

## Is the design worth shipping?

The measurements answer the obvious criticism of this feature - "scoring tool
calls and deleting the losers is filtering, not context management" - with a
qualified yes and a clear redirection.

The criticism is right about the failure mode. At 0.50 the archived sweep
would touch 175 of 378 pairs and 101 of those carry failure or mutation
markers, so the pairs a delete-first rule reaches for are exactly the audit
trail a coding agent needs: the failing test, the mutation receipt, the read
that explains the bug. Deleting those without leaving a trace is how a later
turn retries the same attempt. The labelled calibration adds the second half:
the judge is asked whether a pair's facts are covered while its result body
is replaced by `ok, N chars (omitted)`, and it answers 0.23-0.32 on pairs
that are droppable *by construction* - a structural information gap, not a
tuning problem.

Where the criticism overshoots is the cache argument. It targets mid-history
edits - the plugin's own 60%-usage trigger rewrites messages mid-thread. This
integration only acts at Codex's own compaction boundary, where the prefix is
rewritten wholesale anyway; pruning adds no rewrite that compaction had not
already caused. The axis that does bite is the one the design passes flagged:
bytes saved have only ever been measured against the verbatim window, never
against the *summariser* the feature replaces. That comparison is missing and
is plausibly negative - a verbatim render of the window (median 137 KB) is
larger than a summary of it - so it is the first thing the next sweep must
measure.

So the version worth building is not "score and delete". It is: keep the
execution trace, and drop only the re-fetchable payload. Concretely, the drop
branch should keep the call and leave a stub where the output was
(`[result dropped: N chars, status]`), so nothing ever vanishes silently and
the next turn can see that something was tried and what it returned. The
questions should then ask what the state can actually settle - is this call a
repeat of one already visible in `retained`, is this payload re-obtainable -
because both are answerable from the call text the judge already receives.
The truncation branch already works this way; only the drop branch does not.

Ship it only if that variant clears the bar: median bytes saved against the
summariser above zero on a stratified sweep, no false drop and no truncation
harm on the labelled set, and no silent removal of a marker-carrying pair. If
it cannot clear that bar, the honest outcome is to keep the feature off, keep
the harness and calibration that produced this verdict, and say so in the
changelog rather than tuning a threshold until something moves.

### The deterministic variant, proposed 2026-09-18

The owner proposed replacing the judge entirely: give every tool result a
short description, and at compaction time drop tool inputs and outputs down
to the tool name plus that description, keep tool failures in full, replace
each dropped output with a tool id and a note saying where the full response
lives on disk, and always leave the last N turns intact.

That rule is deterministic, so it has none of the defects this benchmark
found: no request is billed, nothing waits on a judge, the blindness that
produced 0.23-0.32 coverage answers cannot apply, and there is no threshold
to calibrate. It is also the same principle the rest of this report argues
for - keep the execution trace, drop only the re-fetchable payload - with the
trace made durable by an explicit on-disk note instead of a 300-character
fragment.

Two things it needs that do not exist today. Codex's items carry a tool name
and arguments but no description field, so the description has to come from
the call text (which is already the best available description) or from a
generated one-liner; and "look it up on disk" needs a real path - either the
client's own session file, which the router cannot name, or a router-owned
payload store keyed by call id, which is one small new piece of machinery
with its own retention rule.

It also has a limit worth stating: keeping the text transcript intact means
it compresses tool traffic only, so a session that is mostly prose - the
137 KB median render in the first sample was tool output, but not every
session is - gains little from it.

## Recommendation, and what it waits on

1. **Keep 0.90 for now.** Nothing is dropped, so nothing is lost, and the
   sweep gives no evidence that any lower setting is safe: at 0.50 alone,
   101 of the 175 pairs it touches carry failure or mutation markers, and the
   label set cannot yet tell a true positive from a false one. Lowering the
   threshold on this evidence would trade real
   information for unmeasured savings.
2. **Do not treat `on` as useful yet.** The state budget is fixed, but the
   labelled calibration shows the rule cannot fire at any threshold from
   0.40 to 0.99, because coverage never reaches the call-it-still-matters
   band. The blocker is not the threshold; it is that the judge is asked
   about facts it cannot see.
3. **Change the drop branch before tuning anything**: keep the call and
   leave a stub where the output was, so the execution trace survives while
   only the payload goes, and ask questions the state can settle (is this
   call a repeat, is this payload re-obtainable) instead of asking whether
   facts are covered while the facts are withheld. Showing the judge the
   candidate's own text is the alternative, and it is an owner decision
   because it widens what leaves the machine. Then re-run the archived sweep
   and the labelled calibration together.
4. **Add score-level shadow logging** so real compactions accumulate the
   distribution instead of only counts, and hand-adjudicate a sample (about
   50 pairs to start) to build the missing positive class on real threads.
5. **Re-measure against the pinned snapshot** whenever
   `provider_defs.OPENROUTER.decisions_model` changes.

## Limits

The sample is 30 of 2,450 archived rollouts, weighted to the largest files;
windows are tail slices of 160 or 600 items rather than Codex's own
compaction boundary; labels are heuristics; one model snapshot
(`typesafe/jev-1.13-20260917`) at one point in time; and the harness measures
one batch per session, not a whole thread's compaction history.

The calibration set is 24 synthetic cases: it proves known-case behaviour,
not prevalence in real work, and its scores were produced by one pinned
snapshot. Its invariance across thresholds is a property of those scores, not
a guarantee about other snapshots, runs or windows.
