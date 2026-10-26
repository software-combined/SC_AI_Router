# Subagent tools: parent and child

Use the active runtime's schema as authority. The following examples match the
collaboration tools exposed in Codex on 2026-09-12. Other runtimes must discover
their equivalent; do not paste these shapes into a different API. Claude Code
has none of these tools, so it reads only the [Claude Code](#claude-code)
section at the end; everything before it is for Codex.

Codex V1 currently exposes `multi_agent_v1.spawn_agent` with `fork_context`,
`message` or `items`, `model` and `reasoning_effort`; it returns `agent_id`.
Use `fork_context=false` for a fresh child. It has no `task_name` or
`fork_turns`. Its wait tool takes `targets` (agent IDs) and `timeout_ms`.
The V2 examples below apply only when their actual schema is offered.
Never transpose V2 arguments into V1 or infer a child's ID from its nickname.

If `collaboration_plaintext` handoff tools are offered, use them for every
subagent assignment, message and follow-up, whatever the recipient. Otherwise
use the `collaboration` tools. Pass model and reasoning_effort explicitly.
External children need `fork_turns="none"`: inherited history can hold
encrypted items they cannot read. GPT through OpenRouter is external even when
the parent uses GPT. If a brief still arrives encrypted, apply the
transport-failure policy; an encrypted message containing a file path is not a
readable fallback.

## Codex: find the callable tool

Read the current native tool definitions first. Namespaces such as
`collaboration` and `collaboration_plaintext` can be callable directly while
absent from `ALL_TOOLS`. That catalogue covers only tools available inside
`functions.exec`; an empty search there says nothing about native tools.
Call offered native tools directly, using their actual schema.

Use deferred discovery only for tools the runtime marks as deferred. If the
runtime offers a read-only native status tool, such as `list_agents`, use it
when diagnosing access; it does not prove that spawning will succeed. When
delegation is already authorized, attempt the intended native operation before
declaring an offered tool unavailable. Respect denials and normal retry limits.

After a context reset, recheck definitions before adopting a saved claim that
tools disappeared. Report the missing current definition after supported
discovery, or the exact direct-call rejection. Distinguish full lanes, model
access and malformed arguments from a missing tool. Do not ask for an app
restart or a new chat solely because an `ALL_TOOLS` search is empty.

## Parent: launch and brief

The API makes `fork_turns`, `model` and `reasoning_effort` optional, but the parent
must pass model and effort explicitly for every fresh or partial-history child.
Omitting them can select configured defaults instead of the intended model;
writing "inherit GPT" or a model name in `message` does not select it.
Task names use lowercase letters, digits and underscores.
Store the returned agent id and canonical task name, not just your chosen label.
Send this external-model example through `collaboration_plaintext.spawn_agent`,
or `collaboration.spawn_agent` when no plaintext tools are offered:

The assignment message itself must begin with the selected model, fixed effort,
role/pass and task context, including follow-up assignments and replacement
models. Put the same label at the top of a file-based brief. Labels describe the
request; they never establish the served model or effort. Routine status replies
need not repeat the full assignment label.

```json
{
  "task_name": "inspect_parser",
  "fork_turns": "none",
  "model": "deepseek/deepseek-v4.1-flash",
  "reasoning_effort": "max",
  "message": "DeepSeek V4.1 Flash Max — Parser investigation for the empty-input fix. Read-only investigation. Inspect /absolute/worktree/parser.py and its callers. Identify the cause of the reported empty-input failure. Return file:line evidence, one smallest fix and a verification command. Do not edit, commit, contact external systems or delegate. Stop after finding the cause or identifying the missing evidence; report a blocker instead of guessing."
}
```

This OpenRouter example is valid only where the configured router and active
runtime accept that id. The tool description can list a small GPT subset even
when the router catalogue has more models. Check the installed route; omission
from descriptive text alone is not proof of rejection. A schema enum or actual
runtime prohibition still applies. Do not edit the router to force availability.

Choose a full-history native fork deliberately, only when inheritance is wanted
and verified in the active runtime. Full-history forks (`fork_turns` omitted or `"all"`) inherit parent model/effort
and do not accept overrides in this runtime. For an explicit native model use
`"none"` or a supported positive number string such as `"3"`; external children
require `"none"`. Give a no-history child
all necessary task context. Do not send secrets or unnecessary conversation.

A successful spawn proves request acceptance only. Record requested model/effort
and returned/served identity if provided; otherwise record served identity as
`unverified`. Do not report a model's quality from a run that never started.

For Codex V1, record the parent thread ID, returned child ID and assignment
start/completion times with UTC offsets. Router 1.0.11's installed
`ai_router.inspect_requests --agent-summary` can look up that exact pair and
window without credentials or paid calls; [router operations](https://github.com/software-combined/SC_AI_Router/blob/main/docs/operations.md#request-identity-and-failure-evidence)
owns the command. Retained reports identify what the upstream reported, not
independently attested model weights. Keep model and effort evidence separate,
preserve mismatches across retries, and label coverage as retained records only.
Unknown IDs, old routers, missing reports or unsupported clients stay
unverified. Recheck the ID/header contract with the zero-paid
`tools/probe_agent_identity.py` after a Codex upgrade; never guess a mapping.

## Parent: communicate and wait

```json
{"target":"inspect_parser","message":"The failing input is an empty array, not an empty string. Include that distinction in the analysis."}
```

Send that to the child above through `send_message` from the same tool set as
the spawn. It delivers information without starting a new turn on an idle
child. A tool acknowledgement is not proof the child read or acted on it;
inspect a reply or resulting work when it matters.

Use `followup_task` from that tool set with the same `target`/`message` fields to
assign follow-up work and wake an idle child. For a running child it supplies
steering; do not use it to create competing write ownership.

Use `collaboration.list_agents({})` for status and canonical names. Use
`collaboration.wait_agent({"timeout_ms":60000})` to wait for any mailbox update.
It returns a wakeup/status summary, not message content; messages and final
answers arrive separately. New user input can end the wait. Prefer bounded
waits that leave room for user progress updates; do not busy-poll.

The simplification pass in a pre-commit review is commonly the slowest child.
It may remain quiet while it reads the staged tree and relevant context, so
silence or a long wait is not evidence of a stall. Keep one active child and
wait through quiet periods; do not interrupt, respawn, or launch duplicate
write ownership just to produce progress text. Interrupt only for a reported
failure, an attention request, or an established runtime/transport timeout,
then inspect the worktree and index before any focused retry.

Use `collaboration.interrupt_agent({"target":"inspect_parser"})` to stop its
current turn. It remains available; interruption does not undo edits. Inspect
any partial changes before handing its write scope to someone else.

Call V2 collaboration tools directly. In that runtime they are not nested under
`functions.exec` and cannot be called as guessed `tools.collaboration.*` methods.
The V2 `wait_agent` has **no targets argument**. V1 instead requires agent-ID targets;
never reuse a previous `wait_agent.targets` shape without reading the schema.

## Child: report, ask for context, finish

At start, inspect only the assigned scope and constraints. A child can message
the parent using its canonical name, normally `/root` (derive the actual parent
from task context for nested tasks):

```json
{"target":"/root","message":"The empty-array failure is in parser.py:84. I am checking the caller contract before recommending a fix."}
```

Use `send_message` for progress or a blocker, from `collaboration_plaintext`
when those tools are offered. Make it actionable:
what evidence is missing, what work can continue, and what decision is needed.
Do not repeatedly poll for a reply. A parent message can arrive mid-work; apply
it while preserving the assigned scope. If it conflicts with current writes,
stop those writes and report their state before continuing.

Do not create a new Codex task to reply, and do not email/Slack stakeholders on
the parent's behalf without explicit authorization. Child questions normally go
to the parent; do not interrupt the user for information the parent already has.

Finish with a concise final answer containing the deliverable, inspected/changed
paths, evidence and checks, and unresolved gaps. A final answer is automatically
returned to the parent; a progress message alone does not finish the assignment.
Do not claim served model identity from your own name or from the prompt.

## Failures and other task APIs

If no native spawn tool is offered, use supported deferred discovery before
reporting it missing, then continue locally where the task permits. If a call is
rejected, distinguish a model-access error from malformed
instructions or transport. This task encountered router `invalid_instructions`
errors before research children started; that is a transport limitation, not a
benchmark or proof that the selected model lacks tools. Do not bypass exact-model
review gates by switching runtimes or fabricating review results.

A handoff refusal says nothing about model or provider availability. It does
not justify replacing an exact OpenRouter reviewer with a native model. The
router ends the parent turn with a terminal error before executing the bad
call; it cannot create a recoverable Codex tool result or decrypt the brief.
Never reinterpret ciphertext as text. Report the exact delivery blocker and
preserve the work. A completed turn without an assistant reply is not success.

Codex app `create_thread`, `send_message_to_thread`, `read_thread` and
`wait_threads` manage separate user-visible tasks, not child agents. Create one
only when the user explicitly asks. `wait_threads` uses
`targets:[{threadId,hostId,afterCursor}]` and `timeoutMs`; these fields do not
belong to `collaboration.wait_agent`. Verify a task's identity before sending;
read back material delivery instead of treating an echoed id as a receipt.

Upstream reference: the reviewed Codex `rust-v0.153.4`
[multi-agent handler](https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/core/src/tools/handlers/multi_agents_common.rs)
handler limits displayed override candidates to five. Runtime schemas and actual
acceptance remain the contract; an upstream source snapshot does not prove
this desktop build or provider served a requested model. The local update CLI
was separately verified as 0.153.1; its plugin behavior is documented in updates.

## Claude Code

Claude Code has no `collaboration` tools or fork settings. A parent starts a
child with the Agent tool and picks its model like this:

- A Claude model: set the Agent tool's `model` to `sonnet`, `opus`, `haiku` or
  `fable`, the only values it accepts. Leave it out and the child takes its
  agent definition's `model:`, else a configured default subagent model, or
  else the parent's model.
- A router model in a Claude desktop Code session in the subscription profile:
  use [router workers](../../router-workers/SKILL.md). That profile talks to
  Anthropic directly, so a native child cannot run a router model, and a
  router model id sent there fails with HTTP 404.
- A router model in a session attached to the router (an attached terminal
  session, or the desktop gateway profile): use an agent definition
  (`.claude/agents/<name>.md`) whose `model:` is the router listing id and
  whose `effort:` is the model's prescribed effort. Router workers'
  `router_worker.py --list` prints each listing id as `id`. Start the child by
  its `subagent_type` and leave the Agent tool's `model` out, because that
  would override the definition. `model: inherit` keeps the parent's router
  row instead.

Send follow-up work to the same child with SendMessage, using its name or
agent id; a new Agent call starts a fresh child without that context. Pass
`run_in_background: false` when you need the result in the same turn. Children
start in the background by default, and in headless `claude -p` a background
child's result does not come back in that turn.

Record the model the child actually resolved to as its served identity, or
`unverified` when you cannot see it; the label in the brief is not proof. The
entrypoint's brief, label and verification rules still apply, and no brief
carries secrets. As a child, end with one final answer that holds the
deliverable, paths, checks and gaps, and never claim a served model from your
own name or the brief.
