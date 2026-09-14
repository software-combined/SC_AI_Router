"""Read-only installer diagnostics, extracted from install.py.

`do_preflight` (Plan 058 Stage 1) and `do_status` (Plan 049) never write
and never lock. The only network use is the loopback `/health` probe;
nothing external is contacted. Runs on Python 3.9+ like the
installer. Loaded via the installer's file-based import pattern, never
`import packaging.diagnostics`, so installed bundles keep working without
a `packaging` distribution.

The installer injects its seams after load: `bind(find_python=...,
health=..., current_version=..., codex_config=...)`. Until bound,
module-level defaults read the shared service module the same way
install.py does.
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
_state = _svc.load(
    'router_state', Path(__file__).resolve().parents[1] / 'ai_router' / 'state.py')

find_python = _svc.find_python
health = _svc.health
current_version = _svc.current_version

_SEAM_NAMES = {'codex_config': '_codex_config'}


_winacl = _svc.load(
    'router_winacl', Path(__file__).resolve().parents[1] / 'ai_router' / 'winacl.py')
_updater = _svc.load(
    'router_updater', Path(__file__).resolve().parent / 'updater.py')

_MAX_FAILURES = _updater.MAX_VERSION_FAILURES


def _key_private(key_file):
    """Owner-only gate; single owner is winacl.owner_only (Plan 131)."""
    return _winacl.owner_only(key_file)


def _provider_defs():
    """The shared per-provider key walk (Plan 141), spec-loaded for 3.9."""
    module = _svc.load(
        'router_provider_keys', Path(__file__).resolve().parent / 'provider_keys.py')
    module.bind(_svc.load(
        'router_provider_defs',
        Path(__file__).resolve().parents[1] / 'ai_router' / 'provider_defs.py'))
    return module


def bind(**overrides):
    for name, value in overrides.items():
        if name not in ('find_python', 'health', 'current_version',
                        'codex_config'):
            raise AttributeError(f'unknown diagnostics seam: {name}')
        globals()[_SEAM_NAMES.get(name, name)] = value


def do_preflight(args):
    """Report missing install prerequisites together; change nothing.

    Plan 058 Stage 1: one check before anything is written, with a
    platform-correct remedy per missing item. Never creates the router
    home and never touches the network: the public feed needs no
    credential check here, and the bundle is verified when it is fetched.
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
    clients = getattr(args, 'clients', None)
    if clients is None:
        clients = 'none' if (args.client or 'codex') == 'none' else 'codex'
    if clients in ('codex', 'both') and shutil.which('codex') is None:
        missing.append('Codex CLI not found: install Codex first, or pass '
                       '--client none for a service-only install')
    if clients in ('claude', 'both') and shutil.which('claude') is None:
        missing.append('Claude Code CLI not found: install Claude Code first, '
                       'or pass --clients codex for a Codex-only install')
    if missing:
        for line in missing:
            print('preflight: ' + line)
        raise SystemExit(2)
    print('preflight: Python and client prerequisites present')
    return 0


def _status_document(home):
    """Read-only status facts for one router home.

    Plan 049: read-only diagnostics for the manage-router skill. Exit 0
    even when nothing is installed. Key validity is never probed here;
    `key_usable` means the local gates pass (env set, or a non-empty
    owner-only key file, or opencode_auth when no key file shadows it).
    Nothing secret is printed: no tokens, keys, URLs, or config bodies.
    """
    state = _state.read(_state.path(home))
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
    keys = _provider_defs()
    defs = keys.external_defs()
    per_provider = {defn.id: keys.key_state(home, state, os.environ, defn, _key_private)
                    for defn in defs}
    default = keys.default_id()
    present, usable = per_provider.get(default, (False, False))
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
    feed = _svc.channel_feed(home)
    doc = {'installed': installed, 'version': version if installed else None,
           'serving': serving, 'key_present': present, 'key_usable': usable,
           'feed': _svc.feed_source(feed),
           'channel': ((home / 'channel').read_text().strip()
                       if (home / 'channel').exists() else 'stable'),
           'providers': {pid: {'key_present': state_pair[0],
                               'key_usable': state_pair[1]}
                         for pid, state_pair in per_provider.items()},
           'setup_pending': bool(isinstance(state, dict)
                                and isinstance(state.get('setup'), dict)
                                and isinstance(state['setup'].get('expires'), (int, float))
                                and state['setup']['expires'] > time.time()),
           'clients': clients,
           'update': _update_summary(state)}
    return doc


def do_status(args):
    """Print the status document, including update recency and park counts."""
    home = Path(args.home).expanduser()
    doc = _status_document(home)
    if args.json:
        print(json.dumps(doc, indent=2, sort_keys=True))
    else:
        print('version: %s' % (doc['version'] or 'not installed'))
        print('service: %s' % ({True: 'serving', False: 'not serving',
                                None: 'unknown'}[doc['serving']]))
        print('key: %s' % ('usable' if doc['key_usable']
                           else 'present' if doc['key_present'] else 'missing'))
        print('feed: %s' % doc['feed'])
        print('channel: %s' % doc['channel'])
        print('clients: %s' % (', '.join(sorted(doc['clients'])) or 'none'))
        print('update: %s' % _update_line(doc['update']))
    return 0
def _update_summary(state):
    """Update recency, last error code and per-version failure counts."""
    doc = state if isinstance(state, dict) else {}
    failures = doc.get('update_failures')
    seen = ({str(k): v for k, v in failures.items()
             if isinstance(v, int) and v > 0}
            if isinstance(failures, dict) else {})

    def _text(key):
        value = doc.get(key)
        return value if isinstance(value, str) else None

    error = _text('last_error')
    return {'last_check_at': _text('last_check_at'),
            'last_applied_version': _text('last_applied_version'),
            # Only a code from the closed set is ever printed or bundled; a
            # hand-edited state file must not put free text on stdout.
            'last_error': error if error in _updater.ERROR_CODES else None,
            'failures': seen}


def _update_line(summary):
    parked = sorted(v for v, count in summary['failures'].items()
                    if count >= _MAX_FAILURES)
    parts = ['checked ' + summary['last_check_at'] if summary['last_check_at']
             else 'no scheduled pass recorded']
    if summary['last_applied_version']:
        parts.append('applied ' + summary['last_applied_version'])
    if summary['last_error']:
        parts.append('last error ' + summary['last_error'])
    if parked:
        parts.append('parked ' + ', '.join(
            '%s x%d' % (v, summary['failures'][v]) for v in parked))
    return '; '.join(parts)
