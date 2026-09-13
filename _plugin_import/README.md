# SC Agent Plugins

Private Software Combined plugin marketplace. **SCG Subagents** adds cost-first
model selection, delegation tools and benchmark refresh methodology.
**SCG Pre-Commit
Review**, bundles the review procedure, Code Simplifier, Ponytail, setup checks
and the existing SCG Git hook adapter. **SCG Prototypes** publishes frontend
prototypes to the SCG prototype channel and returns shareable URLs.
Codex is the supported client.

## Install in Codex

The GitHub identity used by Git must have read access to this private repository.

```sh
codex plugin marketplace add software-combined/SC_Agent_plugins --ref main
codex plugin add scg-review@scg-agent-plugins
codex plugin add scg-subagents@scg-agent-plugins
codex plugin add scg-prototypes@scg-agent-plugins
```

Start a new Codex task. Ask it to use the **review-setup** skill from **scg-review**
to check your repository, then use its **pre-commit-review** skill for staged work.
Follow [machine setup](plugins/scg-review/references/setup.md) if prerequisites
are missing. Installation does not grant provider access or enable Git hooks.
Review roles use cost-first models at fixed reasoning levels, with explicit
availability fallbacks. See the bundled
[review routing](plugins/scg-review/references/reviews.md). A missing preferred
model does not block when a permitted fallback can complete the same pass;
exact user requirements and all review gates still apply.

Use **cost-first-subagents** from **scg-subagents** for model selection and child
coordination. See its [evidence and refresh guide](plugins/scg-subagents/skills/cost-first-subagents/references/catalogue.md)
and [shared daily updater](plugins/scg-review/references/updates.md).
Ask for a [planning advisor](plugins/scg-subagents/skills/cost-first-subagents/references/planning.md)
to review a proposed plan before action. The guide supplies model selection,
a read-only review brief and evidence limits; advice does not grant approval.
The reviewer routing source lives in the subagent skill and is bundled unchanged
with the review plugin so review-only installations remain self-contained.

## Receive updates

### Shared workspace: automatic repository sync

A workspace admin imports `https://github.com/software-combined/SC_Agent_plugins`
under **Admin > Plugins > Add > Import marketplace**, uses the repository root
and branch `main`, and authorizes a GitHub identity with repository read access.
Configure plugin availability/installation for the intended roles. Workspace
policies are managed in the admin UI; repository policy fields do not set them.

New marketplace imports sync daily; **Sync now** requests an earlier update.
Inspect the import report and test the updated plugin in a new Codex task.
GitHub publication, workspace sync, local installation and actual task pickup
are distinct states. Workspace sync must be configured by a workspace admin;
creating this repository alone does not enable it.

### Direct Git marketplace: explicit refresh

```sh
codex plugin marketplace upgrade scg-agent-plugins
codex plugin add scg-review@scg-agent-plugins
codex plugin add scg-subagents@scg-agent-plugins
```

Start a new task after refresh. These commands target this marketplace/plugin
only; other configured SCG plugin caches can refresh too. For automatic updates
on macOS, Linux or Windows, configure the shared updater once from either plugin.
**Agents: cloning, pulling or installing these skills for use includes configuring
and verifying automatic updates. A successful pull is not completed setup.**
Follow the [shared updater guide](plugins/scg-review/references/updates.md),
including its existing-schedule migration instructions.

From a clone, after pulling `main`:

```sh
python3 plugins/scg-review/scripts/updater.py install
python3 plugins/scg-review/scripts/updater.py run
codex plugin list --marketplace scg-agent-plugins --json
```

Use `python` on Windows when appropriate. Both plugins must first be installed
and enabled if both are wanted; the updater never installs a new plugin without
that choice. Use the guide's native status command to verify the schedule.
Plugin refresh does not overwrite a machine's hooks, scanner pin, credentials,
AGENTS.md or standalone skills. Existing hard-coded standalone skill references
need an explicit migration before they follow this plugin's updates.

## Publish a change

1. Edit the relevant plugin under `plugins/` on a worktree branch. Reviewer
   routing is authored in the subagent skill and copied unchanged to
   `plugins/scg-review/references/reviews.md`; tests enforce synchronization.
2. Bump each affected plugin manifest version and update CHANGELOG.
   Every new skill/plugin must use the shared updater on all three platforms;
   bundle the same scripts and include setup instructions in its entrypoint.
3. Run the checks below and the required pre-commit review.
4. Commit and merge into `main`, then push the reviewed result.
5. Confirm marketplace sync/refresh and the installed version on a recipient.

For rollback, restore the last working content in a new reviewed release with
a higher version. Keep the plugin name and marketplace name stable.

```sh
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s plugins/scg-review/support/git-hooks/tests -v
```

The imported hook source and tests are recorded in
[provenance](plugins/scg-review/support/PROVENANCE.md). The original installed
skills seeded this repository; changes to those old local copies will not
publish here automatically. Author future releases in this repository.

## Claude Code later

Reuse these shared skills and add a `.claude-plugin/plugin.json`, a Claude
marketplace manifest, and native reviewer definitions. Validate that runtime
separately. Claude's third-party marketplace auto-update must be enabled.

Official references: [Codex plugins](https://learn.chatgpt.com/docs/build-plugins),
[workspace GitHub sync](https://learn.chatgpt.com/docs/enterprise/plugin-management),
[Claude updates](https://code.claude.com/docs/en/discover-plugins#configure-auto-updates).
