"""Ordered per-provider key lookup, driven by provider_defs.KeySpec.

Read at request time so rotation needs no restart. The lookup order is the
definition's: environment variable, then the owner-only key file, then the
optional third-party credential file. Never log the key.
"""
import json
import os
from pathlib import Path

from . import errors, key_store, provider_defs, state as state_mod
from .state import default_home  # used below and re-exported for importers

# Per-module flag so tests can drive the Windows branch without patching
# global os.name (which pathlib itself reads).
_ON_WINDOWS = os.name == 'nt'


def opencode_auth_path(env=None):
    """The one credential file the OpenCode client writes.

    Resolved from HOME exactly as the service sees it: the launchd/systemd
    environment carries no XDG_DATA_HOME, so both the router and the
    installer must agree on the client's default data directory. The router
    reads that path only, so a hand-edited state file cannot aim it at
    another file and read that as a credential.
    """
    env = os.environ if env is None else env
    return (Path(env.get('HOME') or Path.home())
            / '.local' / 'share' / 'opencode' / 'auth.json')


def _expand(path_text, env):
    """Expand a leading `~` against the given environment, not the process."""
    if path_text == '~':
        return Path(env.get('HOME') or Path.home())
    if path_text.startswith('~/'):
        return Path(env.get('HOME') or Path.home()) / path_text[2:]
    return Path(path_text)


class Credentials:
    def __init__(self, state, home=None, env=None):
        self.state = state
        self.home = Path(home) if home is not None else default_home()
        self.env = os.environ if env is None else env

    def key_spec(self, provider_id):
        """KeySpec for one provider, or None when it holds no router key."""
        defn = provider_defs.get(provider_id)
        return defn.key if defn is not None else None

    def key_for(self, provider_id=provider_defs.DEFAULT_EXTERNAL):
        """The provider's key. LookupError/PermissionError/ValueError when unusable."""
        defn = provider_defs.get(provider_id)
        spec = defn.key if defn is not None else None
        if spec is None:
            raise LookupError(f'{provider_id} does not use a router key')
        value = self.env.get(spec.env, '').strip()
        if value:
            return value
        key_file = self.home / spec.file
        if key_file.exists():
            # One owner for the key-privacy gate (Plan 131): the platform
            # branch and its message live in winacl.
            from . import winacl as _winacl
            try:
                _winacl.require_owner_only(key_file, _ON_WINDOWS)
            except _winacl.VerificationUnavailable as exc:
                raise errors.CredentialCheckUnavailable(str(exc)) from None
            value = key_file.read_text().strip()
            if value:
                return value
            raise LookupError(f'{key_file} is empty')
        opencode = self.state.get('opencode_auth') if spec.state_key else None
        if opencode:
            expected = opencode_auth_path(self.env)
            if _expand(opencode, self.env) != expected:
                raise LookupError(f'opencode_auth must name {expected}')
            try:
                auth = json.loads(expected.read_text())[spec.state_key]
                if auth.get('type') != 'api':
                    raise ValueError('OpenCode credential is not an API key')
                return auth['key']
            except (KeyError, TypeError, AttributeError):
                raise LookupError(f'{opencode} has no {spec.state_key} api key')
        sources = [f'set {spec.env}', f'create {key_file}']
        if spec.state_key:
            sources.append('configure opencode_auth')
        raise LookupError(f'No {defn.label} key: ' + ', or '.join(sources))

    def check(self, provider_id=provider_defs.DEFAULT_EXTERNAL):
        """Startup probe: raises the same errors as key_for without returning the value."""
        self.key_for(provider_id)
        return True

    def key_missing(self, provider_id):
        """The lookup failure for one provider, or None when it resolves.

        Every failure mode key_for() can raise counts, including an
        unreadable third-party credential file, so callers get one
        defensive check per provider.
        """
        try:
            self.key_for(provider_id)
        except (LookupError, PermissionError, ValueError, OSError) as exc:
            return exc
        return None

    def key_rejected(self, provider_id):
        """True only when the stored key file itself fails check_key on 401/403.

        The env key is not the effective credential when set, and an armed
        setup window already answers the raw 401, so both return False.
        """
        spec = self.key_spec(provider_id)
        if spec is None or self.env.get(spec.env, '').strip():
            return False
        if state_mod.setup_pending(self.state):
            return False
        try:
            stored = (self.home / spec.file).read_text().strip()
        except OSError:
            return False
        if not stored:
            return True
        try:
            key_store.check_key(provider_id, stored)
        except (ValueError, OSError) as exc:
            return isinstance(exc, key_store.KeyRejected) and exc.status in (401, 403)
        return False
