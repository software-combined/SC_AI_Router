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
Media rows (the image and video models behind OpenRouter's Images and
Videos APIs) are likewise hand-authored: the default chat `/models`
list omits them, so `models add` cannot derive them. Author them as unlisted preview
with `media_kind: image` or `video`, `modalities: ["text", "image"]` and
reasoning `["none"]`, following the existing media rows.
See [media generation](media-generation.md) for native image routing and
the video submission boundary.
`models check` and `live_refresh` follow the same rule in reverse: a fetch
only ever rewrites rows owned by the provider whose catalogue it read.

Without `--probe` the row lands as `tier: preview` and `listed: false`:
it stays out of both pickers (the Codex catalogue and `GET /v1/models`)
but remains routable so its own probe can reach it. With `--probe` the
offline route matrix runs first, then both real clients use an isolated router.
Codex checks a streamed tool round trip, images when the row supports them
without dropping them, and compaction when it declares a context window.
Claude Code checks two sequential reads and their matching tool results.
Each route uses the row's default effort, including `none`.
Only a complete pass writes `tier: verified` with `listed: true`.
Anything else leaves the row unlisted and prints why. Structured evidence,
including failed routes, is appended to `docs/acceptance-ledger.json`.
An explicit `--tier` skips promotion; it cannot bypass the probe. A
hand-edited `listed: true` on a non-verified row is refused at
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
The isolated probe allows at most 12 upstream attempts across both routes,
including repair, retry and compaction summaries. Each request is limited to 512 KiB and 65,536
output tokens; an uncapped request is refused before sending. Claude also has
a $0.25 client budget. These are probe limits, not production request limits.

Evidence binds the normalized capability row and Python runtime contents to
the actual client versions. It records requested effort, exposed serving
identity and its source, and attempt counts including summary helpers.
Counts reserve the budget before dispatch, so an unsent connection failure can
count as an attempt without implying a charge. Missing serving facts stay
unverified; a known model or effort mismatch fails the gate. Source, capability
or client changes invalidate the proof. A later failure supersedes an earlier
pass, and conflicting results with the same timestamp cannot certify a row.
Historical Plan 185 cells remain separate and are never inferred from these
route runs. Check a saved candidate record with both current client versions:

```sh
python3.14 tools/check_acceptance_ledger.py --model <slug> \
  --client-version codex=<bundled-CLI-version> --client-version claude=<CLI-version>
```

Preview models route exactly like verified ones; only the picker label
and their position differ: the picker groups rows by vendor A-Z, verified
before preview inside each vendor, and `models add` renumbers priorities
to hold that order. A model that needs behaviour the adapter does not
have (a new quirk type) is a normal code change and release, not a data
row.

The offline conformance gate enumerates every registry row and each protocol
its provider serves, including preview and hidden rows. Run
`python3.14 -m unittest tests.test_model_route_conformance` after changing a
row. The real handler checks preparation, credentials, outcomes, recovery and
cleanup against simulated upstreams. These checks prove shared route behavior;
they do not establish live acceptance for each model.

`observed_item_types` records extra Responses input shapes that a bounded wire
probe actually accepted. It affects diagnostic warnings only. The four shapes
recorded for DeepSeek V4.1 Flash came from the 17 September measurement; other
rows and future aliases inherit none of that evidence. Missing evidence means
unknown, not unsupported. Set the field only with a recorded measurement;
model refresh retains a bundled measurement only while the provider and
effective upstream ID match. A changed target returns to unknown.

To preview a per-portco subset in CI without touching runtime policy:
`python3.14 -m ai_router.catalogue --allowed slug-a,slug-b --merge <file>`
followed by the same `--allowed` with `--check`. Runtime enforcement
reads `<home>/model-policy.json` alone; the flag never widens it.

The current roster pins exact ids from the
[OpenRouter model list](https://openrouter.ai/api/v1/models): Claude Opus 5.5,
Sonnet 5.5, Fable 5.1 and Haiku 4.5; Gemini 3.8 Flash and Gemini 3.1 Pro
Preview; Grok 4.7; the Xiaomi MiMo 2.6 Pro and Flash rows; and the DeepSeek
V4.1 Flash (newest Flash, image-capable) and V4 Pro 0813 (newest Pro,
text-only) rows. The router does not follow
upstream `latest` movement on its own: when a new version ships, add its
pinned row, probe it, and put the superseded slug in `RETIRED_SLUGS` so
upgrades drop it from the picker. Rows land as `preview` until the isolated
`--probe` route checks pass and the run is recorded in the acceptance ledger.
A row that needs capabilities set before probing, such as `drop_images`,
must first be authored as unlisted preview. Then
`python3.14 -m ai_router.candidate <slug> --probe --confirm` bills the legs
that row implies and prints the structured proof. Save that record in the
ledger and check it against the unchanged candidate before reviewing a manual
tier promotion. The standalone command never changes the registry.
A tilde alias slug is used only when the roster deliberately tracks upstream
and upstream actually serves the `~`-prefixed id; never invent one, and an
alias keeps the `Latest` label. New entries are Preview, not
runtime-verified.

A row may pin or steer its serving endpoints with `provider_prefs`,
using OpenRouter's documented `provider` object. Set it only from a recorded
probe or incident in `docs/compatibility.md`, and prefer
`ignore: [<endpoint>]` over a hard `order` plus `allow_fallbacks: false`,
which removes failover.

A row may set `auto_compact_token_limit` to make Codex compact that model's
threads earlier than its context window would; without it, Codex follows the
window. Set it only from recorded evidence in `docs/compatibility.md`, as for
MiMo V2.6 Pro. It is a separate field because `live_refresh` rewrites
`context_window` from the provider's advertised length, so a lowered window
would not stick. `live_refresh` and `models add` leave the limit alone, and
the router's hourly model feed cannot replace the value a release ships.

A new row on the external Responses protocol inherits the shared stream
lifecycle (`docs/architecture.md`, Plan 187) with no per-model code: large
setup frames and reasoning wait until the attempt commits, and a transient provider
failure before anything reaches the client is retried once when the
request's tools are all client-run. Whether a row keeps `web_search` decides replay safety through
the prepared tools, not through the row's name; a row that needs different
stream behaviour is a code change, not a quirk.

Picker labels follow the naming convention in `AGENTS.md` section 8
(`<Vendor>: <Model> <Version?>`); `models add` and `live_refresh` produce
conforming rows automatically. A hyphenated upstream version
(`MiMo-V2.6-Flash`) is stored with spaces (`MiMo V2.6 Flash`).

Two ids, one model

`slug` is the id clients send: it is the routing key and it must stay unique
across the registry. `upstream_id` is the id the provider expects on the
wire, and it is optional: leave it out (or empty) when the provider serves
the slug itself, which every current row does. Set it, or pass
`models add --upstream-id`, when a provider names the model differently, for
example a direct Anthropic key serving `claude-opus-5.5` under the client id
`acme/claude-opus-5.5`.

One upstream model may appear on several providers. Each row keeps its own
host, key and label, so the picker shows `Anthropic: Claude Opus 5.5 ·
OpenRouter` beside `Anthropic: Opus 5.5 · Acme`; two rows that share an
`upstream_id` must not share a `display_name`, and the loader refuses the
pair if they do. `models check` also refuses two rows on one provider with
the same upstream id.

Models with optional reasoning but no advertised effort controls use
`none` (reasoning disabled); non-reasoning models also use `none`. Mandatory
reasoning without known effort controls is refused. This does not invent
Low/High options for older Claude models that only support token budgets.
