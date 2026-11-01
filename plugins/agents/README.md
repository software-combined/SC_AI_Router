# Agents

| Plugin | Skills |
| --- | --- |
| `scg-agent-factory` | [AI Agent Factory Method](scg-agent-factory/skills/ai-agent-factory-method/SKILL.md) |
| `scg-subagents` | [Choose models and coordinate subagents](scg-subagents/skills/optimal-subagents/SKILL.md), [router workers](scg-subagents/skills/router-workers/SKILL.md) |

The factory uses a persistent project orchestrator and role agents that own
areas end to end. Their chats and shared state continue across features.
The factory is self-contained and uses the host's subagent tools directly.
The separate Subagents plugin provides model-selection and delegation guidance
for tasks that request it.

Factory includes a [project progress template](scg-agent-factory/skills/ai-agent-factory-method/references/status-view.md).
It keeps human questions separate from team work and hides technical detail
until needed. Its offline HTML page also works with existing project owners;
using the template does not create a Factory team.

Department briefs live in the same plugin and appear under
[sales](../sales/README.md), [finance](../finance/README.md),
[operations](../operations/README.md), [customer success](../customer-success/README.md)
and [support](../support/README.md).

[All domains](../README.md)
