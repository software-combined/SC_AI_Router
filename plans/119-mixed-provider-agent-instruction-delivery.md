# Plan 119: Preserve task instructions across mixed-provider delegation

> Follow the steps in order. Re-run the drift check and verification gates.
> STOP on unsupported native-client behavior rather than inventing decryption
> or declaring an unverified fallback successful. This is a planning document,
> not authorization to modify the installed client, run paid probes or deploy.
>
> Drift check: `git diff --stat 6840312..HEAD -- ai_router/providers.py ai_router/compaction.py ai_router/tool_adapter.py ai_router/catalogue.py ai_router/capabilities.py tools/probe_codex_runtime.py tests docs/compatibility.md`.
> Compare changed files with the excerpts below before implementation.

## Status

- Priority: P1
- Effort: M, staged
- Risk: MED; subscription catalogue changes would raise the risk and need a
  separate concrete decision after capture
- Depends on: none; coordinate Plan 060 error handling and Plan 062 extraction
- Category: bug / compatibility
- Planned at: `6840312`, 2026-09-09
- Status: TODO; local failure reproduced, successful transport not proved

Follow-up evidence: a file-path/task-name assignment was read and acknowledged
by one Muse Contributor/xhigh audit child. This may support bounded review
work when independently verified, but does not satisfy native plaintext
transport or follow-up delivery. Before deployment, check whether the opaque
input guard would reject that workaround too; do not present file delivery as
an automatic bypass or mark this plan complete from it.

## Outcome

An Astra parent can give a Muse Contributor child a unique synthetic marker
and a read-only assignment, then send a different follow-up marker; the child
returns both exactly without acting outside its scope. Unreadable encrypted
briefs produce a content-free actionable error before an upstream request.

Keep the containment fix, working plaintext delivery, deployment and paid
runtime acceptance as distinct gates. A rejected handoff fixes containment,
but does not complete this plan's working-delivery outcome.

## Current state

Repository: `/Users/cyrilallart/Documents/Github/SC_Codex_openRouter_adapter`.
Python 3.14+, standard library only. Offline tests never call providers.

On Codex CLI `0.153.4`, the owner's running router reports `0.6.9.22`.
The installed provider/compaction/tool adapter files match this plan's source.
The live catalogue preserves Astra v2 and sets Muse Contributor v1. Eleven
inspected agent messages across five failed audit children contain a readable
routing label plus an encrypted task block. Fresh children infer scope from
their names; children with inherited turns act on the broad parent request.
The content is present but unreadable. A child-side v1 setting alone is
insufficient. The exact client selection mechanism remains to be captured.

`ai_router/providers.py:205-216` currently prepares OpenRouter input with:

```python
payload['input'] = comp.scrub_tool_fragments(payload.get('input', []))
```

It then calls `prepare_tools`, `rewrite_input`, `strip_reasoning_blobs` and
image handling, and serializes the result. No client-delivery step handles `agent_message`.
> **Drift 2026-09-11 (Plan 122 reconciliation):** `compaction.rewrite_input` now lives at
> `:103-115` and already maps `agent_message` to plaintext (`:111-112`); the remaining gap is
> the client-side delivery path below. Anchors refreshed against the current tree.

It rewrites `agent_message` items as it walks the input:

```python
if is_compaction_item(item):
    rewritten.append(user_message_item(compaction_text(item)))
else:
    rewritten.append(item)
```

`_item_text` at line 215 omits agent messages from summary input.
`MULTI_AGENT_VERSION = 'v1'` in `capabilities.py:17` applies to OpenRouter
catalogue rows; native OpenAI metadata is preserved. Existing ordinary probes
disable collaboration and therefore cannot verify this contract.

Use the mocked credentials and provider preparation patterns in
`tests/test_mixed_router.py:16-29`; use `PreparationError`, never a raw provider
exception containing message content. Read the incident report in
`plans/2026-09-09-subagent-instruction-delivery.md` for evidence limits.

## Scope and ownership

In scope: the smallest request-normalization change in `compaction.py` and
`providers.py`; focused regression tests; a small synthetic native-client
capture/probe tool if needed; `docs/compatibility.md`; plan status; release
notes/version for an implemented user-visible change. Preserve source limits.

Inspect `catalogue.py`, `capabilities.py`, `tool_adapter.py` and the installed
client schemas to locate the contract. A catalogue or emitter change is
conditional on Step 2 proof, not a prescribed global v1 override.

Out of scope: architecture/domain moves, model roster changes, weakening
approval or sandbox policies, native OpenAI payload mutation, key handling,
raw body logging, decoding or retaining real encrypted blocks, staff changes,
paid-provider calls without authority, and patching proprietary client code.

Reuse the owning task's worktree. This planning task owns
`/Users/cyrilallart/Documents/Github/.worktrees/router-domain-audit-20260909`,
branch `codex/router-domain-audit-20260909`, target `develop`. A different
executor needs an explicit ownership handoff or its own independent worktree.
Never write in the primary checkout or another task's worktree.

## Steps

### 1. Reproduce and contain unreadable briefs

Construct a synthetic item with type `agent_message`, author `/root`, a
synthetic recipient, an `input_text` routing label, and an
`encrypted_content` block containing a dummy string. Add an ordinary user
message control. Call OpenRouter preparation with fake credentials.

The current bug is observable: the opaque item survives unchanged. A new
regression must require `PreparationError` before credentials or any outbound
connection is touched, preserving the control on plaintext-only requests.
Handle initial and follow-up positions; reject mixed plaintext/opaque brief
items too, since the hidden block could carry a scope restriction. Preserve
native subscription passthrough byte-for-byte. A generic text-only routing
label or missing scope is not a successfully delivered assignment.

The error should identify unsupported encrypted agent instructions and a
supported next step, without task text, ciphertext, tokens or raw metadata.
Coordinate Plan 060 so the diagnostic is safe on the client and in logs.
Demonstrate that the regression fails before the fix and passes afterward.

### 2. Capture the native plaintext contract without inference calls

Use an isolated scratch configuration and the installed client's documented
app-server surface, following `tools/probe_codex_runtime.py` RPC conventions.
Discover actual schemas; do not guess tool names or parameters. Bind a local
stub and use only synthetic input, no subscription headers or provider keys.
Stub a parent tool call and inspect what the native client creates for its
child. Keep production configuration and current task unchanged.

Compare the existing v2-parent/v1-child route with supported plaintext
emission. Vary parent metadata only in temporary catalogue copies. Exercise
follow-up delivery as well as spawn. Preserve only structural facts and
synthetic marker results. If the client cannot expose or emit a supported
plaintext handoff, stop at the containment milestone and document the client
limitation; do not claim the router can decrypt native content.

### 3. Implement only the proven plaintext path

If Step 2 proves a plaintext native agent item, normalize it at the OpenRouter
boundary into the endpoint's supported message format. Retain sender and
recipient context, text boundaries and item order. Do not elevate subagent
text above its authority; never turn arbitrary tool output or task text into
a new system/developer instruction. Reject remaining unreadable content.
Include plaintext agent messages in summary input so follow-up scope survives
compaction; encrypted inputs must reach the same guard on compact requests.

If plaintext requires changing the parent protocol or model metadata, first
prepare the exact limited change and its same-provider controls. Do not alter
all subscription rows or live user settings to make a test pass. A native
client change outside this repository is a recorded upstream dependency.

### 4. Verify working delivery and integrate

The offline regression suite must cover encrypted initial/follow-up items,
mixed content rejection, ordinary messages, the observed plaintext shape,
summary retention and unchanged OpenAI passthrough. Avoid speculative shapes.
Reuse shared tests and keep each file within repository source limits.

With explicit paid-probe authority, test Astra to Muse Contributor at xhigh:
initial marker, independent follow-up marker, child reply and a benign
read-only scope assertion. Keep markers out of inherited context and do not
infer delivery from the model greeting or task name. Include fresh/forked
variants and native-to-native and plaintext-to-plaintext controls where the
implemented change applies. Record requested and returned identities, using
`unverified` for absent served values. Never substitute required review models.

Run the commands below, then the current installed pre-commit-review skill
with the reviewer table freshly read from disk. If that review mechanism
depends on the broken route, report the exact gate; do not count a child with
an unreadable brief as a reviewer or switch runtimes to bypass the policy.
Commit bounded stages, target `develop`, verify the integrated result and
clean the task's worktree after safe integration. Deployment and live
acceptance require their own authority and readback.

## Verification commands

| Purpose | Command | Expected |
|---|---|---|
| Focused regression | `python3.14 -B -m unittest tests.test_mixed_router tests.test_compaction tests.test_tool_adapter` | All pass, including new behavioral tests |
| Full suite | `python3.14 -B -m unittest discover -s tests -t .` | All pass; baseline was 473 tests |
| Compilation | `python3.14 -m compileall -q ai_router tools tests` | Exit 0 |
| Source limits | `python3.14 tools/check_source_limits.py` | Zero failures |
| Patch hygiene | `git diff --check` | Exit 0 |

## STOP conditions and maintenance

Stop on changed native schemas, inaccessible plaintext content, requirements
for decryption keys, content logging, global subscription downgrades, missing
paid/deployment authority, or a required review model that cannot receive its
brief. Report exactly which milestone is achieved and which is blocked.

Do not repeat failed real audit assignments to test transport. Use one
bounded synthetic probe with an exact marker. Re-run this compatibility check
after client upgrades or changes to multi-agent catalogue metadata. A v1
catalogue value, successful spawn call, health response, or green ordinary
tool probe is never sufficient evidence of mixed-provider instruction delivery.
