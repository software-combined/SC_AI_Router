# Plan 153: Model identity - separate the client-facing slug from the upstream id

> **Executor instructions**: Follow this plan step by step. If a STOP condition
> occurs, stop and report. When done, update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 0024a42..HEAD -- ai_router/registry.py ai_router/models.json ai_router/models.py ai_router/live_refresh.py ai_router/providers.py ai_router/claude.py ai_router/model_refresh.py ai_router/catalogue.py docs/adding-a-model.md tests/test_registry.py tests/test_provider_swap.py tests/test_models_cmd.py tests/test_claude_ingress.py config/source-limits-baseline.json`
> Land plan 152 first and rebase here. Plan 154 also edits
> `ai_router/catalogue.py`: serialize 153 then 154. Reconcile every cited line
> before editing.

## Status and first proof

- Priority P1; effort M; risk MED; confidence HIGH; category architecture/provider.
- Depends on plan 152 (dialect table). Serialize with plan 154 on
  `ai_router/catalogue.py`, and with plans 135 and 151 on the same file.
- Source: `plans/2026-09-12-architecture-scalability-review.md`, row
  "Registry rows key on the bare slug and reject duplicates".
- First proof: two external providers both serve Claude Opus 5 in the same
  registry, the picker shows two distinguishable rows, each request carries the
  right upstream id on the wire to the right host with the right key, and
  `registry.load` still refuses a genuinely duplicated client-facing id.

## Why this matters

`ai_router/registry.py:64-65` refuses duplicate slugs and `:113` builds a
single flat `BY_SLUG` map, so the routing key is the bare slug. Every consumer
follows: `providers.select` reads `by_slug(model).provider`
(`ai_router/providers.py:88-95`), `claude.row_def` does the same
(`ai_router/claude.py:96-99`), and the wire body carries the client's own
`payload['model']` unchanged (`ai_router/providers.py:144-147`).

The consequence is that the registry can say "OpenRouter serves
`anthropic/claude-opus-5`" or "a direct Anthropic key serves it", never both.
That is the actual blocker for a direct Anthropic API key, Azure OpenAI, a
self-hosted OpenAI-compatible endpoint, or any second provider whose catalogue
overlaps OpenRouter's, which is most of them. It is an identity problem, not a
transport problem: plan 141 already proved the transport works.

The smallest correct fix keeps the client-facing id unique (it must be: it is
what Codex and Claude Code send) and adds the upstream id as a separate,
optional registry field.

## Scope

**In scope**: the files named in the drift check, plus new tests.
**Out of scope**: adding a real second provider (owner-gated and billed),
changing any existing row's slug or wire id, catalogue size work (plan 154),
client visibility policy (plan 155), and the hourly refresh wiring (plan 099).

## Steps

1. **Add the field.** In `ai_router/registry.py`, add `upstream_id: str = ''`
   to the `Model` dataclass and to `FIELDS`. An empty value means "the slug is
   the upstream id", which is true for all 19 current rows, so `models.json`
   needs no edit and the `set(row) - {'listed'} != set(FIELDS)` check at
   `:61-63` must accept the field as optional in the same way `listed` is.
   Validate that a non-empty `upstream_id` is a non-empty string with no
   whitespace.

2. **Add the accessor.** Add `registry.upstream_id_for(entry)` returning
   `entry.upstream_id or entry.slug`. Nothing outside the registry may repeat
   that fallback.

3. **Use it on the wire, Responses side.** In
   `ai_router/providers.py::ExternalResponsesProvider.prepare`, after the
   `entry` lookup at `:120`, set `payload['model'] =
   registry.upstream_id_for(entry)` before the body is serialized at `:147`.
   The serialization already happens unconditionally on this path, so no extra
   re-encode is introduced. `summarize` at `:205-227` builds its own body and
   must use the same id.

4. **Use it on the wire, Messages side.** In
   `ai_router/claude.py::ExternalMessagesProvider.prepare`, the alias rewrite
   at `:116-121` already re-serializes when the id changes. Extend the same
   condition so the rewritten value is `registry.upstream_id_for(entry)`
   rather than the registry slug, and keep byte-identity when the two are
   equal. That byte-identity is the ingress contract
   (`ai_router/claude.py:1-13`) and the existing test at
   `tests/test_protocol_contracts.py:73-80` must still pass unchanged.

5. **Keep picker labels unambiguous.** `catalogue.catalog_name`
   (`ai_router/catalogue.py:164-167`) strips the provider suffix from
   `display_name`, and `provider_defs.label_for` supplies that suffix, so two
   rows for the same model already read as `Anthropic: Opus 5 · OpenRouter`
   and `Anthropic: Opus 5 · Anthropic`. Add a registry test that two rows
   sharing an `upstream_id` must not share a `display_name`, with a clear
   `SystemExit` message, so an ambiguous picker cannot ship.

6. **Teach the onboarding command.** In `ai_router/models.py`, `derive_row`
   (`:66-103`) writes `upstream_id` only when the target provider's id
   namespace differs from the slug, which today is never; add the key with an
   empty value so the row shape stays exact, and add `--upstream-id` to the
   `add` subparser (`:281-286`) for a hand-authored `manual`-shape provider.
   `cmd_check` (`:201-232`) gains a duplicate-`(provider, upstream_id)` check
   alongside the existing duplicate-slug and duplicate-priority checks.

7. **Teach the refresh path.** `live_refresh.refresh`
   (`ai_router/live_refresh.py:45-63`) looks live rows up by `row['slug']` at
   `:56`. Change that lookup to the row's upstream id so a row whose client
   id differs from its upstream id still refreshes. `model_refresh.validate`
   (`ai_router/model_refresh.py:32-41`) must apply its slug-shape rule to the
   upstream id as well as the slug.

8. **Prove it end to end offline.** Extend `tests/test_provider_swap.py` with a
   second fixture row: provider `acme`, slug `acme/claude-opus-5`,
   `upstream_id` `claude-opus-5`, alongside the real
   `anthropic/claude-opus-5` OpenRouter row. Assert that the two rows coexist
   in `registry.load`, that `providers.select` picks the right adapter for
   each, that each `Prepared` carries the right host, path, key and
   `payload['model']`, that neither request carries the other provider's key,
   and that `catalogue.merge` emits two rows with distinct display names.

9. **Document it.** Add a short section to `docs/adding-a-model.md` explaining
   that the slug is the id clients send and the optional `upstream_id` is the
   id the provider expects, with the two-provider example.

## Verification

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_registry tests.test_provider_swap tests.test_models_cmd tests.test_live_refresh tests.test_model_refresh tests.test_claude_ingress tests.test_protocol_contracts` | pass |
| Registry shape | `python3.14 -m ai_router.models check --offline` | `0 problems` |
| Catalogue | `python3.14 -m ai_router.catalogue --merge ./ci-catalogue.json && python3.14 -m ai_router.catalogue --check ./ci-catalogue.json` | `identical: 19 entries`, exit 0 |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Policy scans | `python3.14 tools/check_policy_scans.py` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | `failures=0` |

## STOP conditions

- Any existing row's on-wire model id changes: stop. All 19 current rows must
  send exactly the bytes they send today.
- The Messages byte-identity contract breaks for a row where slug and upstream
  id are equal: stop and report the diff.
- `registry.load` would have to accept two rows with the same slug: stop. The
  client-facing id stays unique; only the upstream id may repeat.

## Acceptance checklist

- [ ] `Model` carries `upstream_id`; empty means the slug, and all 19 existing
      rows are unchanged in `models.json`.
- [ ] Both adapters send the upstream id and nothing else changes on the wire.
- [ ] Two registry rows for the same upstream model on different providers
      load, route and label distinctly, proven offline.
- [ ] `models check` rejects a duplicated `(provider, upstream_id)` pair and a
      duplicated display name for the same upstream id.
- [ ] `live_refresh` and `model_refresh` follow the upstream id.
- [ ] `docs/adding-a-model.md` explains the two ids.
- [ ] Full suite, compile and limits pass; `plans/README.md` row updated.

## Maintenance notes

- `AGENTS.md` section 8 pins exact upstream ids in the roster. After this plan
  the pin lives in `upstream_id` when the two differ, and the naming test
  should say so.
- This plan makes a second provider possible; it does not add one. The real
  second provider stays an owner decision with a billed acceptance leg.
