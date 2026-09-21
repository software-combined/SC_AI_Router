"""Claude desktop gateway adapter (Plan 073). Python 3.9-safe helper.

Owns the four owned inference values merged into the third-party
profile's applied configLibrary entry, plus that profile's
deploymentMode, with conflict refusal on hand-edited owned values and
activation receipt handling. Mirrors the claude_config.py discipline:
private before image, atomic replacement at mode 600, owned values only,
receipt entry recording the pre-attach snapshot, and an exact detach.
Loaded through the installer's explicit file-import pattern and shipped
in the release bundle. No runtime/protocol import here.
"""
import json
import os
import sys
import uuid
import importlib.util as _ilu
from pathlib import Path

_spec = _ilu.spec_from_file_location(
    'router_runtime_atomic_write',
    Path(__file__).resolve().parents[1] / 'ai_router' / 'atomic_write.py')
atomic_write = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(atomic_write)

PROVIDER_KEY = 'inferenceProvider'
CREDENTIAL_KIND_KEY = 'inferenceCredentialKind'
BASE_URL_KEY = 'inferenceGatewayBaseUrl'
API_KEY_KEY = 'inferenceGatewayApiKey'
OWNED_KEYS = (PROVIDER_KEY, CREDENTIAL_KIND_KEY, BASE_URL_KEY, API_KEY_KEY)

PROVIDER_VALUE = 'gateway'
CREDENTIAL_KIND_VALUE = 'static'
# Placeholder: the router authorises on the loopback path token, not this.
API_KEY_VALUE = 'router-path-token'

CLIENT_KEY = 'claude-desktop'


PROFILE_DIRNAME = 'Claude-3p'


def profile_root(env=None, platform_name=None):
    """Parent of the app's userData directory, the way Electron resolves it.

    macOS uses Application Support, Windows uses the roaming AppData
    directory and Linux uses XDG_CONFIG_HOME (falling back to ~/.config).
    Getting this wrong pointed the installer at a macOS path that does not
    exist on the other platforms, so `--desktop` silently did nothing there.
    """
    env = os.environ if env is None else env
    platform_name = sys.platform if platform_name is None else platform_name
    if platform_name == 'darwin':
        return Path.home() / 'Library' / 'Application Support'
    if platform_name == 'win32':
        appdata = env.get('APPDATA')
        return Path(appdata) if appdata else Path.home() / 'AppData' / 'Roaming'
    xdg = env.get('XDG_CONFIG_HOME')
    return Path(xdg) if xdg else Path.home() / '.config'


def user_data_dir(env=None, platform_name=None):
    """Third-party profile dir, honoring CLAUDE_USER_DATA_DIR when set."""
    env = os.environ if env is None else env
    override = env.get('CLAUDE_USER_DATA_DIR')
    if override:
        return Path(override).expanduser()
    return profile_root(env, platform_name) / PROFILE_DIRNAME


def desired_values(state):
    return {PROVIDER_KEY: PROVIDER_VALUE,
            CREDENTIAL_KIND_KEY: CREDENTIAL_KIND_VALUE,
            BASE_URL_KEY: 'http://127.0.0.1:%s/%s' % (state['port'], state['token']),
            API_KEY_KEY: API_KEY_VALUE}


def applied_entry_path(data_dir):
    """Applied configLibrary entry selected by _meta.json/appliedId."""
    data_dir = Path(data_dir)
    try:
        meta = json.loads((data_dir / 'configLibrary' / '_meta.json').read_text())
    except (OSError, ValueError):
        raise SystemExit('Claude desktop library metadata is missing or invalid: %s'
                         % (data_dir / 'configLibrary' / '_meta.json'))
    applied = meta.get('appliedId') if isinstance(meta, dict) else None
    if not applied or not isinstance(applied, str):
        raise SystemExit('Claude desktop has no applied configuration entry')
    return data_dir / 'configLibrary' / (applied + '.json')


def read_entry(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text())
    except ValueError:
        raise SystemExit('Claude desktop entry is not valid JSON: %s' % path)
    if not isinstance(doc, dict):
        raise SystemExit('Claude desktop entry is not a JSON object: %s' % path)
    return doc


def read_desktop_config(data_dir):
    path = Path(data_dir) / 'claude_desktop_config.json'
    if not path.exists():
        return {}, None
    try:
        doc = json.loads(path.read_text())
    except ValueError:
        raise SystemExit('Claude desktop config is not valid JSON: %s' % path)
    if not isinstance(doc, dict):
        raise SystemExit('Claude desktop config is not a JSON object: %s' % path)
    return doc, path


def merge_entry(state, path):
    """Merge the four owned values; refuse conflicting hand-edited values.

    Returns (doc, changed, previous_owned) where previous_owned maps each
    owned key to its prior value (or None when absent) for the receipt.
    """
    doc = read_entry(path)
    want = desired_values(state)
    previous = {key: doc.get(key) for key in OWNED_KEYS}
    for key in OWNED_KEYS:
        if previous[key] is not None and previous[key] != want[key]:
            raise SystemExit(
                'Claude desktop setting %s is managed outside this installer; '
                'remove or correct it by hand, then re-run.' % key)
    changed = any(previous[key] != want[key] for key in OWNED_KEYS)
    doc.update(want)
    return doc, changed, previous


def write_json(path, doc):
    """Atomically replace a desktop JSON file with owner-only permissions."""
    path = Path(path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.router.tmp')
    try:
        atomic_write.replace_json(path, doc, tmp_name=tmp.name)
    except atomic_write.StaleTmp:
        # A crash between create and replace leaves the deterministic tmp
        # behind; the writer clears it once and retries, and only a lost
        # race to the retry lands here.
        raise SystemExit('stale desktop temp file: delete %s and re-run' % tmp)


def restore_entry(path, previous):
    """Restore owned keys to their pre-attach values; drop those added."""
    doc = read_entry(path)
    for key in OWNED_KEYS:
        old = previous.get(key)
        if old is None:
            doc.pop(key, None)
        else:
            doc[key] = old
    write_json(path, doc)


def _owned_snapshot(home, data_dir, state, receipts):
    """Only the same applied entry with matching router settings is owned."""
    existing = receipts.read_receipt(home).get('clients', {}).get(CLIENT_KEY, {})
    try:
        path = applied_entry_path(data_dir)
        if Path(existing['config_path']).resolve() != path.resolve():
            return None
        snapshot = receipts.parse_snapshot(existing['inserted_block'])
        if not all(key in snapshot for key in OWNED_KEYS + ('deploymentMode',)):
            return None
        current = read_entry(path)
        if any(current.get(key) != value for key, value in desired_values(state).items()):
            return None
        return snapshot
    except (OSError, ValueError, TypeError, KeyError, SystemExit):
        return None


def _install_switch_launcher(home, python):
    spec = _ilu.spec_from_file_location(
        'router_desktop_switch', Path(__file__).with_name('claude_desktop_switch.py'))
    switch = _ilu.module_from_spec(spec)
    spec.loader.exec_module(switch)
    try:
        switch.install_launcher(home, python)
    except switch.SwitchError as exc:
        print('Claude connected; ' + str(exc))
    except (OSError, switch.subprocess.SubprocessError):
        # Attachment still works if the optional native launcher cannot be built.
        print('Claude connected; Switch Claude could not be installed. Run setup again to retry.')


def attach(home, state, receipts, data_dir_override=None, env=None, *, python=None):
    """Attach the desktop gateway without touching first-party state.

    Merges only the four owned entry values and sets the third-party
    profile's deploymentMode to 3p on first attachment. An owned profile keeps
    its selected mode on later runs; conflicting effective overrides refuse
    with a redacted message. Records the attachment in the versioned
    receipt. Returns the applied entry path written.
    """
    if state.get('claude_mode', 'subscription') == 'none':
        raise SystemExit('claude_mode is none: re-run with --claude-mode subscription '
                         'to attach the Claude desktop gateway')
    data_dir = (Path(data_dir_override) if data_dir_override is not None
                else user_data_dir(env))
    # Refuse before writing anything: a mode conflict must leave both the
    # entry and the desktop config untouched.
    cfg, cfg_path = read_desktop_config(data_dir)
    previous_mode = cfg.get('deploymentMode')
    owned = _owned_snapshot(home, data_dir, state, receipts)
    if previous_mode not in (None, '3p') and not (previous_mode == '1p' and owned is not None):
        raise SystemExit(
            'Claude desktop deploymentMode is managed outside this installer; '
            'remove or correct it by hand, then re-run.')
    library = data_dir / 'configLibrary'
    if not library.exists() or not any(library.iterdir()):
        entry_id = str(uuid.uuid4())
        write_json(library / '_meta.json', {
            'appliedId': entry_id,
            'entries': [{'id': entry_id, 'name': 'SCG Router'}]})
    entry_path = applied_entry_path(data_dir)
    doc, _, previous = merge_entry(state, entry_path)
    write_json(entry_path, doc)
    if previous_mode is None:
        cfg['deploymentMode'] = '3p'
        write_json(cfg_path if cfg_path is not None
                   else data_dir / 'claude_desktop_config.json', cfg)
    if owned is not None:
        # Mode switching does not change attachment or the restore authority.
        previous = owned
        previous_mode = owned['deploymentMode']
    snapshot = dict(previous)
    snapshot['deploymentMode'] = previous_mode
    entry = {'config_path': str(entry_path),
             'inserted_block': json.dumps(snapshot, sort_keys=True),
             'claude_mode': state.get('claude_mode', 'subscription')}
    receipts.write_client_receipt(home, CLIENT_KEY, entry)
    if python is not None:
        _install_switch_launcher(home, python)
    return entry_path


def attach_current(args, receipts, write_state, *, python=None):
    """An explicit desktop attachment is independent of update availability."""
    if args.client == 'none':
        raise SystemExit('--desktop conflicts with --client none')
    if args.dry_run:
        print('would connect Claude desktop to the installed router')
        return 0
    home = Path(args.home).expanduser()
    try:
        state = json.loads((home / 'mixed-router-state.json').read_text())
    except (OSError, ValueError):
        raise SystemExit('Router settings are missing or invalid; run setup first')
    if args.claude_mode is not None and args.claude_mode != state.get('claude_mode'):
        state['claude_mode'] = args.claude_mode
        write_state(home, state)
    attach(home, state, receipts, python=python)
    print('Claude desktop connected; quit and reopen Claude, then choose Code and a model.')
    return 0


def detach(home, receipts, data_dir_override=None, env=None):
    """Restore desktop settings to pre-attach values; forget the attachment."""
    receipt = receipts.read_receipt(home)
    entry = receipt.get('clients', {}).get(CLIENT_KEY, {})
    if data_dir_override is None and not entry:
        return  # never attached: nothing to restore, nowhere to resolve
    if data_dir_override is not None:
        data_dir = Path(data_dir_override)
        path = applied_entry_path(data_dir)
    elif isinstance(entry, dict) and entry.get('config_path'):
        path = Path(entry['config_path'])
        data_dir = path.parents[1] if path.parent.name == 'configLibrary' else None
    else:
        data_dir = user_data_dir(env)
        path = applied_entry_path(data_dir)
    previous = receipts.parse_snapshot(entry.get('inserted_block', '{}'))
    restore_entry(path, previous)
    old_mode = previous.get('deploymentMode')
    if data_dir is not None:
        cfg, cfg_path = read_desktop_config(data_dir)
        if cfg_path is not None:
            if old_mode is None:
                cfg.pop('deploymentMode', None)
            else:
                cfg['deploymentMode'] = old_mode
            if not cfg and old_mode is None:
                # Attach created this file; detach removes it instead of
                # leaving an empty object the app never had.
                try:
                    cfg_path.unlink()
                except OSError:
                    write_json(cfg_path, cfg)
            else:
                write_json(cfg_path, cfg)
    receipts.drop_client(home, CLIENT_KEY)
