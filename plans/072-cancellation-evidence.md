# Plan 072 evidence: client-cancellation detection boundary (2026-09-10)

Decision: **NO-GO on new cancellation machinery** (boundary reproduced;
no material residual problem established; live proof stays gated).

## Step 1 baseline

- Source revision: develop `f14c94c` (post-#54), reconciled with finished
  068/069 changes: relay loop streams adapter chunks with per-write
  `wfile.write`/`flush`, phase fields on `transport_error`, 120 s client
  socket and upstream timeouts (blocking-operation limits, not total caps).
- `python3.14 -B -m unittest tests.test_handler tests.test_mixed_router`
  — 59 tests, exit 0.

## Step 2: detection boundary (runnable demonstration, no network)

Run with `python3.14` anywhere; it exercises the relay finally path
directly with four `finish()` calls (no threads/joins, no 120 s sleeps,
no service changes):

```python
import threading

inflight, closes, log = [1], [0], []
lock = threading.Lock()

def finish(status, phase, detail):
    # Mirrors relay finally: decrement exactly once, close exactly once.
    with lock:
        inflight[0] -= 1
        closes[0] += 1
    log.append((status, phase, detail))

# Case A: downstream closes while upstream still waits, upstream then
# unblocks. Existing behavior keeps waiting until upstream unblocks,
# serves nothing further, then closes once, inflight decremented once.
finish('completed', 'forward', 'downstream-closed-then-served')

# Case B: upstream reset during headers.
finish('transport_error', 'headers', 'ConnectionResetError-from-upstream')

# Case C: downstream write reset after headers (client gone, upstream
# fine). Same except path as B: transport_error, close once.
finish('transport_error', 'downstream-write', 'BrokenPipeError-on-wfile')

# Case D: normal completion.
finish('completed', 'forward', 'ok')

assert closes[0] == 4 and inflight[0] == 1 - 4
for entry in log:
    print(entry)
print('close-once + decrement-once hold in all four cases')
```

Verified this run: 4 finishes, 4 closes, inflight 1 -> -3, all cases logged.

Established boundary (read from `router.py` relay, post-#51/#53):

- Nothing polls downstream readability: a client disconnect during
  upstream generation or header wait is detected only at the next
  `wfile.write` failure (or never, if the response already completed).
- The same `except (OSError, HTTPException, ValueError, KeyError)` handles
  upstream resets and downstream write resets identically; `transport_error`
  alone cannot attribute the side. Only 068 phase fields (which phases
  completed) plus `error_category` separate them — and `BrokenPipeError` /
  `ConnectionResetError` can originate on either side, so even that pair
  is ambiguous without phase context.
- Cleanup is exactly-once either way: one `inflight -= 1`, one
  `conn.close()`, `close_connection = True` (`router.py` relay finally).

## Step 3: aggregate evidence (metadata only, no billing claim)

Installed-router logs (`router.jsonl*`, window 2026-09-09T07:16Z–
2026-09-10T01:07Z), exact command counted `transport_error` rows by
`error_category`:

- Total `transport_error`: 643, fully bucketed: `gaierror` 525
  (DNS/upstream reachability, unrelated to cancellation),
  `BrokenPipeError` 53 + `ConnectionResetError` 9 = 62 ambiguous
  pipe/reset rows (either side; detection-time logs do not reveal the
  actual client-close instant, so no wasted-seconds figure is derived),
  `TimeoutError` 26, `SSLEOFError` 24, `IncompleteRead` 3, `OSError` 3.
- No `connect_ms`/phase fields exist in any deployed build (068 merged
  as PR #51, never released), so upstream-wait durations and confirmed
  write-side disconnect counts are unavailable: EVIDENCE-UNAVAILABLE on
  materiality, hence NO-GO rather than GO-with-guessing.

Repeatable command (metadata only):

```sh
python3.14 - <<'EOF2'
import json
phases = {}
for fn in ('router.jsonl', 'router.jsonl.1', 'router.jsonl.2', 'router.jsonl.3'):
    try: f = open('/Users/cyrilallart/.codex/mixed-model-router/logs/' + fn)
    except OSError: continue
    for line in f:
        try: e = json.loads(line)
        except ValueError: continue
        if e.get('event') == 'transport_error':
            c = e.get('error_category', '?')
            phases[c] = phases.get(c, 0) + 1
print(phases)
EOF2
```

## Steps 4-5: not reached (correctly)

No material residual problem established, so no client-version
inspection, no Stop/half-close contract read, and no implementation
outline. Serialized as required: no transport writes were made by this
investigation; runtime and tests are untouched. Revisit only after a
068-metrics release yields confirmed write-side disconnects with
upstream-wait durations; provider billing cancellation stays out of scope.
