# Plan 093: Trim avoidable work from the prepare and failure paths

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat a985197..HEAD -- ai_router/context_budget.py ai_router/providers.py ai_router/claude.py ai_router/router.py tests/test_context_budget.py tests/test_claude_ingress.py`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P2; effort S-M; risk LOW-MED; confidence HIGH; category perf; depends on none.
- Planned at `a985197`, 2026-09-10.
- First proof: an aliased Claude request is rewritten from the already-parsed payload; an OpenRouter
  request materializes one payload string instead of two; failure paths no longer re-parse the body.

## Why this matters

Three independent avoidable costs on hot paths:

1. **Double serialization** — `ai_router/context_budget.py:20-35` `estimate()` builds a throwaway
   JSON string of input+tools for the token estimate, then `ai_router/providers.py:263` serializes
   the whole payload again for the wire. Every OpenRouter row has `context_window > 0`, so this
   runs on every routed request. Images are deliberately excluded from the estimate; deriving the
   estimate from the wire body is **rejected** because the 16 image-capable OpenRouter rows keep
   base64 image blocks, which would cause spurious fail-closed `context_length_exceeded` refusals.
2. **Claude alias re-parse** — `ai_router/claude.py:109-116` decodes and re-parses `raw_body` even
   though `ai_router/router.py:302` already parsed it (`payload` is passed into `prepare`).
3. **Failure-path image parse** — `ai_router/router.py:341` and `:389` call `_payload_has_image(prepared.body)`,
   which JSON-decodes the whole (≤16 MB) outgoing body. At `:341` the failure has no exception, so
   `providers.describe_failure` never reads `has_image` (`ai_router/providers.py:130-136`): the work
   is pure waste. Additionally, because `~x-ai` rows set `drop_images=True` and
   `comp.note_images` rewrites images to text before serialization (`providers.py:225`), the
   "Grok image turns stall" hint can currently never fire on the serialized body.

## Current state (verified at a985197)

- `ai_router/context_budget.py:28-30`:
  ```python
  total = len(json.dumps([_without_images(i) for i in items])) // 4
  if isinstance(payload.get('tools'), list):
      total += len(json.dumps(payload['tools'])) // 4
  ```
- `ai_router/providers.py:246-263`: `used = estimate_tokens(payload)` at `:249`; the fail-closed
  `ContextWindowExceeded` at `:252-259`; `json.dumps(payload).encode()` at `:263`.
- `ai_router/claude.py:107-116`: `slug = resolve(model)`; when `slug != model` it re-parses
  `raw_body` and serializes a new dict; otherwise the body travels byte-identical.
- `ai_router/router.py:61-74` `_payload_has_image(body)` parses bytes; called at `:341` (exc `None`)
  and `:389` (may be a `TimeoutError`). `payload` from `read_body` is available at `:192` and is
  mutated in place by `provider.prepare` at `:221`.
- `ai_router/capabilities.py:80-90` `has_images(items)` already walks a parsed payload for
  `input_image` blocks — reuse that logic rather than adding a third walker.

## Scope

**In scope**: `ai_router/context_budget.py`, `ai_router/providers.py`, `ai_router/claude.py`,
`ai_router/router.py`, `tests/test_context_budget.py`, `tests/test_claude_ingress.py`,
`tests/test_handler.py` (failure-path test only).
**Out of scope**: the `check_effort`/`check_images` semantics, `max_output_tokens` math,
`describe_failure` wording (except the has_image plumbing), Anthropic passthrough behavior for
non-aliased ids, the serialized wire shape for OpenRouter requests.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -m unittest tests.test_context_budget tests.test_claude_ingress tests.test_providers tests.test_handler` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; update baseline entries for any pinned file whose count changes (context_budget 35, providers 390, claude no entry, router 400) |

## Steps

### Step 1: Claude alias rewrite from the parsed payload (commit 1, independent)

In `ai_router/claude.py:107-116`, when `slug != model`, set `payload['model'] = slug` and
`body = json.dumps(payload).encode()` behind an `isinstance(payload, dict)` guard; on a non-dict
payload keep `body = raw_body`. Preserve the `slug != model` gate so direct slugs and subscription
rows stay byte-identical. Update the comment: the payload is the parsed form of this same body.
This incidentally fixes zstd bodies on the alias path (previously the decode failed and a compressed
body was forwarded under a `Content-Type: application/json` header).

**Verify**: new test in `tests/test_claude_ingress.py`: an aliased `anthropic/...` id with a
`claude/` discovery prefix gets `model` rewritten to the registry slug; a direct slug is forwarded
byte-identical; a zstd-compressed aliased body is rewritten to plain JSON.

### Step 2: image hint from the parsed payload, once (commit 2, independent)

Replace `_payload_has_image(body)` with `_payload_has_image(payload)` operating on the already-parsed
dict (reuse `capabilities.has_images` semantics: walk `payload['input']` for `input_image` blocks).
Compute `has_image = _payload_has_image(payload)` in `do_POST` immediately after `read_body` (before
`provider.prepare` mutates the payload), carry it into both `describe_failure` info dicts at `:336-341`
and `:384-389`, and delete the two serialized-body calls. This makes the hint reachable (pre-strip
images) and cheap.

**Verify**: update/extend a handler or providers test to assert the info passed to
`describe_failure` carries `has_image=True` for an image turn with a `~x-ai/` model; run the focused
package. If an existing test asserts the old byte-parse helper, port it to the payload form.

### Step 3: counting-writer estimate (commit 3)

In `ai_router/context_budget.py`, replace the two `json.dumps(...)` calls with `json.dump(..., sink)`
against a tiny counting sink (object with `write(self, s): self.size += len(s)`), keeping the exact
same structures (`[_without_images(i) for i in items]`, `payload['tools']`, `payload['instructions']`)
and `// 4` arithmetic. Do not change which fields count or the image exclusion. Add parity tests in
`tests/test_context_budget.py` that pin the returned counts against the previous implementation for:
images excluded, tools included, instructions included, malformed payload → 0.

**Verify**: focused tests pass; `rg -n "json.dumps" ai_router/context_budget.py` → no matches.

## Done criteria

- [ ] Aliased Claude requests no longer decode `raw_body`; direct slugs still byte-identical.
- [ ] `_payload_has_image` takes a parsed payload; `:341`/`:389` no longer decode the body.
- [ ] `context_budget.estimate` materializes no JSON strings; parity tests pass.
- [ ] Full suite, compile and limit gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- Any parity test shows the counting sink changes token counts for a real payload shape: stop; the
  fail-closed context check must not shift.
- A test proves OpenRouter image rows do strip images before serialization (making the hint genuinely
  dead): stop and report; the right fix may be removing the hint instead.
- `payload` is not in scope where assumed at `claude.py:103` (signature changed by another writer):
  stop.

## Maintenance notes

- If image accounting ever changes, update `context_budget` and the client counter together.
- The hint now reflects "turn had images" rather than "serialized body had images"; that is the
  intended meaning for the Grok stall message.
- Reviewers: confirm `providers.py` still serializes exactly once at `:263`.
