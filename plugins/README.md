# Plugins and skills by domain

Start with the domain you need. Each domain links to its plugins and skills.

| Domain | Work |
| --- | --- |
| [Sales](sales/README.md) | Lead research, CRM work and outbound drafts |
| [Development](development/README.md) | Coding, review, testing and prototype publishing |
| [Finance](finance/README.md) | Financial analysis and finance delegation |
| [Operations](operations/README.md) | Processes, IT and HR work |
| [Customer success](customer-success/README.md) | Account health, onboarding and renewals |
| [Support](support/README.md) | Ticket triage and response drafts |
| [Documentation](documentation/README.md) | Technical writing and READMEs |
| [Agents](agents/README.md) | Model selection, delegation, router workers and outcome-owning agents |
| [Router management](../skills/manage-router/SKILL.md) | Set up, check, repair or remove SCG Router |

Author plugins under `plugins/<domain>/<plugin-name>/`. Keep each plugin's
manifests, skills, references and scripts together. Put a skill's supporting
files beside that skill, following the existing package structure.

Department delegation skills share `scg-subagents` because they use its model
selection and authority rules. Their domain pages link to that single source.
Keep plugin names and skill names stable when moving source folders.
The root `scg-openrouter` plugin remains separate from this marketplace.

Register each plugin's source path in
[the marketplace](../.agents/plugins/marketplace.json). Router delivery reads
both domain folders and older flat bundles, then writes the existing flat
client paths. Domain pages are repository navigation, not extra plugins.

See [installation and release rules](../docs/agent-plugins.md).
