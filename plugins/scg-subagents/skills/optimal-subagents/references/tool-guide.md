# Subagent tools: parent and child

Use the active runtime's schema as authority. The following examples match the
collaboration tools exposed in Codex on 2026-09-12. Other runtimes must discover
their equivalent; do not paste these shapes into a different API.

For externally billed recipients, use `collaboration_plaintext.spawn_agent`,
`collaboration_plaintext.send_message` and `collaboration_plaintext.followup_task`
when the router exposes them. Use `fork_turns="none"` for external children:
encrypted inherited history cannot be translated. Keep using the plaintext
namespace on later turns even if saved calls appear under `collaboration`;
Codex executes those aliases under their native names. Native OpenAI recipients
keep the original encrypted `collaboration` tools. If the required plaintext
surface is unavailable, apply the transport-failure policy; an encrypted
message containing a file path is not a readable fallback.

## Parent: launch and brief

`spawn_agent` takes `task_name`, `message`, optional `fork_turns`, `model`, and
`reasoning_effort`. Task names use lowercase letters, digits and underscores.
Store the returned agent id and canonical task name, not just your chosen label.
Send this external-model example through `collaboration_plaintext.spawn_agent`:

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

Full-history forks (`fork_turns` omitted or `"all"`) inherit parent model/effort
and do not accept overrides in this runtime. For an explicit native model use
`"none"` or a supported positive number string such as `"3"`; external children
require `"none"`. Give a no-history child
all necessary task context. Do not send secrets or unnecessary conversation.

A successful spawn proves request acceptance only. Record requested model/effort
and returned/served identity if provided; otherwise record served identity as
`unverified`. Do not report a model's quality from a run that never started.

## Parent: communicate and wait

```json
{"target":"inspect_parser","message":"The failing input is an empty array, not an empty string. Include that distinction in the analysis."}
```

Send that to the external child above through `collaboration_plaintext.send_message`.
For native recipients use `collaboration.send_message`. It delivers information without
starting a new turn on an idle child. A tool acknowledgement is not proof the
child read or acted on it; inspect a reply or resulting work when it matters.

Use the recipient's matching `followup_task` namespace with the same `target`/`message` fields to
assign follow-up work and wake an idle child. For a running child it supplies
steering; do not use it to create competing write ownership.

Use `collaboration.list_agents({})` for status and canonical names. Use
`collaboration.wait_agent({"timeout_ms":60000})` to wait for any mailbox update.
It returns a wakeup/status summary, not message content; messages and final
answers arrive separately. New user input can end the wait. Prefer bounded
waits that leave room for user progress updates; do not busy-poll.

Use `collaboration.interrupt_agent({"target":"inspect_parser"})` to stop its
current turn. It remains available; interruption does not undo edits. Inspect
any partial changes before handing its write scope to someone else.

Call collaboration tools directly. In this runtime they are not nested under
`functions.exec` and cannot be called as guessed `tools.collaboration.*` methods.
The current `wait_agent` has **no targets argument**. Some older runtimes differ;
never reuse a previous `wait_agent.targets` shape without reading the schema.

## Child: report, ask for context, finish

At start, inspect only the assigned scope and constraints. A child can message
the parent using its canonical name, normally `/root` (derive the actual parent
from task context for nested tasks):

```json
{"target":"/root","message":"The empty-array failure is in parser.py:84. I am checking the caller contract before recommending a fix."}
```

Use the recipient's matching `send_message` namespace for progress or a
blocker: `collaboration.send_message` for a native parent and
`collaboration_plaintext.send_message` for an external parent. Make it
actionable:
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

If spawning is unavailable, search deferred tools where supported, then continue
locally. If a call is rejected, distinguish a model-access error from malformed
instructions or transport. This task encountered router `invalid_instructions`
errors before research children started; that is a transport limitation, not a
benchmark or proof that the selected model lacks tools. Do not bypass exact-model
review gates by switching runtimes or fabricating review results.

If the handoff error requests `collaboration_plaintext`, use that exact tool
with a fresh readable assignment and the same intended recipient. Do not repeat
the rejected encrypted call or reinterpret ciphertext as text. If the corrected
call also fails, stop that delivery path and report the error under the bounded
fallback policy; a completed turn without an assistant reply is not success.

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
