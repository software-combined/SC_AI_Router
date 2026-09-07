# SC Codex OpenRouter Adapter

Use OpenRouter models inside the Codex desktop app as first-class citizens:
subagents, model switching with history, compaction, and computer use, billed
to your OpenRouter key while OpenAI models stay on the ChatGPT subscription.

| Model | Subagents | Switching | Compaction | Computer use | Image input |
| --- | --- | --- | --- | --- | --- |
| Muse Spark 1.3 | yes | yes | yes | yes | yes |
| Muse Spark 1.3 Contributor | yes | yes | yes | yes | yes |
| GLM 5.3 Flash | yes | yes | yes | yes | yes |
| GLM 5.3 | yes | yes | yes | yes | text only |
| Kimi K3 | yes | yes | yes | yes | yes |
| Grok latest | yes | yes | yes | yes | yes |

Reasoning effort follows live OpenRouter metadata per model. Contributor
rejects `max`; requesting an unsupported effort fails loudly, never silently
downgrades.

Proof scope, kept current: computer-use state reads pass on all six models.
Subagents are proven with Flash and Contributor parents and Flash, Kimi, GLM,
and Muse children. Switching with history is proven Kimi to Flash.
Standalone compaction preserves a synthetic marker verbatim on Flash and
Kimi; retrieval after compact-then-switch is under diagnosis and not yet
claimed.

## How it works

- A loopback router (`codex-model-router/mixed_router.py`) keeps ChatGPT
  subscription authentication on OpenAI routes and attaches the federated
  OpenRouter key only to OpenRouter routes. Subscription headers never cross
  to OpenRouter. Codex keeps enforcing tool execution and permissions; the
  adapter only translates protocols.
- A merged model catalogue advertises the six models with proven
  capabilities: plaintext V1 subagents, no forced-compaction hash, Node REPL
  offered, image input where the provider advertises it.
- Compaction is transparent: a plain-language summary with exact values
  quoted verbatim, plus retained recent messages. Opaque history renders as a
  visible note, never a silent drop. Empty summaries are rejected.

## Requirements

- macOS with the Codex desktop app and Python 3.14+.
- An OpenRouter API key available to the router at request time (federated,
  never committed).
- The macOS LaunchAgent `com.local.codex-mixed-model-router`.

## Install and verify

New installs are operator-led from this source (see `AGENTS.md`). After any
change, verify from `codex-model-router/`:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_mixed_router test_tool_adapter test_capabilities test_compaction test_apply_catalogue test_packaging
```

Then run the bounded paid probes for tool round trip, switching, compaction,
and computer-use state (all read-only). A successful greeting is not proof.

## Operations

- Health: the router listens on loopback port 18749 and logs JSON request,
  compact, and transport events to its stdout log. No URLs, headers, keys, or
  payload text ever enter the logs.
- Spending guard: OpenRouter requests are capped per router process (default
  1000, explicit state key wins). The cap is an accidental-use guard, not a
  budget. A missing state key falls back to the default instead of failing.
- Rollback: every install keeps a timestamped backup of the live directory;
  restore it and restart the service. `disable.py` removes only this
  integration's exact settings block and stops the service.
- Compatibility: re-verify the catalogue and probes after Codex or provider
  upgrades. Compaction handoffs are same-trust-tier working notes, not
  trusted content.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `429` on OpenRouter models | Per-process request cap reached | Restart the router at an idle boundary |
| `400` on every OpenRouter request | Predated state or payload shape | Check the router log event, then state keys |
| `409` naming a fresh task | Opaque history the model cannot read | Start a fresh task; the note in context is the visible fallback |
| Model says no computer-use tool | Catalogue still disables Node REPL | Re-apply the catalogue from `capabilities.py` and restart |
| Chat shows first sentence as title | Title generation call failed | Retry in a fresh task; check router availability |

Staff packaging stubs live in `codex-model-router/packaging/`. No staff-wide
rollout without explicit release authority.
