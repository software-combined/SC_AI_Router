# Plan 163: Listener robustness and token hygiene

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report; do not improvise.
> When done, update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat c068368..HEAD -- ai_router/router.py ai_router/setup.py ai_router/key_prompt.py packaging/install.py tests/test_ingress_guards.py tests/test_setup.py tests/test_setup_handler.py tests/test_key_prompt.py tests/test_lifecycle.py tests/test_install_key_window.py tests/test_install_config.py config/source-limits-baseline.json`
> If any in-scope file changed, compare the "Current state" excerpts against
> the live code before proceeding; on a mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none; serialize with 164 on `ai_router/router.py` (163 first)
- **Category**: security, robustness
- **Planned at**: commit `c068368` (`origin/develop`), 2026-09-13
- **Source**: `plans/2026-09-13-router-four-lane-audit.md`, finding F3

## Why this matters

Five small gaps share one theme: the loopback listener should never crash a
request thread, drop a request it accepted, or expose the path token.

1. A body of about 1.2 KB nesting 600 arrays (the audit reproduced 1,242
   bytes; the Step 1 snippet builds 1,271) parses in `json.loads` (the C
   scanner is bounded) and then raises `RecursionError` in
   `image_items.count_images`, which uses two to three Python frames per
   level. `RecursionError` is not in the handler's `except` tuple, so the
   connection is dropped with no response and a traceback lands in the
   supervisor log, which rotates only at service start. Reproduced on
   2026-09-13. This is the class of crash plan 136 removed for the
   unauthenticated `TypeError`; this one needs the token.
2. The setup nonce is compared with `hmac.compare_digest` on two `str`
   values (`ai_router/setup.py:50`); plan 136 moved the token compare to
   bytes for exactly this reason (`ai_router/ingress.py:59-61`). A non-ASCII
   nonce during a live setup window raises `TypeError` the same way.
3. `do_POST` reads `server.draining` outside the lock and claims the
   in-flight slot afterwards; `drain_and_exit` sets the flag, samples
   `inflight == 0` and calls `os._exit(0)`. A request between the two
   moments is killed with no response and no `request_completed` record.
4. `Router` inherits the stdlib listen backlog of 5. Codex opens several
   sub-agent connections at once; the sixth pending connect is dropped and
   the client waits for a SYN retransmit (about a second on macOS) before
   its turn begins. The in-flight cap from plan 146 is applied after
   `accept`, so it does not help here.
5. The installer starts the native key window with the setup URL, which
   carries the path token and the nonce, as a process argument
   (`packaging/install.py:276`). On a shared machine another local user can
   read it from `ps` for as long as the dialog is open (up to 900 s). The
   key itself never touches `argv` (`ai_router/key_dialog.py:1-8`); the token
   should not either.

## Current state (verified at c068368)

- `ai_router/router.py:17-23`: `MAX_INFLIGHT = 32`; `class Router(ThreadingHTTPServer)` sets `daemon_threads`, `drain_deadline_s`, `max_inflight` and nothing else.
- `ai_router/router.py:49-58` (`drain_and_exit`): sets `self.draining = True` with no lock, calls `self.shutdown()`, polls `self.inflight`, then `os._exit(0)`.
- `ai_router/router.py:103-104`: `if self.server.draining: return self.drain_reject()` before the lock; `:122-129`: the lock section that compares `inflight` to `max_inflight` and increments.
- `ai_router/router.py:191-192`: the generic handler is
  `except (ValueError, KeyError, OSError, zstd.ZstdError, AttributeError, TypeError) as exc:`
  and `errors.map_client_error` (`ai_router/errors.py:233-260`) returns
  `invalid_payload()` (400) for anything it does not recognise.
- `ai_router/setup.py:42-52` (`valid_nonce`): `if not hmac.compare_digest(nonce, expected): return False` at `:50`.
- `packaging/install.py:271-283` (`_open_key_window`): `subprocess.Popen([python, '-m', 'ai_router.key_prompt', setup_url, '--clients', clients], ..., stdin=subprocess.DEVNULL, ...)`.
- `ai_router/key_prompt.py:155-172`: `_parse(argv)` accepts exactly one positional URL starting with `http://127.0.0.1:` plus an optional `--clients` pair; `main` prints usage and returns 1 otherwise.
- Test patterns: `tests/test_ingress_guards.py` (server through `tests/harness.py`, `install_fake` upstream, assert status plus stable code plus no upstream call); `tests/test_setup.py:54` (`test_nonce_validation`); `tests/test_key_prompt.py:298-305` (`test_cli_parses_the_client_set`) pins `_parse`; `tests/test_lifecycle.py` covers drain.
- The key-window `Popen` is pinned in `tests/test_install_key_window.py:59`
  and `tests/test_install_config.py:273`: both assert the recorded `argv`
  carries `/setup/<nonce>` in its fourth element. `tests/test_install_config.py:278`
  also asserts `kwargs['stdin']` is `subprocess.DEVNULL`, above a comment that
  the popup must never hold the installer's pipes. `tests/test_install.py`
  does not touch the key window. Each case defines its own local `FakePopen`
  that records the command (and at `tests/test_install_config.py:254` the
  keyword arguments) and exposes no `stdin`; there are nine of them across the
  two files.
- Line budget: `ai_router/router.py` is 219 lines (soft cap 250); its
  baseline entry (204) is inert and plan 166 removes it.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_ingress_guards tests.test_setup tests.test_setup_handler tests.test_key_prompt tests.test_lifecycle tests.test_install_key_window tests.test_install_config tests.test_handler` | all pass |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Lint | `python3.14 -m ruff check --select F401,F811 ai_router packaging tools tests` | pass |
| Limits | `python3.14 tools/check_source_limits.py` | `failures=0` |
| Policy scans | `python3.14 tools/check_policy_scans.py` | pass |

## Scope

**In scope**: `ai_router/router.py`, `ai_router/setup.py` (one line),
`ai_router/key_prompt.py`, `packaging/install.py` (`_open_key_window` only),
`tests/test_ingress_guards.py`, `tests/test_setup.py`,
`tests/test_setup_handler.py`,
`tests/test_key_prompt.py`, `tests/test_install_key_window.py`,
`tests/test_install_config.py`, `CHANGELOG.md`,
`packaging/VERSION`, `pyproject.toml` (version),
`config/source-limits-baseline.json` if a count changes.

**Out of scope**: `ai_router/ingress.py` (plan 146 owns its guards),
`ai_router/image_items.py` (the walk stays; containment is the fix),
`ai_router/model_prompt.py` (its nonce compare already encodes both sides),
any change to the in-flight cap value, any automatic port re-binding.

## Git workflow

- Worktree based on `develop`; branch like `<you>/163-listener-hygiene-20260913`.
- One commit per numbered step is fine; subjects like
  `fix: answer deeply nested bodies with 400 instead of dropping the connection`.
  Run `pre-commit-review` before each commit. No push or PR unless instructed.

## Steps

### Step 1: Contain `RecursionError`

`ai_router/router.py:191`: add `RecursionError` to the tuple. No change to
`errors.map_client_error` is needed: an unrecognised exception already maps
to `invalid_payload()`. Add to `tests/test_ingress_guards.py`:

```python
    def test_a_deeply_nested_body_is_400_not_a_dropped_connection(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server()
        depth = 600
        body = ('{"model": "z-ai/glm-5.3", "input": ' + '[' * depth
                + '{"type": "input_text", "text": "x"}' + ']' * depth + '}').encode()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('POST', '/test-token/responses', body=body,
                     headers={'Content-Type': 'application/json'})
        response = conn.getresponse()
        self.assertEqual(response.status, 400)
        self.assertEqual(json.loads(response.read())['error']['code'], 'INVALID_PAYLOAD')
        self.assertEqual(recorded, [])
```

Before the fix this test fails with `http.client.RemoteDisconnected`; run it
once unfixed to confirm, then fix.

**Verify**: `python3.14 -B -m unittest tests.test_ingress_guards` → pass.

### Step 2: Compare the nonce as bytes

`ai_router/setup.py:50`:

```python
    if not hmac.compare_digest(nonce.encode('iso-8859-1'), expected.encode('iso-8859-1')):
```

with a one-line comment citing plan 136's reason (`ai_router/ingress.py:59-60`
has the wording). `expected` is always ASCII (`secrets.token_urlsafe`); the
URL nonce is latin-1 decodable by construction of `http.server`. Extend
`tests/test_setup.py::test_nonce_validation` with
`self.assertFalse(setup.valid_nonce(state, '\xff'))` (no exception) and a
handler-level case that a live window answers 404 for a non-ASCII nonce.
`http.server` never percent-decodes the request target, so `%FF` reaches
`valid_nonce` as the ASCII string `%FF` and answers 404 with or without the
fix; send the raw byte instead, `GET /<token>/setup/\xff`, through the
raw-socket helper `tests/test_ingress_guards.py::_raw_request` (used by
`test_a_hostless_http10_request_still_answers`), and confirm it drops the
connection before the fix and answers 404 after.

**Verify**: `python3.14 -B -m unittest tests.test_setup tests.test_setup_handler tests.test_ingress_guards` → pass. Put the handler case where the server has a home: `tests/test_setup_handler.py` already builds a real `Credentials(state, home, env={})` and a live window, and the raw socket is opened the way `tests/test_ingress_guards.py::_raw_request` does. A server built by the shared harness's default `StubCredentials` cannot serve `/setup/` — it has no `home` and `ai_router/setup.py:297` reads it before the nonce — so the case must use real credentials, not that default.

### Step 3: Decide drain and admission under one lock

In `ai_router/router.py` `do_POST`, keep the early `if self.server.draining`
check at `:103-104`: it still guards the branches that sit above the lock
(`/shutdown`, `/setup/`, `/model-prompt/`), and it is also a cheap first pass
for owned requests. Add the same decision to the lock section at `:122-129`
so admission and the drain flag are read together:

```python
        with self.server.lock:
            if self.server.draining:
                verdict = 'draining'
            elif self.server.inflight >= self.server.max_inflight:
                verdict = 'over'
            else:
                self.server.inflight += 1
                verdict = None
        if verdict == 'draining':
            return self.drain_reject()
        if verdict == 'over':
            return self.retryable_reject(errors.too_many_inflight(), retry_after='1')
```

Leave the `/shutdown`, `/setup/` and `/model-prompt/` branches above the lock
as they are (they take no slot). The early check stays for good: the lock
section never sees those branches, and without it a second `/shutdown` starts
a second drain thread. In `drain_and_exit`, set the flag under the same lock:

```python
        with self.lock:
            self.draining = True
```

The lock is never held across I/O, so contention is unchanged.

**Verify**: `python3.14 -B -m unittest tests.test_lifecycle tests.test_ingress_guards` → pass. Add one case that pins the check and the increment to one critical section: hold `server.lock` from the test thread, start a POST on another thread, wait until the handler is actually blocked on the lock before flipping the flag (connect first, then a short bounded poll plus `time.sleep(0.05)` is enough — without that handshake the POST has not reached the handler, the case passes against the pre-fix code and pins nothing), set `draining` under the same lock, release, and assert 503 with `Retry-After: 2` and `inflight == 0`. The existing cap case sets `max_inflight = 0` and the drain cases set `draining` before the request, so neither discriminates.

### Step 4: Raise the listen backlog

Add `request_queue_size = 64` to `class Router` beside `daemon_threads`.
`server_activate()` calls `listen(request_queue_size)`, including on the
inherited launchd socket (`ai_router/router.py:41`). Add a one-line test in
`tests/test_ingress_guards.py` that `router_mod.Router.request_queue_size == 64`
with a comment naming why (parallel sub-agent connects; the stdlib default
is 5). This is not the rejected request cap: `tools/check_policy_scans.py`
greps for the two retired cap identifiers, and a listen backlog admits
bursts rather than refusing them.

**Verify**: `python3.14 tools/check_policy_scans.py` → pass; focused tests pass.

### Step 5: Keep the setup URL out of `argv`

- `ai_router/key_prompt.py`: extend `_parse` so `--stdin` replaces the
  positional URL: when `args == ['--stdin']` (after the `--clients` pair is
  stripped), read one line from `sys.stdin`, strip it, and apply the same
  `http://127.0.0.1:` check. Keep the positional form for manual use; update
  the usage string and module docstring (`:13`, `:169-170`).
- `packaging/install.py:276-280`: pass `'--stdin'` instead of `setup_url`,
  open the child with `stdin=subprocess.PIPE`, write one line to `proc.stdin`
  and close it. This deliberately changes a pinned invariant:
  `tests/test_install_config.py:278` asserts `stdin=DEVNULL` today so the
  popup never holds the installer's pipes. The replacement keeps that
  guarantee by writing once and closing at once, never reading the pipe. A
  `PIPE` is binary unless the child is opened with `text=True`, so either
  pass `text=True` or write `(setup_url + '\n').encode()`. Wrap the write
  and close in the same best-effort handling the spawn already has (`except
  OSError: pass`, or move both inside the existing `try`): the child can
  exit before the write lands, and a bare `BrokenPipeError` would abort an
  install that has already succeeded, against `AGENTS.md`'s "no popup ever
  blocks or fails an install". Add one case whose fake `stdin.write` raises
  `BrokenPipeError` and assert `do_install` still returns 0 and prints the
  fallback line. The child is detached (`start_new_session=True`) so the
  parent does not wait. Keep the TTY-only `print` at `:273-274`; that goes
  to the operator's own terminal.
  **Budget**: `packaging/install.py` is 698 lines against the 700
  `packaging` hard cap, so the write and close must not add net lines
  (reuse the call site, drop a line, or keep the guard inline); STOP if the
  file would exceed 700.
- `tests/test_key_prompt.py`: add `_parse(['--stdin', '--clients', 'both'])`
  with `sys.stdin` patched to `io.StringIO('http://127.0.0.1:1/t/setup/n\n')`
  returning that URL and `'both'`; and a bad line returning `(None, None)`.
- `tests/test_install_key_window.py:59` and `tests/test_install_config.py:273`
  currently assert the setup URL is the fourth `argv` element: replace each
  with an assertion that no element of the recorded `argv` starts with
  `http://`. Change the `stdin` pin at `tests/test_install_config.py:278`
  from `DEVNULL` to `PIPE` and keep its comment, restated for the new
  mechanism. Every `Popen` substitute that spawns the key window needs a
  stub `stdin` with `write` and `close`, or the installer's write raises
  `AttributeError` — that is the nine `FakePopen` classes plus the two bare
  `lambda *a, **k` stubs at `tests/test_install_config.py:304` and
  `tests/test_install_key_window.py:459`, which return `None` today and must
  return a stub object instead. Define one module-level stub per file and
  reuse it: `tests/test_install_key_window.py` is 470 lines against the 500
  `tests` hard cap, so a per-case stub for each of its six classes plus the
  lambda would leave almost no headroom.

**Verify**: `python3.14 -B -m unittest tests.test_key_prompt tests.test_install_key_window tests.test_install_config` → pass.

### Step 6: Changelog and version

Add a `CHANGELOG.md` entry (one to three lines: nested-body 400, drain
admission, backlog, setup URL off the command line) and bump
`packaging/VERSION` with the `pyproject.toml` version unless already bumped
on your branch. Re-sync the baseline only if a file crosses its soft cap.

## Test plan

- New cases: nested body → 400; non-ASCII nonce → False and 404;
  `request_queue_size` pinned; `--stdin` parsing; installer `argv` carries
  no URL.
- Existing: `tests/test_lifecycle.py` drain cases and the plan 146 cap cases
  keep passing.
- Full suite exit 0 with at least 1336 tests.

## Done criteria

- [ ] `grep -n "RecursionError" ai_router/router.py` shows it in the except tuple.
- [ ] `grep -n "compare_digest(nonce" ai_router/setup.py` shows both sides encoded.
- [ ] `grep -n "request_queue_size" ai_router/router.py` shows `64`.
- [ ] `grep -n "setup_url, '--clients'" packaging/install.py` returns no matches.
- [ ] Full suite, compile, lint, limits and policy scans pass; only in-scope files changed.
- [ ] `plans/README.md` status row for 163 updated.

## STOP conditions

- The nested-body test does not fail before the fix (the repository has
  changed the walk): report what happens instead.
- `tests/test_key_prompt.py` pins that `_parse` accepts exactly one
  positional argument in a way that forbids a flag: report before changing
  the contract.
- `ai_router/router.py` crosses 250 lines: re-sync the baseline rather than
  splitting; if it would cross 400, STOP.
- Any verification fails twice after a reasonable fix.

## Maintenance notes

- Any new place that walks client JSON recursively inherits Step 1's
  containment; do not add a second recursion guard per walker.
- Plan 164 restructures `do_POST`/`_owned_post` next; it must keep the
  single lock section from Step 3.
- If a future dialog is spawned by the installer, it takes the URL on
  stdin the same way; a reviewer should reject a token in `argv`.
