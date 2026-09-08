# Claude Code via the local router (Preview)

The router speaks the Anthropic Messages API alongside the Codex
backend, with the same billing split: registry slugs owned by OpenRouter
bill the OpenRouter key, everything else passes through to the Claude
subscription untouched.

## Setup

Point Claude Code at the loopback router with the path token in the URL,
mirroring the Codex base URL. With `port` and `token` from
`mixed-router-state.json` (do not share that URL):

```sh
export ANTHROPIC_BASE_URL="http://127.0.0.1:<port>/<token>/"
```

Set only the base URL. Never set `ANTHROPIC_API_KEY` or
`ANTHROPIC_AUTH_TOKEN`: either would override the subscription bearer
and break subscription passthrough. Unset the variable to return to
direct routing.

To list the router models in the picker (CLI `/model`, app model
picker), also set:

```sh
export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=true
```

Claude Code 2.1.x fetches `GET <base>/v1/models` on startup and caches
it at `~/.claude/cache/gateway-models.json`; entries whose `id`
contains `claude` or `anthropic` appear as `From gateway` options.
Restart Claude Code after changing the base URL so it refetches.
`ANTHROPIC_AUTH_TOKEN` must stay unset for the fetch: when it is set
the CLI sends it as the listing credential, and the router answers the
listing from its local registry without needing any credential.

## Choosing a model

Set `ANTHROPIC_MODEL` to a listing id for OpenRouter billing, or leave
the default Claude model for subscription billing. Listing ids mirror
the Codex registry: `claude/<vendor>/<name>` aliases (for example
`claude/z-ai/glm-5.3-flash`) plus the bare `anthropic/...` Claude
aliases, which already pass the client filter. The router strips the
alias back to the registry slug before routing, so billing follows the
registry row. A registry slug also routes directly. Reasoning is
governed by each call's `max_tokens` and `thinking` fields, which
travel untouched. Start a fresh session when switching providers.

## Behaviour and limits

- OpenRouter-bound bodies are forwarded byte-identical to OpenRouter's
  Anthropic-compatible endpoint, so thinking blocks, `tool_use` IDs and
  `cache_control` keep full fidelity. `count_tokens` follows the same
  split. `GET /v1/models` answers `{data: [{id, display_name}]}` from
  the local registry without touching the network; unknown paths answer
  404.
- Subscription requests forward the client's `Authorization` or
  `x-api-key` plus version and beta headers, minus hop headers. The
  router key never accompanies them. In `none` mode the passthrough is
  refused; OpenRouter models still serve.
- The Claude path is pure passthrough, so `/health` `served_models`
  does not track it and no compaction endpoint exists for it.
- Live verification is pending: run a paid probe with one OpenRouter
  model and one subscription model through real Claude Code sessions
  before relying on this, and record the Claude Code version in
  `docs/compatibility.md`.
