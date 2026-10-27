"""Scheduled-update orchestration, extracted from install.py (Plan 067).

Runs on Python 3.9+ like the installer and is loaded through the installer's
file-based import pattern, never `import packaging.updater`. The installer
injects its own seams after load (`bind(newer=..., verify_sha256=...,
sync_seams=...)`); until bound, the module defaults behave the same.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
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
_models = _svc.load('router_control_models', Path(__file__).with_name('control_models.py'))
_resources = _svc.load('router_native_resources', Path(__file__).with_name('native_resources.py'))
_status = _svc.load('router_update_status', Path(__file__).with_name('update_status.py'))
_reconcile = _svc.load('router_update_reconcile', Path(__file__).with_name('update_reconcile.py'))

MAX_VERSION_FAILURES = 3
ANNOUNCE_TIMEOUT_S = 5
REPLY_LIMIT = 1 << 20

_SHA256_SHAPE = re.compile(r'^[0-9a-f]{64}$')


def _required_sha256(latest):
    """The feed document's bundle checksum, or an UpdateError when unusable."""
    value = latest.get('sha256')
    if not isinstance(value, str) or not _SHA256_SHAPE.fullmatch(value.strip().lower()):
        raise UpdateError('feed_invalid', 'feed document has no usable bundle checksum')
    return value.strip().lower()

# Closed set of `last_error` codes (Plan 147): the doctor and the support
# bundle read only these names; the updater's free text never travels.
ERROR_CODES = _status.ERROR_CODES
_KEEP = object()


class UpdateError(SystemExit):
    """A failed pass carrying the code the state document records."""

    def __init__(self, code, message):
        super().__init__(message)
        # `SystemExit.code` already carries the message; keep the closed-set
        # code beside it so the exit text stays intact for the timer log.
        self.error_code = code


def _record_pass(home, error=_KEEP, applied=None, latest=None, feed=None, etag=None, channel=None):
    """Record one update pass in the shared state document, ageing logs too.

    `error` is a code from ERROR_CODES, or '' to clear the previous one;
    omitted leaves the stored value alone. The read-modify-write goes through
    the single state writer (Plan 131): counter and pass record stay together.
    """
    _svc.prune_logs(home / 'logs')
    try:
        state = _svc._state.read(_svc._state.path(home))
    except (AttributeError, OSError, ValueError):
        return
    if not isinstance(state, dict):
        return
    if latest is not None:
        _status.verified(state, latest, feed, channel or _status.channel(home), etag)
    _status.record(state, error=None if error is _KEEP else error,
                   applied=applied, repaired=bool(applied and error == ''))
    try:
        _svc._write_state(home, state)
    except OSError:
        return


def _default_newer(a, b):
    return tuple(int(x) for x in a.split('.')) > tuple(int(x) for x in b.split('.'))


def _default_verify(data, want):
    if hashlib.sha256(data).hexdigest() != want:
        raise SystemExit('bundle checksum mismatch')
    return True


def _noop_sync():
    return None


def _pending_reply(state, _urlopen=None):
    """The running router's pending-model reply, or {}."""
    port, token = state.get('port'), state.get('token')
    if not isinstance(port, int) or not 0 < port < 65536:
        return {}
    if not isinstance(token, str) or not token:
        return {}
    # No proxy handling: the path token stays on the loopback, never on the
    # wire to whatever http_proxy names. The reply is capped before parsing.
    opener = _urlopen or urllib.request.build_opener(
        urllib.request.ProxyHandler({})).open
    url = 'http://127.0.0.1:%d/%s/model-prompt' % (port, token)
    with opener(url, timeout=ANNOUNCE_TIMEOUT_S) as response:
        return json.loads(response.read(REPLY_LIMIT).decode())


def _codex_attached(state):
    """True when this install serves Codex, so the offer is not a dead end.

    `--clients` records the attachments; legacy state carries only `client`
    (absence means Codex). Claude-only and service-only installs are skipped.
    """
    clients = state.get('clients')
    if clients is not None:
        return clients in ('codex', 'both')
    return state.get('client', 'codex') != 'none'


def _announce_new_models(home, state, _urlopen=None):
    """Show one native dialog when the router reports new models."""
    try:
        if os.environ.get('ROUTER_NO_NOTICE') == '1':
            return
        if not _codex_attached(state):
            return
        reply = _pending_reply(state, _urlopen)
        rows = reply.get('pending') or []
        if not rows:
            return
        names = _svc.notice.dialog_names(rows)
        version = _svc.current_version(home)
        _svc.notice.record(home, version, version, state.get('clients'),
                           names=names)
        _svc.notice.show_pending(home, names=names)
    except Exception:
        pass  # a dialog or loopback failure must not disturb the update


def _offer_notices(home):
    """Independent best-effort offers after the final update result is recorded."""
    for name in ('codex_switch_offer', 'update_warning'):
        try:
            _svc.load('router_' + name, Path(__file__).with_name(name + '.py')).offer(home)
        except (Exception, SystemExit):
            pass


# Installer-owned seams; rebound via bind() after file-based load.
newer = _default_newer
verify_sha256 = _default_verify
sync_seams = _noop_sync


def bind(**overrides):
    for name, value in overrides.items():
        if name not in ('svc', 'newer', 'verify_sha256', 'sync_seams'):
            raise AttributeError(f'unknown updater seam: {name}')
        globals()[name if name != 'svc' else '_svc'] = value


def _read_failures(home):
    """State document plus its failure map; (None, {}) when unreadable.

    Update-failure owner (Plan 131), moved out of service.py. Always read
    fresh: the child installer writes the same file, and merging onto a
    stale copy would drop its changes.
    """
    state = _svc._state.read(_svc._state.path(home))
    if state is None:
        return None, {}
    failures = state.get('update_failures')
    return state, dict(failures) if isinstance(failures, dict) else {}


def update_failures(home):
    """Failed attempts per version; {} when none are recorded."""
    return _read_failures(home)[1]


def record_update_failure(home, version):
    """Count a failed attempt at one version; returns the new count."""
    state, failures = _read_failures(home)
    if state is None:
        return 0
    verified = state.get('latest_verified', {})
    contexts = state.setdefault('update_failure_context', {})
    if isinstance(verified, dict) and verified.get('version') == version and isinstance(contexts, dict):
        context = {key: verified.get(key) for key in ('channel', 'source')}
        if version in contexts and contexts[version] != context:
            failures.pop(version, None)
        contexts[version] = context
    failures[version] = failures.get(version, 0) + 1
    state['update_failures'] = failures
    _svc._write_state(home, state)
    return failures[version]


def clear_update_failures(home, version):
    state, failures = _read_failures(home)
    if state is None or version not in failures:
        return
    del failures[version]
    state['update_failures'] = failures
    _svc._write_state(home, state)


def _park(home, etag, etag_path, version):
    """Count a failed attempt and stop retrying once it is hopeless.

    A version that has failed this often will not start working on its own,
    and every pass costs a service restart. The saved ETag skips the feed
    re-read on a 304; the state count is the hard stop.
    """
    count = record_update_failure(home, version)
    if count < MAX_VERSION_FAILURES:
        return
    if etag:
        etag_path.write_text(etag + '\n')
    print(f'parking {version} after {count} failed attempts; '
          f'run the installer by hand to retry')


def _read_feed_pass(feed, etag, read_feed, sleep):
    """One conditional feed read with the existing bounded retry."""
    for attempt in range(4):
        try:
            return read_feed(feed, etag)
        except OSError as exc:
            if isinstance(exc, urllib.error.HTTPError) or attempt == 3:
                raise
            sleep(30 * 2 ** attempt)
            print(f'retrying feed fetch ({exc})')


def _persist_models_url(home, latest):
    """Remember the feed's models_url for the router's refresh thread.

    Plan 099 Step 3: the router boots from this file with a channel default;
    a missing or malformed URL leaves the previous file alone, and a stale
    URL is safer than a broken update.
    """
    url = latest.get('models_url')
    if not isinstance(url, str) or not url.startswith('https://'):
        return
    try:
        (Path(home) / 'models-url').write_text(url.strip() + '\n')
    except OSError:
        pass


# Test seam: tests inject an ephemeral public key so signed fixtures verify.
_FEED_VERIFY_KEY = None


def _verified_feed(feed, body, _fetch):
    """Parse one feed document after Ed25519 verification (Plan 145).

    `https` feeds must carry a valid detached sidecar; rejection raises
    `UpdateError('feed_signature', ...)`. A `file://` feed stays
    operator-trusted without a sidecar, and must verify with one.
    """
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location(
        'router_feed_verify_upd',
        Path(__file__).resolve().parent / 'feed_verify.py')
    fv = _ilu.module_from_spec(spec)
    spec.loader.exec_module(fv)
    if _FEED_VERIFY_KEY is not None:
        fv.FEED_PUBLIC_KEY = _FEED_VERIFY_KEY
    _fspec = _ilu.spec_from_file_location(
        'router_feed_sig',
        Path(__file__).resolve().parent / 'feed.py')
    _fmod = _ilu.module_from_spec(_fspec)
    _fspec.loader.exec_module(_fmod)
    if feed.startswith('file://') and _FEED_VERIFY_KEY is None:
        try:
            return json.loads(body.decode())
        except ValueError:
            raise UpdateError('feed_invalid', 'feed document is not JSON')
    try:
        sig = _fmod.live_signature(feed, _fetch)
    except (OSError, SystemExit):
        sig = None
    if feed.startswith('file://'):
        if sig is None:
            try:
                return json.loads(body.decode())
            except ValueError:
                raise UpdateError('feed_invalid', 'feed document is not JSON')
        try:
            return fv.checked_feed(body, sig)
        except SystemExit as exc:
            raise UpdateError('feed_signature', str(exc) or 'feed signature rejected')
    if sig is None:
        raise UpdateError('feed_signature', 'feed signature missing')
    try:
        return fv.checked_feed(body, sig)
    except SystemExit as exc:
        raise UpdateError('feed_signature', str(exc) or 'feed signature rejected')


def _up_to_date(home, announce, etag_path=None, etag=None, feed=None):
    """Record an unchanged regular check, then offer any new models."""
    if etag_path is not None and etag:
        etag_path.write_text(etag + '\n')
    _record_pass(home, error='')
    facts = _status.summary(_svc._state.read(_svc._state.path(home)),
                            _svc.current_version(home), feed, _status.channel(home))
    prefix = {'repair': 'update needs repair; current ', 'update': 'update available; current '}
    print(prefix.get(facts['required_action'], 'up to date ') + _svc.current_version(home))
    try:
        state = json.loads((home / 'mixed-router-state.json').read_text())
        (announce or _announce_new_models)(home, state)
    except Exception:
        pass


def _apply_update(args, home, sleep, _fetch, _read_feed, _announce):
    """One applying pass; behavior matches the pre-split code."""
    sync_seams()
    express_only = getattr(args, 'express_only', False)
    feed = args.feed or _svc.channel_feed(home)
    # Injected fetchers retain their one-argument contract.
    injected = _fetch
    _fetch = injected or _svc.fetch
    _models.refresh(home, _fetch)
    read_feed = _read_feed or (lambda url, etag: _svc.fetch_feed(url, etag, injected))
    etag_path = home / 'update-etag'
    stored_tag = etag_path.read_text().strip() if etag_path.exists() else None
    current, channel = _svc.current_version(home), _status.channel(home)
    etag = _status.cache_tag(_svc._state.read(_svc._state.path(home)),
                            current, feed, channel, stored_tag)
    conditional = etag
    try:
        status, body, etag = _read_feed_pass(feed, etag, read_feed, sleep)
        fresh = _status.cache_tag(_svc._state.read(_svc._state.path(home)),
                                  _svc.current_version(home), feed, _status.channel(home), conditional)
        if status == 304 and (not conditional or fresh != conditional or channel != _status.channel(home)
                or not args.feed and feed != _svc.channel_feed(home)
                or not express_only and not _resources.ready(home)):
            status, body, etag = _read_feed_pass(feed, None, read_feed, sleep)
            if status == 304:
                raise UpdateError('feed_invalid', 'cached response has no verified current release')
    except UpdateError:
        raise
    except SystemExit as exc:
        raise UpdateError('feed_untrusted', str(exc) or 'feed redirected off the trusted update origin')
    if status == 304:
        if express_only:
            return 0
        _record_pass(home, latest={'version': current}, feed=feed, etag=conditional, channel=channel)
        _up_to_date(home, _announce, feed=feed)
        return 0
    try:
        latest = _verified_feed(feed, body, _fetch)
    except UpdateError:
        raise
    except ValueError:
        raise UpdateError('feed_invalid', 'feed document is not JSON')
    if not isinstance(latest, dict) or not _status.version(latest.get('version')):
        raise UpdateError('feed_invalid', 'feed document has no valid version')
    _persist_models_url(home, latest)
    try:
        _svc.check_serial(home, latest, pinned=bool(args.feed))
    except SystemExit as exc:
        raise UpdateError('feed_serial', str(exc) or 'feed document refused')
    if not args.feed and (not express_only or latest.get('express') is True):
        _models.accept(home, latest)
        _models.refresh(home, _fetch)
    bundle_url = _svc.sibling_bundle(feed, latest.get('url', ''))
    if not _svc.trusted_origin(bundle_url):
        raise UpdateError('feed_untrusted',
                          'feed points off the trusted update origin; refusing')
    if express_only and latest.get('express') is not True or not newer(latest['version'], _svc.current_version(home)):
        if express_only:
            if (_svc._state.read(_svc._state.path(home)) or {}).get('last_error') in _status.FEED_ERRORS:
                _record_pass(home, latest=latest, feed=feed, etag=None, channel=channel)
            return 0  # Feed recovery cannot claim an applied release or clear install failures.
        _record_pass(home, latest=latest, feed=feed, etag=etag, channel=channel)
        if not _resources.ready(home):
            with _svc.install_lock(home) as held:
                if not held:
                    print('deferred: another router operation is in progress')
                    return 0
                _resources.deliver(home, latest, feed, injected)
        _up_to_date(home, _announce, etag_path, etag, feed)
        return 0
    _record_pass(home, latest=latest, feed=feed, etag=etag, channel=channel)
    failed = _status.failures(_svc._state.read(_svc._state.path(home)),
                             feed, _status.channel(home)).get(latest['version'], 0)
    if express_only and failed:
        return 0  # Retry failures on the regular cadence, not every minute.
    if failed >= MAX_VERSION_FAILURES:
        if etag:
            etag_path.write_text(etag + '\n')
        # The reason stays in state: a skipped pass is not a recovered one.
        _record_pass(home)
        print(f"skipping {latest['version']}: {failed} failed attempts; "
              f"run the installer by hand to retry")
        return 0
    try:
        state = json.loads((home / 'mixed-router-state.json').read_text())
    except (OSError, ValueError):
        raise UpdateError('update_failed', 'router state is missing or unreadable')
    want = _required_sha256(latest)
    try:
        tarball = _fetch(bundle_url)
    except SystemExit as exc:
        raise UpdateError('feed_untrusted', str(exc) or 'feed redirected off the trusted update origin')
    try:
        verify_sha256(tarball, want)
    except SystemExit as exc:
        raise UpdateError('bundle_checksum', str(exc) or 'bundle checksum mismatch')
    with tempfile.TemporaryDirectory() as tmp:
        try:
            _svc.safe_extract(tarball, tmp)
        except (OSError, SystemExit) as exc:
            raise UpdateError('bundle_invalid',
                              str(exc) or 'bundle could not be extracted')
        installer = Path(tmp) / 'packaging' / 'install.py'
        if not installer.exists():
            raise UpdateError('bundle_invalid', 'downloaded bundle has no installer')
        # Only forward an explicitly pinned feed; a channel-resolved feed must
        # not pin home/'feed', or beta would freeze on one release asset URL.
        # Scheduled and manual update checks never pop the first-run key
        # window; the next request opens it through the request path. The
        # nonce is still minted so a keyless service can boot.
        cmd = [sys.executable, str(installer), '--home', str(home), '--python', sys.executable]
        if args.feed:
            cmd += ['--feed', feed]
        try:
            result = _svc.run(cmd, capture_output=True, text=True, timeout=900,
                              env=dict(os.environ, ROUTER_NO_KEY_WINDOW='1', ROUTER_AUTOMATIC_UPDATE='1'))
        except subprocess.SubprocessError as exc:
            # A child that is killed or never starts reports nothing itself,
            # so count it here or a hanging release retries every poll
            # forever. TimeoutExpired is a SubprocessError, not an OSError.
            _park(home, etag, etag_path, latest['version'])
            code = ('installer_timeout' if isinstance(exc, subprocess.TimeoutExpired)
                    else 'installer_failed')
            raise UpdateError(code, f'installer did not complete: {type(exc).__name__}')
        print(result.stdout[-2000:] if result.stdout else '')
        if result.returncode != 0:
            print(result.stderr[-2000:] if result.stderr else '')
            # A child can fail after the swap and a healthy restart (a refused
            # Codex settings merge). That release keeps serving, so record the
            # pass, show the notice, and still report the failure; a pointer
            # without a serving router is a release to retry and park.
            landed = (_svc.current_version(home) == latest['version']
                      and _svc.wait_version(state, latest['version'])
                      and (sys.platform != 'win32' or _resources.ready(home)))
            if not landed:
                _park(home, etag, etag_path, latest['version'])
                _record_pass(home, error='installer_failed')
                raise SystemExit(result.returncode)
            _svc.notice.show_pending(home)
            failure = result.returncode
        else:
            failure = 0
    if (_svc.current_version(home) != latest['version'] or
            sys.platform == 'win32' and not _resources.ready(home)):
        print('deferred: installer did not activate the requested version')
        _record_pass(home)
        return failure
    clear_update_failures(home, latest['version'])
    (home / 'logs').mkdir(exist_ok=True)
    with open(home / 'logs' / 'update.log', 'a') as stream:
        stream.write(json.dumps({'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                                 'version': latest['version'],
                                 'source': _svc.feed_source(feed)}) + '\n')
    if etag:
        etag_path.write_text(etag + '\n')
    (_announce or _announce_new_models)(home, state)
    if failure:
        print(f'installed {latest["version"]}; the installer exited {failure} after the swap')
        _record_pass(home, error='installer_failed', applied=latest['version'])
        return failure
    _record_pass(home, error='', applied=latest['version'])
    print(f"installed {latest['version']}")
    return 0


def do_update(args, _fetch=None, _read_feed=None, _sleep=None, _announce=None):
    """Apply updates, reconcile attachments, and record closed-set outcomes."""
    import random
    home = Path(args.home).expanduser()
    _svc._feed.configure_home(home)
    sleep = _sleep or time.sleep
    sleep(random.uniform(0, 10 if getattr(args, 'express_only', False) else 120))
    task, result = ('express' if getattr(args, 'express_only', False) else 'regular'), 0
    _reconcile.log(home, task, 'launched')
    with _svc.install_lock(home, 'update.lock') as held:
        if not held:
            _reconcile.log(home, task, 'completed', outcome='deferred')
            print('deferred: another update check is in progress')
            return 0
        try:
            result = _apply_update(args, home, sleep, _fetch, _read_feed, _announce)
            return result
        except UpdateError as exc:
            _record_pass(home, error=exc.error_code)
            raise
        except _svc._feed.SignInRequired:
            _record_pass(home, error='download_signin_required')
            _svc.load('router_download_notice', Path(__file__).with_name('download_notice.py')).show(home)
            raise SystemExit('Sign in through SCG Router to download updates.') from None
        except OSError:
            _record_pass(home, error='feed_unreachable')
            raise
        except ValueError:
            _record_pass(home, error='feed_invalid')
            raise
        except Exception:
            _record_pass(home, error='update_failed')
            raise
        finally:
            _reconcile.run(home, _svc)
            _reconcile.log(home, task, 'failed' if sys.exc_info()[0] or result else 'completed')
            _offer_notices(home)


def do_check_update(args, _fetch=None, _read_feed=None, _sleep=None):
    """Read-only pass: report the installed and available versions.

    It never installs, never writes the ETag and never touches the state
    document; the applying verb is `do_update`.
    """
    home = Path(args.home).expanduser()
    _svc._feed.configure_home(home)
    feed = args.feed or _svc.channel_feed(home)
    injected = _fetch
    read_feed = _read_feed or (lambda url, etag: _svc.fetch_feed(url, etag, injected))
    try:
        status, body, _ = _read_feed_pass(feed, None, read_feed, _sleep or time.sleep)
    except OSError as exc:
        raise SystemExit(f'update check failed: {type(exc).__name__}')
    if status == 304:
        raise SystemExit('update check failed: cached response has no verified release')
    try:
        latest = _verified_feed(feed, body, _fetch or _svc.fetch)
    except UpdateError as exc:
        raise SystemExit(f'update check failed: feed signature {exc}')
    except ValueError:
        raise SystemExit('update check failed: feed document is not JSON')
    if not isinstance(latest, dict) or not _status.version(latest.get('version')):
        raise SystemExit('update check failed: feed document has no version')
    try:
        _svc.check_serial(home, latest, pinned=bool(args.feed))
    except SystemExit as exc:
        raise SystemExit(str(exc) or 'update check failed: feed document refused')
    if not _svc.trusted_origin(_svc.sibling_bundle(feed, latest.get('url', ''))):
        raise SystemExit('update check failed: untrusted bundle origin')
    current = _svc.current_version(home)
    available = (latest['version']
                 if newer(latest['version'], current) else None)
    channel = ((home / 'channel').read_text().strip()
               if (home / 'channel').exists() else 'stable')
    state = dict(_svc._state.read(_svc._state.path(home)) or {})
    _status.verified(state, latest, feed, channel, None)
    facts = _status.summary(state, current, feed, channel)
    if args.json:
        print(json.dumps({'installed': current, 'available': available,
                          'channel': channel, 'latest': latest['version'],
                          'checked': True, 'source': facts['source'],
                          'checked_at': state['last_successful_check_at'],
                          'required_action': facts['required_action']}, sort_keys=True))
    elif available:
        print(f'current {current}; available {available}')
    elif facts['required_action']:
        print(f'current {current}; update needs repair')
    else:
        print(f'up to date {current}')
    return 0
