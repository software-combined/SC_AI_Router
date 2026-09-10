# Changelog

## 0.6.13

- Auto-update without repo access (Plan 054, source slice): the scheduled
  updater learns a feed token from `latest.json` and switches itself from
  private GitHub Releases (gh) to the token-gated feed at
  `dist.softwarecombined.com`, per host, with no manual step. Hosts without
  a token keep the exact pre-migration route, so old and new installs
  coexist; a host that is already current still migrates on its next poll,
  because the token is learned after the serial check and before the
  version comparison. Feed and token handling consolidate into
  `packaging/feed.py`; feeds and bundles off the trusted origins are
  refused, and refusal messages never echo a URL query string. The
  CloudFront distribution, publish workflow, and library page remain
  owner-gated.

- Refuse mutating installer runs against a scratch `--home` unless
  `ROUTER_LIVE_RUN=1`: service names are machine-wide, so a run pointed at
  /tmp still bootstraps, bootouts, or TERMs the production jobs. Read-only
  `--status`/`--preflight` stay exempt; `--uninstall` is refused with or
  without `--dry-run`. A prior simulation against /tmp took down the
  production router this way; the guard makes that shape refuse before any
  service call.

- Rename the runtime package `codex_router` to `ai_router` (Plan 074): the
  router serves Codex, Claude Code, and OpenRouter side by side, and the old
  prefix misled readers into treating the Codex adapter as the whole router.
  Distribution and bundle names become `ai-router`. Installed homes, service
  labels, state/catalogue filenames, and the `codex_router` log name stay so
  existing installs keep working; a thin `codex_router` alias re-exports
  `ai_router` during the transition, and the launcher boots either package
  layout. Client-specific modules (`clients/codex.py`, `claude.py`,
  `codex_config.py`) keep their names.

- Keep one effective discovered schema per tool through compaction: the
  discovered-tool store deduplicates by (namespace, name) before memory/disk
  writes and on recall, so repeated rediscovery no longer grows duplicate
  definitions; first full definition wins with stub completion preserved.

- Name the model id on catalog misses: `UNKNOWN_MODEL` now carries the
   requested `model` plus a `candidates` list holding at most the exact
  tilde-alias slug (e.g. bare `anthropic/claude-opus-latest` offers
  `~anthropic/claude-opus-latest`), so a parent can retry once instead
  of probing the catalog. Identity stays strict: nothing auto-routes,
  and the hint never names a slug the portco allowlist excludes.

- List every OpenRouter row in the Claude desktop third-party gateway
  picker: `GET /v1/models` rows now project `anthropic_family_tier`
  (`sonnet` for non-Anthropic rows, each Anthropic alias's own tier
  word), which the desktop requires for non-Anthropic-looking ids. No
  registry field is added and ordering and labels are untouched.
  `packaging/install.py --desktop` attaches and detaches the desktop
  gateway profile with the same ownership receipt discipline as the
  Claude Code CLI attach, and refuses when `claude_mode` is `none`.

## 0.6.12

- Make the Windows installer work end to end (Plan 057 Stages 3, 4 and
  the first real-machine proof, Windows 11 2026-09-10): the router task's
  logon trigger is scoped to the installing user (an unscoped one needs
  elevation) and its recovery trigger carries the `StartBoundary` Task
  Scheduler requires; an update or restart drains the running router through
  `/shutdown` and waits for the instance to end before relaunching, since
  `IgnoreNew` made the old `/run` a no-op; uninstall ends both tasks before
  deleting them (a deleted task leaves its process running); both tasks run
  `pythonw.exe` through a home-root `task_launch.py` (written on every
  install) that routes stdout/stderr to `logs\launchd.log` and
  `logs\update.log`, and every console child is spawned windowless.
- `stop` on a never-registered task no longer masks the real failure, and
  the installer prints why a backend refused before it rolls back.
- Ship `packaging/platforms/windows.py` in the release bundle: without it
  every scheduled update and rollback on an installed Windows router failed
  to load the backend.
- Write the Codex catalogue path with forward slashes: a native Windows
  path in the TOML block made `config.toml` unreadable to Codex.
- Protect `mixed-router-state.json` (loopback token) and the router home
  itself on Windows with the key's owner-only `icacls` grant, inheritable so
  every file the router writes later is born owner-only; grants name the
  account as `whoami` reports it.
- `install.ps1` runs the installer through the `py` launcher instead of the
  bare `python` alias, which opens the Microsoft Store on a stock profile;
  the no-interpreter message names the Windows remedy instead of Homebrew.
- Uninstall drops the Codex activation receipt after restoring the config
  (all platforms): a stale receipt made the next install refuse the
  subagent guidance it found missing and exit 1 with the service running.

## 0.6.11

- Forward stream bytes without waiting for identity inspection: the
  tool-free observer now yields each piece as it arrives and parses at
  most 64 KiB retained bytes (JSON, post-EOF) or complete SSE frames,
  instead of buffering the body first. Oversized or malformed bodies
  disable observation, never forwarding. No deployed latency claimed.

- Attribute router latency per phase instead of one cumulative number:
  `request_completed` now carries `read_ms`, `prepare_ms`, `connect_ms`,
  `send_ms`, `headers_ms`, `first_data_ms`, and `first_write_ms`, plus
  fixed-category `response_kind`/`response_encoding`; failures record
  the phases that completed. Cumulative fields keep their meanings.
  This enables measurement; it claims no latency improvement.

- Attribute context refusals and estimate the full billable request:
  the pre-flight estimate now counts serialized tools and instructions
  alongside input (image blocks excluded, matching the client counter),
  and each `context_length_exceeded` rejection logs the model, path,
  and `used`/`reserved`/`window` integers so the next incident needs
  no by-traffic attribution.

- Enforce per-portco model allowlists as resolved data (Plan 068, source
  only): `<home>/model-policy.json` (`0600`, atomic write) carries the
  centrally resolved slug subset; the picker (`merge`/`check` plus the
  `--allowed` CI flag) and both protocol routers reject non-listed
  OpenRouter slugs with the existing closed error while subscription
  rows are unaffected. Absent file means all approved models; malformed
  files fail closed to an empty OpenRouter set. Central grant schema,
  refresh delivery, and per-install issuance stay gated on Plan 054 Stage 4.

- Give the first-run key page an executive light-theme layout matching
  SC_360 (single card, blue-600 primary control, slate hairlines,
  labelled key field and described subscription choices, inline error
  banner, detail list on the connected page). Style is inline only, so
  the loopback page still fetches nothing; the form contract, statuses,
  single-use nonce and owner-only key write are unchanged.

- Tell the Windows truth sooner and more usefully: `--status` and
  `--preflight` now run on Windows (read-only; install and update still
  refuse before changing anything), and the owner-only key check
  tolerates the OS principals every default profile inherits
  (`NT AUTHORITY\SYSTEM`, `BUILTIN\Administrators`) while still
  refusing broad groups and other users.

- Steer parents back to readable handoffs: an encrypted handoff that cannot
  arrive readably (OpenRouter-model spawn, or follow-up/message to an
  OpenRouter-spawned child) is replaced with a targeted error naming the
  exact `collaboration_plaintext` call to make instead, before history is
  poisoned. Proven by a Luna v1 parent reaching a real Muse child end to
  end after one steered retry (Codex 0.153.4).

- Deliver readable agent handoffs to OpenRouter children without weakening
  native encryption: new `collaboration_plaintext` aliases for the already
  exposed spawn/message/follow-up tools, restored to native calls with
  `encrypted_function_args: []` on JSON and SSE responses, plaintext agent
  messages converted at the OpenRouter boundary with sender/recipient kept,
  and opaque or mixed encrypted assignments rejected before credential
  lookup. Proven Astra v2 parent to Muse child with scripted children
  (installed router, Codex 0.153.4); v1 subscription parents stay
  fail-closed and need their own plan.

- Attach Claude Code without touching Codex: new `--clients
  claude|both` merges only the two owned `env` settings into the
  user's `settings.json` with conflict refusal and receipt record,
  plus validated `scg-openrouter` plugin manifests and a shared
  `manage-router` skill driving the canonical installer (offline
  proofs; staff-surface acceptance still pending).

- Read installer state without touching it: new `--status [--json]`
  prints installed version, service state, attached clients, and
  key-present/usable booleans with no secret-bearing values. The
  read-only preflight/status commands move to `packaging/diagnostics.py`,
  bringing the installer back under its entrypoint size budget.

- Recover a missing or revoked key without hand-deleting files: a keyless
  router boots, the first request opens the loopback setup page once per
  live nonce with a clear message, and the page replaces a stored key
  only after OpenRouter itself rejects it on 401/403 (offline proofs;
  central issuance remains owner-gated).

- Report missing install prerequisites before writing anything: new
  `--preflight` flag prints each missing item (Python 3.14, `gh`
  binary for the transitional feed route, Codex CLI unless `--client
  none`) with its remedy and exits non-zero, without creating the
  router home.

- Harden Windows key protection in source: icacls owner-only enforcement
  with verify-after-write, a read-time ACL gate mirroring the POSIX check,
  and setup-window refusal on unprotectable keys (offline proofs only;
  the installer still refuses Windows until backend acceptance).

- Add the Windows Task Scheduler backend in source (Plan 057 Stage 3,
  offline proofs only): per-user logon router task plus 15-minute updater
  task, pythonw.exe router with python.exe updater, graceful /shutdown
  restart, and registration readback that names group-policy refusals.
  The backend is now wired: the installer routes Windows to it instead
  of refusing. Staff rollout stays gated on real-machine acceptance.

- Pin the private CPython 3.14 runtime: new `packaging/runtime.lock`
  names one install-only distribution per qualified target with validation
  and wrapper-table generation (Stage 1). All four targets now carry
  reviewed pins (CPython 3.14.7, astral-sh build 20260814) with URLs and
  SHA-256 digests verified against the downloaded archives.
  Release builds validate the lock first.

- Give each client explicit activation: new `packaging/codex_config.py`
  owns the Codex block, picker preservation, guidance, and receipts; the
  installer checks the remover's exit status instead of its wording.
  `--client none` installs service-only without touching client settings,
  and `--anthropic-mode` sets the Claude subscription choice independently
  (unset follows the OpenAI mode as before).

- Give model facts one owner each: pure metadata normalization moves to
  `model_metadata.py`, the Codex capability projection is shared by merge
  and apply (identical fields for the same snapshot, audio preserved where
  advertised), and picker visibility moves to the client domain. No roster,
  tier, or routing changes.

- Tell the truth up front: the README names Windows installer support as
  not-yet (the installer refuses before changing anything), lists GitHub
  CLI access as a transitional requirement, moves Arch setup below the
  generic Linux path, and qualifies key-file protection per platform.
  Supervisor logs rotate at service start (1 MB each, two backups).

- Separate HTTP transport from wire-protocol policy: shared `Prepared`,
  hop-header, stream, and header-relay leaves move to `transport.py`, and
  the handler dispatches through an explicit `protocols/` method/path
  table instead of client-specific branches. On-wire behavior is unchanged.

- Refuse unreadable encrypted agent briefs before dispatch: an
  `agent_message` carrying an encrypted block now fails closed with a
  content-free preparation error instead of forwarding opacity a child
  would infer around. Plaintext agent labels survive compaction summaries.

- Keep upstream prose and exception text out of diagnostics: rejected
  upstream turns now name a fixed category (tool-schema, tool-call, or
  request rejection) with the provider and offending tool instead of
  reflecting upstream prose, and structured logs carry the stable error
  code without message content. Client status codes are unchanged.

- Wrap Grok tools whose object root carries an `anyOf`/`oneOf` union with a
  non-object branch (reported 409: `automation_update` declares
  `type: object` with a root `oneOf` including a scalar). The PR #25 guard
  only checked the root `type`, so the tool sailed through unwrapped and
  xAI rejected the turn. Object-only unions stay native.

- Order the picker for scanning: subscription rows in roster order, then
  verified OpenRouter rows A-Z by display name, then preview rows A-Z, in
  both the Codex catalogue merge and the Claude `GET /v1/models` listing.
  Values are never rewritten to achieve the order.
- Seed fresh installs with the native subscription reasoning levels per
  model (e.g. Sol defaults low, Spark defaults high) instead of a single
  medium placeholder, so the effort picker works on a new Mac the way it
  does on an upgraded one. Existing catalogues are untouched.
- Drop `gpt-reserve` from the default subscription roster and picker.
  The next scheduled update evicts the row from the catalogue and prunes it
  from preserved state, so routing stops authorizing it as well.
- Repair subscription rows stuck on the 0.6.10.23 single-medium placeholder:
  the next merge upgrades exactly that legacy signature to the native levels
  per model and leaves richer and custom rows untouched. Updated machines
  whose GPT rows showed only medium effort regain the full picker.
- Default omitted OpenRouter output limits to at most 32,000 tokens, bounded
  by the provider ceiling and the headroom after Codex's 90% compaction
  threshold. Reserving half the window previously rejected long tasks well
  before native compaction. Explicit output limits keep their existing caps.
- Report estimated context exhaustion and explicit upstream context-limit
  codes using Codex's `context_length_exceeded` signal: `response.failed`
  over SSE for streaming requests and HTTP 400 JSON otherwise. Other
  preparation errors remain 409. Native compaction thresholds are unchanged.

## 0.6.9 (unreleased)

- Make `--feed` one-shot for the anti-replay serial as well as the URL. A
  local bundle carries its own build number as its serial, so a pinned
  install recorded a number the real feed had not reached, and every later
  scheduled check refused the real feed with `stale feed serial` -- updates
  stopped silently. A pinned feed is now exempt on both sides: its serial is
  neither checked against nor recorded. Checking it was the trap that invited
  choosing a build number high enough to pass, which is what froze the
  channel; the unattended channel keeps full replay protection.

- Stop the updater from unloading the router and leaving nothing running.
  `launchctl bootout` returns 0 as soon as teardown *starts*, so the
  `bootstrap` issued immediately after it failed with `Bootstrap failed: 5:
  Input/output error` and the job ended up loaded nowhere. Recovery then
  could not work either: both the reload's heal and the health-check rollback
  relied on `launchctl kill TERM` plus `KeepAlive`, and an absent job has
  nothing to keep alive. Every subsequent 15-minute update run spent 150s
  waiting on a `/health` that nobody was serving and reported "new version
  failed health check" against a release that was perfectly good. Unload and
  load now wait for the launchd domain to settle, retry a bootstrap that lost
  the teardown race, verify the end state, and fail closed rather than
  mistaking a surviving stale job for a successful reload.
- Never report a clean rollback over a router that is not serving. Every
  install path, success or rollback, now ends by asserting a loaded job that
  answers `/health` on the expected version, bootstrapping it when missing,
  and says the router is down when it cannot.
- Reload the service only when launchd's in-memory copy actually differs from
  what is being written, compared against the loaded job rather than the file
  on disk. An ordinary version update now hands over in place with a TERM:
  `router_launch.py` re-reads `current` on exec and launchd keeps the
  listening socket, so in-flight requests drain on the old process, no
  connection is refused, and no bootout can strand the machine.
- Compare interpreter identity by resolved path. `/opt/homebrew/bin/python3.14`
  and `/opt/homebrew/opt/python@3.14/bin/python3.14` are one binary reached by
  two symlinks, and a string compare called them different, forcing the
  destructive reload path on runs that needed only a handover.
- Point the scheduled-update job at a stable `update_launch.py` in the router
  home instead of a per-release `install.py` path, and reload that job when
  its command changes. launchd runs its in-memory copy of a loaded plist, so a
  versioned path outlived the release it named: after a prune the updater kept
  invoking a deleted installer every 15 minutes.
- Adopt a changed scheduled-update command by comparing the whole loaded
  command, not just the interpreter. On a normal upgrade the interpreter is
  unchanged, so an argv[0] check never fired and launchd kept running the old
  per-release installer path indefinitely.
- Never `bootout` the scheduled updater from inside it. That job is what runs
  the installer, so the bootout would kill the process issuing it, wait out
  its whole timeout for a label that cannot leave the domain while its own
  process lives, and return without bootstrapping: automatic updates gone,
  exit status clean. A scheduled run now leaves the rewritten plist for the
  next manual install or login to adopt, and the installer reports it when
  the updater is not loaded instead of exiting quietly.
- Stop waiting for an idle router before updating. A swap is a pointer write
  plus a `TERM`: launchd holds the listening socket, so new connections queue
  for the incoming process while the outgoing one drains the requests it
  already accepted. The idle gate delayed every update on a machine that was
  actually in use and protected nothing the drain does not already cover.
- Serialise installs on every platform, not just Linux, with one advisory
  lock on `install.lock` taken at the entry point. The scheduled pass and a
  manual run could previously interleave on macOS, both swapping `current`,
  rewriting both plists and reloading the same label. The duplicate lock in
  `systemd.py` is gone; `--dry-run` takes no lock and creates no router home.
- Enforce the documented source budget on `packaging/` too. The checker only
  walked `codex_router`, `tools` and `tests`, so the two installer entrypoints
  grew unguarded and their baseline entries were decorative; `install.py` had
  reached 16 lines short of its hard limit with no signal. The failure-count
  helpers moved to `service.py`, which already owns state reads and writes.
- Keep the release that launchd's loaded updater command still names. A
  scheduled run defers the updater reload (it cannot bootout its own job), so
  launchd goes on running the old per-release installer path; pruning that
  release would leave it firing a missing file every fifteen minutes, which is
  the failure this release exists to remove.
- Count an installer child that never reports as a failed attempt. A child
  killed by the 900-second timeout raises `TimeoutExpired`, which is a
  `SubprocessError` and not an `OSError`, so nothing recorded it and the
  version was never parked.
- Park a version that fails three times instead of
  re-fetching and re-activating it every fifteen minutes. Each failed pass
  cost a service restart and most of a cycle with the router down. A
  successful install clears the count, and a different version always gets
  its own attempts. The count lives in the state file, which is what parks a
  version on the production feed: that feed is read through the GitHub CLI
  and carries no ETag to save.
- Let installer failures reach their own rollback. The health guard caught only
  `OSError` and `CalledProcessError`, so the `SystemExit` raised by a failed
  reload or launcher install skipped the rollback block entirely and left the
  pointer on an unverified release.

- String-wrap non-object tool parameter roots for `~x-ai/grok-latest`
  (new `json_text_root` schema mode): xAI rejects union-root schemas such
  as the desktop automation tool, failing even a plain greeting. Ordinary
  object-root tools are unchanged; Meta recursive-schema handling is kept.
- Name upstream failures at the client: stalls before upstream headers keep
  502 but name the model, elapsed wait and timeout with a retry action
  (Grok image turns stall upstream, retry text-only); DNS/refused names the
  host; parseable upstream 4xx bodies become 409 with the provider reason
  and offending tool instead of a bare passthrough; unknown shapes relay
  verbatim and mid-stream disconnects stay log-only.
- Retire the stale `deepseek/deepseek-v4-pro` (V4 Pro 0423) picker row via
  `RETIRED_SLUGS`. Kept DeepSeek rows: Pro 0813, the Flash Latest tracking
  alias, and Flash Vision Exp.

- Preserve the owner's picker selection (`model`, `model_reasoning_effort`)
  inside the managed Codex config block across installs and scheduled
  updates instead of resetting it on every rewrite.
- Reject image-bearing turns routed to a text-only model (409 naming the
  image content and the target model) instead of silently stripping the
  images: switch back to an image-capable model or continue without images.
- Route defined HTTP failures through one shared error catalog with stable
  codes (`codex_router/errors.py`, now in the deploy list); CLI/tool exits
  print `CODE: message` and logs record the same code.
- Promise and prove mid-thread model switching in Codex: switching models
  from the picker continues the same thread with history and tools
  intact, since every turn routes on its own model. If one
  model reports it is at capacity, switch to another and carry on.
  Astra subscription history (encrypted reasoning blobs, compaction
  items, tool calls/results) replays cleanly on Muse; blobs are
  stripped, readable summaries and results are kept, and opaque native
  compaction replays as a visible note rather than readable context.
  Image blocks do not carry over to text-only models. A model
  tool-count ceiling (Grok, 350 tools) defers instead of rejecting:
  over-ceiling turns go out with the search tool plus already-released
  tools, and the rest load on demand; the 409 stays only when the turn
  cannot fit under the ceiling that way. Grok image turns run text-only (new pinned
  `drop_images` registry quirk) with a short note where each image was,
  instead of stalling upstream.
  The thread effort carries over, and an effort the new model does not
  support (for example carried max onto Contributor) is rejected with
  the allowed levels instead of failing opaquely upstream.
- Scrub incomplete tool history before forwarding: partial calls and
  orphan outputs left by interrupted turns are dropped from replayed
  history instead of failing the whole turn with an upstream 400.
  Complete call pairs pass through untouched, on every model.

## 0.6.7

- Reject OpenRouter requests whose estimated input plus reserved output
  would exceed the model's context window (409 with an actionable message)
  instead of forwarding a doomed turn that the endpoint 400s outright.
- Retry transient feed-fetch failures inside the scheduled update check
  (up to 4 attempts, 30s/60s/120s backoff) instead of waiting a full
  15-minute poll cycle; deterministic errors still fail fast.
- Normalize picker labels to `<Vendor>: <Model> <Version?>` (e.g. `Z.ai: GLM 5.3
  Flash`, `Anthropic: Claude Haiku Latest`, `DeepSeek: V4 Flash Latest`):
  every `display_name` is stored qualified with its vendor prefix, alias rows
  track with `Latest` instead of a pinned snapshot, and pinned rows keep any
  version/snapshot token verbatim. `models add` (`qualify_name`) and
  `live_refresh` (alias rows keep their pinned tracking label) now produce
  conforming rows, and a registry test pins the convention.
- Merge the dated DeepSeek flash snapshots into the tracking alias
  `~deepseek/deepseek-v4-flash-latest` (upstream serves this id, aliasing
  0731); the old `deepseek-v4-flash` and `deepseek-v4-flash-0731` picker rows
  retire via `RETIRED_SLUGS`. Upstream serves no pro-latest id, so Pro keeps
  dated ids with clean names. Vision Exp stays separate as the only
  image-capable DeepSeek row.
- Repair existing bare or incomplete subscription catalogue rows on merge,
  preserving their model-specific metadata. Catalogue checks now reject
  rows missing schema fields instead of accepting an unusable picker.
- Add Linux systemd user service installation, updates, rollback and uninstall.
  Migrate legacy symlink installations to the stable launcher, replace old
  checkout/local-feed timers, and serialize installation operations. The
  service grants the router's drain time and restarts on exit.
- Leave busy installations untouched, restore the previous catalogue on a
  failed upgrade, and retain the updater's ETag when a child installer defers.
- Download this private repository's release assets through the user's
  authenticated GitHub CLI, including scheduled checks.
- Make the cross-platform pieces work on Windows so `python -m unittest
  discover` runs green there. The discovered-tools cache stamped each new file
  one nanosecond past its siblings to order eviction by insertion, but Windows
  FILETIME truncates that bump on readback, tying timestamps and evicting the
  wrong entries; it now steps past the sibling by an amount it confirms
  survives readback. Release bundles and the source-limit checker build member
  and baseline paths with POSIX separators (`as_posix`) instead of the host
  separator, and the stable launcher reads its pointer file as UTF-8. The
  install, update and service suites (macOS launchd / Linux systemd, which have
  no Windows equivalent) and a few POSIX-permission assertions are skipped on
  Windows only; they still run in full on macOS and Linux.

## 0.6.6

- Fix launchd spawning nothing after update: the installer persisted
  find_python's bare discovery token (`python3.14`) into the plist,
  which launchd cannot resolve (no Homebrew PATH). It now persists the
  probed absolute `sys.executable`, both plist renderers fail closed on
  non-absolute interpreters, and upgrades detect a legacy bare-python
  plist and reload the main agent (updater untouched) to heal it.

## 0.6.5 (unreleased)

- Remove feed signature enforcement: the installer accepts unsigned
  feeds again, trusting version, URL, checksum and serial plus the
  feed/manifest/marker identity check. The Ed25519 module and its
  `--gen-key`/`--sign` tooling stay in the tree as a documented
  opt-in for later. Owner decision: ceremony overhead outweighed
  the publisher-authentication benefit on this channel.
- Fix Claude POSTs with a query string (`/v1/messages?beta=true`)
  being rejected: `do_POST` now strips `?...` for route matching,
  mirroring `do_GET`, so query-bearing inference calls route like
  the bare path.
- Fix tag-gated releases never matching: the workflow stripped
  `-v` instead of `v`, so every tag would have failed the
  version check. Tags now compare correctly.
- Fix the Codex picker catalogue for Codex >=0.153.4 (desktop
  26.901.51231): every catalogue row now carries the full required schema
  (`display_name`, `available_in_plans`, `prefer_websockets`,
  `minimal_client_version`, `supports_parallel_tool_calls`,
  `supports_reasoning_summaries`, `default_service_tier`, `model_specialty`,
  `auto_compact_token_limit`, `auto_review_model_override`). Subscription
  roster rows seed as full-schema `subscription_stub()` entries with the
  live picker labels instead of bare `{'slug': ...}` stubs, which made chat
  creation fail with `missing field 'display_name'`. Defaults mirror the
  client's own embedded model catalogue.
- Test credential isolation: handler/compact/setup tests inject credentials
  instead of reading the machine's router home, so the suite stays green on
  machines where the router is installed (the real `openrouter.key`
  previously won the ordered lookup and turned 15 contract tests red).
  `Router` and `Credentials` accept optional injected credentials/home, and
  `default_home()` resolves `ROUTER_HOME` at call time. Also fixes the flaky
  `test_compact_holds_inflight_slot` (slot releases after response bytes
  leave the socket) and documents Linux `systemd` units plus the Arch
  `codex-desktop-git` pre-req in the README.
- Harden updates against live traffic: installs defer when the router
  is busy instead of killing in-flight requests, rollback restores the
  old pointer with `TERM` (never `bootout`, which stranded machines
  with no router), releases install only when feed, manifest and
  bundled marker versions agree, `--feed` is one-shot and never pinned,
  and three releases are retained for rollback depth. Releases publish
  from `v*` tags only; work lands on `develop` via short-lived
  branches, `main` stays release-only.
- Serve Claude Code model discovery: `GET /v1/models` answers
  `{data: [{id, display_name}]}` from the local registry so the CLI
  `/model` picker and the app picker list the router models as `From
  gateway` entries when
  `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=true` (Claude Code
  2.1.x, restart after changing the base URL). Listing ids are
  `claude/<vendor>/<name>` aliases, plus the bare `anthropic/...`
  Claude aliases which already pass the client's `claude|anthropic`
  filter; the router strips each alias back to its registry slug
  before routing, so billing follows the registry row and direct
  slugs keep working byte-identical. Unknown `claude/`-prefixed ids
  pass through to the subscription untouched.
- Hide OpenRouter-billed GPT rows from the Codex picker: the
  `openai/*` OpenRouter entries no longer list, so the picker shows
  the ChatGPT subscription models instead of a same-name paid
  duplicate. A directly requested hidden slug still routes to
  OpenRouter; nothing else in request handling changes. The future
  Claude listing reuses the same rule to hide OpenRouter-billed
  Anthropic rows.
- Fix context overflow on OpenRouter models: the output reservation is now
  capped at half the model's context window. The registry's 943718-token
  reservation on a 1048576-token window left ~105k for input, so ordinary
  long-task requests were rejected as exceeding the context.
- Clarify that the router runtime supports macOS, Windows, and Linux while
  the managed installer remains macOS-specific.
- Fix subscription-model 401s: the router no longer requires a
  subscription `Authorization` header on the loopback hop. Codex 0.153.4
  authenticates with the URL path token and omits that header, so every
  subscription request was rejected locally before reaching chatgpt.com.
  Headers now forward unchanged; missing or expired subscription
  credentials surface as the upstream response instead.

- Beta channel resolves to `beta/latest.json` on the same origin
  instead of calling the GitHub releases API.
- First-run key window claims the installer's empty key placeholder, and
  none-mode Codex config authenticates through the per-install path token.
- Service lifecycle: `POST /<token>/shutdown` drains and exits behind the
  path token; the service runs `router_launch.py` from the router home and
  `current` is a pointer file instead of a symlink.
- Offline probe accepts `--provider <id>` for the tool round trip on a
  custom provider.

## 0.6.1

- Rename the repository to
  `software-combined/SC_OpenRouter_adapter` and reframe the README for
  both clients: the router now serves the Codex picker and Claude Code.
  Update the release and updater URLs to the new location. No behavior
  change.

## 0.6.0 (Claude Code ingress, Preview)

- The loopback router now speaks the Anthropic Messages API at
  `/<token>/v1/messages` (plus `count_tokens`) for Claude Code, with the
  same billing split as the Codex picker: OpenRouter-registry slugs go to
  OpenRouter's Anthropic-compatible endpoint with the router key as the
  only credential, everything else passes through to `api.anthropic.com`
  with the client's own subscription credentials.
- OpenRouter-bound bodies travel byte-identical, so thinking blocks,
  tool_use IDs and cache_control keep full fidelity with no translation
  layer. Subscription requests keep version and beta headers; hop headers
  are stripped. No-subscription mode still serves OpenRouter models.
- Setup is one variable, `ANTHROPIC_BASE_URL` with the path token, and
  deliberately no API key variable, which would override the subscription
  bearer. Operator notes live in `docs/claude-code.md`.
- Preview status and residual risk: unit-verified against a fake upstream
  only. A paid live probe through real Claude Code sessions (one
  OpenRouter model, one subscription model) must pass before this is
  relied upon. Installer support for `~/.claude/settings.json` is
  deferred to a follow-up slice.

## 0.5.0

- Offer only the four Claude Latest aliases: Opus, Fable, Sonnet, and Haiku.
  Remove the previously pinned Opus 5 and Fable 5.1 picker entries on upgrade.
- Add DeepSeek V4 Pro 0813, V4 Flash 0731, and V4 Flash Vision Exp with
  current reasoning levels, input modalities, and token limits. Retain
  the original 0423 identities for existing tasks.
- Models without advertised effort controls can onboard with reasoning
  disabled; mandatory or unknown reasoning capabilities still fail closed.
- Newly added models remain Preview until paid Codex runtime probes pass.
- Install one global subagent-discovery rules block in Codex's active
  global AGENTS file, preserving existing instructions. Updates replace
  only the owned block; uninstall removes it. Rules are not repeated in
  the model catalogue and do not override permissions or delegation bans.

## 0.4.8 (first-run key window)

First-run setup and plan reconciliation from the audit brief, committed on
`codex/isolated-install-state`, not yet deployed (live router still runs
the pre-restructure prototype; see Plan 047 section 2):

- The router serves a first-run key window at `/<token>/setup/<nonce>`
  (Plan 047 G): single-use short-lived nonce, same-origin POST check, key
  validated against OpenRouter before anything is stored, owner-only key
  file, mode question asked up front, nonce closed on success. The generic
  DNS-rebinding rejection is unchanged for everything else.
- The router boots keyless while a fresh setup nonce is pending; every
  billable path still fails closed until a key resolves. `install --setup`
  mints the link and opens it instead of exiting without a key.
- `codex_router/router.py` stands at 256 lines against the 250 soft limit,
  pinned in the source-limits baseline with this justification: the loopback
  setup route shares the authenticated socket by design and all of its logic
  lives in the new `setup.py`; the router holds dispatch lines only.
- Plans truthfully reconciled: 041/043/045 marked implemented-not-accepted,
  044/046 partial, 042's two inaccurate plan-text claims corrected in-file,
  obsolete worktree instructions removed, request-cap and repository
  decisions recorded as settled, hourly hot-reload noted deferred.
- Residual risk: the setup window needs a live browser run before release;
  key validation calls OpenRouter but is never billed.

## 0.4.7 (acceptance harness slice)

Harness repairs from the audit brief, committed on
`codex/isolated-install-state`, not yet deployed (live router still runs
the pre-restructure prototype; see Plan 047 section 2):

- Compaction failure now fails verification: the probe raises instead of
  printing a status line and exiting zero, for both failed turns and
  protocol errors.
- New legs: `--compact-then-switch` compacts first and then retrieves the
  exact tool-result marker on another model; `--compact-twice` exercises
  repeated compaction; `--switch-to` replaces the hardcoded switch target
  so smaller-context models can be covered; `--expect-error` asserts a
  named rejection (unsupported effort, Grok's tool ceiling) exits clean
  while anything else still fails.
- Media evidence is attached, not discarded: `--image` sends a solid-red
  PNG and `--audio` a silence clip, with byte counts printed. Models with
  image input must name the color; text-only models pass by completing
  through the strip path. Wire shapes follow the canonical app-server
  protocol (`image`/`audio` items with data URLs).
- `CODEX_BIN` overrides the desktop binary so the legs above are proven
  offline against a scripted fake app-server (12 tests); isolated routers
  gain `restart()` for compact-restart-switch acceptance to build on.
- Residual risk: image/audio wire shapes and the color assertion still
  need one live paid run per modality before release.

## 0.4.6 (tool identity slice)

Tool-history, onboarding, and served-model fixes from the audit brief,
committed on `codex/isolated-install-state`, not yet deployed (live router
still runs the pre-restructure prototype; see Plan 047 section 2):

- Namespaced custom-tool history now converts exactly like its flattened
  definition: replayed calls and results take the wire name with no
  namespace, matching what the response leg already expects. Previously
  the guard missed namespaced entries entirely and survivors kept the
  wrong name.
- Served-model capture no longer depends on tool adaptation: tool-free
  200 responses are forwarded byte-identical while recording their model
  from JSON bodies and `response.completed` SSE events, for both
  providers. Error and malformed bodies stay untouched and unrecorded.
- `models add --probe` follows preview-activate-verify-promote: the
  candidate is written as preview first (the file-baked registry cannot
  route it otherwise), verified through an isolated router with its own
  home, port, token and catalogue, and only a pass promotes it to
  verified. `--dry-run` no longer bills a probe, and an explicit `--tier`
  still decides without probing.
- Alias display names refreshed from live `alias_target` data (four tilde
  rows); wire slugs, vendors, and all other fields untouched. Catalogue
  descriptions no longer double the vendor prefix on alias names.
- Residual risk: isolated probes bill the key and need the desktop app,
  so they stay owner-gated like all paid probes.

## 0.4.5 (compaction contract slice)

Compaction fixes from the audit brief, committed on
`codex/isolated-install-state`, not yet deployed (live router still runs
the pre-restructure prototype; see Plan 047 section 2):

- V2 `compaction_trigger` turns on OpenRouter models are answered inline
  with exactly one `ocx1:` compaction item briefed by the local
  summarizer; the trigger is never forwarded upstream. Contract proven
  against lidge-jun/opencodex f7f890f (MIT): trigger arrives as a normal
  non-streamed /responses call and the client fatals unless exactly one
  compaction item returns. Subscription traffic still flows to OpenAI,
  which mints its own blobs natively. `comp_hash` stays null.
- The summarizer rejects explicitly incomplete results
  (`incomplete_details.reason`) instead of installing a cut-off summary.
- An oversized newest message truncates to its tail instead of yielding
  an empty transcript.
- Discovered tool schemas persist per summary to `discovered-tools/`
  (owner-only, capped, insertion-ordered eviction) and chain across
  repeated compactions, so V1, V2, and restarted routers all resolve the
  same entry. Residual risk: live Codex acceptance of a real V2 trigger
  turn still needs a paid long-thread probe before release.

## 0.4.4 (installer lifecycle slice)

Lifecycle fixes from the audit brief, committed on
`codex/isolated-install-state`, not yet deployed (live router still runs
the pre-restructure prototype; see Plan 047 section 2):

- The pre-replacement Codex config is now backed up before the marked
  block is rewritten; previously the file was truncated first, so a crash
  between the two steps lost the backup.
- Uninstall runs the restore script with the installed home, checks that
  the restore actually happened, and aborts without stopping services
  when it did not. A failed restore used to be ignored while the agents
  were booted out anyway.
- `--version` rolls back to a previously installed release directory and
  health-checks it (restoring the prior pointer on failure) instead of
  trying to unpack the JSON feed document as a bundle. Only installed
  releases can be restored; the feed carries the latest bundle only.
- A failed first install removes the `current` pointer it created, so a
  retry reinstalls instead of reporting a never-served version as
  up to date.

## 0.4.3 (isolated-install slice)

Clean-install and configuration fixes from the audit brief, committed on
`codex/isolated-install-state`, not yet deployed (live router still runs
the pre-restructure prototype; see Plan 047 section 2):

- Fresh installs configure the static picker catalogue by default: the
  router serves no `/models`, so omitting `model_catalog_json` left a
  fresh picker with nothing to read. `--static-catalogue` stays accepted
  as a no-op.
- Fresh picker catalogues now list the subscription roster alongside the
  OpenRouter registry entries. `catalogue --merge` seeds missing roster
  slugs from the sibling state file as stubs and never rewrites existing
  rich entries. Plan 039's live `/models` remains the proper replacement.
- The no-subscription config block keeps root keys (`model_provider`,
  `model_catalog_json`) above the `[model_providers.scg_router]` table,
  uses the Plan 043 spike key name `SCG_ROUTER_TOKEN` instead of a
  per-port variable nothing provisions, and always points at the catalogue.
- Updates without `--openai-mode` keep the installed mode from state
  instead of silently rewriting a no-subscription block as a subscription
  block; the receipt records the installed mode.
- The updater agent is bootstrapped on fresh installs and carries
  `--home` always plus `--feed` when explicitly pinned. An explicit feed
  is pinned in `home/feed` (channel resolution otherwise); scheduled
  re-invokes no longer pin a channel-resolved feed.

## 0.4.2 (Plan 047)

Router correctness and installer fixes, committed on
`chore/no-request-cap-guard`, not yet deployed (live router still runs
the pre-restructure prototype; see Plan 047 section 2):

- Compaction keeps the newest transcript tail and names tools; runs
  before request preparation and holds a drain slot, so a release
  landing mid-compaction no longer loses the work.
- Discovered tools survive compaction; catalogue stubs are completed
  from discovered schemas instead of blocking them.
- Upstream 429 maps to retryable 503 with `Retry-After`.
- Summariser pinned to the lowest supported effort with a higher
  output cap; unreadable reasoning blobs stripped for OpenRouter
  models; image blocks stripped for text-only models.
- Installer seeds the picker catalogue (`catalogue --merge`) and
  writes `model_catalog_json` only with `--static-catalogue`.
- `/health` reports `served_models` (which upstream model actually
  served); tilde aliases display upstream alias names.
- CI fails if a request cap is reintroduced; `packaging/VERSION` is
  semver (`0.4.2`) and matches `pyproject.toml`.
- Internal router bugs surface as 500 with a traceback instead of 400.
- Upstream `openai-model` header is pinned to the requested slug so a
  rerouted model never triggers a mismatch warning; `/health` keeps
  reporting which model actually served.
- Release feed carries a monotonic `serial`; the installer refuses feeds
  older than the last accepted one and records it in `feed-serial`.
- OpenRouter picker entries carry the shared prompt in
  `model_messages.instructions_template` instead of the legacy
  `base_instructions` field.
- Fresh installs write the subscription-side model roster into runtime
  state (previously missing, so the router refused to start); existing
  state missing the roster is backfilled, never overwritten.

## 0.4.0 (Plan 041)

First installer release: `packaging/release.py` builds a deterministic
versioned bundle with `MANIFEST.json` and `latest.json`;
`packaging/install.py` (stdlib, Python 3.9+) verifies the checksum and
manifest, self-tests the bundle, swaps releases atomically with
health-check rollback, manages the LaunchAgents and daily update check,
and inserts the Codex config block. `packaging/install.sh` and
`packaging/install.ps1` are thin wrappers around the installer. GitHub
releases publish on `v*` tags with a beta channel.
