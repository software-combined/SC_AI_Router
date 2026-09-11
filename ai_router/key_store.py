"""Key validation and storage for first-run setup (Plan 141).

One owner for the provider-scoped key lifecycle: validate against the
provider's key-info endpoint when it has one, write through the single
shared writer, and prove a stored key is dead before replacing it. The
nonce, window and state machine stay in `setup.py`.
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from . import provider_defs


class KeyRejected(ValueError):
    """check_key refusal carrying the HTTP status; 401/403 means a dead key."""
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def check_key(provider_id, key, _urlopen=urllib.request.urlopen):
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


def _claim_truncated(key_path):
    """Open an existing key file for overwrite, keeping owner-only mode."""
    fd = os.open(key_path, os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
    except OSError:
        pass
    return fd


def store_key(home, key, provider_id=provider_defs.DEFAULT_EXTERNAL, _check_live=None):
    """Write one provider's key through the one shared writer."""
    key_path = Path(home) / provider_defs.get(provider_id).key.file
    try:
        return os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    try:
        stored = key_path.read_bytes().strip()
    except OSError:
        raise OSError('could not store the key')
    if not stored:
        return _claim_truncated(key_path)
    if _check_live is not None and _check_live(stored.decode('utf-8', 'replace')) is False:
        return _claim_truncated(key_path)
    raise KeyExists('a key file already exists; delete it to rotate keys')


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


