# Plan 072: Establish whether cancelled requests need earlier upstream cleanup

> Investigation only. No production cancellation logic, timeout changes,
> client mutations or paid probes are authorised by this plan.
> Drift check: `git diff --stat 83a5023..HEAD -- codex_router/router.py codex_router/providers.py codex_router/transport.py codex_router/tool_adapter.py tests/test_handler.py tests/test_mixed_router.py plans/README.md`
> Reconcile the finished 068/069 changes before interpreting cancellation data.

## Status and first proof

- DONE (investigation, 2026-09-10): NO-GO on new cancellation machinery;
  detection boundary reproduced (detect-at-next-write; 62 ambiguous
  pipe/reset rows of 643 transport_errors; materiality unavailable without
  068 live phases). Evidence in plans/072-cancellation-evidence.md; P3;
  effort S spent.
- Planned at `83a5023`, 2026-09-10. Depends on 068 and 069; independent of 071's
  decision, but serialize any future transport writers with it.
- First proof: a phase-aware reproduction distinguishes upstream failure from
  downstream closure and establishes the remaining wait after cancellation.

## Current state and scope

`router.py:265-266` can wait for upstream headers; `:309-313` waits for adapter
chunks before writing downstream. Cleanup occurs at `:339-343`:

```python
for chunk in provider.adapt(response, prepared.tool_names, metrics):
    self.wfile.write(chunk)
    self.wfile.flush()
# finally: decrement inflight and close upstream connection
```

Both client socket and upstream HTTPSConnection have 120-second timeouts
(`router.py:176,261`); summarizer also has a 120-second upstream timeout.
These are blocking-operation limits, not a maximum total generation duration.
Fixing 069 may shrink detection delay without new cancellation machinery.

Permitted writes: this plan, plans/README.md, and new
`plans/072-cancellation-evidence.md`. Source/tests remain read-only. Do not
equate every BrokenPipeError/ConnectionResetError with a client disconnect:
the same exceptions can originate upstream. 068 owns phase-aware logging.
Provider billing cancellation is explicitly outside the claim and scope.

## Steps and verification

1. Read the actual handler cleanup, compaction inflight accounting and 068's
   error phases. Run `python3.14 -B -m unittest tests.test_handler tests.test_mixed_router`.
   **Expected:** pass; record the exact baseline, including 120-second limits.
2. Build an in-memory fake-connection demonstration in the evidence document,
   runnable as a Python heredoc with no filesystem/service changes. Use Events
   and finite joins, not a paid endpoint or 120-second sleeps. Show: upstream
   waiting while downstream has closed; an upstream reset; a downstream write
   reset; and normal completion. Patch external boundaries only. **Verify:**
   existing behavior keeps waiting until upstream unblocks, then closes once and
   decrements inflight exactly once; classify each failure by its real phase.
3. Assess aggregate 068 evidence after 069 is installed, if authorised data is
   available: number of confirmed write-side disconnects, upstream-wait durations,
   and affected workload. Note that detection-time logs do not reveal the actual
   client-close instant; do not derive wasted-seconds/billing from them. If no
   material residual problem is established, record NO-GO. **Verify:** record
   exact metadata-only analysis command, interval, n and unavailable facts.
4. Only if the problem is material, inspect the installed client's exact version
   and matching upstream source for Stop/cancellation and half-close behavior.
   Follow repository AGENTS.md section 9: verify repository/tag identity and
   record the pinned source. EOF/readability alone is not a safe abort signal;
   HTTP clients can finish request writing while still expecting response data.
   **Verify:** evidence cites the concrete cancellation signal/contract or states
   that it could not be established. Never infer full disconnect from FIN alone.
5. For a GO, outline a separate implementation with a deterministic regression
   for abort-before-headers, quiet stream, live slow client, valid half-close,
   upstream reset, compaction and drain. Preserve ordinary streaming, exactly-once
   cleanup, and platform compatibility. Do not shorten model reasoning timeouts
   globally or add a request cap. **Verify:** each accepted failure path has a
   concrete test and source owner; no runtime code changed.

## Done, integration and stop conditions

- [ ] Evidence reproduces the current detection boundary without real network.
- [ ] GO / NO-GO / EVIDENCE-UNAVAILABLE is justified, with no billing claim.
- [ ] `git diff --check` passes and only the three allowed planning paths changed.
- Use one owned `codex/` worktree based on develop. Current pre-commit-review
  applies before docs commit; integrate into develop, verify and safely clean up.
- Stop if reliable cancellation cannot be distinguished from valid half-close,
  live proof needs unapproved paid/client actions, or the fix would require an
  async rewrite. Record the limitation; do not implement speculative select loops.
- Maintenance: pooling, drain and cancellation share connection ownership;
  any later implementation must preserve all three contracts in one writer stream.
