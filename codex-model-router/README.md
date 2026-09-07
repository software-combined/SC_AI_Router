# Codex mixed-model adaptor

Canonical source for Cyril's local compatibility adaptor. The installed copy is
`~/.codex/mixed-model-router/`; it remains the runtime and private-state directory.
This source import is not a company deployment package. Python 3.14+ is required.

OpenAI requests retain the user's ChatGPT subscription authentication. The six
configured OpenRouter models use the existing OpenCode API credential, read at
request time. OpenAI account headers and cookies never accompany OpenRouter
requests. The service binds to loopback and requires the local bearer path token.

Credentials, local state, configuration backups, logs and the generated model
catalogue are deliberately excluded. Do not copy the entire runtime directory
into Git. Do not print the endpoint URL or private JSON files.

## Verification

From this directory:

```sh
python3 -m unittest discover -p 'test_*.py'
```

For an already configured local installation, the following bounded paid probe
requires native tool discovery, a synthetic tool invocation and its exact result:

```sh
python3 probe_codex_runtime.py z-ai/glm-5.3 --installed --deferred --effort max
```

Keep `supports_search_tool=true` and `tool_mode=null` in OpenRouter catalogue
entries. `capabilities.py` is the single source for per-model values:
plaintext V1 subagents, no forced-compaction hash, Node REPL offered, and
image input only where live metadata advertises it (GLM 5.3 stays text-only). The adaptor maps tool schemas and events; Codex
continues to enforce tool execution and permissions. Recheck compatibility after
Codex/provider upgrades. Initial verification used bundled Codex 0.153.4.

The existing `disable.py` belongs in the runtime directory, beside the private
activation receipt. It removes only the exact installed settings block and stops
the macOS LaunchAgent `com.local.codex-mixed-model-router`. A changed settings
block requires manual reconciliation. Never restore an old complete config over
newer settings.

The request cap and output-token cap are not spending budgets. HTTP streaming is
supported. Compaction uses a transparent summary envelope with visible
fallback for opaque native history; empty summaries are rejected.
Staff packaging lives in `packaging/` (versioned source, macOS/Windows
install stubs, federated OpenRouter key, never committed). No staff-wide
rollout without explicit release authority. Compaction handoffs are
same-trust-tier working notes, not trusted content; V1 keeps recent user
messages plus the summary and may drop older detail.
