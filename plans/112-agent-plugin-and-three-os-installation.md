# Plan 112: Install and manage the router through Codex and Claude Code on macOS, Windows and Arch Linux

> **Consolidation, 2026-09-09 at `96db57f`:** retain this umbrella's full
> Codex/Claude and macOS/native-Windows/Arch acceptance scope. Later decisions
> override historical wording below: 106 owns private token-gated downloads
> and future main-to-stable/develop-to-beta publication; 107 owns centrally
> provisioned keys recipients never paste; 105 implements the selected private
> Python runtime. Current releases remain tag-driven until 106's approved
> cutover. PR #3 is merged (`cc365629`); qualify its Linux implementation.
>
> Execution owners: 067 updater extraction, 056 OS backends/CI, 116 Windows,
> 117 recipient docs/native Linux acceptance, 105 interpreter/bootstrap,
> 061 domain/bundle rules, 063 shared client receipts/modes, 113 Claude
> settings, and 114 Claude plugin. This umbrella retains the Codex manifest,
> shared skill, catalogue publication and cross-client/OS acceptance. Reuse
> their source, never build it twice. Synthetic bootstrap/client slices need
> not wait for AWS publication or staff hosts.

> Planning only. This document does not authorise implementation, paid probes,
> staff-machine changes, cloud deployment, marketplace publication or live-router
> cutover. Execute one working slice at a time after implementation is requested.
> Read current repository instructions and preserve other contributors' work.

## Outcome and decisions

A staff member installs **SCG OpenRouter Setup** from the SCG marketplace,
asks their existing agent to set it up, enters their IT-issued OpenRouter key
in a local browser window, restarts the selected client, and completes a real
model/tool round trip. The agent performs prerequisite and installer work.

- **First observable proof:** on a designated Mac, the installed Codex plugin
  runs the packaged setup workflow, a versioned router starts, and a fresh
  Codex task completes one OpenRouter tool round trip while OpenAI still uses
  the existing subscription. This is an internal slice, not the supported release.
- **First supported release:** macOS, native Windows and Arch Linux all pass
  their staff-machine acceptance gates for both Codex and Claude Code.
  Cyril explicitly selected all three OS families and designated staff machines.
- **Linux ownership:** Cyril reports an Arch contributor preparing a PR.
  Integrate and qualify that contribution; do not start a competing Linux
  implementation. No open adapter PR was visible during this planning pass.
- **Repository split:** keep router source, installer, tests, release pipeline
  and plugin package in `software-combined/SC_OpenRouter_adapter`.
  `software-combined/SC_Agent_plugins` remains the discovery catalogue.
- **Local execution:** one router per OS user, shared by both clients. No
  hosted inference proxy, MCP server, background AI agent, install hook or
  automatic machine mutation on plugin enable/refresh is required.
- **Authentication:** preserve native client sign-in. IT supplies one
  OpenRouter key per user, entered outside chat. No new provisioning portal,
  shared key, subscription purchase, SSO replacement or request cap.
- **Release policy:** retain the current tag-driven release policy. Older
  plans describing release on every push do not change that policy here.

Priority P1; effort L, delivered in bounded commits; delivery risk HIGH because
setup changes authentication routing, user configuration and service lifecycle.
Planned 2026-09-08 against adapter `9f2a6faa2e4392aac72015afb2c2a1e9411e94ca`
and marketplace `ab8d9434548d724dd392d68cf4335c534fc99f72`.

## Current source and boundaries

The local adapter checkout is `~/Documents/Github/SC_Codex_openRouter_adapter`;
its canonical remote is `software-combined/SC_OpenRouter_adapter`, private.
The integration target is `develop`; release promotion is a separate PR to
`main`. Planning worktree: `~/Documents/Github/.worktrees/router-plugin-plan`,
branch `codex/plan-router-plugins-multios`, owner this planning task.

Run `git diff --stat 9f2a6fa..HEAD -- packaging codex_router tools tests .github docs AGENTS.md`
before execution. Reconcile changed contracts, especially the Arch PR and the
active Claude verification stream, before editing. Do not reclaim their worktrees.

Relevant verified source:

| Location | Current behaviour and implication |
|---|---|
| `packaging/install.py:232` | Main installation path; shared download/verification plus macOS service and Codex-only configuration in one function. |
| `packaging/service.py:36` | Feed points to private GitHub; anonymous staff updater cannot use repository credentials it does not possess. |
| `packaging/install.py:248`, `CHANGELOG.md` | Owner-approved signature removal is integrated. Installer accepts unsigned JSON feeds and retains serial, checksum and feed/manifest/marker identity checks. Ed25519 tooling remains optional; this plan does not restore enforcement. |
| `.github/workflows/release.yml` | Tag-driven; the `v` prefix fix is integrated. Extend the existing publication path for AWS distribution. |
| `packaging/install.py:250` | Same-version early return precedes setup/configuration, so adding another client or reopening key setup cannot rely on reinstalling the same version today. |
| `packaging/install.py:323` | Always writes Codex configuration; no Claude-only installation target. |
| `packaging/service.py:144` | Scheduled updater points inside a versioned release; use a stable management entrypoint so pruning cannot remove its executable. |
| `tools/disable.py` | Restores the Codex block and invokes `launchctl`; configuration detachment and shared-service removal are not separated. |
| `codex_router/router.py:136` | Authenticated `POST /shutdown` already exists. Reuse it for portable drain; do not add another control endpoint. |
| `codex_router/setup.py` | Local, expiring key-entry window exists; subscription selection currently changes state separately from installer-written configuration. |
| `codex_router/credentials.py:20` | Windows bypasses POSIX mode checks; Windows needs actual ACL enforcement. |
| `docs/claude-code.md` | Claude uses `ANTHROPIC_BASE_URL`; native subscription headers must remain intact. Live verification is recorded as pending on this baseline. |
| Plan 106 feed table | Existing delivery direction is AWS account `651116729473`, `ap-southeast-2`; feed publication and live cutover remain separate gates. |

Code excerpts for drift detection:

```python
# packaging/install.py, after feed/version verification
if not newer(latest['version'], current_version(home)):
    print(f"up to date {current_version(home)}")
    return 0
# Current client configuration target
config_path = Path.home() / '.codex' / 'config.toml'
# packaging/service.py
installer = base / 'packaging' / 'install.py'
```

Match the existing Python stdlib style: `Path`, small functions, explicit
`SystemExit` failures and injectable `run`/`fetch` boundaries. Use
`tests/test_install_config.py` and `tests/test_install_lifecycle.py` as examples:
temporary homes, synthetic bundles, mocked upstream/service operations,
and assertions on preserved configuration and observable outcomes.

Scope is packaging/service lifecycle, client configuration, local setup,
credential permissions, associated tests, plugin metadata/skills and release
documentation. Touch `router.py`/`activation.py` only for lifecycle and independent
client-mode handling required here. No provider/model roster expansion, protocol
parity project, review-plugin migration, repository move or unrelated cleanup.
AWS infrastructure belongs in `SC_Infrastructure`, under its own instructions;
this adapter plan defines the required delivery outputs, not a second IaC source.

This plan supersedes the installer/package approach in 047 E/F with plugin-led
setup. It retains 047 A's AWS-feed dependency and B's separate cutover gate,
and the current 048 IT-issued-key decision. The integrated signature-removal
decision supersedes older signing requirements. Do not resurrect the superseded
invitation service. Historical plans remain evidence, not parallel work orders.

## Product and installation contract

### Supported surfaces

| OS | Required acceptance target | Background mechanism | Clients |
|---|---|---|---|
| macOS | Designated staff Mac; record exact OS and CPU | Existing per-user LaunchAgents | Codex desktop and CLI; Claude Code CLI |
| Windows | Designated native Windows 11 x64 staff machine | Per-user Task Scheduler | Codex desktop and CLI; Claude Code CLI |
| Linux | Contributor's Arch Linux x86_64/glibc/systemd staff machine; record package versions | systemd user units from the Arch PR | Codex CLI and Claude Code CLI |

Support only architectures actually qualified. Add bootstrap pins for macOS
arm64/x86_64, Windows x64 and Linux x64; an untested variant stays explicitly
unqualified. Additional Linux distributions, musl, WSL cross-host routing,
Windows ARM, headless servers and cloud-hosted agent sessions are outside v1.
No Linux desktop-app promise. Services run in the user's session; do not require
root, store a Windows password or silently enable systemd lingering.

### Plugin and user journey

1. Add `.codex-plugin/plugin.json` and `.claude-plugin/plugin.json` at the
   adapter repository root, with plugin name `scg-openrouter`, display name
   `SCG OpenRouter Setup`, and a shared `skills/manage-router/SKILL.md`.
   The whole repository is the plugin root, so the skill can use the existing
   `packaging/` and `codex_router/` files without escaping its installed cache.
   This deliberately uses a repository-root source instead of duplicating
   installer code into a plugin subdirectory. Publish matching semver metadata
   from `packaging/VERSION`; runtime bundle build identifiers remain separate.
2. Provide setup, status, update and removal workflows through that one skill.
   A Codex starter prompt can say "Set up OpenRouter on this computer"; the
   equivalent Claude command is `/scg-openrouter:manage-router setup`.
3. Default setup to the client the user invoked. Configure both only when
   requested. Detect existing clients/configuration and report the exact
   proposed target before running the mutating setup action. Respect the
   user's existing authorisation and the host's real approval policy; do not
   demand a second generic confirmation or grant new tool permissions.
4. Run native prerequisite bootstrap, then the canonical Python installer.
   Reuse a verified suitable Python if present; otherwise install a pinned,
   private CPython 3.14 runtime. The user does not manually install Python.
5. Collect client subscription modes before activation. The key window only
   collects the key and displays those choices; it must not independently
   change routing after config was written. Preserve the CLI's explicit mode
   flags. Never request a key in chat, command arguments or environment edits.
6. Keep the service running from its stable private installation directory,
   never a plugin-cache path. Removing/upgrading the plugin must not strand
   the router. Restarting a client is a separate user-visible step, not an
   automatic termination of the session performing installation.
7. Report separate states: prerequisites ready, service healthy, key configured,
   client restart needed, and client round trip verified. Health alone is not
   successful model setup. A working signed-in agent is a bootstrap prerequisite;
   document the same packaged script as the manual fallback.

### Installer interfaces and ownership

- Extend the existing entrypoint; keep `--home`, `--python`, `--dry-run`,
  `--setup`, `--check-update`, `--version`, `--uninstall` and `--openai-mode`.
  Add `--clients codex|claude|both`, `--claude-mode subscription|none`, and
  `--status --json`. Setup attaches selected clients and never silently detaches
  an already attached client. Uninstall with an explicit client selection
  detaches that selection; without one it removes all recorded attachments.
- Retain `~/.codex/mixed-model-router` as the default router home on all OSes
  for compatibility; `--home` remains authoritative and no state relocation is
  needed. Resolve client homes from `CODEX_HOME` and `CLAUDE_CONFIG_DIR` when
  present, otherwise their normal user locations. Store resolved paths for
  scheduled operations rather than rediscovering them in a different environment.
- Separate release acquisition from configure/repair/setup. The same installed
  version must allow adding Claude, repairing a service, reopening an expired
  key window and detaching a client without downloading or deleting that release.
- Upgrade activation receipts to a versioned record with a `clients` map.
  Each attachment stores its config path and exact owned prior/installed values;
  retain Codex's managed-instruction receipt. Import the current legacy receipt
  as a Codex attachment without losing its original restore information.
- Codex keeps the existing managed TOML block/static catalogue. Serialize Windows
  paths correctly for TOML and reject conflicting/hand-edited owned values.
  Claude merges only `env.ANTHROPIC_BASE_URL` and
  `env.CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY` into user `settings.json`.
  Leave native login, default model, API-key overrides and managed policies alone;
  conflicting effective overrides block activation with a redacted explanation.
- Keep `openai_mode` for Codex and add independent `claude_mode`, defaulting to
  `subscription`. A Codex OpenRouter-only configuration must not disable a user's
  Claude subscription. Native Claude via Claude Code and native OpenAI via Codex
  preserve their respective billing routes; Claude inside Codex bills OpenRouter.
- Preflight every selected configuration before touching the live service.
  Write atomically with concurrent-edit checks. If applying several client files
  fails, restore only writes still matching this invocation, keep a needed
  router running, and report partial/blocked state rather than success.
- Refactor `tools/disable.py` into configuration restore plus installer-owned
  service removal. Restore owned values only if still exact; preserve unrelated
  edits. Leave the shared service/updater running while any client remains
  attached. Retain credentials/state after full uninstall, matching current
  behaviour; deletion and provider-key revocation are explicit separate actions.
- Status JSON includes installed version, service state, registered client
  states and key-present/usable booleans. No raw config, bearer/path tokens,
  setup URLs, keys, prompts or tool content in tool output or diagnostic exports.
  Open the setup page locally without printing its secret-bearing URL; browser
  failure leaves setup pending and directs the user to the local helper.

## Implementation sequence and verification gates

### 1. Freeze contribution boundaries and prove a local bootstrap

Record the Arch contributor's PR/head when available, its target branch and
ownership. Review the implementation before adapting it; an unpublished PR
does not authorise duplicate Linux work. Coordinate integration through the
owner without sending messages or changing their branch under this plan.

Use the root plugin layout and existing installer in an isolated home to prove
that installation from a plugin cache resolves every required file. Do not
extract a broad installer framework first. Complete one Mac setup/configuration
path using synthetic feeds before extending the OS boundary.

**Verify:** plugin manifest validation; run the relevant existing installer tests;
the first local smoke must produce a versioned home and redacted healthy status.
Use only disposable fixtures at this stage, with no paid or subscription call.

### 2. Complete trusted distribution and native Python bootstrap

Complete 047 A's delivery prerequisite using private S3 origins and CloudFront
HTTPS in the recorded AWS account/region. Verify current identity, OIDC claims,
repository IDs and existing infrastructure before proposing cloud changes.
Do not reuse historical claim formats blindly. The source repository stays
private; distribute only reviewed, non-secret runtime assets through the feed.

Publish stable/beta feeds over HTTPS and immutable versioned bundles. Retain
serial, checksum, manifest and version-identity checks; check downloaded update
code before executing it. Preserve the owner's decision to accept unsigned
feeds. Checksums do not authenticate the publisher: access to feed/bundle
publication is the trust boundary, owned by the release/infrastructure team.
Do not introduce a signing-key ceremony or restore signature enforcement.

Extend the shell/PowerShell wrappers to run without Python already installed.
Use reviewed `python-build-standalone` install-only CPython 3.14 artifacts, pinned
by immutable URL and SHA-256 in one checked-in runtime lock. Generate wrapper
pin data from that lock; avoid two independently maintained sets of hashes.
Verify the archive with native OS hash tools before executing it, install under
the router user's private home, retain licenses, and verify `compression.zstd`.
Do not change system Python/PATH, install a package manager, use `curl | sh`,
disable TLS checks, bypass execution policy or remove quarantine protections.
Updates to the router must not re-download an unchanged interpreter.

**Verify:** mocked checksum/version-identity mismatch and stale-feed cases leave the
working install unchanged; wrong-platform/checksum Python downloads never run;
the clean-Mac plugin slice completes against the authorised HTTPS beta feed.
Account, domain and publication stay separate approval gates. Local synthetic
fixtures keep implementation work unblocked before them.

### 3. Deliver shared client lifecycle on macOS

Implement the installer/receipt contract above, including same-version setup,
independent client modes and safe partial removal. Extract only the service and
client operations needed by this working slice; keep entrypoints below their
700-line hard limit and ordinary modules below 400 lines.

Keep macOS LaunchAgent labels and socket activation. Add a stable management
launcher beside `router_launch.py` that resolves the active release for update,
status, rollback and uninstall. Scheduled jobs must never reference prunable
release paths or plugin caches. Share the existing verification/activation code.

Serialise install/update/rollback/uninstall for one router home with an OS-held
lock released on process death. Stage immutable candidates before activation;
wait for idle before switching pointers. A live non-idle router defers the
operation. Unknown health of a still-running process is a blocked operation,
not proof of idleness. Health-check activation and roll back a failed candidate.
Do not prune releases until success; retain the existing rollback depth.
Reject rollback to an installer unable to read the active receipt version.

**Verify:** `tests.test_install_config`, `tests.test_install_lifecycle`,
`tests.test_setup`, `tests.test_credentials` and new client-management tests pass.
On the designated Mac, attach both clients, detach either, and prove the other
continues working; rehearse two plugin-aware versions and failed-update rollback.

### 4. Deliver the native Windows slice

Add a Windows service backend behind the installer service boundary. Use
Task Scheduler under the current user's SID with interactive-token/least-privilege
execution, no stored password, a logon trigger and repeated recovery trigger.
Set `IgnoreNew`, an unlimited router execution time (`PT0S`), and laptop battery
settings that do not stop working sessions. Run with `pythonw.exe`; use correct
Windows argument quoting for paths with spaces. The update task runs every
15 minutes and calls the stable management launcher.

Reuse authenticated `/shutdown` for graceful restart. Wait for the old task to
exit and explicitly start the router task; successful exit must not be assumed
to trigger Task Scheduler's failure-restart policy. Keep a one-minute repeated
router trigger as recovery, with duplicate launches ignored. Busy operations
defer, never use `taskkill /F`. A brief reconnect interval is acceptable; do not
claim launchd-style socket continuity on Windows.

Apply and verify Windows ACLs on router state, credentials and sensitive
receipts/backups before storing secrets: current SID plus SYSTEM/Administrators,
no broad inherited user access. Use native Windows facilities, with a shared
permission helper used on creation and verification; `chmod(600)` is not evidence.
Keep handles closed before rename/prune and preserve releases locked by another
process instead of forcing deletion. The router remains stdlib-only.

**Verify:** Windows backend, quoting, ACL, concurrent-operation, same-version
repair and lifecycle tests. On the designated Windows machine, prove logon
start, one shared router, model/tool round trips, update, rollback, partial
uninstall and full uninstall without administrative elevation.

### 5. Integrate and qualify the Arch contributor's Linux slice

After the contributor's PR is available, compare it with steps 2-4 and reuse its
Linux implementation. Resolve only gaps needed for the shared contract; do not
replace it merely to match provisional module names. The integration owner
owns cross-platform contracts and review; the contributor retains their branch.

Required Linux behaviour: systemd **user** service/socket and update timer;
loopback listener only; `WantedBy=default.target`; native `LISTEN_PID`/`LISTEN_FDS`
validation for socket activation; restart support and stop timeout above the
120-second drain deadline; private user files; stable management launcher.
Use POSIX modes 700 for the router home and 600 for secret-bearing files.
No root service, global Python replacement or implicit `enable-linger`.
If the user systemd manager is unavailable, report the unsupported environment
before mutation rather than falling back to a shell-profile background process.

**Verify:** PR tests plus the same installer/receipt/update suite on Linux;
`systemd-analyze --user verify` for rendered units. The Arch staff machine must
prove login start, socket activation, both clients, authenticated key setup,
scheduled update, rollback, independent detachment and complete service removal.
CI Linux checks supplement this machine; they do not replace its acceptance.

### 6. Publish the catalogue entries only after qualification

In `SC_Agent_plugins`, append `scg-openrouter` to the Codex marketplace and add
a Claude marketplace at `.claude-plugin/marketplace.json`. Preserve existing
`scg-review` contents and its support claims. Use repository-root URL sources
pointing at the adapter and pin both entries to the same reviewed full commit
SHA; version changes advance that pin through a reviewed marketplace change.
Codex entries retain required category/installation/authentication metadata;
Claude uses its native manifest schema. Do not add the review plugin to Claude
until its own separate Claude support work is qualified.

Test the actual installed cache, not just source paths. Codex workspace import
requires an authorised GitHub identity able to read both private repositories;
workspace members' plugin access is configured by their admin. Direct Git
installs require repository read access on the recipient. Claude private
marketplace access must be verified on each pilot machine. No GitHub credential
is copied into the router or unattended updater.

Plugin updates refresh setup skills/bootstrap; the independent HTTPS router
feed updates the running service. Publish a compatible runtime first, then the
plugin/catalogue pin. Explicit setup/repair reconciles client configuration;
plugin refresh alone does not rewrite it or restart either application.

**Verify:** both native manifest validators and marketplace tests pass; a fresh
Codex task and Claude session discover the installed skill; source commit,
installed plugin version, runtime version and client verification are recorded
separately. A plugin refresh/uninstall leaves a configured router usable.

## Test and release acceptance

Existing required commands, run from the adapter worktree with Python 3.14:

Baseline on the planned commit: 369 tests passed; compilation and source limits
passed. The suite emitted existing unclosed-socket ResourceWarnings. This is
local source verification, not native Windows/Linux or paid-client acceptance.

```sh
python3.14 -m unittest discover -s tests -t .
python3.14 -m compileall -q codex_router tools tests
python3.14 tools/check_source_limits.py
```

On Windows use the resolved runtime executable instead of the `python3.14`
command name. Baseline tests are offline/synthetic; real upstream probes remain
separate and require authorisation. CI must run the suite and packaging checks
on native macOS, Windows and Linux runners. Avoid platform-wide skips that hide
client/configuration defects; skip only genuinely OS-specific assertions.

Add focused tests beside the relevant implementation, using existing fakes:

- Plugin-cache install without Python; existing Python; unsupported architecture;
  missing prerequisite; tampered interpreter/feed/bundle; no secret in output.
- New install; same-version configure/repair; expired or invalid key setup;
  rejected key; network unavailable; setup complete only after config matches.
- Codex-only, Claude-only and both; independent subscription modes; inherited
  configuration homes; Windows TOML/path escaping; conflicting managed settings.
- Add second client; concurrent edits; rollback of only owned writes; legacy
  receipt import; edited receipt/config refusal; partial/full uninstall.
- Busy updater; unknown health with live service; concurrent installers; failed
  health rollback; scheduler remains valid after multiple releases are pruned;
  incompatible rollback refusal; plugin-cache deletion while router runs.
- Real native permissions, service definitions and reboot/login behaviour on
  the three designated staff machines. Test disconnect recovery on Windows.

Before first supported release, all boxes must be checked:

- [ ] Relevant tests, compilation, source limits, manifests and review gates pass.
- [ ] HTTPS feed and interpreter bootstrap work without staff GitHub/AWS keys.
- [ ] Exact OS/architecture, client versions, plugin SHA/version and runtime
      version are recorded in `docs/compatibility.md` for each staff machine.
- [ ] On each OS, each client completes one subscription request and one
      OpenRouter request, including a tool call/result/final-answer round trip.
      Use an already qualified OpenRouter model, not a new-model onboarding test.
- [ ] Native auth stays intact and no subscription header reaches OpenRouter.
- [ ] Each machine observes a scheduled verified update at the next eligible
      idle check (15-minute cadence plus up to 120-second jitter); rollback and
      re-login recovery pass; no claim of updates while the machine is offline.
- [ ] Partial uninstall leaves the other client working; full uninstall restores
      owned client settings and removes only owned services/tasks/timers.
- [ ] Marketplace install/pickup and actual staff usability pass separately from
      GitHub publication. Cyril accepts the pilot before broader availability.

## Handoff, unresolved inputs and stop conditions

One writer/worktree per repository. Reuse the execution worktree across slices;
take ownership of no existing contributor branch without a handoff. Commit in
coherent increments under the shared size gate, run current pre-commit review,
integrate through `develop`, and verify/clean up at each milestone. Match
`feat:`/`fix:`/`test:`/`docs:` subjects. User-visible implementation increments
update CHANGELOG and VERSION; this planning-only document changes no release.

Inputs still required before their dependent operations, not before local work:

| Input | Owner and gate |
|---|---|
| Arch PR URL/head and contribution boundary | Existing contributor/Cyril; before Linux edits or merge. |
| Named Windows pilot and exact Mac/Arch details | Cyril/staff owners; before staff-machine changes. |
| Feed domain, existing AWS stack and publisher access confirmation | Infrastructure/release owner; before cloud publication or real install. |
| Subscription/test seats, IT-issued keys and bounded probe authorisation | Account owners/Cyril; before any live billable request. |
| GitHub import identity and marketplace role availability | Workspace/repository admins; before pilot distribution. |

Stop the affected slice if a contribution owns the same files, policies block
custom routing/plugin access, prerequisites require bypassing OS protections,
an owned config cannot be restored safely, publisher access is unavailable,
or a required staff/client combination fails. Continue independent local work.
Do not silently drop Linux/Windows or substitute CI proof for the agreed staff
acceptance. Preserve the current live prototype until authorised cutover and a
tested rollback; neither a plan commit nor a green unit suite authorises it.

This investigation covered installer, update, configuration, plugin distribution
and their tests. It did not re-audit model protocol parity, inspect staff devices,
deploy AWS, validate billing live or review the not-yet-published Arch PR.

## Source references and maintenance

- [Codex plugin packaging and root sources](https://developers.openai.com/plugins/build/plugins)
- [Codex workspace import, private referenced repositories and sync](https://learn.chatgpt.com/docs/enterprise/plugin-management)
- [Claude plugin sources, caching and versioning](https://code.claude.com/docs/en/plugin-marketplaces)
- [Claude settings scopes and configuration homes](https://code.claude.com/docs/en/settings)
- [Python standalone distribution targets and licensing](https://github.com/astral-sh/python-build-standalone/blob/main/docs/running.rst)
- [Windows task lifetime](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-executiontimelimit)
- [Windows duplicate-task policy](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-multipleinstances)

Reverify host plugin contracts after client upgrades, runtime pins after Python
updates, and Linux assumptions against the contributor's actual PR. Plugin,
runtime and marketplace versions are independent delivery states. Keep this
plan and the existing status index aligned with observed acceptance.

## Planning verification

Required source checks passed on `9f2a6fa`: 369 offline tests, compilation and source
limits. The vault routing note was updated and its validator passed.

Simplification completed as a no-op. Correctness, quality and adversarial
reviews returned `ALL_CLEAR` on the complete staged plan and index at tree
`406e0467c7b1b2b63b9d3ff7f7e7ebe200bbb704`. All four passes requested
`meta/muse-spark-1.3-contributor` at `xhigh`; returned model/effort were
`unverified`. The final delta only updates this verification record; the
implementation contracts are unchanged. Final whitespace and secret checks
passed before exact-tree approval.
Implementation and release acceptance remain separate from this plan's review.
