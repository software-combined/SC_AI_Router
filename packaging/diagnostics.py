"""Read-only installer diagnostics, extracted from install.py.

`do_preflight` (Plan 058 Stage 1) and `do_status` (Plan 049) never write
and never lock. The only network use is the loopback `/health` probe;
nothing external is contacted. Runs on Python 3.9+ like the
installer. Loaded via the installer's file-based import pattern, never
`import packaging.diagnostics`, so installed bundles keep working without
a `packaging` distribution.

The installer injects its seams after load: `bind(find_python=...,
health=..., current_version=..., feed_url=..., route_prefix=...,
codex_config=...)`. Until bound, module-level defaults read the shared
service module the same way install.py does.
"""
import importlib.util
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Bootstrap loader (Plan 123 exception): service must be spec-loaded before
# service.load() exists, so this single bootstrap copy stays.
_spec = importlib.util.spec_from_file_location(
    'packaging.service',
    Path(__file__).resolve().parent / 'service.py')
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)
_codex_config = _svc.load(
    'router_codex_config', Path(__file__).resolve().parent / 'codex_config.py')
# Same injection as install.py: this copy is read-only by contract today, but a
# future write path must not hit the un-injected guard (Plan 094).
_codex_config._atomic_write = _svc.load(
    'router_atomic_write', Path(__file__).resolve().parent / 'atomic_write.py')

find_python = _svc.find_python
health = _svc.health
current_version = _svc.current_version
FEED_URL = _svc.FEED_URL
github_route_prefix = _svc.RELEASES_PREFIX

_SEAM_NAMES = {'feed_url': 'FEED_URL', 'route_prefix': 'github_route_prefix',
               'codex_config': '_codex_config'}


_winacl = _svc.load(
    'router_winacl', Path(__file__).resolve().parents[1] / 'ai_router' / 'winacl.py')


def _key_private(key_file):
    """Owner-only gate mirroring credentials.openrouter_key() precedence.

    POSIX checks mode bits; Windows defers to the icacls owner-only check
    (st_mode carries no ACL meaning on NTFS). A failed Windows check means
    not usable, never an exception: this is read-only diagnostics.
    """
    if os.name == 'nt':
        try:
            _winacl.check(key_file)
            return True
        except SystemExit:
            return False
    try:
        return not (key_file.stat().st_mode & 0o077)
    except OSError:
        return False


def bind(**overrides):
    for name, value in overrides.items():
        if name not in ('find_python', 'health', 'current_version',
                        'feed_url', 'route_prefix', 'codex_config'):
            raise AttributeError(f'unknown diagnostics seam: {name}')
        globals()[_SEAM_NAMES.get(name, name)] = value


def do_preflight(args):
    """Report missing install prerequisites together; change nothing.

    Plan 058 Stage 1: one check before anything is written, with a
    platform-correct remedy per missing item. Never creates the router
    home, never touches the network: the feed check only reads which
    route is selected (the transitional GitHub route needs the `gh`
    binary; an explicit `--feed` needs nothing beyond this machine).
    Sign-in itself is verified when the feed is actually fetched.
    """
    missing = []
    if find_python(args.python) is None:
        if args.python:
            missing.append('no Python 3.14 at ' + args.python + ': pass a '
                           'verified --python interpreter path')
        else:
            missing.append('no Python 3.14 found: the managed install provisions '
                           'the pinned private runtime; otherwise install '
                           'Python 3.14 first')
    home = Path(args.home).expanduser()
    feed = args.feed or _svc.channel_feed(home)
    # Same route decision as fetch(): only the pre-migration GitHub route
    # needs the `gh` binary; the token-gated feed needs nothing beyond this
    # machine. Prefix test only: github_asset() itself would spawn `gh`.
    if feed.startswith(github_route_prefix):
        if _svc.feed_token(home) is None and _svc.gh_binary() is None:
            missing.append('GitHub CLI (gh) binary not found: install gh, sign it in '
                           'with `gh auth login` as this user, or re-run the '
                           'bootstrap from the Technology library to migrate '
                           'this host to the token-gated feed')
    if (args.client or 'codex') == 'codex' and shutil.which('codex') is None:
        missing.append('Codex CLI not found: install Codex first, or pass '
                       '--client none for a service-only install')
    if missing:
        for line in missing:
            print('preflight: ' + line)
        raise SystemExit(2)
    print('preflight: Python, feed-route, and client prerequisites present')
    return 0


def do_status(args):
    """Print installed version, service state, clients, and key booleans.

    Plan 049: read-only diagnostics for the manage-router skill. Exit 0
    even when nothing is installed. Key validity is never probed here;
    `key_usable` means the local gates pass (env set, or a non-empty
    owner-only key file, or opencode_auth when no key file shadows it).
    Nothing secret is printed: no tokens, keys, URLs, or config bodies.
    """
    home = Path(args.home).expanduser()
    try:
        state = json.loads((home / 'mixed-router-state.json').read_text())
    except (OSError, ValueError):
        state = None
    version = current_version(home)
    installed = version != '0.0.0'
    serving = None
    if (installed and isinstance(state, dict) and isinstance(state.get('port'), int)
            and isinstance(state.get('token'), str)):
        try:
            body = health(state, timeout=5)
        except OSError:
            body = None
        serving = bool(body and body.get('status') == 'ok'
                       and body.get('version') == version)
    key_file = home / 'openrouter.key'
    # Mirror credentials.openrouter_key() precedence without storing secrets:
    # env wins; else an existing key file decides by non-blank content and
    # owner-only mode; opencode_auth counts only when no key file shadows
    # it and it actually carries an openrouter api key.
    try:
        key_exists = key_file.is_file()
    except OSError:
        key_exists = False
    try:
        key_text = key_file.read_text() if key_exists else ''
    except OSError:
        key_text = ''
    key_private = _key_private(key_file) if key_exists else False
    auth_path = (state or {}).get('opencode_auth') if isinstance(state, dict) else None
    auth_key = ''
    if isinstance(auth_path, str) and auth_path:
        try:
            auth_doc = json.loads(Path(auth_path).read_text())
            auth_entry = auth_doc.get('openrouter') if isinstance(auth_doc, dict) else None
            if isinstance(auth_entry, dict) and auth_entry.get('type') == 'api':
                auth_key = str(auth_entry.get('key') or '').strip()
        except (OSError, ValueError, AttributeError):
            auth_key = ''
    present = bool(os.environ.get('OPENROUTER_API_KEY', '').strip()
                   or key_text.strip() or auth_key)
    usable = bool(os.environ.get('OPENROUTER_API_KEY', '').strip()
                  or (key_text.strip() and key_private) or auth_key)
    def _client(entry):
        if not isinstance(entry, dict):
            return {'attached': False, 'config_path': ''}
        try:
            attached = Path(entry['config_path']).exists()
        except (KeyError, TypeError, OSError):
            attached = False
        return {'attached': attached,
                'config_path': str(entry.get('config_path', ''))}
    try:
        receipt_clients = _codex_config.read_receipt(home).get('clients', {})
    except (OSError, ValueError):
        receipt_clients = {}
    if not isinstance(receipt_clients, dict):
        receipt_clients = {}
    clients = {name: _client(entry) for name, entry in receipt_clients.items()}
    doc = {'installed': installed, 'version': version if installed else None,
           'serving': serving, 'key_present': present, 'key_usable': usable,
           'setup_pending': bool(isinstance(state, dict)
                                and isinstance(state.get('setup'), dict)
                                and isinstance(state['setup'].get('expires'), (int, float))
                                and state['setup']['expires'] > time.time()),
           'clients': clients}
    if args.json:
        print(json.dumps(doc, indent=2, sort_keys=True))
    else:
        print('version: %s' % (doc['version'] or 'not installed'))
        print('service: %s' % ({True: 'serving', False: 'not serving', None: 'unknown'}[serving]))
        print('key: %s' % ('usable' if usable else 'present' if present else 'missing'))
        print('clients: %s' % (', '.join(sorted(clients)) or 'none'))
    return 0
