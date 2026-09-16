# Adding a model

One command derives the row from live OpenRouter metadata:

```sh
python3.14 -m ai_router.models add <slug> --dry-run   # inspect first
python3.14 -m ai_router.models add <slug> --probe     # verify, then write
```

Rows belong to a provider (`ai_router/provider_defs.py`); `--provider ID`
picks a different one, and defaults to `openrouter`. A provider whose
definition carries `catalogue_shape: manual` (no live model list) has its
rows authored by hand, and `models add` refuses it rather than guessing.
`models check` and `live_refresh` follow the same rule in reverse: a fetch
only ever rewrites rows owned by the provider whose catalogue it read.

Without `--probe` the row lands as `tier: preview` and `listed: false`:
it stays out of both pickers (the Codex catalogue and `GET /v1/models`)
but remains routable so its own probe can reach it. With `--probe` the
implied legs run on an isolated router (tool round trip always, `--image`
when the row's modalities include image, compaction when it declares a
context window); a pass writes `tier: verified` with `listed: true`,
anything else leaves the row unlisted and prints why, and the run is
recorded in `docs/compatibility.md` with the legs that ran. An explicit
`--tier verified` without a passing probe keeps the row unlisted and says
so, and a hand-edited `listed: true` on a non-verified row is refused at
load. Rows shipped before the flag keep working without it and stay
visible. Validate with `python3.14 -m ai_router.models check`
(`0 problems` required) and remove with
`python3.14 -m ai_router.models remove <slug>`.

`models discover` diffs the live catalogue against `models.json` without
writing anything or billing a probe (no key needed for OpenRouter):

```sh
python3.14 -m ai_router.models discover            # addable / registered / unavailable / retired
python3.14 -m ai_router.models discover --json     # same document as JSON
python3.14 -m ai_router.models discover --provider ID
```

A standalone probe preview bills nothing: `python3.14 -m ai_router.candidate
<slug>` prints the legs it would run; add `--probe --confirm` to bill them.

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

The current roster pins exact ids from the
[OpenRouter model list](https://openrouter.ai/api/v1/models): Claude Opus 5,
Sonnet 5, Fable 5.1 and Haiku 4.5; Gemini 3.8 Flash and Gemini 3.1 Pro
Preview; Grok 4.6; and the DeepSeek V4.1 Flash (newest Flash, image-capable)
and V4 Pro 0813 (newest Pro, text-only) rows. The router does not follow
upstream `latest` movement on its own: when a new version ships, add its
pinned row, probe it, and put the superseded slug in `RETIRED_SLUGS` so
upgrades drop it from the picker. Rows land as `preview` until the isolated
`--probe` round trip passes and the run is recorded in
`docs/compatibility.md`. `models add --probe` runs its round trip at `low`
and takes no effort flag, so a model whose only effort is `none` (Claude
Haiku 4.5) is verified by hand: add the row as `preview`, boot
`ai_router.candidate.IsolatedRouter(slug)`, run
`python3.14 tools/probe_codex_runtime.py <slug> --router-state
<home>/mixed-router-state.json --catalog <home>/candidate-catalogue.json
--effort none`, then set the row's `tier` to `verified` in
`ai_router/models.json` and record the run in `docs/compatibility.md`.
A tilde alias slug is used only when the roster deliberately tracks upstream
and upstream actually serves the `~`-prefixed id; never invent one, and an
alias keeps the `Latest` label. New entries are Preview, not
runtime-verified.

A row may pin or steer its serving endpoints with `provider_prefs`,
using OpenRouter's documented `provider` object. Set it only from a recorded
probe or incident in `docs/compatibility.md`, and prefer
`ignore: [<endpoint>]` over a hard `order` plus `allow_fallbacks: false`,
which removes failover.

Picker labels follow the naming convention in `AGENTS.md` section 8
(`<Vendor>: <Model> <Version?>`); `models add` and `live_refresh` produce
conforming rows automatically.

Two ids, one model

`slug` is the id clients send: it is the routing key and it must stay unique
across the registry. `upstream_id` is the id the provider expects on the
wire, and it is optional: leave it out (or empty) when the provider serves
the slug itself, which every current row does. Set it, or pass
`models add --upstream-id`, when a provider names the model differently, for
example a direct Anthropic key serving `claude-opus-5` under the client id
`acme/claude-opus-5`.

One upstream model may appear on several providers. Each row keeps its own
host, key and label, so the picker shows `Anthropic: Claude Opus 5 ·
OpenRouter` beside `Anthropic: Opus 5 · Acme`; two rows that share an
`upstream_id` must not share a `display_name`, and the loader refuses the
pair if they do. `models check` also refuses two rows on one provider with
the same upstream id.

Models with optional reasoning but no advertised effort controls use
`none` (reasoning disabled); non-reasoning models also use `none`. Mandatory
reasoning without known effort controls is refused. This does not invent
Low/High options for older Claude models that only support token budgets.
