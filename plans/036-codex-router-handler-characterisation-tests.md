# Plan 036: Pin the request handler's end-to-end behaviour with characterisation tests before refactoring it

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 749a6b8d..HEAD -- <ROUTER_ROOT>`
> On any in-scope change, compare the "Current state" excerpts against the
> live code first; on a mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (tests only)
- **Depends on**: Plan 035 (health JSON and `load_state`); can run before it if you skip the health assertion
- **Category**: tests
- **Planned at**: commit `749a6b8d`, 2026-09-07

## Path convention

`ROUTER_ROOT` is `domains/ai-platform/codex-model-router` pre-Plan 034 or the repository root post-034. Router module: `mixed_router.py` pre-034, `codex_router/router.py` post-034. New test file: `test_handler.py` pre-034, `tests/test_handler.py` post-034.

## Why this matters

The only tests that exercise `Handler.do_POST` end to end are the compaction branch tests. The main paths, an OpenRouter `/responses` request and an OpenAI subscription request, are covered only at the `route()` and `prepare_openrouter()` function level. Plan 037 will decompose the 115-line handler into a provider interface. Without a pinned end-to-end contract, that refactor can silently change what reaches upstream (headers, body fields, streaming adaptation) and the suite would still pass. These tests are the safety net. They also lock in the security invariants that matter most: the ChatGPT bearer never reaches OpenRouter, the OpenRouter key never reaches OpenAI, and hop headers and cookies are stripped.

## Current state

- `do_POST` at router module `:113-229` performs, in order: token path check (`authorized_path`, `:94-100`), route allow-list (`:118`), `Content-Length`/`MAX_BODY` check and optional zstd decode (`:121-131`), JSON parse, model presence check (`:136-137`), OpenRouter preparation (`prepare_tools`, `prepare_openrouter`, `:140-145`), request cap (`:146-150`), credential read from `state['opencode_auth']` (`:151-154`), compaction branch (`:155-...`), `route()` (`:31-43`), bearer requirement for chatgpt (`401`), then upstream relay with `http.client.HTTPSConnection(host, timeout=120)` at `:183` and chunked streaming with tool adaptation via `stream_events` when `custom_tools` is non-empty and the response is `text/event-stream`.
- The existing fake upstream used by the compaction tests, `test_mixed_router.py:99-110`:

```python
def _fake_conn_class(status, payload, seen=None):
    class FakeConn:
        def __init__(self, *a, **k):
            pass
        def request(self, method, path, body=None, headers=None):
            if seen is not None and body is not None:
                seen['body'] = json.loads(body)
        def getresponse(self):
            return _FakeResp(status, payload)
        def close(self):
            pass
    return FakeConn
```

and `_FakeResp` (`:92-97`) exposes only `status` and `read`. The relay also calls `response.getheaders()`, `response.getheader('Content-Type', '')`, `response.read1(65536)`, and iterates `for line in response` for SSE. The fake must grow to support those.

- Server start helper `_start_server(state)` (`:72-75`) binds port 0; `_test_state(auth_path)` (`:68-70`).
- `prepare_openrouter` (`:23-29`) removes `service_tier`, caps `max_output_tokens` at 32768, rewrites compaction items.
- Route allow-list: `NATIVE_SERVICE_PATHS = {'/alpha/search', '/alpha/notes/v2/thread_hint', '/guardian', '/guardian-classifier'}` (`:21`) plus `/responses` and `/responses/compact`.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Tests (pre-034) | `/opt/homebrew/bin/python3 -m unittest discover -s domains/ai-platform/codex-model-router -p 'test_*.py' -v` | `OK` |
| Tests (post-034) | `python3.14 -m unittest discover -s tests -t . -v` | `OK` |
| Only the new file | `python3.14 -m unittest tests.test_handler -v` (post-034) | `OK`, 10 tests |

## Scope

**In scope**: the new test file only. You may add a shared fake upstream helper module `tests/fakes.py` (post-034) or `test_fakes.py` (pre-034) and import it from the new file. Do not edit the router module.

**Out of scope**: any production code; `test_mixed_router.py` (leave its fakes in place; duplicate rather than refactor them).

## Git workflow

- Branch `codex/router-handler-tests-<yyyymmdd>`; commit type `test:`. Do not push unless instructed.

## Steps

### Step 1: Build a recording fake upstream

In the fakes module write `FakeUpstream(status, body_bytes, headers)` with attributes `status`, `getheaders()` returning a list of tuples, `getheader(name, default)`, `read()`, `read1(n)`, and `__iter__` yielding lines (split the body on `\n`, keeping the newline, so SSE blocks separated by blank lines work). Write `install_fake(testcase, responder)` that patches `http.client.HTTPSConnection` in the router module with a class whose `request(method, path, body, headers)` records `(host, method, path, body, headers)` into a list the test can inspect, and whose `getresponse()` returns `responder()`.

**Verify**: `python3.14 -c "import tests.fakes"` (post-034) exits 0.

### Step 2: Write the ten characterisation tests

Each test starts a real server via the pattern in `test_mixed_router.py` (temporary auth file containing `{"openrouter": {"type": "api", "key": "test-key"}}`, `_start_server`, `addCleanup(server.shutdown)`) and posts with `http.client.HTTPConnection('127.0.0.1', port)`.

1. `test_openrouter_request_reaches_openrouter_with_router_key_only`: POST `/test-token/responses` with `{"model": "z-ai/glm-5.3", "input": [{"type": "message", "role": "user", "content": "hi"}], "service_tier": "priority", "max_output_tokens": 99999}` and incoming headers `Authorization: Bearer subscription-secret`, `Cookie: c=1`. Assert the recorded upstream host is `openrouter.ai`, path `/api/v1/responses`, headers exactly `{'Authorization': 'Bearer test-key', 'Content-Type': 'application/json'}`, and the body JSON has no `service_tier` and `max_output_tokens == 32768`. Assert the string `subscription-secret` is absent from the recorded headers and body.
2. `test_openai_request_forwards_subscription_bearer_and_strips_hop_headers`: state `openai_models=['gpt-6-astra']`; POST with model `gpt-6-astra`, headers `Authorization: Bearer subscription-secret`, `ChatGPT-Account-ID: acct`, `Connection: keep-alive`. Assert host `chatgpt.com`, path `/backend-api/codex/responses`, headers include `Authorization` and `ChatGPT-Account-ID`, exclude `Connection`, `Host`, `Content-Length`, and never include `test-key`.
3. `test_openai_request_without_bearer_is_401`.
4. `test_unknown_model_is_400_and_never_reaches_upstream`: model `nobody/none`; assert 400 and the recorded request list is empty.
5. `test_unsupported_route_is_404`: POST `/test-token/nope`.
6. `test_oversized_content_length_is_413`: header `Content-Length: 17000000`, no body sent (use `conn.putrequest`/`putheader`/`endheaders` and then `getresponse()`); assert 413.
7. `test_zstd_body_is_decoded`: body `compression.zstd.compress(json.dumps(payload).encode())` with `Content-Encoding: zstd`; assert the upstream body decodes to the payload's model.
8. `test_upstream_status_and_body_are_relayed`: fake upstream returns 429 with JSON `{"error": "slow down"}`; assert client sees 429 and that body.
9. `test_streaming_tool_call_is_adapted_end_to_end`: payload includes a `custom` tool `exec` (as in `test_tool_adapter.test_freeform_tool_and_history_round_trip`) so `custom_tools` is non-empty; fake upstream returns `Content-Type: text/event-stream` and SSE blocks where the model emits a `function_call` named `exec` with arguments `{"input": "code"}`; assert the client receives a `response.output_item.done` event whose item has `type == 'custom_tool_call'` and `input == 'code'`.
10. `test_health_json` (post-Plan 035 only): GET `/test-token/health` returns 200 with `status == 'ok'`. Pre-035, assert 200 and skip the body shape.

**Verify**: `python3.14 -m unittest tests.test_handler -v` prints ten `ok` lines.

### Step 3: Run the whole suite and record the count

**Verify**: full suite `OK`; note the total test count in your report (the pre-plan count plus ten).

## Test plan

This plan is the test plan. Pattern to model on: `CompactBranchTests` in `test_mixed_router.py:112-188` for server start and POST helper, and `test_tool_adapter.test_freeform_tool_and_history_round_trip` for SSE wire construction.

## Done criteria

- [ ] New test file exists with the ten tests named above and all pass.
- [ ] Full suite ends `OK`.
- [ ] `git diff --stat` shows only the new test file and the fakes module.
- [ ] Tests never open a real network connection (grep the new file for `openrouter.ai` or `chatgpt.com` only inside assertions on recorded values).
- [ ] `plans/README.md` status row updated.

## STOP conditions

- The handler at the cited lines differs from the description (for example the credential read or `HTTPSConnection` call has moved); re-read and adapt the patch target, but STOP if the handler no longer uses `http.client.HTTPSConnection` at module scope, since the fake relies on that name.
- Test 9 cannot be made to pass without changing production code. Report the exact event sequence observed; do not "fix" the router here.

## Maintenance notes

- Plan 037 must keep these ten tests green without editing their assertions. Any assertion change there is a behaviour change and needs the operator's explicit approval.
- When Plan 040 lands, test 1's fixture writes the key through the new credential lookup (env var or key file) rather than the OpenCode file; update only the fixture setup.
