# SC Codex OpenRouter Adapter

Local adapter that serves configured OpenRouter models inside the Codex
desktop app alongside OpenAI subscription models: native subagents, model
switching with history, transparent compaction, computer use where the
upstream supports it, and a versioned path toward staff packaging with a
federated OpenRouter key.

- Canonical source: `codex-model-router/` (router, tool adapter,
  capabilities, compaction, catalogue writers, probes, tests, packaging).
- Operator docs: `codex-model-router/README.md` and `packaging/`.
- Agent rules: `AGENTS.md`.

Billing stays split by route: OpenAI requests keep the ChatGPT subscription,
OpenRouter requests use the existing credential read at request time.
Verify with the module test suite before every change; see `AGENTS.md`.
