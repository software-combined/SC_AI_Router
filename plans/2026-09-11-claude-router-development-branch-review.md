# Claude router: development-branch review and plan amendments

> Read-only advisory, 2026-09-11. No repository changes were made by the
> audit that produced this document. Reviewed commit:
> `1c20ec91856b3141fdf37b36a6c1dac0e3f76b68` on `develop`. Findings F1-F9
> were re-checked against `develop` `1440645` on 2026-09-11 while applying
> the plan amendments and still describe the current control flow.

Review date: 11 September 2026
Repository: software-combined/SC_OpenRouter_adapter
Branch: develop
Reviewed commit: 1c20ec91856b3141fdf37b36a6c1dac0e3f76b68
Review type: Read-only source and planning audit, checked against current official documentation. No repository changes, staff-machine changes, releases, paid probes, or test-suite execution were performed.

## Decision

Keep the shared router and the existing protocol boundaries. Do not build a second Claude router, an embedded MCP gateway, or a replacement Claude interface.

Do not approve the current Claude plans unchanged. The highest-value changes are reliable client attachment and restoration, desktop-native connector provisioning, protocol compatibility, and evidence-based acceptance. Picker descriptions are useful but are not the critical path.

The target is equivalent setup quality, operational reliability, usable model selection, and convenient tools, not a claim that Claude and Codex expose identical interfaces or authentication models.

## 1. Source-confirmed findings

These findings follow from the reviewed control flow. They are not reports of incidents reproduced on a staff machine.

F1. Same-version installation skips client attachment

Priority: Release blocker for adding Claude to existing installations.
Owner: packaging/install.py::do_install.

The installer returns up to date when the available runtime is not newer, before it resolves the requested clients or invokes the Claude attachment helpers. A current Codex installation therefore cannot reliably add Claude using that installation path. The same problem prevents same-version configuration repair.

Amendment: Separate runtime version reconciliation from client configuration reconciliation. Explicit attachment, repair, key setup and policy changes must run independently of whether a runtime download is necessary. Do not restart a healthy service solely to add a client.

Acceptance: Start with the current runtime and an existing Codex attachment. Add Claude, repeat, detach Claude, then repair its attachment. Codex remains unchanged and the runtime version is not artificially incremented.

F2. The setup skill and preflight remain Codex-biased

Owners: skills/manage-router/SKILL.md, packaging/diagnostics.py::do_preflight, packaging/install.py::build_parser.

The skill's setup example omits --clients claude, while the installer defaults to Codex. Saying "for the invoking client" does not make that command client-specific. Preflight checks (args.client or 'codex') rather than the newer client selection, so a Claude-only request can still report a missing Codex CLI prerequisite.

Amendment: Give each supported surface an explicit setup invocation. Resolve client selection once and use that resolution in preflight, installation, status and removal. Do not require Codex to install Claude.

Acceptance: On a clean machine with Claude but no Codex, Claude preflight and setup do not request or modify Codex. Test the literal commands shipped in the skill.

F3. Claude-only setup returns before the key window opens

Owner: packaging/install.py::do_install.

The clients == 'claude' branch returns before the later code that prints and opens setup_url. With --setup, this can leave the first-run path dependent on subsequent recovery rather than the promised setup window.

Amendment: Complete shared first-run credential onboarding before a client-specific return. Keep credentials out of model conversations, skill arguments and ordinary diagnostics. Validate the existing recovery path separately instead of treating it as successful first-run setup.

F4. Claude detach can overwrite later user changes

Priority: Release blocker for safe configuration ownership.
Owners: packaging/claude_config.py::restore_settings, packaging/claude_desktop_config.py::restore_entry, and their detach callers.

Both restore paths unconditionally restore or remove owned keys using the previous snapshot. They do not first compare the current values with the values installed by the router. A user who changes the base URL after attachment can have that later setting removed during detach.

The attach paths also write configuration before the receipt is persisted. Desktop attachment spans multiple files. A later write failure can leave partially applied configuration without a complete ownership record. Reattachment only preserves the original snapshot in the completely unchanged case, which needs additional repair tests.

Amendment: Use a three-way ownership record: original value and presence, installed value, and current value. Refuse conflicting edits before any mutation. Preserve the original pre-attach state across repairs. Add recoverable transaction handling for multi-file changes and receipt failures. Reuse existing ownership primitives where suitable instead of creating a second configuration framework.

Acceptance: A post-attach hand edit survives a refused detach; unrelated fields survive every operation; interruption at each write boundary is recoverable; partial repair does not corrupt the original rollback snapshot.

F5. Attachment mode and runtime subscription mode can disagree

Owners: packaging/install.py, ai_router/protocols/messages.py, ai_router/claude.py::select.

The installer stores and checks claude_mode; the Messages policy passes anthropic_mode to runtime routing. Without that runtime field, routing falls back to the OpenAI mode. Changing --claude-mode is therefore not necessarily changing the policy used by an actual Claude request. In addition, claude_mode == none blocks attachment instead of merely prohibiting subscription passthrough.

Amendment: Define one canonical Anthropic billing policy and migrate legacy state explicitly. Keep attachment presence, billing permission and desktop profile selection separate. An OpenRouter-only client path must be qualified against actual client authentication requirements, not enabled using an untested credential workaround.

Acceptance: Test the full mode matrix, including no OpenAI subscription, existing conflicting legacy modes, OpenRouter-only requests, and refused native-subscription requests. Status must show the effective runtime policy.

F6. Status overstates attachment

Owner: packaging/diagnostics.py::do_status.

The attachment check is currently existence of the receipt's configuration path. A present settings file without the router's values can still be reported as attached. Plan 121 already identifies this gap.

Amendment: Read effective owned values, selected desktop profile and runtime policy. Distinguish installed, serving, configured, restart needed, models discovered and actual tool/billing acceptance. Avoid claiming that key presence establishes upstream key validity.

F7. Desktop attachment assumes a previously initialized Mac profile

Owner: packaging/claude_desktop_config.py::applied_entry_path and user_data_dir.

The helper expects an existing configLibrary/_meta.json with an applied entry. Its default directory is macOS-specific. That does not establish clean-install or Windows desktop support.

Amendment: Add a first-run desktop qualification step using supported configuration paths. Guard unsupported OS/surface combinations before any service or client mutation. Prefer documented configuration/export mechanisms to relying on private profile implementation details without a version check.

F8. Messages feature forwarding needs a compatibility contract

Owner: ai_router/claude.py::ClaudeOpenRouterProvider.prepare and tests/test_claude_ingress.py.

The OpenRouter-bound request is rebuilt with only OpenRouter authorization and JSON content type. Protocol feature/version headers are omitted. Existing tests assert that two-header result. Direct-slug bodies remain unchanged, but alias requests are JSON-reserialized after changing the model. The documentation's blanket "byte-identical" claim is therefore too broad.

Amendment: Separate credential isolation from protocol forwarding. For each upstream, preserve the supported Anthropic protocol headers and fields, with explicit handling for incompatible upstream features. Never forward subscription authorization or cookies to OpenRouter. Avoid a frozen list of individual beta values that silently breaks on a client upgrade. Test feature negotiation against the actual OpenRouter Messages endpoint before enabling dependent client features.

This is a verified forwarding gap, not proof that every ordinary MCP call currently fails. Basic function calling and deferred tool search are different capabilities.

F9. Discovery policy and route provenance need completion

Owner: ai_router/claude.py.

models_listing() does not receive the model allowlist, although routing does. Unknown gateway-style aliases can fall through to the Anthropic subscription provider. Claude passthrough also lacks the served_models tracking described for the other path in the documentation.

Amendment: Apply the same eligibility rule to discovery and execution. Treat unknown gateway-namespace IDs as errors rather than silently selecting a different billing route, while preserving intentionally supported native model IDs. Record only bounded, non-content request metadata: requested identity, reported served identity where available, route, timing, usage, and error category. A missing served identity must remain unknown.

## 2. Recommended MCP design

Separate inference from tools

The model router should continue to route inference. Native client MCP implementations should connect to tools. The setup/distribution layer should configure those clients. Do not make the inference router execute CRM, finance or Microsoft 365 tools.

Maintain one small approved connector catalogue only where it removes duplicated deployment work. Store endpoint/transport, owner, auth method, permitted surfaces, default tool policy and version requirements. Credentials and OAuth state do not belong in it. Generate client-specific declarations, not a universal configuration file that pretends every client uses the same schema.

Treat Desktop as a native deployment target

Current official documentation lists local and remote MCP, plugins, and marketplaces for Desktop 3P. Use the desktop configuration surface for desktop deployments and the Code surface for CLI deployments. The same setting name can have different shapes; desktop managedMcpServers is an array and Code's managed form is an object. [W1, W2, W3]

For the first staff-facing version, provision a small managed connector set with per-user authentication. Keep the existing router-management plugin focused on setup and diagnostics. Add a separate optional workflow/connector bundle only when grouping tools and instructions materially helps users.

The lack of portable connector toggles is not a reason to build nothing for onboarding. Preserve existing profiles; recreate approved definitions through supported native configuration; let the destination client perform its own sign-in. Do not copy OAuth caches or infer credentials from tool toggle IDs.

Fix private marketplace assumptions before sharing packaging

Desktop's documented git marketplace flow does not fetch plugin sources located in another repository. Plan 114's separate catalogue and adapter repositories therefore need a desktop-specific distribution proof. A plugin can appear in the catalogue without actually installing. [W4]

Prefer an automatically built deployment package or an authenticated, digest-pinned archive distribution if the installed desktop supports it. Keep canonical source in the existing repository. Do not require ordinary staff to clone private source repositories, and do not repurpose OpenRouter keys or loopback path tokens as download credentials.

Qualify tool search, do not merely turn it on

CLI custom-gateway and desktop gateway deployments have different controls. Desktop documents toolSearchEnabled; an ordinary ENABLE_TOOL_SEARCH=true environment setting does not override its gateway suppression. The feature requires compatible headers and deferred-tool request content. [W5, W6]

Make this a client-build, route and model capability. Do not globally enable it for all OpenRouter models. Where it is unsupported, use a small role-based connector set rather than loading every possible tool into every session. Measure startup context, time to first useful tool result and task success with a realistic inventory.

A desktop-wide feature setting also cannot be treated as a magical per-model switch. Until the full selectable model set supports the request shape, keep the shared profile conservative or create an explicitly qualified profile. Do not silently strip deferred tool references.

Pick two useful pilots

Use a standard remote MCP integration and Microsoft 365 as separate qualification cases. GitHub has documented hosted and bundled desktop routes. Microsoft 365 has its own desktop setup and approval prerequisites; it is not the old first-party connector copied into another profile. [W7, W8]

Require delegated user access, limited scopes and explicit approval for consequential writes. Keep portfolio identities separated. Model eligibility must reflect the data a connected tool can return, not only which model has the lowest token price.

## 3. Define parity by surface

Surface

Required evidence

Do not infer

Codex

Preserve existing successful installation and tool flows; run relevant regressions

That every advertised model capability is already proven

Claude Code CLI

Correct client attachment, approved inference routes, built-in tools and real MCP tools

Desktop readiness from a CLI subprocess

Desktop Code, gateway profile

Fresh-session model discovery, real tools, connector sign-in and safe restoration

Active subscription access merely because the first-party profile survives

Desktop Cowork

Explicitly qualify its setup, MCP, permissions, file workflow and long-session behavior when it is a promised surface

That desktop Code acceptance proves Cowork

Desktop Chat

Explicitly qualify enabled Chat features and connectors when promised

That desktop configuration automatically changes claude.ai web

The existing desktop evidence describes separate first-party and gateway profiles. A unified subscription-plus-gateway picker has not been established. Remove that assumption from mandatory release gates. A supported hybrid feasibility check may be a separate discovery task, but do not create a bootstrap service merely to chase parity or to configure MCP.

Preserve native Claude session management and compaction. Test long sessions, model switching, reasoning fields, tool call/result continuity and cancellation. Do not transplant Codex's Responses compaction endpoint into the Messages protocol.

## 4. Amend the existing plans rather than add a competing roadmap

Existing plan

Required amendment

113: CLI and desktop setup

Correct superseded credential and shorthand claims. Specify separate surfaces, canonical billing policy and first-run requirements.

114: Private setup plugin

Keep it a thin wrapper. Make commands client-specific, fix preflight and same-version attachment, provide safe client-scoped removal, and prove installed-package paths. Qualify desktop distribution separately from CLI.

115: Billing and acceptance

Replace a universal desktop subscription-pair gate with per-surface route requirements. Add an actual MCP invocation and result-use proof, not only a built-in Read probe. Retain spend approval and correlated billing evidence.

120: Desktop discovery/attach

Preserve implemented history. Add remaining live evidence and safe lifecycle tests. Do not promote temporary-listener discovery into full client acceptance.

121: Models, effort and connectors

Retain useful allowlist, status and deterministic-default fixes. Rewrite the MCP section around native desktop provisioning plus separate CLI integration. Add tool-search qualification and marketplace packaging checks. Put descriptions after blockers.

118 and compatibility records

Reuse the principle of provider facts versus proven client delivery. Do not inherit Codex verification as Claude verification.

For each edited plan, mark superseded steps in place and reconcile the index. The executor must not have to decide which conflicting instructions are authoritative.

## 5. Proposed implementation order

Change set 1: Safe lifecycle and correct setup

Fix same-version attachment, selection-aware preflight, first-run key-window completion, one billing-policy owner, conflict-safe restoration and partial-write recovery. Add explicit per-client attach/repair/detach behavior without uninstalling the shared router or silently detaching Codex.

Change set 2: Protocol and discovery correctness

Qualify feature forwarding, error/retry behavior and aliases. Complete allowlist projection and truthful status. Keep model identity and capability labels honest. Preserve tool IDs, results, caching fields and streaming behavior. Avoid inventing a reasoning picker through misleading model aliases.

Change set 3: Native MCP onboarding

Implement the smallest supported desktop configuration and CLI configuration paths for the pilot connectors. Validate existing managed policy before writing. Exercise actual cached plugin installation only for the distributions being promised.

Change set 4: Capability and release acceptance

Run offline tests first, then explicitly approved live probes against pinned client builds. Publish only the surface/model/capability combinations that have evidence. Release and fleet rollout remain separate decisions.

## 6. Acceptance checklist

Offline lifecycle: Clean Claude-only host; existing Codex host; same-version attach and repair; repeat operations; conflicting manual edits; original snapshot preservation; failure after each configuration write; missing receipt; token/port changes; unsupported desktop OS; no paid/network provider calls in unit tests.

Offline protocol: Direct and aliased IDs; rejected unknown gateway IDs; all billing modes; listing/route policy agreement; ordinary and deferred tools; feature/version headers; streaming and cancellation; 401/403/429 and retry metadata; cache fields; no credential or content leakage in diagnostics.

Real client: Fresh model picker, a built-in tool result, a real MCP tool call whose unpredictable returned marker is used in the answer, OAuth sign-in and renewal where applicable, a denied tool, and recovery from an unavailable connector. Test desktop sessions themselves, not a CLI launched from within the app.

Efficiency: Realistic connector inventory, measured initial context and latency, a multi-step task, long-session continuation and model switching where promised. Capture actual served identity when available. Do not assert native reasoning or tool-search support because a discovery row is assigned a Claude family tier.

Release: Record source SHA, runtime release, OS, desktop build, bundled Code build, route, model, tool outcome and accounting evidence. Keep source, packaged installation, runtime, billing and rollout statuses separate. Run repository-required checks and review in the prescribed owned worktree before proposing integration.

Confidence and limitations

Overall confidence: 0.93. Source-control-flow findings are high confidence. Actual desktop, gateway and model compatibility must still be demonstrated on the promised client builds. No globally optimal architecture or live release readiness is established by a planning audit.

Source map

Repository paths below were read at the reviewed commit. Use this immutable base for all repository references:

https://github.com/software-combined/SC_OpenRouter_adapter/blob/1c20ec91856b3141fdf37b36a6c1dac0e3f76b68/

AGENTS.md

plans/113-claude-cli-and-desktop-gateway-setup.md

plans/114-claude-code-private-plugin.md

plans/115-claude-billing-probes-and-release-acceptance.md

plans/118-codex-router-full-capability-parity.md (opening sections)

plans/120-claude-desktop-gateway-discovery-and-attach.md

plans/121-claude-desktop-models-effort-and-connectors.md

ai_router/claude.py

ai_router/protocols/__init__.py

ai_router/protocols/messages.py

packaging/install.py

packaging/claude_config.py

packaging/claude_desktop_config.py

packaging/diagnostics.py

.claude-plugin/plugin.json

skills/manage-router/SKILL.md

tests/test_claude_ingress.py (returned opening sections)

docs/architecture.md

docs/claude-code.md

docs/compatibility.md

Official references consulted on 11 September 2026:

W1: https://claude.com/docs/third-party/claude-desktop/feature-matrix
W2: https://claude.com/docs/third-party/claude-desktop/configuration
W3: https://code.claude.com/docs/en/managed-mcp
W4: https://claude.com/docs/third-party/claude-desktop/extensions
W5: https://claude.com/docs/third-party/claude-desktop/gateway
W6: https://code.claude.com/docs/en/mcp
W7: https://claude.com/docs/third-party/claude-desktop/connectors-github
W8: https://claude.com/docs/third-party/claude-desktop/connectors-m365
W9: https://code.claude.com/docs/en/llm-gateway-protocol
W10: https://code.claude.com/docs/en/llm-gateway

W9 is the protocol reference for F8. W10 distinguishes native subscription passthrough from gateway/API credentials and states Anthropic's support boundary for non-Claude models. Cross-model use through this router is an SCG-qualified compatibility path, not an Anthropic endorsement.
