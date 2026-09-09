# Subagent instruction delivery investigation, 9 September 2026

## Finding

The failed Muse audit briefs were present in Codex's child conversation as
`agent_message` items with an `input_text` routing label and an
`encrypted_content` block. The task itself was not available as ordinary
readable text. The OpenRouter preparation path neither converts nor rejects
this item. This is a concrete mixed-provider compatibility gap, not evidence
that Muse cannot delegate or that its task was submitted empty.

The installed catalogue has `gpt-6-astra.multi_agent_version = "v2"` and
`meta/muse-spark-1.3-contributor.multi_agent_version = "v1"`. Setting v1 on
the receiving model does not establish plaintext delivery from a v2 sender.
Attribution of encryption specifically to the sender's v2 setting is strongly
supported by these observations, but a controlled v1/v2 client capture is
still required before prescribing a catalogue change.

## Evidence and limits

- Audit worktree source: `6840312510c182f4a7e2f439ab5229e36293fc6a`.
- Installed Codex CLI: `0.153.4`. Running router `/health`: status `ok`,
  version `0.6.9.22`. Its installed `providers.py`, `compaction.py`, and
  `tool_adapter.py` are byte-identical to this audit's copies. These readbacks
  establish the implementation currently present, not a successful handoff.
- Inspected five child records created by this task: the three first-pass
  audit agents and two retries. All eleven inspected initial/follow-up
  `agent_message` items contain an encrypted block. No plaintext audit brief
  occurs inside those items. Only types, lengths and presence were needed;
  no encrypted block or private instruction text belongs in this report.
- First-pass children were created without inherited turns. The initial
  runtime lane reported an empty brief and inferred a network-domain audit
  from its task name.
- Retry children inherited the original broad audit request and the user's
  retry message. Their scoped review brief was still encrypted. They acted
  on the broad request; one produced duplicate plan files. Their records
  contain no read of the dedicated review brief before that work.
- Child turn configuration records name Muse Contributor and `xhigh`.
  These are requested settings; the served model/effort remain `unverified`.
- Synthetic replay through `OpenRouterProvider.prepare` confirmed that an
  opaque agent item is forwarded unchanged and ordinary user text is
  preserved. No network requests or real credentials were used.
- `compaction._item_text` also returns an empty string for `agent_message`.
  Thus agent content is omitted from local summary input. This is a second
  source gap; compaction was not needed to trigger this incident.
- Original production wire bodies were not captured. The exact OpenRouter
  parsing behavior for native `agent_message` has not been isolated. The
  observed child records plus identical installed code and synthetic replay
  establish the local compatibility gap without proving every upstream hop.

## Code ownership

- `codex_router/providers.py:167`: OpenRouter request preparation calls the
  fragment scrub, tool adapter, compaction rewrite and reasoning/image
  transforms before serialization; none handles agent messages.
- `codex_router/compaction.py:102`: `rewrite_input` handles compaction items
  only. `strip_reasoning_blobs` at line 191 handles top-level reasoning only.
  It does not recover encrypted agent content.
- `codex_router/compaction.py:213`: `_item_text` recognizes messages, selected
  tool records, reasoning and compaction; agent messages fall through empty.
- `codex_router/capabilities.py:17` and `codex_router/catalogue.py:40` select
  v1 for OpenRouter entries while native OpenAI values remain intact.
- `tools/probe_codex_runtime.py:84` disables `collab` and `multi_agent` for
  its ordinary probe. Existing tool smoke passes do not test child delivery.

## Smallest correction

1. Add a content-free preparation error for an unreadable encrypted agent
   brief destined for OpenRouter. Reject before credential lookup/upstream
   dispatch; do not let a child infer its assignment from inherited context.
2. Capture the native client handoff with synthetic data and a local stub.
   Determine where supported plaintext emission must be selected. Inspect
   both the emitting parent and receiving child, not just the child catalogue.
3. If the client supports a usable plaintext agent item, normalize that item
   into an ordinary message while retaining sender/recipient context, message
   order and instruction precedence. Include it in compaction summaries.
4. Verify the complete path with a synthetic marker and bounded authority:
   initial spawn, follow-up, child reply and same-provider controls. The
   marker must be absent from inherited context so guessing cannot pass.

There is no router-owned decryption key or decoder for native agent blocks.
Do not mistake `ocx1` compaction decoding for native agent decryption. Do not
change all subscription models to v1 or create another user-visible task as
an untested workaround. [Plan 066](066-mixed-provider-agent-instruction-delivery.md)
owns the bounded implementation and acceptance work.

## Closeout

Follow-up during the full backlog audit: one fresh Muse Contributor/xhigh
child successfully read a non-secret brief file whose path was conveyed by
its task name, returned the unique acknowledgement marker and delivered the
requested read-only findings. The parent verified the actual file-read call.
This is a demonstrated workaround for file assignments, not a repaired
initial/follow-up native message path. Served identity/effort remain
`unverified`. Plan 066 must account for any containment guard also rejecting
the opaque item accompanying this workaround.

Investigation and planning only. No router source, live configuration,
installed catalogue or service was changed; no new paid probe was run. The
earlier six architecture plans remain valid, with this transport issue to be
addressed before relying on mixed-provider review agents.
