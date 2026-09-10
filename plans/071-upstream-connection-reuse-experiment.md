# Plan 071: Decide whether upstream connection reuse is worth implementing

> Investigation plan only. It does not authorise a production pool, release,
> installation, credentials change or paid inference benchmark.
> Drift check: `git diff --stat 83a5023..HEAD -- codex_router/router.py codex_router/providers.py codex_router/transport.py docs/architecture.md plans/README.md`
> Read 068's installed measurement contract and 069's stream behavior before work.

## Status and first proof

- DONE (investigation, 2026-09-10): EVIDENCE-UNAVAILABLE, no-go by
  default; zero deployed completions carry connect_ms (068 unreleased), so
  the 10% rule cannot be applied without inferring the handshake.
  Evidence in plans/071-connection-reuse-evidence.md; P3; effort S spent.
- Planned at `83a5023`, 2026-09-10. Depends on 068 measurements and 069 behavior.
- First proof: a reproducible cost breakdown supports a go/no-go decision with
  sample sizes and explicit connection-establishment contribution.

## Current state and scope

`router.py:261-266` creates one HTTPSConnection per request; `:342` closes it.
`providers.py:298-312` does the same for synchronous compaction summarisation.

```python
conn = http.client.HTTPSConnection(prepared.host, timeout=120)
# ... request, getresponse, adaptation ...
conn.close()
```

The audit measured HTTPS object construction at ~3.46 ms, without any network;
that does not measure DNS/TCP/TLS. OpenRouter first-chunk median was ~3.66 s in
515 completed requests, but its connection share is currently unknown.
Compaction can block the next user turn; do not dismiss it as non-interactive.

Permitted writes for this investigation: this plan, plans/README.md, and new
`plans/071-connection-reuse-evidence.md`. Runtime and tests are read-only.
Reuse existing Plan 062 transport ownership and Plan 045 drain contracts.
No new request cap, async migration, generic pool library or automatic POST retry.

## Steps and verification

1. Verify source revision and inspect current connection creation/cleanup and
   exception paths, including compaction. Run
   `python3.14 -B -m unittest tests.test_providers tests.test_handler tests.test_mixed_router`.
   **Expected:** exit 0; record any changed behavior before comparisons.
2. With 068 metrics actually available, aggregate only timing/count metadata
   from equivalent version/model/provider/stream workloads. Report n, time
   window, failures, connection interval distribution and per-request share of
   headers/total. Report compaction separately. Do not collect request contents,
   credentials, tool schemas or secret-bearing URLs. **Verify:** a repeatable
   documented read-only aggregation command reproduces the table; missing
   connection fields result in UNVERIFIED, never an inferred handshake estimate.
3. Use a declared screening rule: investigate further if connection setup is at
   least 10% of pre-first-response time on the representative median request,
   or demonstrably creates material user-visible tail delays. This is a planning
   threshold, not an observed fact. Otherwise record no-go and stop. A meaningful
   sample must cover repeated tool turns; tiny or mixed-version samples cannot
   pass the gate. **Verify:** evidence states exact arithmetic and sample limits.
4. If go, specify the smallest later implementation and its tests: bounded idle
   reuse by origin/provider/authentication identity, no headers inherited between
   requests, no lock held during network I/O, discard unread/failed/aborted or
   will-close responses, and close retained sockets on drain. Concurrent streams
   never share an active connection. Idle-pool bounds are not request admission
   caps. Stale sockets never trigger automatic replay of a paid POST, including
   the summarizer. **Verify:** evidence maps each invariant to a proposed fake
   connection regression and a concrete source owner, without runtime edits.
5. Record GO / NO-GO / EVIDENCE-UNAVAILABLE, expected benefit, added failure
   modes, and exact future acceptance gates. Paid direct-versus-router or real
   keep-alive tests require separate authority. **Verify:** `git diff --check`
   exits 0 and changed paths are only the three allowed planning files.

## Done and stop conditions

- [ ] Reproducible aggregate evidence or an explicit missing-evidence result.
- [ ] A go/no-go decision; no claims that a connection pool is already justified.
- [ ] Any go decision has anti-replay, identity isolation and drain test designs.
- Use one owned `codex/` worktree from develop; current pre-commit-review governs
  any docs commit. Integrate into develop and verify before safe cleanup.
- Stop when measurement is absent/insufficient, upstream keep-alive contracts
  cannot be verified, or useful reuse would require retrying ambiguous paid POSTs.
  Complete the investigation with that limitation rather than building a pool.
- Maintenance: revisit only after measured workload/latency changes; a NO-GO is
  a valid finished investigation, not an invitation to broaden architecture.
