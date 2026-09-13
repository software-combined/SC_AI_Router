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
