# Plan 071 evidence: connection-reuse go/no-go (2026-09-10)

Decision: **EVIDENCE-UNAVAILABLE** (no-go by default; revisit after 068 ships).

## What was checked

- Source revision: develop `f14c94c` (post-#54). Relay path creates one
  `HTTPSConnection` per request (`router.py:305`) and closes it in
  `finally` (`router.py:399`); compaction summariser does the same
  (`providers.py:331`, `finally: conn.close()`). Post-#51 code records
  `connect_ms`/`send_ms`/`headers_ms` via `transport.post_with_phases`.
- Suites: `tests.test_providers tests.test_handler tests.test_mixed_router`
  — 85 tests, exit 0, no behavior change observed.
- Installed-router logs (`~/.codex/mixed-model-router/logs/router.jsonl*`,
  57,111 lines, window 2026-09-09T07:16Z–2026-09-10T01:07Z):
  26,134 `request_completed` events, of which **zero** carry `connect_ms`.
  The installed router reports versions up to `0.6.11.27`, which predates
  the 068 phase metrics (merged as PR #51, never released). The 068 fields
  needed to attribute connection setup do not exist in any deployed build.

## What the old fields do (and do not) say

- `upstream_headers_ms` median 3,618.5 ms (n=12,116, current log files);
  `total_ms` median 5,876.8 ms. These bound pre-first-response time but
  include DNS+TCP+TLS+server queue+first-byte wait indistinguishably.
- The audit's ~3.46 ms HTTPS object-construction figure measures Python
  object setup without network. Against a 3.6 s headers median that is
  ~0.1%, but object construction is not the handshake: recording NO-GO
  or GO on that ratio would be the inferred-handshake estimate the plan
  forbids. Result: UNVERIFIED.

## Screening rule application

The plan requires connection setup ≥10% of pre-first-response time on the
representative median request, or demonstrably material tail delays, over
a meaningful repeated-tool-turn sample. Neither input exists:
no `connect_ms` distribution, no per-request share. Tiny or mixed-version
samples cannot pass the gate; inventing the handshake share is out of scope.

## Repeatable aggregation command (metadata only)

```sh
python3.14 - <<'EOF2'
import json, statistics
rows = []
for fn in ('router.jsonl', 'router.jsonl.1', 'router.jsonl.2', 'router.jsonl.3'):
    try: f = open('/Users/cyrilallart/.codex/mixed-model-router/logs/' + fn)
    except OSError: continue
    for line in f:
        try: e = json.loads(line)
        except ValueError: continue
        if e.get('event') == 'request_completed' and 'connect_ms' in e:
            rows.append(e)
print('phase-field completions:', len(rows))
if rows:
    conn = sorted(e['connect_ms'] for e in rows)
    head = sorted(e['upstream_headers_ms'] for e in rows if 'upstream_headers_ms' in e)
    print('median connect_ms:', statistics.median(conn))
    print('median upstream_headers_ms:', statistics.median(head))
EOF2
```

Re-run after a 068-metrics release has served representative traffic; a
week of mixed-version logs is the minimum sample before applying the 10%
rule. No runtime, test, pool, retry, or benchmark change was made by this
investigation. Paid direct-versus-router or keep-alive tests need separate
authority.
