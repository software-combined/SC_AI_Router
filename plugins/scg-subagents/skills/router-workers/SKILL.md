---
name: router-workers
description: Run a bounded task on a router model (the SCG Router's OpenRouter models, such as DeepSeek, GLM, MiMo, Muse, Kimi, Qwen, Gemini, Grok or the GPT twins) as an isolated headless Claude Code worker with shell and file tools. Only for a Claude desktop Code session in the subscription profile (the first-party profile that talks to Anthropic directly). Use when the user asks to use or delegate to one of those models, to fan work out to other or cheaper models, or when optimal-subagents picks a router model that session cannot spawn itself.
---

# Router workers

This skill is only for a Claude desktop Code session in the subscription
profile: the first-party profile that talks to Anthropic directly, so its own
subagents can only run Claude models. The local SCG Router serves the
approved OpenRouter models to Claude Code, so this skill starts a separate
headless Claude Code process on the chosen model and returns one JSON result.
The worker works in the folder you give it, with shell and file tools; you
stay the orchestrator and verify what it returns.

A session that can already spawn router models as native subagents, such as
Codex, an attached terminal Claude Code session, or a Claude desktop session
in the gateway profile, should keep doing that through the
[tool guide](../optimal-subagents/references/tool-guide.md). The guide's
runtime-neutral rules apply here too: no secrets in a brief, and record the
requested and served model for every worker.

## Choose the model

[optimal-subagents](../optimal-subagents/SKILL.md) owns model choice. Read it
before the first delegation in a session, take the model's slug and its one
prescribed effort from the
[catalogue](../optimal-subagents/references/catalogue.md), and use its
[fallbacks](../optimal-subagents/references/fallbacks.md) when a model is
unavailable. A model the user names wins. To see what this router offers now:

```sh
python3 <skill-dir>/scripts/router_worker.py --list
```

## Brief the worker

The worker sees only the brief and the files in its folder. It has no
conversation history, no connectors and none of the caller's own instructions
or memory, although `CLAUDE.md` files in the folder and in the folders above
it still load. Write a brief that stands alone:

- start with the label optimal-subagents requires, for example
  `DeepSeek V4.1 Flash Max: bug fix for issue 42`;
- give one deliverable, the paths involved, what it may change, the checks it
  should run and when to stop;
- ask it to report a blocker instead of guessing, because it cannot ask you.

Give every worker that edits files its own git worktree or scratch copy.
Never point two writers at the same files.

## Run it

```sh
python3 <skill-dir>/scripts/router_worker.py --model deepseek/deepseek-v4.1-flash \
  --effort max --cwd /path/to/worktree --task-file brief.md
```

Run anything longer than a quick lookup in the background, and start
independent workers in parallel, a handful at most. `--tools` narrows the
default `Bash,Read,Edit,Write,Grep,Glob`, for example to `Read,Grep,Glob` for
a review. `--timeout` stops the worker after 900 seconds by default, giving it
ten seconds to end its own shell commands first, and stopping the runner
(Ctrl-C, or stopping its background task in Claude Code) does the same. On
Windows the stop is immediate, so a shell command can outlive it.

## Read the result

The runner prints one JSON object and exits non-zero when `ok` is false:

- `ok`: the worker finished without an error, a timeout, an interruption or a
  final reply that is empty, narration-only or a recognized report of missing
  tool results. The usable-answer check is conservative and recognizes common
  explicit failure wording; it does not attempt semantic validation.
- `answer`: its final reply.
- `served`: the model names the upstream reported. Record them beside the
  requested model; a mismatch invalidates the result.
- `tool_calls`, `turns`, `seconds` and `tokens`: the size of the run.
- `transcript`: the redacted event stream, kept in `~/.cache/router-workers`.
- `error`: why it did not finish or which unusable final-reply category was
  recognized.

Treat the answer as a claim. Read the diff, rerun the checks and verify facts
yourself before you use or report them. When `ok` is false, a model the router
does not offer needs a fallback, a timeout usually needs a smaller brief, and a
router or transport failure means stop and report rather than cycle models.

## How it works

The worker gets a fresh `CLAUDE_CONFIG_DIR`, a minimal environment and an empty
MCP configuration, so the caller's settings, hooks, plugins, logins,
connectors and tokens never reach it. Its credential is a placeholder, because
the router bills its own OpenRouter key for routed models. Claude Code's
`--bare` mode looks like the natural switch for this, but in testing it
dropped the worker's Grep and Glob tools.

Claude Code also loads `CLAUDE.md` files from the folders above the working
folder, and for any folder under the home folder that includes the caller's
own `~/.claude/CLAUDE.md`. The runner excludes the home `.claude` folder with
Claude Code's `claudeMdExcludes` setting, so project instructions load and the
caller's do not. The runner also refuses the home folder itself as `--cwd`,
because Claude Code would read `~/.claude/settings.json` as that folder's
project settings and bring the caller's hooks and environment with it. Claude
Code also runs each shell command in its own process group, which is why a
timeout asks it to stop before forcing it.

The worker runs in a session of its own, so Ctrl-C in a terminal, or SIGTERM
or SIGHUP sent to the runner, never reaches it. The runner therefore catches
those signals while the worker runs and stops it the same way as at a timeout.
Only then does it remove the worker's temporary configuration and print the
result, with `error` naming the signal. After Ctrl-C it then ends by SIGINT,
as an unhandled Ctrl-C would, so a shell loop of workers stops instead of
starting the next one. A signal the caller already ignores,
such as SIGHUP under `nohup`, stays ignored. A forced kill (SIGKILL) cannot be
caught, so a worker whose runner is killed that way keeps running with no
deadline. On Windows, which is not yet verified, the worker shares the
runner's console, so Ctrl-C reaches both of them. Windows has no SIGHUP, and a
runner ended from outside cannot stop its worker there.

The router lists Anthropic models by their bare slug and every other model as
`claude/scg/` plus the slug's SHA-256, so an id is the same on every machine.
The runner resolves the slug against the router's live list and refuses a
model it does not offer.

The router's per-install token is redacted from the output and the transcript.
The worker's shell can still read anything the user's account can, including
the router's key file, so brief it the way you would brief a contractor at your
desk. Claude Code prices unknown models as if they were Claude, so the runner
leaves out its cost figure; OpenRouter's usage page is the record of spend.

When installing or updating this plugin for use, complete the shared
[automatic-update setup](../optimal-subagents/references/updates.md) on macOS,
Linux or Windows.
