"""Private feed token handling (Plan 054 source slice). Python 3.9-safe.

Trusted-origin gate, per-request token header, token persistence with a
previous-value fallback for one 403 retry. Never logs the token. Loaded via
importlib like the other packaging helpers (never `import packaging.x`,
which collides with the third-party distribution).
"""
import urllib.error
import urllib.request
from pathlib import Path


def token_path(home):
    return Path(home) / 'feed-token'


def current(home):
    """Current feed token, or empty when the feed never issued one."""
    try:
        return token_path(home).read_text().strip()
    except OSError:
        return ''


def persist(home, latest):
    """Keep the feed's rotated token; previous value stays for one 403 retry."""
    token = latest.get('feed_token', '')
    if not token or home is None:
        return
    path = token_path(home)
    try:
        previous = path.read_text().strip()
    except OSError:
        previous = ''
    if previous and previous != token:
        (Path(home) / 'feed-token.previous').write_text(previous)
    path.write_text(token)


def previous(home):
    try:
        return (Path(home) / 'feed-token.previous').read_text().strip()
    except OSError:
        return ''
