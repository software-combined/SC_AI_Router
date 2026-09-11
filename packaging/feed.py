"""Token-gated update feed: origin, token storage, and fetch (Plan 054 T).

Hosts without a feed token stay on the pre-migration GitHub route over
gh; the first feed that carries a token migrates every later poll to the
token-gated origin. Runs on Python 3.9+ like the installer. Loaded via
the installer's file-based import pattern, never `import packaging.feed`.
"""
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import importlib.util as _ilu
_spec = _ilu.spec_from_file_location(
    'router_feed_verify',
    Path(__file__).resolve().parents[1] / 'ai_router' / 'feed_verify.py')
_feed_verify = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_feed_verify)

FEED_ORIGIN = 'https://dist.softwarecombined.com'
FEED_URL = FEED_ORIGIN + '/stable/latest.json'
RELEASES_PREFIX = 'https://github.com/software-combined/SC_OpenRouter_adapter/releases/'
FEED_TOKEN_HEADER = 'X-SCG-Feed-Token'
FEED_TOKEN_FILE = 'feed-token'
FEED_TOKEN_PREVIOUS_FILE = 'feed-token.previous'

_GITHUB_REPO = 'software-combined/SC_OpenRouter_adapter'
_TOKEN_REMEDY = ('feed refused the stored token (HTTP 403); '
                 're-run the bootstrap from the Technology library')


def _safe_url(url):
    """URL safe to name in an error: no query string, bounded length."""
    return str(url).split('?')[0][:200]


def feed_token(home):
    """Current feed token, or None when this host has not migrated yet."""
    try:
        value = (Path(home) / FEED_TOKEN_FILE).read_text().strip()
    except OSError:
        return None
    return value or None


def _write_feed_token(home, value):
    """Persist a feed token owner-only; keep the previous value for retry."""
    home = Path(home)
    path = home / FEED_TOKEN_FILE
    previous = home / FEED_TOKEN_PREVIOUS_FILE
    try:
        current = path.read_text().strip()
    except OSError:
        current = ''
    if current and current != value:
        fd = os.open(previous, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(current + '\n')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(value + '\n')


def persist_feed_token(home, latest):
    """Store the feed's token after the serial check, before comparing."""
    token = latest.get('feed_token') if isinstance(latest, dict) else None
    if not isinstance(token, str) or not token.strip():
        return False
    _write_feed_token(home, token.strip())
    return True


def feed_headers(home):
    """Auth header for the token-gated feed origin, else no header."""
    token = feed_token(home) if home is not None else None
    return {FEED_TOKEN_HEADER: token} if token else {}


def trusted_origin(url):
    """True for feed/bundle URLs the installer may fetch unattended."""
    if url.startswith('file://'):
        return True
    if url.startswith(RELEASES_PREFIX):
        return True
    return url.startswith(FEED_ORIGIN + '/')


# Test seam for the gh subprocess; production default is subprocess.run.
_gh_run = subprocess.run

# Absolute locations checked when PATH lookup fails: schedulers start
# the updater with a minimal PATH, so an installed gh is invisible.
GH_POSIX_FALLBACKS = ('/opt/homebrew/bin/gh', '/usr/local/bin/gh',  # macOS (brew)
                      '/usr/bin/gh', '/snap/bin/gh',  # Linux (apt/dnf, snap)
                      '/home/linuxbrew/.linuxbrew/bin/gh')  # Linuxbrew
GH_WINDOWS_TAILS = (('ProgramFiles', ('GitHub CLI', 'gh.exe')),
                    ('LOCALAPPDATA', ('Programs', 'GitHub CLI', 'gh.exe')),
                    ('ProgramData', ('chocolatey', 'bin', 'gh.exe')),
                    ('USERPROFILE', ('scoop', 'shims', 'gh.exe')))


def gh_candidates(env=None):
    """Absolute gh locations beyond PATH; skips unset Windows variables."""
    if env is None:
        env = os.environ
    paths = list(GH_POSIX_FALLBACKS)
    for var, tail in GH_WINDOWS_TAILS:
        if env.get(var):
            paths.append(str(Path(env[var]).joinpath(*tail)))
    return tuple(paths)


def gh_binary():
    """Absolute GitHub CLI path, or None when it is not installed."""
    return shutil.which('gh') or next(
        (p for p in gh_candidates() if Path(p).is_file()), None)


def _beta_github_feed(home):
    """Newest pre-release's latest-beta.json asset URL via gh.

    GitHub Releases does not serve a CDN-style /beta/latest.json path on a
    private repo before the token-gated origin is live; the workflow
    publishes the feed as a release asset, so return the tagged asset URL.
    """
    gh = gh_binary()
    if gh is None:
        raise SystemExit('Cannot resolve beta release: install GitHub CLI (gh) '
                         'and sign in as this user')
    cmd = [gh, 'release', 'list', '--repo', _GITHUB_REPO,
           '--limit', '10', '--json', 'tagName,isPrerelease,isDraft', '--jq',
           '.[] | select(.isPrerelease == true and .isDraft == false) | .tagName']
    try:
        result = _gh_run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f'Cannot resolve beta release: {exc}')
    if result.returncode or not result.stdout.strip():
        raise SystemExit('Cannot resolve beta release; check gh auth status')
    tag = result.stdout.strip().splitlines()[0]
    if not tag or any(c in tag for c in '/?# '):
        raise SystemExit(f'refusing malformed beta release tag: {tag!r}')
    return f'{RELEASES_PREFIX.rstrip("/")}/download/{tag}/latest-beta.json'


def channel_feed(home):
    """Feed URL for this host: GitHub until it learns a token, then origin."""
    home = Path(home)
    if (home / 'feed').exists():
        return (home / 'feed').read_text().strip()
    channel = (home / 'channel').read_text().strip() if (home / 'channel').exists() else 'stable'
    if feed_token(home) is None:
        if channel == 'beta':
            return _beta_github_feed(home)
        return RELEASES_PREFIX + 'latest/download/latest.json'
    if channel == 'beta':
        return _feed_verify.beta_feed_url(FEED_URL)
    return FEED_URL


def github_route_parts(url):
    """(tag, asset) for a router release URL, or None when not one."""
    if not url.startswith(RELEASES_PREFIX):
        return None
    parts = url[len(RELEASES_PREFIX):].split('/')
    if len(parts) != 3 or not ((parts[0] == 'latest' and parts[1] == 'download')
                               or parts[0] == 'download'):
        raise SystemExit('unsupported router GitHub release URL')
    tag = None if parts[0] == 'latest' else parts[1]
    asset = parts[2]
    if not asset or any(c in asset for c in '?*[]'):
        raise SystemExit('invalid router release asset name')
    return tag, asset


def github_command(gh, tag, asset):
    """gh argv fetching one release asset to stdout."""
    cmd = [gh, 'release', 'download', '--repo', _GITHUB_REPO,
           '--pattern', asset, '--output', '-']
    if tag is not None:
        cmd += ['--', tag]
    return cmd


def _get(url, headers, etag):
    """One GET; keeps the caller's ETag when the response carries none."""
    with urllib.request.urlopen(
            urllib.request.Request(url, headers=headers), timeout=30) as response:
        return (response.status, response.read(),
                response.headers.get('ETag', etag))


def live_feed(url, etag, home, fetch):
    """Default feed read: token header, ETag, one previous-token retry."""
    headers = {'If-None-Match': etag} if etag else {}
    headers.update(feed_headers(home))
    if url.startswith('file://') or url.startswith(RELEASES_PREFIX):
        return 200, fetch(url), etag
    if not trusted_origin(url):
        raise SystemExit('refusing untrusted feed URL: %s' % _safe_url(url))
    try:
        return _get(url, headers, etag)
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return 304, b'', etag
        if exc.code == 403 and home is not None:
            try:
                previous = (Path(home) / FEED_TOKEN_PREVIOUS_FILE).read_text().strip()
            except OSError:
                previous = ''
            if previous and previous != headers.get(FEED_TOKEN_HEADER, ''):
                retry = dict(headers)
                retry[FEED_TOKEN_HEADER] = previous
                try:
                    return _get(url, retry, etag)
                except urllib.error.HTTPError:
                    pass
            raise SystemExit(_TOKEN_REMEDY)
        raise


def feed_source(feed_url):
    """Short feed name for update.log: cloudfront, github, or local."""
    feed_url = str(feed_url)
    if feed_url.startswith(FEED_ORIGIN + '/'):
        return 'cloudfront'
    if feed_url.startswith('file://'):
        return 'local'
    return 'github'
