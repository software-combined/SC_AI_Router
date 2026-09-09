# Plan 063: Give each client explicit activation and subscription policy

> Planning only. Execute only when implementation is authorised. This extracts
> the existing Codex client and enables a service-only installation. Actual
> Claude configuration and plugin behavior remain Plans 051 and 053.
>
> Drift check: `git diff --stat 6840312..HEAD -- packaging/install.py packaging/codex_config.py packaging/service.py packaging/release.py tools/disable.py tools/global_instructions.py codex_router/runtime.py codex_router/router.py codex_router/claude.py codex_router/protocols/messages.py codex_router/setup.py tests/test_install_config.py tests/test_install_lifecycle.py tests/test_global_instructions.py tests/test_runtime.py tests/test_claude_ingress.py tests/test_client_activation.py tests/test_release.py docs/architecture.md docs/operations.md config/source-limits-baseline.json CHANGELOG.md packaging/VERSION plans/README.md`
> Reconcile the current installer with integrated 056 first; never copy its old
> function body from this plan over newer rollback/update safety logic.

## Status and outcome

- Priority P1; effort L across small stages; risk HIGH; category architecture.
- Planned at `6840312`, 2026-09-09. Depends on 056 platform extraction, 061
  packaged-import gates and 062 runtime boundaries. Plan 056 is now integrated
  as a planning document at `96db57f`; its implementation is still pending.
  Its source extraction must land before dependent installer edits.
- First proof: an isolated service-only install/update/uninstall leaves Codex
  configuration and guidance unchanged, while ordinary existing Codex installs
  retain selection and restore their exact owned configuration successfully.
- Separate proof: an explicitly enabled Anthropic subscription can coexist
  with disabled OpenAI subscription without broadening any legacy installation.

## Current state

`packaging/install.py:430-470` always builds/writes a Codex configuration block
and global instructions after health succeeds:

```python
config_path = Path.home() / '.codex' / 'config.toml'
# ... previous receipt, preserve picker, write config and global instructions ...
receipt_path.write_text(json.dumps({'config_path': str(config_path),
                                  'inserted_block': block,
                                  'global_instructions': rules_receipt,
```

`tools/disable.py:9-25` restores one Codex-shaped receipt and checks exact block
ownership. `do_uninstall` uses human text to infer success (`install.py:635`):

```python
if 'OpenAI direct routing restored' not in out:
    raise SystemExit('configuration restore failed; services left running for manual review')
```

`router.py:164-166` passes `openai_mode` to Claude. `claude.py:123-129` rejects
subscription passthrough when that field is `none`. The test at
`tests/test_claude_ingress.py:128-138` deliberately protects that legacy behavior.

Good conventions: exact-owned block restoration and concurrent-edit checks in
`tools/disable.py`; `_preserve_picker_selection` in `install.py:199-221`;
`tools/global_instructions.py` exposes prepare/write/restore functions. Preserve
these safeguards. A different `--home` alone does not isolate native user
services or `Path.home()` client config; tests must use fake OS boundaries and
temporary client paths, never the operator's real profile.

## Scope and boundaries

Only files in the drift check plus this plan/index. New
`packaging/codex_config.py` is a Python 3.9-safe installer helper loaded through
the existing explicit file-import pattern and included in the release bundle.
It owns Codex block generation, selected-model preservation, guidance and
activation receipt handling. No runtime/protocol import from this helper.

Out: a generic configuration framework, editing Claude settings now, Kiro,
renaming `.codex` router homes, migrating user accounts, changing provider
credentials, retiring legacy receipts, deploying plugins, AWS or paid probes.

## Steps

### 1. Characterize client-owned changes and restoration

Add `tests/test_client_activation.py`. Model it on `tests/test_install_config.py`
and `tests/test_global_instructions.py`. Pin pre-existing file preservation,
owner-chosen model/effort, edited or duplicate managed-block rejection, legacy
receipt restore, and failure before any service removal when restore fails.
Capture the current return-code/output relation for `disable.py` in a subprocess
with temporary profile and fake service boundary.

**Verify:** `python3.14 -m unittest tests.test_client_activation tests.test_install_config tests.test_global_instructions tests.test_install_lifecycle`
passes before moving code. Assertions examine files/service outcomes, not
private helper identities.

### 2. Extract the Codex adapter without changing its contract

Move Codex configuration/receipt functions out of the shared installation
transaction into `packaging/codex_config.py`. Keep the initial receipt format,
default client selection and existing CLI entrypoints. Wire install and restore
to the same ownership implementation; leave `tools/disable.py` as a compatible
wrapper with an explicit success/failure exit status. Change the installer's
restore check to the machine result, not an English substring. Preserve the
rule that a failed restore leaves services running.

Do not leave a second unmaintained copy for the tools wrapper. Ensure invoking
the matching remover after rollback still loads the matching receipt reader;
old release support is part of the test, not a reason to call an arbitrary old
script. Include the helper in `release.bundle_files`.

**Verify:** Step 1 tests and `python3.14 -m unittest tests.test_release` pass
against source and extracted bundle. Changing success text alone cannot change
the installer's verdict; a nonzero result must stop service removal.

### 3. Add an explicit service-only client selection

Add an explicit installer option `--client codex|none`, with `codex` as the
fresh-install default for compatibility. Persist the selection with versioned
activation metadata; scheduled updates preserve it when no option is supplied.
Absence in legacy state/receipts means Codex, not service-only. `none` means
install/update the router lifecycle without touching client config/guidance;
it is not the subscription mode and must not affect billing routes.

Do not silently detach an already active Codex configuration when changing to
`none`. Require a successful owned restore as part of that explicit transition,
or refuse if the block was edited. Uninstall of a service-only installation
must succeed without a fabricated Codex receipt. Reject an unimplemented client
name before filesystem/service mutation. Keep current router home paths.

**Verify:** Step 1 tests include service-only install/update/rollback/uninstall,
persisted choice after update, legacy migration and edited-block refusal. The
temporary Codex file/guidance hashes are unchanged for service-only operations.
Run extracted installer `--help` smoke and full lifecycle harness.

### 4. Separate the two subscription choices with legacy-safe defaults

Add optional `anthropic_mode` with the same `subscription|none` validation and
an explicit `--anthropic-mode` option. Responses still uses `openai_mode`.
Messages uses `anthropic_mode` if present, otherwise the legacy `openai_mode`
fallback. Do not populate a more permissive value during automatic migration.
Validate it in `runtime.load_state` and persist only an explicit choice. The
existing setup window remains compatible; do not change its old `openai_mode`
control into implicit permission to enable Anthropic routing.

Test all four explicit mode combinations with fake upstreams and real handler
paths; OpenRouter remains usable in each. Missing Anthropic mode must reproduce
today's legacy tests. Subscription passthrough still requires the client auth
and path-token checks; independent modes do not manufacture subscription auth.

**Verify:** `python3.14 -m unittest tests.test_runtime tests.test_claude_ingress tests.test_handler tests.test_client_activation`
passes. In the new explicit combination OpenAI-disabled/Anthropic-enabled,
the fake OpenAI route is rejected and the authenticated Anthropic route reaches
its own host; no OpenRouter request carries either subscription credential.

### 5. Finish integration and hand off Claude activation

Document exact selection/legacy behavior in `docs/architecture.md` and
`docs/operations.md`. Update 051/053's execution handoff via the index: they
consume the service-only path and implement a separate Claude activation
adapter after verifying the actual client settings surface. Do not mark either
plan complete from this extraction.

**Verify:** all commands exit 0:

```sh
python3.14 -m unittest discover -s tests -t .
python3.14 -m compileall -q codex_router tools tests packaging
python3.14 tools/check_source_limits.py
git diff --check
```

## Done criteria

- [x] Ordinary Codex installs and legacy receipts preserve exact owned settings.
- [x] Service-only lifecycle leaves all client settings/guidance unchanged.
- [x] Selected client survives scheduled updates; unsupported clients fail early.
- [x] Uninstall uses a machine outcome and refuses removal after restore failure.
- [x] Explicit independent subscription choices work; legacy permission is preserved.
- [x] Packaged bootstrap/runtime and full tests pass; source limits pass.
- [x] Current review gate, `develop` integration and worktree cleanup recorded.

## STOP conditions and maintenance

Stop if files outside the temporary profile might be touched during verification,
receipt rollback compatibility cannot be preserved, 056 is still owned and
unintegrated, new defaults widen access, or the same verification fails twice.
Multi-client simultaneous activation is deferred until Claude's real adapter
exists; do not introduce a speculative receipt database now.

Use one owned `codex/` worktree, conventional focused commits under staged
limits, and the current required review skill/models before each commit. Target
`develop` and verify integrated behavior. Live client mutations, subscription
terms acceptance and billing tests remain separate explicit gates.
