# Plan 136: Contain the unauthenticated ingress compare crash

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If any
> "STOP conditions" item occurs, stop and report - do not improvise. When done,
> update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 08aff1e..HEAD -- ai_router/router.py tests/test_ingress_guards.py config/source-limits-baseline.json`
> If any in-scope file changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `08aff1e`, 2026-09-11 (refreshed after plan 090 landed)

First proof: a raw `GET /<0xFF>/x` and a `POST` with
`Authorization: Bearer <0xFF>` each receive a 403 rejection instead of an
aborted connection; the manual probe in Step 3 runs clean with no traceback in
its output; and `ai_router/router.py` stays at or below the 400-line cap (it is
395 lines today).

## Why this matters

Any local process that can open a socket can put a non-ASCII byte in the request
path, or in the bearer value. `hmac.compare_digest` refuses non-ASCII `str`
arguments with `TypeError`; nothing catches it, so the handler aborts with no
response and `socketserver.handle_error` prints a traceback to stderr. The
supervisor captures stderr into `logs/launchd.log`, which only rotates when the
service starts, so a loop of such requests grows that file without bound
between restarts. Reproduced end-to-end on 2026-09-11; see
`plans/2026-09-11-router-external-security-audit.md`, finding 2.

## Current state

- `ai_router/router.py` - `authorized_path()` is the single pre-auth choke
  point (`:99`); `do_GET` (`:136`) and `do_POST` (`:163`) call it first and
  neither wraps the call in `try`/`except`.
- `ai_router/router.py` is 395 lines (baseline value 395, five below the 400
  hard cap). Plan 090 landed at `02e8e6e`; it added `Handler.timeout = 120`
  (`:71`) and removed the fallback listener's `allow_reuse_port`.
- Current code at `:100-113`:

```python
        # Setup URLs carry their own token plus nonce and enforce same-origin
        # themselves, so the generic rebinding rejection exempts their path.
        if (self.headers.get('Origin')
                and '/setup/' not in self.path.split('?', 1)[0]):
            return None, False
        prefix = '/' + self.server.state['token']
        candidate, sep, _ = self.path[1:].partition('/')
        if sep and hmac.compare_digest(candidate, self.server.state['token']):
            return self.path[len(prefix):].removeprefix('/backend-api/codex'), True
        header = self.headers.get('Authorization', '')
        if header.startswith('Bearer ') and hmac.compare_digest(
                header[len('Bearer '):], self.server.state['token']):
            return self.path.removeprefix('/backend-api/codex'), False
        return None, False
```

- `self.path` and header values are `iso-8859-1`-decoded by the stdlib, so they
  only ever contain code points 0-255. `.encode('iso-8859-1')` cannot fail for
  them, and comparing `bytes` preserves constant-time behaviour.
- Supervisor log: `packaging/service.py:250-251` points both stdout and stderr
  at `logs/launchd.log`; `packaging/router_launch.py:32` rotates it at launch
  only (`packaging/service.py:566` owns `rotate_log`). Windows routes the same
  streams through `packaging/platforms/windows.py`.
- Conventions: ingress guard tests live in `tests/test_ingress_guards.py`
  (Plan 092, 89 lines; it imports `_auth_file` from `tests/test_handler.py` and
  `_start_server`/`_test_state` from `tests/test_mixed_router.py`).
  `LoopbackBoundaryTests` (`tests/test_mixed_router.py:171`) shows the
  boundary-test style.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Focused tests | `python3.14 -m unittest tests.test_ingress_guards -v` | all pass |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Source limits | `python3.14 tools/check_source_limits.py` | exit 0 |
| Line count | `wc -l ai_router/router.py` | 395 before the edit; at most 400 after |

## Scope

**In scope**: `ai_router/router.py`, `tests/test_ingress_guards.py`,
`config/source-limits-baseline.json` (router.py baseline sync only).
**Out of scope**: `do_POST`/`do_GET` structure, the Origin/setup logic, provider
or transport code, `/shutdown` handling, and log-rotation policy.

## Git workflow

- One writable worktree per session, branch based on `develop`, integrated back
  to `develop`.
- Commit subject: `fix: contain the unauthenticated ingress compare crash`.
- Run the shared `pre-commit-review` skill before committing.

## Steps

### Step 1: add the regression tests first (they must fail)

In `tests/test_ingress_guards.py`, add `import socket` with the other imports,
then extend `IngressGuardTests` with a raw-socket helper and two tests. Follow
the file's existing `self._server()` helper style:

```python
    def _raw_request(self, port, request_bytes):
        sock = socket.create_connection(('127.0.0.1', port), timeout=10)
        self.addCleanup(sock.close)
        sock.sendall(request_bytes)
        data = b''
        while b'\r\n\r\n' not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        return data

    def test_non_ascii_path_is_rejected_not_crashed(self):
        server = _start_server(_test_state('/nonexistent'))
        self.addCleanup(server.shutdown)
        raw = self._raw_request(
            server.server_port, b'GET /\xff/x HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n')
        self.assertIn(b'403', raw.split(b'\r\n', 1)[0])

    def test_non_ascii_bearer_is_rejected_not_crashed(self):
        server = _start_server(_test_state('/nonexistent'))
        self.addCleanup(server.shutdown)
        raw = self._raw_request(
            server.server_port,
            b'POST /responses HTTP/1.1\r\nHost: 127.0.0.1\r\n'
            b'Authorization: Bearer \xff\r\nContent-Length: 2\r\n\r\n{}')
        self.assertIn(b'403', raw.split(b'\r\n', 1)[0])
```

No baseline change is needed for `tests/test_ingress_guards.py`: it is 89 lines,
well below the 300 soft cap. Keep the file under 300 lines.

**Verify**: `python3.14 -m unittest tests.test_ingress_guards -v` -> the two new
tests FAIL (the connection closes before any status line) and every existing
test passes.

### Step 2: make both compares byte-based

Replace `ai_router/router.py:105-112` with this shape; `token` is hoisted so
both compares take `bytes` (net +1 line):

```python
        prefix = '/' + self.server.state['token']
        token = self.server.state['token'].encode()
        candidate, sep, _ = self.path[1:].partition('/')
        if sep and hmac.compare_digest(candidate.encode('iso-8859-1'), token):
            return self.path[len(prefix):].removeprefix('/backend-api/codex'), True
        header = self.headers.get('Authorization', '')
        if header.startswith('Bearer ') and hmac.compare_digest(
                header[len('Bearer '):].encode('iso-8859-1'), token):
            return self.path.removeprefix('/backend-api/codex'), False
        return None, False
```

ASCII requests keep exactly the same decisions and return values; non-ASCII
input now compares false and falls through to the normal 403. Do not change the
`prefix` computation or the setup exemption. Then set the `ai_router/router.py`
value in `config/source-limits-baseline.json` to the new exact line count (396
with the edit above); the 400 hard cap still applies.

**Verify**: `python3.14 -m unittest tests.test_ingress_guards -v` -> all pass;
`wc -l ai_router/router.py` -> 396; `python3.14 tools/check_source_limits.py`
-> exit 0.

### Step 3: manual reproduction and full gates

Run this probe; the status line must now be `HTTP/1.1 403 Forbidden` where it
previously produced no response:

```bash
python3.14 - <<'EOF'
import socket, tempfile, threading
from ai_router.credentials import Credentials
from ai_router.router import Router

state = {'port': 0, 'token': 'test-token', 'openai_models': []}
server = Router(state, credentials=Credentials(state, tempfile.mkdtemp()))
threading.Thread(target=server.serve_forever, daemon=True).start()
sock = socket.create_connection(('127.0.0.1', server.server_address[1]), timeout=5)
sock.sendall(b'GET /\xff/x HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n')
print(sock.recv(200).split(b'\r\n', 1)[0])
sock.close(); server.shutdown(); server.server_close()
EOF
```

Then run the full suite, compile and source-limit gates from the table.

**Verify**: probe prints `b'HTTP/1.1 403 Forbidden'`; full suite exit 0; compile
exit 0; limits exit 0.

## Test plan

- New: non-ASCII path returns 403 (fails before the fix with a closed socket);
  non-ASCII bearer returns 403 (same).
- Existing `LoopbackBoundaryTests` cases pin that ASCII token behaviour, Origin
  rejection and missing-token 403 are unchanged.
- Structural pattern: `tests/test_ingress_guards.py:1-30`.

## Done criteria

- [ ] No reachable unauthenticated `compare_digest` call in
      `ai_router/router.py` receives `str` (the token-gated nonce compare at
      `ai_router/setup.py:49` is out of scope; see Maintenance notes).
- [ ] Both new tests fail before Step 2 and pass after it.
- [ ] `ai_router/router.py` stays at or below 400 lines and its baseline entry
      matches the new count; limits gate exits 0.
- [ ] Full suite and compile gate exit 0; the guard test file stays under 300.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- `.encode('iso-8859-1')` raises for any reachable input: stop and report
  (should be impossible for stdlib latin-1-decoded strings).
- `wc -l ai_router/router.py` would exceed 400 after the edit: stop and report
  instead of shipping an over-cap file.
- Any existing ASCII-path test changes behaviour: stop; this fix must be
  behaviour-preserving for ASCII.

## Maintenance notes

- When plan 128 splits `router.py`, move `authorized_path` as-is; the byte
  compare travels with it.
- If a future ingress surface compares secrets again, compare `.encode()`d
  bytes, never raw `str`.
- Known residual (found in adversarial review, accepted): `ai_router/setup.py:49`
  (`valid_nonce`) still compares `str` values, so a non-ASCII setup nonce
  raises the same `TypeError` on a token-bearing request while a setup window
  is live. That path already requires the path token and a live single-use
  nonce, and its holder can already spend the key and call `/shutdown`, so it
  is out of scope here; fold it in only if a token-gated traceback is ever
  treated as material.
