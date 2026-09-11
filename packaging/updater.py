"""Scheduled-update orchestration, extracted from install.py (Plan 067).

Runs on Python 3.9+ like the installer. Loaded via the installer's
file-based import pattern, never `import packaging.updater`, so installed
bundles without a `packaging` distribution keep working.

The installer injects its own seams after load: `bind(newer=...,
verify_sha256=..., sync_seams=...)`. Until bound, module-level defaults
provide the same behavior for direct/extracted use.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import importlib.util
# Bootstrap loader (Plan 123 exception): service must be spec-loaded before
# service.load() exists, and this module stays usable when loaded directly.
_spec = importlib.util.spec_from_file_location(
    'packaging.service',
    Path(__file__).resolve().parent / 'service.py')
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)

MAX_VERSION_FAILURES = 3


def _default_newer(a, b):
    return tuple(int(x) for x in a.split('.')) > tuple(int(x) for x in b.split('.'))


def _default_verify(data, want):
    if hashlib.sha256(data).hexdigest() != want:
        raise SystemExit('bundle checksum mismatch')
    return True


def _noop_sync():
    return None


# Installer-owned seams; rebound via bind() after file-based load.
newer = _default_newer
verify_sha256 = _default_verify
sync_seams = _noop_sync


def bind(**overrides):
    for name, value in overrides.items():
        if name not in ('svc', 'newer', 'verify_sha256', 'sync_seams'):
            raise AttributeError(f'unknown updater seam: {name}')
        globals()[name if name != 'svc' else '_svc'] = value


def _park(home, etag, etag_path, version):
    """Count a failed attempt and stop retrying once it is hopeless.

    A version that has failed this often will not start working on its own,
    and every pass costs a service restart. The saved ETag skips even the
    feed re-read, but the production feed is served through the GitHub CLI
    and carries no ETag, so the count in the state file is what actually
    parks it there.
    """
    count = _svc.record_update_failure(home, version)
    if count < MAX_VERSION_FAILURES:
        return
    if etag:
        etag_path.write_text(etag + '\n')
    print(f'parking {version} after {count} failed attempts; '
          f'run the installer by hand to retry')


def do_check_update(args, _fetch=None, _read_feed=None, _sleep=None):
    """Run one scheduled-update pass; behavior matches the pre-split code."""
    sync_seams()
    import random
    home = Path(args.home).expanduser()
    feed = args.feed or _svc.channel_feed(home)
    # The default home-bound fetch sends the stored feed token to the feed
    # origin; bundle fetches below reuse it, so a migrated host never needs
    # gh. An injected fake keeps its one-argument shape all the way down.
    injected = _fetch
    _fetch = injected or (lambda url: _svc.fetch(url, home))
    read_feed = _read_feed or (lambda url, etag: _svc.fetch_feed(url, etag, injected, home=home))
    sleep = _sleep or time.sleep
    sleep(random.uniform(0, 120))
    etag_path = home / 'update-etag'
    etag = etag_path.read_text().strip() if etag_path.exists() else None
    # Transient fetch failures (offline, locked-keychain TLS, DNS blip) retry
    # in-run with bounded backoff. HTTPError is an OSError subclass, so HTTP
    # errors re-raise without retry; deterministic errors (SystemExit from
    # serial/version checks, HTTP status) still fail fast below.
    for attempt in range(4):
        try:
            status, body, etag = read_feed(feed, etag)
            break
        except OSError as exc:
            if isinstance(exc, urllib.error.HTTPError) or attempt == 3:
                raise
            sleep(30 * 2 ** attempt)
            print(f'retrying feed fetch ({exc})')
    if status == 304:
        print(f"up to date {_svc.current_version(home)}")
        return 0
    latest = json.loads(body.decode())
    # check_serial persists the feed token after the serial check but
    # before the version comparison, so a host that is already current
    # still migrates: its next poll resolves CloudFront.
    _svc.check_serial(home, latest, pinned=bool(args.feed))
    if not _svc.trusted_origin(latest.get('url', '')):
        raise SystemExit('feed points off the trusted update origin; refusing')
    if not newer(latest['version'], _svc.current_version(home)):
        if etag:
            etag_path.write_text(etag + '\n')
        print(f"up to date {_svc.current_version(home)}")
        return 0
    failed = _svc.update_failures(home).get(latest['version'], 0)
    if failed >= MAX_VERSION_FAILURES:
        if etag:
            etag_path.write_text(etag + '\n')
        print(f"skipping {latest['version']}: {failed} failed attempts; "
              f"run the installer by hand to retry")
        return 0
    state = json.loads((home / 'mixed-router-state.json').read_text())
    tarball = _fetch(latest['url'])
    if latest.get('sha256'):
        verify_sha256(tarball, latest['sha256'])
    with tempfile.TemporaryDirectory() as tmp:
        _svc.safe_extract(tarball, tmp)
        installer = Path(tmp) / 'packaging' / 'install.py'
        if not installer.exists():
            raise SystemExit('downloaded bundle has no installer')
        # Only forward an explicitly pinned feed; a channel-resolved feed must
        # not pin home/'feed', or beta would freeze on one release asset URL.
        cmd = [sys.executable, str(installer), '--home', str(home)]
        if args.feed:
            cmd += ['--feed', feed]
        try:
            result = _svc.run(cmd, capture_output=True, text=True, timeout=900)
        except subprocess.SubprocessError as exc:
            # A child that is killed or never starts reports nothing itself,
            # so count it here or a hanging release retries every 15 minutes
            # forever. TimeoutExpired is a SubprocessError, not an OSError.
            _park(home, etag, etag_path, latest['version'])
            print(f'installer did not complete: {type(exc).__name__}')
            raise SystemExit(1)
        print(result.stdout[-2000:] if result.stdout else '')
        if result.returncode != 0:
            print(result.stderr[-2000:] if result.stderr else '')
            # A child can fail after the swap and a healthy restart (a refused
            # Codex settings merge). That release keeps serving, so record the
            # pass, show the notice, and still report the failure; a pointer
            # without a serving router is a release to retry and park.
            landed = (_svc.current_version(home) == latest['version']
                      and _svc.wait_version(state, latest['version']))
            if not landed:
                _park(home, etag, etag_path, latest['version'])
                raise SystemExit(result.returncode)
            _svc.notice.show_pending(home)
            failure = result.returncode
        else:
            failure = 0
    if _svc.current_version(home) != latest['version']:
        print('deferred: installer did not activate the requested version')
        return failure
    _svc.clear_update_failures(home, latest['version'])
    (home / 'logs').mkdir(exist_ok=True)
    with open(home / 'logs' / 'update.log', 'a') as stream:
        stream.write(json.dumps({'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                                 'version': latest['version'],
                                 'source': _svc.feed_source(feed)}) + '\n')
    if etag:
        etag_path.write_text(etag + '\n')
    if failure:
        print(f'installed {latest["version"]}; the installer exited {failure} after the swap')
        return failure
    print(f"installed {latest['version']}")
    return 0
