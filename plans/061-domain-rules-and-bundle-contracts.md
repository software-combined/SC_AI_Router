# Plan 061: Define domain ownership and protect packaged imports

> Planning only. Execute only after implementation is authorised. Every stage
> must leave the existing commands runnable. Update `plans/README.md` with the
> actual gate reached.
>
> Drift check: `git diff --stat 6840312..HEAD -- AGENTS.md docs/architecture.md README.md packaging/release.py packaging/install.py tests/test_release.py tests/test_domain_boundaries.py tools/check_source_limits.py config/domain-boundaries.json config/source-limits-baseline.json .github/workflows/check.yml CHANGELOG.md packaging/VERSION plans/README.md`
> Refresh changed excerpts; coordinate with the owner of draft Plans 056-059.

## Status and outcome

- Priority P1; effort M; risk LOW-MED; category architecture/tests/tooling.
- Planned at `6840312`, 2026-09-09. No implementation dependency; 060 should
  land first where possible. Does not require Windows implementation.
- First proof: tests run the actual extracted release's runtime and installer
  import paths without seeing the checkout, and fail when a required helper or
  resource is deliberately omitted. Domain rules explain where new work goes.

## Current state

`packaging/release.py:20-28` uses different inclusion rules:

```python
sorted(p.relative_to(root).as_posix() for p in (root / 'codex_router').rglob('*.py'))
# ... only top-level .txt/.json; fixed installer helper paths ...
```

`tests/test_release.py:64-85` checks a short resource list then runs:

```python
'from codex_router.registry import MODELS; print(len(MODELS))'
```

`packaging/install.py:132-139` smoke-imports catalogue and registry, not the
HTTP handler or installer backends. A reorganised bundle can therefore pass a
narrow import check while missing another required module or nested resource.
Existing deterministic archive/hash tests are good and must remain unchanged.

`tools/check_source_limits.py:15-25` recursively checks Python file sizes. It
does not constrain dependencies. The model registry is already a useful leaf
(`registry.py:6-8` imports only stdlib), but provider, client, protocol and
installer boundaries are not documented as enforceable rules.

Installer scripts deliberately remain Python 3.9-compatible while the runtime
requires 3.14. File-based imports avoid depending on an installed third-party
package named `packaging`; retain a tested bootstrap path.

## Scope

Only: `AGENTS.md`, new `docs/architecture.md`, `README.md`,
`packaging/{release,install}.py`, `tests/test_release.py`, new
`tests/test_domain_boundaries.py`, optionally `config/domain-boundaries.json`
if a table in the test is insufficient, `tools/check_source_limits.py` only if
needed to preserve existing limits, size baseline, `.github/workflows/check.yml`,
changelog/version, this plan/index.

Out: moving runtime modules, changing routes, changing credentials, state/home
renames, dynamic plugin loading, HTTP framework replacement, releasing, and
implementing OS backends. Existing 056 owns platform extraction/CI matrix;
coordinate edits to the shared workflow and bundler rather than duplicate them.

## Ownership rules to document

1. HTTP transport owns loopback auth, body limits, drain/inflight and connection
   cleanup. Protocol handlers own Responses/Messages representation. Upstream
   adapters own target/credential construction; OpenRouter headers start fresh.
2. Canonical model data and normalization are leaves. Client listing/config
   modules may consume them; the registry must not import a CLI or client.
3. Installer orchestration calls one explicit platform backend. Unsupported OS
   is an explicit refusal. Backends do not import runtime providers or client
   catalogue policy. Client activation is separately owned and reversible.
4. A client is not a provider and an OS is neither. New clients reuse a proven
   wire protocol; a new protocol is added only after its contract is verified.
5. Keep `codex_router`, current commands, service labels, state paths and
   compatibility imports stable. Do not split folders merely to lower counts.
6. Preserve Python 3.9 bootstrap isolation, stdlib-only runtime, secret safety,
   clear error codes, exact-owned config restore, meaningful tests and existing
   source/commit limits. Backend namespace must not shadow stdlib `platform`.
7. Source, packaged imports, native lifecycle, real-client tools, billing and
   release acceptance are different gates. Record client and OS evidence by
   version; a global model tier does not assert every combination works.

## Steps and verification

### 1. Write the architecture map and a small boundary check

Reconcile the new AGENTS section 9 in this documentation change. Codex and
OpenCode expose client source; the public Claude Code repository supplies
docs, releases, issues and examples, not an equivalent complete open-source
client implementation. Use official docs and the installed version where
internals are absent. Preserve upstream links and version-pinning rules.
Evidence checked 2026-09-09: [Codex](https://github.com/openai/codex),
[OpenCode](https://github.com/anomalyco/opencode),
[Claude Code](https://github.com/anthropics/claude-code).

Create `docs/architecture.md` with current-to-target responsibilities, allowed
dependency direction and examples from `registry.py`, `Prepared` in
`providers.py`, and `systemd.Manager`. Add a short AGENTS rule pointing to it.
Mark existing mixed modules as transitional owners assigned to 056/062/063/064.

Use stdlib `ast` in `tests/test_domain_boundaries.py` for a few high-value rules:
registry/normalization cannot import client CLI/installer/HTTP orchestration;
runtime inference modules cannot import `packaging` or setup plugins; extracted
protocol/transport leaves cannot import the HTTP handler. Handle relative
imports. Do not build a generic graph framework or prohibit valid local imports.
Test the detector against a tiny synthetic forbidden import so its check is
not vacuous before future extraction creates those folders.

**Verify:** `python3.14 -m unittest tests.test_domain_boundaries` passes and the
synthetic violating fixture is rejected. `git diff --check` exits 0.

### 2. Prove release closure from the extracted artifact

Extend `tests/test_release.py` to extract the real deterministic bundle into a
temporary directory and launch subprocesses with the checkout absent from
`PYTHONPATH`/working-directory search. Import router, provider/protocol, setup,
registry, catalogue and required runtime resources. Run the extracted installer
with `--help`; this imports its helpers but cannot install, fetch or touch a
user profile. Assert imports originate under the extraction root.

Cover nested package resources and the installer helper namespace as they are
introduced. Preserve a narrow explicit resource allowlist, not `rglob('*')`
which could ship state, logs or credentials. A missing helper/resource must make
the extracted smoke fail. Keep runtime .py recursion and deterministic hashes.

If changing `self_test`, retain the lightweight offline smoke role; do not run
repo tests against staff profiles. Avoid growth in the 699-line installer:
replace its existing short smoke expression or wait for 067 to make room.

**Verify:** `python3.14 -m unittest tests.test_release tests.test_install` passes.
The test's deliberately incomplete extracted fixture fails its smoke with a
specific missing dependency, while the complete fixture passes.

### 3. Wire the rules to CI and preserve bootstrap compatibility

The new unittest files run through existing discovery. Add packaging to the
compile target. Coordinate with 056's OS matrix so these gates run on each
available runner; Windows skips must remain visible until 057 removes them.
Add a narrowly scoped Python 3.9 installer `--help` smoke for the extracted
artifact, or run it in the existing bootstrap verification job if one has
landed. It must not import Python 3.14-only runtime modules. Keep the Python
3.14 full suite as the runtime gate.

**Verify:** `python3.14 -m unittest discover -s tests -t .`,
`python3.14 -m compileall -q codex_router tools tests packaging`,
`python3.14 tools/check_source_limits.py`, and `git diff --check` pass. CI's
Python 3.9 extracted installer `--help` returns 0. Do not call local source
checks proof that all OS runners have passed.

## Done criteria

- [ ] Architecture map gives every listed domain one owner and test gate.
- [ ] Boundary tests reject a synthetic reversed dependency.
- [ ] Complete extracted runtime and installer smoke pass without checkout imports.
- [ ] Missing nested resource/helper fails the smoke; deterministic/hash tests pass.
- [ ] Installer bootstrap retains its documented minimum interpreter contract.
- [ ] No broad resource glob can include generated state or secrets.
- [ ] Required review, commit, `develop` integration and cleanup are recorded.

## STOP conditions and maintenance

Stop for a missing live-source dependency, disputed ownership with 056, an
out-of-scope runtime change, or repeat failure after two reasonable attempts.
Do not create a second installer package manager to solve an import issue.
Add each future package's runtime resources and import path to the extracted
artifact test in the same commit as its first caller.

Git: reuse one owned `codex/` worktree based on `develop`; conventional
`test:`/`docs:`/`refactor:` commits within staged limits; read current review
skill and model table before every commit. Target `develop`, preserve concurrent
changes, verify integration, then clean up. No release or deploy is authorised.
