# Plan 161: Update chain: mandatory bundle checksum and origin-pinned fetches

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report; do not improvise.
> When done, update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat c068368..HEAD -- packaging/updater.py packaging/install.py packaging/service.py packaging/feed.py ai_router/key_store.py ai_router/setup.py tests/install_fixtures.py tests/test_feed_migration.py tests/test_install.py tests/test_install_config.py tests/test_install_lifecycle.py tests/test_update_channel.py tests/test_setup.py docs/operations.md config/source-limits-baseline.json`
> If any in-scope file changed, compare the "Current state" excerpts against
> the live code before proceeding; on a mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (independent of 162-167)
- **Category**: security
- **Planned at**: commit `c068368` (`origin/develop`), 2026-09-13
- **Source**: `plans/2026-09-13-router-four-lane-audit.md`, finding F1

## Why this matters

The self-update chain is the one path that executes code on every staff
machine, and its only authenticity control is a SHA-256 in the feed document
(the Ed25519 signature path is not wired; see F14 in the audit). Today that
control is applied only `if latest.get('sha256')`: a feed document that omits
the field installs and runs an unverified tarball, and the bundle's
`MANIFEST.json` is read out of the unverified archive. Separately, every feed
and bundle fetch goes through `urllib.request.urlopen`, which follows HTTP
redirects to any host, so the "trusted origin" check protects only the first
URL; and the key-info check sends the operator's provider key in an
`Authorization` header through the same redirect-following opener, so a 3xx
from the key endpoint would forward the key to whatever host the redirect
names. None of this widens the trust root (the feed origin already is the
root), but each is a fail-open shape on a critical path, and each is a few
lines to close. The bootstrap scripts already verify unconditionally
(`packaging/bootstrap.sh:49`, `packaging/bootstrap.ps1`), and
`tools/publish_feed.py:47-49` refuses to publish a document without `sha256`,
so a conforming feed never exercises the new refusal.

## Current state (verified at c068368)

- `packaging/updater.py:303-308`, inside `_apply_update`:

```python
    tarball = _fetch(bundle_url)
    if latest.get('sha256'):
        try:
            verify_sha256(tarball, latest['sha256'])
        except SystemExit as exc:
            raise UpdateError('bundle_checksum', str(exc) or 'bundle checksum mismatch')
```

- `packaging/install.py:321-327`, inside `do_install`:

```python
    tarball = _svc.feed_read(_fetch, _svc.sibling_bundle(feed, latest['url']))
    if latest.get('sha256'):
        verify_sha256(tarball, latest['sha256'])
    manifest_doc = {'files': {}}
    with tarfile.open(fileobj=io.BytesIO(tarball), mode='r') as tar:
        try:
            manifest_doc = json.loads(tar.extractfile('MANIFEST.json').read())
```

- `packaging/service.py:96-107` (`fetch`) checks `_feed.trusted_origin(url)`
  and then calls `urllib.request.urlopen(url, timeout=30)`; its docstring
  claims "a compromised feed cannot redirect a host elsewhere".
- `packaging/feed.py:67-72` (`_get`) does the same for the feed document
  with an `If-None-Match` header. `packaging/feed.py:29-33` (`trusted_origin`)
  returns True for any `file://` URL and for `FEED_ORIGIN + '/'` prefixes.
- `ai_router/key_store.py:29-50` (`check_key`) builds
  `urllib.request.Request(defn.key_info_url, headers={'Authorization': 'Bearer ' + key})`
  and opens it with the injectable `_urlopen`, whose default is
  `urllib.request.urlopen`. It maps `urllib.error.HTTPError` to
  `KeyRejected(status=exc.code)`.
- CPython's `urllib.request.HTTPRedirectHandler.redirect_request` copies every
  request header except `Content-Length` and `Content-Type` onto the
  redirected request, regardless of host. `packaging/updater.py:121-122`
  already shows the repo's pattern for a custom opener:
  `urllib.request.build_opener(urllib.request.ProxyHandler({})).open`.
- The updater's error codes are a closed set (`packaging/updater.py:43-47`):
  `feed_invalid` and `bundle_checksum` already exist; do not add a code.
- Repo conventions: stdlib only; `packaging/` must stay Python 3.9
  compatible (no `match`, no `X | Y` unions); tests never open a network
  connection (`tests/test_feed_migration.py:20-35` shows the `_Response`
  stand-in and `:92` the `mock.patch.object(svc.urllib.request, 'urlopen', ...)`
  pattern); error text never names a URL query string
  (`packaging/feed.py:24-26`).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_feed_migration tests.test_install tests.test_install_lifecycle tests.test_update_channel tests.test_feed_serial tests.test_setup tests.test_fetch_hardening` | all pass |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0, 1331 or more tests |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Lint | `python3.14 -m ruff check --select F401,F811 ai_router packaging tools tests` | `All checks passed!` |
| Limits | `python3.14 tools/check_source_limits.py` | `failures=0` (re-sync the `packaging/updater.py` and `packaging/install.py` baseline counts if they change) |
| Policy scans | `python3.14 tools/check_policy_scans.py` | `policy-scans: pass` |
| 3.9 grammar | `python3.14 -B -m unittest tests.test_packaging` | passes (it parses `packaging/` with `feature_version=(3, 9)`) |

## Scope

**In scope** (the only files you should modify):
- `packaging/updater.py`, `packaging/install.py`, `packaging/service.py`,
  `packaging/feed.py`, `ai_router/key_store.py`, `ai_router/setup.py` (Step 4: one line plus two orphaned imports)
- `tests/test_fetch_hardening.py` (create), small additions to
  `tests/test_feed_migration.py`, `tests/test_install.py`, `tests/test_setup.py`
- fixture digests only (Step 1): `tests/install_fixtures.py`,
  `tests/test_install_config.py`, `tests/test_install_lifecycle.py`
- `docs/operations.md` (one sentence), `CHANGELOG.md`, `packaging/VERSION`,
  `pyproject.toml` (version), `config/source-limits-baseline.json`

**Out of scope** (do not touch):
- `packaging/feed_verify.py` and the signature path: F14 is an owner
  decision, not part of this plan.
- `packaging/bootstrap.sh`, `packaging/bootstrap.ps1`: already verify
  unconditionally.
- `tools/publish_feed.py`, `infra/`: plan 167 owns the publisher and bucket.
- The `fetch_feed(url, etag, _fetch)` test seam in `packaging/service.py`:
  keep its shape; tests depend on it.
- Any change to the feed document format or to serial handling.

## Git workflow

- Worktree based on `develop`, one writer; branch name like
  `<you>/161-update-chain-fetch-hardening-20260913`.
- Commit subjects: `fix: require the bundle checksum and pin fetch redirects`.
  Run the shared `pre-commit-review` skill before committing. Do not push or
  open a PR unless the operator instructed it.

## Steps

### Step 1: Require the checksum in the scheduled updater

In `packaging/updater.py`, add a module helper that validates the field
shape and replace the conditional at `:304-308`:

```python
_SHA256_SHAPE = re.compile(r'^[0-9a-f]{64}$')  # `re` is already imported


def _required_sha256(latest):
    """The feed document's bundle checksum, or an UpdateError when unusable."""
    value = latest.get('sha256')
    if not isinstance(value, str) or not _SHA256_SHAPE.fullmatch(value.strip().lower()):
        raise UpdateError('feed_invalid', 'feed document has no usable bundle checksum')
    return value.strip().lower()
```

then, in `_apply_update`, fetch the tarball and verify unconditionally:

```python
    want = _required_sha256(latest)
    tarball = _fetch(bundle_url)
    try:
        verify_sha256(tarball, want)
    except SystemExit as exc:
        raise UpdateError('bundle_checksum', str(exc) or 'bundle checksum mismatch')
```

Resolve `want` before the fetch so a malformed document is refused without a
download. Keep `verify_sha256` as the injected seam it is today.

**Verify**: `python3.14 -B -m unittest tests.test_install tests.test_install_lifecycle tests.test_install_config tests.test_update_channel tests.test_feed_migration` → pass. Several fixtures build feed documents with `'sha256': None`: the shared `craft_bundle` at `tests/install_fixtures.py:93` (consumed by `tests/test_update_channel.py`, `tests/test_install_config.py`, `tests/test_systemd.py`, `tests/test_client_activation.py` and `tests/test_install_key_window.py`) and the inline documents at `tests/test_feed_migration.py:108`, `tests/test_install.py:171` and `:396`, `tests/test_install_config.py:391` and `tests/test_install_lifecycle.py:349`. Give each a real digest of the bundle bytes it serves (`hashlib.sha256(blob).hexdigest()`; `install_fixtures.py` already imports `hashlib` and computes one at `:40`) so they keep testing what they test today. Do not turn them into refusal tests: the refusal is tested once, in Step 5. `tests/test_operator_surface.py:266` and `:331` drive the read-only `do_check_update`, which this plan does not change; leave them.

### Step 2: Require the checksum in the installer

In `packaging/install.py:321-327`, mirror Step 1 with the installer's own
failure style (`SystemExit`, no error code):

```python
    want = latest.get('sha256')
    if not isinstance(want, str) or not re.fullmatch(r'[0-9a-f]{64}', want.strip().lower()):
        raise SystemExit('feed document has no usable bundle checksum; refusing to install')
    tarball = _svc.feed_read(_fetch, _svc.sibling_bundle(feed, latest['url']))
    verify_sha256(tarball, want.strip().lower())
```

Add `import re` to the installer's imports. The `MANIFEST.json` read that
follows now only ever runs on a verified archive; leave it as it is.

**Verify**: `python3.14 -B -m unittest tests.test_install` → pass.

### Step 3: One redirect-pinning opener for feed and bundle fetches

In `packaging/feed.py`, add a redirect handler that re-runs the origin check
on the redirect target, and an opener built from it:

```python
class _PinnedRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only when it stays on a trusted origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not trusted_origin(newurl) or newurl.startswith('file://'):
            raise SystemExit('feed redirected off the trusted update origin; refusing')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def opener():
    """The one opener every unattended feed or bundle fetch goes through."""
    return urllib.request.build_opener(_PinnedRedirects())
```

Refusing a `file://` target closes the "redirect to a local path" corner
`trusted_origin` otherwise allows. Use `opener().open(...)` instead of
`urllib.request.urlopen(...)` in `packaging/feed.py:69` (`_get`) and in
`packaging/service.py:106` (`fetch`); `service.py` already holds `_feed`
(`packaging/service.py:52`), so call
`_feed.opener().open(urllib.request.Request(url), timeout=30)` (a `Request`
in both call sites, so one fake shape serves both tests below).
Keep both `file://` branches exactly as they are.

The handler raises `SystemExit`, as `service.fetch` already does for an
untrusted URL, and `do_update` (`packaging/updater.py:376-399`) classifies
only `UpdateError`, `OSError`, `ValueError` and `Exception`, so a bare
`SystemExit` would skip `_record_pass` and leave no `last_error` for the
doctor. In `_apply_update`, wrap the feed read at `packaging/updater.py:267`
and the bundle fetch at `:303` with `except SystemExit as exc: raise
UpdateError('feed_untrusted', str(exc) or 'feed redirected off the trusted
update origin')`, mirroring the existing pattern at `:276-279`. The code
`feed_untrusted` already exists in the closed set at `:43-47`; add none.

**Verify**: `python3.14 -B -m unittest tests.test_feed_migration` → pass. Two
tests there patch `svc.urllib.request.urlopen` and would otherwise reach the
network once the fetches go through the opener:
`test_conditional_get_sends_no_credential_and_handles_304`
(`tests/test_feed_migration.py:86-94`) and
`test_scheduled_poll_reads_feed_and_bundle_without_headers` (`:96-133`, the
real-wiring test whose fixture also takes the Step 1 digest). Change both
patch targets to `svc._feed.opener`, returning an object whose
`.open(req, timeout=None)` is the existing fake, and keep every assertion
(the `If-None-Match` header, the exact URLs seen, no credential header).

### Step 4: Never follow a redirect with the provider key

In `ai_router/key_store.py`, give `check_key` a default opener that refuses
every redirect, keeping the `_urlopen` seam for tests:

```python
class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # urllib raises HTTPError(code) instead of following


def _open_without_redirects(req, timeout):
    return urllib.request.build_opener(_NoRedirects()).open(req, timeout=timeout)


def check_key(provider_id, key, _urlopen=_open_without_redirects):
```

and, in the `except urllib.error.HTTPError as exc:` branch, treat a 3xx as
unreachable rather than as a rejected key:

```python
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            raise OSError('key check was redirected; refusing to follow')
        raise KeyRejected(label + ' rejected the key', status=exc.code)
```

The production setup path does not use that default: `ai_router/setup.py:86`
binds `_fetch = _urlopen or urllib.request.urlopen` and passes it positionally
at `:105` (`check_key(provider_id, key, _fetch)`) and `:114`
(`_stored_key_live(provider_id, stored, _fetch)`). Change `:86` to
`_fetch = _urlopen or key_store._open_without_redirects` (same call shape:
`check_key` invokes `_urlopen(req, timeout=20)`), so the freshly pasted key
and the stored key both go through the no-redirect opener; the `_urlopen`
test seam is unchanged. That line was the file's only use of `urllib`, so
also delete the now-orphaned `import urllib.error` and `import urllib.request`
at `ai_router/setup.py:16-17` or the plan's ruff gate fails with F401 (no
test patches `setup.urllib`; every `tests/test_setup.py` case injects
`_urlopen`). `ai_router/setup.py:104-109` already maps `OSError`
from `check_key` to "could not reach <label>; retry shortly" (HTTP 502),
which is the right message. Both files stay Python 3.14 only, so no 3.9
constraint applies here.

**Verify**: `python3.14 -B -m unittest tests.test_setup` → pass.

### Step 5: Tests

Create `tests/test_fetch_hardening.py` (model the fixtures on
`tests/test_feed_migration.py`; `install_fixtures.install_mod` exposes the
loaded installer and `svc = install_mod._svc` the service module):

- `test_updater_refuses_a_feed_without_a_checksum`: call
  `install_mod._updater._required_sha256({'version': '9.9.9', 'url': '...'})`
  and assert it raises `UpdateError` with `error_code == 'feed_invalid'`;
  repeat with `{'sha256': 'not-hex'}` and with an uppercase but otherwise
  valid digest (accepted, lowercased).
- `test_installer_refuses_a_feed_without_a_checksum`: drive `do_install`
  with a fake `_fetch` returning a document without `sha256` and a bundle;
  assert `SystemExit` whose text names the missing checksum and that the
  fake `safe_extract` seam was never called (see how
  `tests/test_install.py` patches `install_mod` attributes through
  `_patch_attrs`).
- `test_feed_redirect_off_origin_is_refused`: instantiate
  `svc._feed._PinnedRedirects()` and call
  `redirect_request(req, None, 302, 'Found', {}, 'https://evil.example/x')`
  with `req = urllib.request.Request(ORIGIN + '/stable/latest.json')`;
  assert `SystemExit`. Then with `newurl = ORIGIN + '/stable/other.json'`
  assert a `Request` is returned whose `full_url` is that URL. Then with
  `newurl = 'file:///tmp/x'` assert `SystemExit`.
- `test_key_check_never_follows_a_redirect`: `check_key` with a fake
  `_urlopen` that raises `urllib.error.HTTPError(url, 302, 'Found', {}, None)`
  must raise `OSError`, not `KeyRejected`; assert the default opener's
  handler chain contains `key_store._NoRedirects` and that
  `_NoRedirects().redirect_request(...)` returns `None` for any target.
  Then call `setup._submit(state, home, b'key=abc', None)` with
  `key_store._open_without_redirects` patched to a recorder that raises
  `urllib.error.HTTPError(url, 302, 'Found', {}, None)` and
  `urllib.request.urlopen` patched to fail the test if called: the result
  is the 502 "could not reach" answer and the recorder was called once.
- `test_feed_and_bundle_fetches_go_through_the_pinned_opener`: patch
  `svc._feed.opener` with a recorder returning an object whose `.open`
  returns a `_Response`; call `svc.fetch(ORIGIN + '/bundles/x.tar.gz')` and
  `svc._feed._get(ORIGIN + '/stable/latest.json', {}, None)` and assert the
  recorder was called once each; separately assert
  `any(isinstance(h, svc._feed._PinnedRedirects) for h in svc._feed.opener().handlers)`.

Model the test module docstring and the "never opens a network connection"
statement on `tests/test_ingress_guards.py:1-7`.

**Verify**: focused command from the table → all pass, including the new
file; then the full suite.

### Step 6: Docs and release rule

- `docs/operations.md`: in the "Update feed: public and automatic" section,
  after the sentence that begins "Security rests on HTTPS from the trusted
  feed origin only", add: "Feeds and bundles never follow a redirect off that
  origin, and a feed document without a bundle checksum is refused."
- `CHANGELOG.md`: add an entry under the next unreleased version heading
  describing the refusal and the redirect pinning in one or two lines.
- `packaging/VERSION` and the `version` field in `pyproject.toml`: bump the
  patch together (they read `0.6.42` at the planning commit) unless another
  change on your branch already bumped them.
- `config/source-limits-baseline.json`: re-sync the `packaging/updater.py`
  and `packaging/install.py` counts if `check_source_limits.py` reports them.

**Verify**: `python3.14 tools/check_source_limits.py` → `failures=0`;
`python3.14 tools/check_policy_scans.py` → pass.

## Test plan

- New: `tests/test_fetch_hardening.py` with the five cases in Step 5.
- Existing: the whole installer and feed suites keep passing unchanged
  except the one patch-target adjustment named in Step 3.
- Verification: `python3.14 -m unittest discover -s tests -t .` → exit 0
  with at least 1336 tests.

## Done criteria

- [ ] `grep -n "if latest.get('sha256')" packaging/updater.py packaging/install.py` returns no matches.
- [ ] `grep -n "urllib.request.urlopen" packaging/feed.py` returns no matches, and `grep -n "urllib.request.urlopen(url, timeout=30)" packaging/service.py` returns no matches (`fetch` and `_get` go through `feed.opener()`; the loopback `health` call and the `fetch_feed` seam are untouched).
- [ ] `grep -n "_urlopen=urllib.request.urlopen" ai_router/key_store.py` and `grep -n "urllib.request.urlopen" ai_router/setup.py` both return no matches.
- [ ] Full suite, compile, lint, limits and policy scans all pass.
- [ ] `git status` shows only in-scope files changed.
- [ ] `plans/README.md` status row for 161 updated.

## STOP conditions

- A `tests/test_*` module drives `fetch_feed` or `do_update` with an
  injected `_fetch` and an `https://` feed URL and starts failing: that seam
  is out of scope; report which test and stop.
- `docs/operations.md` or `docs/compatibility.md` records that the feed
  origin serves any redirect (for example a trailing-slash normalisation):
  refusing off-origin redirects would still be right, but report it before
  merging.
- `tests/test_packaging.py`'s Python 3.9 grammar gate fails on your edits.
- Any step's verification fails twice after a reasonable fix.

## Maintenance notes

- Every future unattended fetch in `packaging/` must go through
  `feed.opener()`; a reviewer should reject a bare `urlopen` there.
- Any future credentialed request from the router (a second provider's key
  check, for example) must reuse `key_store._open_without_redirects`.
- If the owner later wires the Ed25519 signature (F14), the checksum check
  stays: the signature authenticates the document, the checksum binds the
  bundle bytes to it.
