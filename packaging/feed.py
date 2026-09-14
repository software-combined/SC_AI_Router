"""Public update feed: origin, channel resolution, and fetch.

Every install updates from the public feed at dist.softwarecombined.com:
no token, no account, no repository access. An explicit `--feed` pin or a
`feed` file is the manual path. Runs on Python 3.9+ like the installer.
Loaded via the installer's file-based import pattern, never
`import packaging.feed`.
"""
import urllib.error
import urllib.request
from pathlib import Path

import importlib.util as _ilu
_spec = _ilu.spec_from_file_location(
    'router_feed_verify',
    Path(__file__).resolve().parent / 'feed_verify.py')
_feed_verify = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_feed_verify)

FEED_ORIGIN = 'https://dist.softwarecombined.com'
FEED_URL = FEED_ORIGIN + '/stable/latest.json'


def _safe_url(url):
    """URL safe to name in an error: no query string, bounded length."""
    return str(url).split('?')[0][:200]


def trusted_origin(url):
    """True for feed/bundle URLs the installer may fetch unattended."""
    if url.startswith('file://'):
        return True
    return url.startswith(FEED_ORIGIN + '/')


def sibling_bundle(feed, url):
    """Bundle beside a local feed document, else the document's own URL.

    A handoff directory carries latest.json and the bundle together; the
    document's `url` may still name the published asset, which the recipient
    cannot fetch. The sibling is used only when it exists, and the
    document's sha256 still verifies it.
    """
    if str(feed).startswith('file://'):
        candidate = (Path(str(feed)[len('file://'):]).parent
                     / str(url).rsplit('/', 1)[-1])
        if candidate.is_file():
            return 'file://' + str(candidate)
    return url


def channel_feed(home):
    """Feed URL for this host: a pinned `feed` file, else its channel.

    `channel` names beta for the pre-release document; anything else, or a
    missing file, is stable. Both documents are public.
    """
    home = Path(home)
    if (home / 'feed').exists():
        return (home / 'feed').read_text().strip()
    channel = (home / 'channel').read_text().strip() if (home / 'channel').exists() else 'stable'
    if channel == 'beta':
        return _feed_verify.beta_feed_url(FEED_URL)
    return FEED_URL


def _get(url, headers, etag):
    """One GET; keeps the caller's ETag when the response carries none."""
    with urllib.request.urlopen(
            urllib.request.Request(url, headers=headers), timeout=30) as response:
        return (response.status, response.read(),
                response.headers.get('ETag', etag))


def live_feed(url, etag, fetch):
    """Default feed read: conditional GET with ETag from the public feed."""
    headers = {'If-None-Match': etag} if etag else {}
    if url.startswith('file://'):
        return 200, fetch(url), etag
    if not trusted_origin(url):
        raise SystemExit('refusing untrusted feed URL: %s' % _safe_url(url))
    try:
        return _get(url, headers, etag)
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return 304, b'', etag
        raise


def feed_source(feed_url):
    """Short feed name for update.log: cloudfront, local, or https."""
    feed_url = str(feed_url)
    if feed_url.startswith(FEED_ORIGIN + '/'):
        return 'cloudfront'
    if feed_url.startswith('file://'):
        return 'local'
    return 'https'


def fetch_feed(url, etag, _fetch=None, _live_feed=None):
    """Read a feed document, revalidating with a saved ETag.

    Feed-channel owner (Plan 131): moved out of service.py; service keeps a
    thin re-export so installer patches still resolve. Returns
    (status, body, etag). Injected fakes keep their one-argument shape and
    bypass the conditional-GET path. The default path calls back into
    service.fetch through _live_feed so the installer's seam still applies.
    """
    import urllib.error as _httperr
    import urllib.request as _urlreq
    live = _live_feed if _live_feed is not None else live_feed
    default_fetch = getattr(live, '__self__', None)
    if _fetch is None:
        import sys as _sys
        _svc_mod = _sys.modules.get('packaging.service')
        _fetch = getattr(_svc_mod, 'fetch', None)
        if _fetch is None:
            raise SystemExit('service.fetch seam unavailable')
        return live(url, etag, _fetch)
    if url.startswith('file://'):
        return 200, _fetch(url), etag
    req = _urlreq.Request(url, headers={'If-None-Match': etag} if etag else {})
    try:
        with _urlreq.urlopen(req, timeout=30) as response:
            return response.status, response.read(), response.headers.get('ETag', etag)
    except _httperr.HTTPError as exc:
        if exc.code == 304:
            return 304, b'', etag
        raise


def feed_serial(home):
    """Last accepted feed serial; 0 when no serialed release was installed."""
    home = Path(home)
    try:
        return int((home / 'feed-serial').read_text().strip())
    except FileNotFoundError:
        return 0
    except ValueError:
        raise SystemExit('feed serial file is corrupt')


def check_serial(home, latest, pinned=False):
    """Refuse feeds older than the last accepted one (replay protection).

    A pinned `--feed` is exempt on both sides: operator-supplied for this
    one run, neither the unattended channel the guard protects nor recorded
    afterwards.
    """
    if pinned:
        return 0
    serial = latest.get('serial', 0)
    if type(serial) is not int:
        raise SystemExit('feed has a bad serial')
    stored = feed_serial(home)
    if serial < stored:
        raise SystemExit(f'stale feed serial {serial} is older than {stored}')
    return serial
