# Agents

| Plugin | Skills |
| --- | --- |
| `scg-agent-factory` | [AI Agent Factory Method](scg-agent-factory/skills/ai-agent-factory-method/SKILL.md) |
| `scg-subagents` | [Choose models and coordinate subagents](scg-subagents/skills/optimal-subagents/SKILL.md), [router workers](scg-subagents/skills/router-workers/SKILL.md) |

The factory uses a persistent project orchestrator and role agents that own
areas end to end. Their chats and shared state continue across features.
Subagents supplies model selection and temporary helper delegation when needed.
These are separate top-level plugins; a role owner can complete work without
temporary helpers.

Department briefs live in the same plugin and appear under
[sales](../sales/README.md), [finance](../finance/README.md),
[operations](../operations/README.md), [customer success](../customer-success/README.md)
and [support](../support/README.md).

[All domains](../README.md)
