"""Key validation and storage for first-run setup (Plan 141).

One owner for the provider-scoped key lifecycle: validate against the
provider's key-info endpoint when it has one, write through the single
shared writer, and prove a stored key is dead before replacing it. The
nonce, window and state machine stay in `setup.py`.
"""
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

from . import provider_defs
from .atomic_write import replace_text

# Two setup windows can submit at once (ThreadingHTTPServer); the lock keeps
# the check-then-replace claim from silently losing an update to its twin.
_LOCK = threading.Lock()


class KeyRejected(ValueError):
    """check_key refusal carrying the HTTP status; 401/403 means a dead key."""
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # urllib raises HTTPError(code) instead of following


def _open_without_redirects(req, timeout):
    return urllib.request.build_opener(_NoRedirects()).open(req, timeout=timeout)


def check_key(provider_id, key, _urlopen=_open_without_redirects):
    """(label, limit, usage) for a live key; KeyRejected when refused, OSError when down.

    A provider with a key-info endpoint is validated before anything is
    stored. One without it stores unvalidated and still fails closed on the
    first request, so no provider is blocked on an endpoint it lacks.
    """
    defn = provider_defs.get(provider_id)
    label = provider_defs.label_for(provider_id)
    if defn is None or not defn.key_info_url:
        return (label, None, None)
    req = urllib.request.Request(defn.key_info_url,
                                 headers={'Authorization': 'Bearer ' + key})
    try:
        with _urlopen(req, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            raise OSError('key check was redirected; refusing to follow')
        raise KeyRejected(label + ' rejected the key', status=exc.code)
    data = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise KeyRejected(label + ' returned an unexpected key response')
    return (data.get('label') or 'key', data.get('limit'), data.get('usage'))


def window_provider(state):
    """Provider id the pending window collects for, defaulting safely."""
    cfg = state.get('setup') if isinstance(state, dict) else None
    provider_id = cfg.get('provider') if isinstance(cfg, dict) else None
    if provider_defs.is_external(provider_id):
        return provider_id
    return provider_defs.DEFAULT_EXTERNAL


class KeyExists(OSError):
    """The key file holds a live key; rotation needs explicit deletion."""


def store_key(home, key, provider_id=provider_defs.DEFAULT_EXTERNAL, _check_live=None):
    """Write one provider's key through the one shared writer.

    Replaces a missing or empty file and a key proven dead by `_check_live`;
    a live stored key raises KeyExists. The write is atomic, so a crash
    never leaves a half-written secret behind.
    """
    key_path = Path(home) / provider_defs.get(provider_id).key.file
    with _LOCK:
        if key_path.exists():
            try:
                stored = key_path.read_bytes().strip()
            except OSError:
                raise OSError('could not store the key')
            if stored and not (_check_live is not None
                               and _check_live(stored.decode('utf-8', 'replace')) is False):
                raise KeyExists('a key file already exists; delete it to rotate keys')
        replace_text(key_path, key + '\n')
    return key_path


def _stored_key_live(provider_id, stored, _fetch):
    """True when the stored key still validates; False only on 401/403.

    Any other outcome (network down, rate limit, unparseable body) refuses
    the carve-out: truncating there could destroy the only copy of a live
    provisioned secret.
    """
    try:
        check_key(provider_id, stored, _fetch)
    except KeyRejected as exc:
        return exc.status not in (401, 403)
    except (ValueError, OSError):
        return True
    return True
