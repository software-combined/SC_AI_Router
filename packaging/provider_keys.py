"""Per-provider key presence for the installer surface (Plan 141).

The installer and diagnostics both need to know whether a provider's key
resolves, without ever reading the value out. One owner for that walk keeps
the two surfaces aligned with `ai_router/credentials.py`'s key_for()
precedence, which is the router's own contract.

Runs on Python 3.9+ like the installer and is spec-loaded by its callers;
the provider definitions arrive through `bind` so this module imports no
router package.
"""
import json
import os
import time
from pathlib import Path

_defs = None


def bind(defs_module):
    """Inject the loaded ai_router.provider_defs module."""
    global _defs
    _defs = defs_module


def external_defs():
    return _defs.external_defs()


def default_id():
    return _defs.DEFAULT_EXTERNAL


def _opencode_auth_path(env=None):
    """Same client rule as ai_router/credentials.py, for the 3.9 tree.

    The two trees cannot share the function; they must agree on which file
    the OpenCode client owns, or the installer would count a key handled
    that the router then refuses. HOME only: the installed service carries
    no XDG_DATA_HOME, so honouring one here would let the two disagree.
    """
    env = os.environ if env is None else env
    return (Path(env.get('HOME') or Path.home())
            / '.local' / 'share' / 'opencode' / 'auth.json')


def _owns_opencode_auth(state, env=None):
    """The client's own auth path when the state names it, else None."""
    auth_path = state.get('opencode_auth') if isinstance(state, dict) else None
    if not isinstance(auth_path, str) or not auth_path:
        return None
    env = os.environ if env is None else env
    if auth_path == '~':
        expanded = Path(env.get('HOME') or Path.home())
    elif auth_path.startswith('~/'):
        expanded = Path(env.get('HOME') or Path.home()) / auth_path[2:]
    else:
        expanded = Path(auth_path)
    if expanded != _opencode_auth_path(env):
        return None
    # Return the expanded path: the readers below must open exactly what was
    # compared, or a `~`-form state key would count here and read elsewhere.
    return str(expanded)


def key_state(home, state, env, defn, private=None, client_env=None):
    """(present, usable) for one provider; no value ever leaves this call.

    Precedence mirrors credentials.key_for(): env wins; else an existing key
    file decides by non-blank content, and counts as usable only when
    `private` accepts its permissions; a configured third-party credential
    counts only when no key file shadows it and it actually carries an api
    key. `private` None treats any non-blank key file as usable, which is
    the installer's pre-existing contract.
    """
    key_file = home / defn.key.file
    try:
        exists = key_file.is_file()
    except OSError:
        exists = False
    try:
        text = key_file.read_text() if exists else ''
    except OSError:
        text = ''
    private_ok = bool(private(key_file)) if (exists and private is not None) else bool(text.strip())
    auth_key = ''
    # The key env and the client's own data directory are separate inputs:
    # `unhandled` ignores the shell's provider variables but must still
    # resolve the same auth file the service will read.
    auth_path = (_owns_opencode_auth(state, client_env or env)
                 if defn.key.state_key else None)
    if auth_path:
        try:
            doc = json.loads(Path(auth_path).read_text())
            entry = doc.get(defn.key.state_key) if isinstance(doc, dict) else None
            if isinstance(entry, dict) and entry.get('type') == 'api':
                auth_key = str(entry.get('key') or '').strip()
        except (OSError, ValueError, AttributeError):
            auth_key = ''
    env_key = env.get(defn.key.env, '').strip() if env else ''
    present = bool(env_key or text.strip() or auth_key)
    # Mirror key_for()'s order exactly: an existing key file is terminal, so
    # the third-party credential is consulted only when there is no key file
    # at all. An empty placeholder therefore reports not usable, which is
    # what the router does with it (LookupError: the file is empty).
    if env_key:
        usable = True
    elif exists:
        usable = bool(text.strip() and private_ok)
    else:
        usable = bool(auth_key)
    return present, usable


def ensure(home, state, env, protect):
    """Prompt for the first provider without a key, then stop the install.

    The placeholder file is created owner-only and protected before the
    message prints; a failed protection removes it rather than leaving an
    unprotected placeholder the next run would trust.

    A provider counts as supplied when any source the router will try
    exists, including a blank placeholder the operator has not filled yet:
    the installer's own first run creates that file and then hands over to
    the setup window, and the scheduled updater must keep advancing while
    the operator finishes. `key_state` stays the stricter reading for
    `--status`.
    """
    pending = [defn for defn in external_defs()
               if not supplied(home, state, env, defn)]
    if not pending:
        return
    defn = pending[0]
    key_file = home / defn.key.file
    if not key_file.exists():
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        try:
            protect(key_file)
        except SystemExit:
            try:
                key_file.unlink()
            except OSError:
                pass
            raise
    if _setup_armed(state):
        # The installer already minted the first-run window: it collects the
        # key, so the placeholder is created silently and the install
        # proceeds instead of stopping with the paste-and-re-run instruction.
        return
    print(f'Paste your {defn.label} key into {key_file} '
          '(owner-only file) and re-run the installer')
    raise SystemExit(3)


def _setup_armed(state):
    """True while a fresh installer-minted setup nonce is pending.

    Same shape as ai_router.setup.setup_pending, kept literal so this
    3.9-compatible module never imports the router package.
    """
    cfg = state.get('setup') if isinstance(state, dict) else None
    nonce = cfg.get('nonce') if isinstance(cfg, dict) else None
    expires = cfg.get('expires') if isinstance(cfg, dict) else None
    if not isinstance(nonce, str) or not nonce:
        return False
    if isinstance(expires, bool) or not isinstance(expires, (int, float)):
        return False
    return expires > time.time()


def unhandled(home, state, private):
    """External defs the installed service cannot serve yet.

    A service-visible read: the environment is ignored because the installer
    passes only ROUTER_HOME to the service and never the invoking shell's
    environment, so a provider counts as handled only through a non-blank
    owner-only key file, or opencode_auth carrying an API key when no key
    file exists. An empty placeholder is not handled.

    A non-blank key file that fails the owner-only check raises SystemExit
    naming the file and the required permission instead of arming a window:
    the setup route would return 409 on that file. A blank placeholder
    never refuses; the window claims it.
    """
    missing = []
    for defn in external_defs():
        _, usable = key_state(home, state, {}, defn, private,
                              client_env=os.environ)
        if usable:
            continue
        key_file = home / defn.key.file
        try:
            non_blank = bool(key_file.read_text().strip()) if key_file.is_file() else False
        except OSError:
            non_blank = False
        if non_blank:
            # A non-blank file can be unusable only when the owner-only check
            # failed; the setup route would return 409 on that file, so
            # refuse instead of arming a window.
            if os.name == 'nt':
                raise SystemExit(
                    '%s is not owner-only; restrict it to the installing user '
                    'with icacls, or delete it and re-run the installer'
                    % key_file)
            raise SystemExit(
                '%s must be readable by the owner only (chmod 600); fix the '
                'permission or delete it and re-run the installer' % key_file)
        missing.append(defn)
    return missing


def supplied(home, state, env, defn):
    """True when the installer should consider this provider already handled.

    Mirrors the installer's long-standing contract rather than the router's
    readiness: env non-empty, the key file present at all, or a configured
    third-party credential file that exists.
    """
    if env and env.get(defn.key.env, '').strip():
        return True
    try:
        if (home / defn.key.file).exists():
            return True
    except OSError:
        return False
    auth_path = _owns_opencode_auth(state, env) if defn.key.state_key else None
    return bool(auth_path and Path(auth_path).exists())
