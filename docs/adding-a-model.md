# Adding a model

One command derives the row from live OpenRouter metadata:

```sh
python3.14 -m ai_router.models add <slug> --dry-run   # inspect first
python3.14 -m ai_router.models add <slug> --probe     # verify, then write
```

Without `--probe` the row lands as `tier: preview`: it appears in the
picker labelled Preview but is not trusted yet (an `openai/*` row lists
in the Codex picker beside its subscription twin; the `--client claude`
catalogue merge still drops OpenRouter-billed Anthropic rows). With
`--probe` the base tool round trip runs on the installed router; a pass
writes `tier: verified`, anything else stays `preview` and appends a row
to `docs/compatibility.md`. Validate with
`python3.14 -m ai_router.models check` (`0 problems` required) and
remove with `python3.14 -m ai_router.models remove <slug>`.

Preview models route exactly like verified ones; only the picker label
and their position differ: the picker groups rows by vendor A-Z, verified
before preview inside each vendor, and `models add` renumbers priorities
to hold that order. A model that needs behaviour the adapter does not
have (a new quirk type) is a normal code change and release, not a data
row.

To preview a per-portco subset in CI without touching runtime policy:
`python3.14 -m ai_router.catalogue --allowed slug-a,slug-b --merge <file>`
followed by the same `--allowed` with `--check`. Runtime enforcement
reads `<home>/model-policy.json` alone; the flag never widens it.

The current roster uses only the Opus, Fable, Sonnet, and Haiku Latest
Claude aliases from the [OpenRouter model list](https://openrouter.ai/api/v1/models).
The current DeepSeek rows are V4.1 Flash (newest Flash, pinned snapshot,
image-capable) and V4 Pro 0813 (newest Pro, pinned snapshot, text-only).
Upstream serves no pro-latest id, so Pro keeps dated ids with clean display
names instead of invented slugs. Rows land as `preview` until the isolated
`--probe` round trip passes and the run is recorded in
`docs/compatibility.md`. Tilde alias
slugs are used only when upstream actually serves the `~`-prefixed id; never
invent one. New entries are Preview, not runtime-verified.

Picker labels follow the naming convention in `AGENTS.md` section 8
(`<Vendor>: <Model> <Version?>`); `models add` and `live_refresh` produce
conforming rows automatically.

Models with optional reasoning but no advertised effort controls use
`none` (reasoning disabled); non-reasoning models also use `none`. Mandatory
reasoning without known effort controls is refused. This does not invent
Low/High options for older Claude models that only support token budgets.
