# Adding a model

One command derives the row from live OpenRouter metadata:

```sh
python3.14 -m ai_router.models add <slug> --dry-run   # inspect first
python3.14 -m ai_router.models add <slug> --probe     # verify, then write
```

Without `--probe` the row lands as `tier: preview`: it appears in the
picker labelled Preview but is not trusted yet (an `openai/*` row stays
out of the Codex picker, and an `anthropic/*` row will stay out of the
Claude listing). With `--probe` the base
tool round trip runs on the installed router; a pass writes
`tier: verified`, anything else stays `preview` and appends a row to
`docs/compatibility.md`. Validate with
`python3.14 -m ai_router.models check` (`0 problems` required) and
remove with `python3.14 -m ai_router.models remove <slug>`.

Preview models route exactly like verified ones; only the picker label
and ordering differ. A model that needs behaviour the adapter does not
have (a new quirk type) is a normal code change and release, not a data
row.

To preview a per-portco subset in CI without touching runtime policy:
`python3.14 -m ai_router.catalogue --allowed slug-a,slug-b --merge <file>`
followed by the same `--allowed` with `--check`. Runtime enforcement
reads `<home>/model-policy.json` alone; the flag never widens it.

The 2026-09-08 roster uses only the Opus, Fable, Sonnet, and Haiku Latest
Claude aliases from the [OpenRouter model list](https://openrouter.ai/api/v1/models).
The current DeepSeek rows are V4 Pro 0813 (pinned snapshot), V4 Flash Latest
(tracking alias `~deepseek/deepseek-v4-flash-latest`), and V4 Flash Vision Exp
(kept separate: the only image-capable DeepSeek row); the 0423 Pro slug remains
available for existing tasks. Upstream serves no pro-latest id, so Pro keeps
dated ids with clean display names instead of invented slugs. Tilde alias
slugs are used only when upstream actually serves the `~`-prefixed id; never
invent one. New entries are Preview, not runtime-verified.

Picker labels follow the naming convention in `AGENTS.md` section 8
(`<Vendor>: <Model> <Version?>`); `models add` and `live_refresh` produce
conforming rows automatically.

Models with optional reasoning but no advertised effort controls use
`none` (reasoning disabled); non-reasoning models also use `none`. Mandatory
reasoning without known effort controls is refused. This does not invent
Low/High options for older Claude models that only support token budgets.
