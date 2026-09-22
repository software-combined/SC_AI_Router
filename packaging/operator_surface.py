"""Operator surface: doctor, support bundle and rollback listing (Plan 147).

Every path here is read-only except the support bundle the operator
explicitly asks for; the doctor's only I/O is the loopback health probe and
one `ai_router.catalogue --check` run. Python 3.9-safe and loaded via the
installer's file-based import pattern, never `import packaging.operator`.
"""
import calendar
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import importlib.util
_spec = importlib.util.spec_from_file_location(
    'packaging.service', Path(__file__).resolve().parent / 'service.py')
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)

# The status contract stays in diagnostics.py: the doctor reports the same
# facts, and the installer binds diagnostics' seams (find_python, health,
# current_version) once for both modules.
_diag = _svc.load('router_diagnostics',
                  Path(__file__).resolve().parent / 'diagnostics.py')
_updater = _svc.load('router_updater', Path(__file__).resolve().parent / 'updater.py')
_atomic = _svc.load('router_atomic_write',
                    Path(__file__).resolve().parent / 'atomic_write.py')

OK, WARN, FAIL = 'OK', 'WARN', 'FAIL'
_MAX_FAILURES = _updater.MAX_VERSION_FAILURES
# The activation receipt's client names are a closed set; a hand-edited or
# corrupted key must never ride into the support bundle as free text.
_BUNDLE_CLIENTS = ('codex', 'claude', 'claude-desktop')
# The bundle may carry timestamps and versions, so their shape is checked
# before anything from the state document reaches it.
_STAMP = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z')
_VERSION = re.compile(r'[0-9A-Za-z._+-]{1,32}')
# Listing ids come from the registry or the loopback answer; anything else
# is not printable in a doctor row (Plan 148 review).
_ID_SHAPE = re.compile(r'[A-Za-z0-9._/~+-]{1,128}')

# Installer-owned subprocess seam; rebound via bind() after file-based load.
run = _svc.run


def _default_listing(state):
    """The live GET /v1/models answer over loopback, or None."""
    port, token = state.get('port'), state.get('token')
    if not isinstance(port, int) or not 0 < port < 65536:
        return None
    if not isinstance(token, str) or not token:
        return None
    # No proxy handling: the path token stays on the loopback.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})).open
    url = 'http://127.0.0.1:%d/%s/v1/models' % (port, token)
    try:
        with opener(url, timeout=5) as response:
            return json.loads(response.read(1 << 20).decode())
    except (OSError, ValueError):
        return None


listing = _default_listing


def bind(**overrides):
    for name, value in overrides.items():
        if name not in ('run', 'diag', 'listing'):
            raise AttributeError(f'unknown operator seam: {name}')
        globals()[name if name != 'diag' else '_diag'] = value


def _utc_stamp():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _age_hours(stamp):
    """Hours since one `%Y-%m-%dT%H:%M:%SZ` stamp, or None when unreadable."""
    try:
        parsed = time.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ')
    except (TypeError, ValueError):
        return None
    return max(0.0, (time.time() - calendar.timegm(parsed)) / 3600.0)


def _row(check, status, detail, fix=None):
    return {'check': check, 'status': status, 'detail': detail, 'fix': fix}


def _systemd_unit():
    """The Linux update unit the installer re-renders, or None elsewhere."""
    if not sys.platform.startswith('linux'):
        return None
    config = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    return config / 'systemd' / 'user' / 'codex-mixed-model-router-update.service'


def _scheduler_state(home):
    """('current'|'legacy'|'missing'|'unknown', detail) from the carriers.

    The launchd plist and the Windows task name the home launcher, so the
    launcher is the carrier to inspect on every platform; the systemd unit
    embeds the flag itself.
    """
    try:
        text = (home / 'update_launch.py').read_text()
    except OSError:
        return 'missing', 'update_launch.py is missing from the router home'
    # Judge the verb the launcher actually passes, not any mention of one:
    # a current launcher keeps --check-update only as its documented fallback
    # for a rolled-back pre-147 release.
    argv_line = next((line for line in text.splitlines()
                      if line.startswith('sys.argv')), '')
    if '--check-update' in argv_line:
        return 'legacy', 'update_launch.py still runs the read-only --check-update'
    if '--update' not in argv_line and 'verb' not in argv_line:
        return 'unknown', 'update_launch.py names no update verb'
    unit = _systemd_unit()
    if unit is not None:
        try:
            unit_text = unit.read_text()
        except OSError:
            return 'unknown', 'the systemd update unit is not readable'
        if '--check-update' in unit_text:
            return 'legacy', 'the systemd update unit still runs --check-update'
    return 'current', 'the scheduled command is current'


def _catalogue_counts(home):
    """Picker rows in the installed catalogue; 0 when missing or unreadable."""
    try:
        doc = json.loads((home / 'mixed-models.json').read_text())
    except (OSError, ValueError):
        return {'rows': 0}
    rows = doc.get('models') if isinstance(doc, dict) else None
    return {'rows': len(rows) if isinstance(rows, list) else 0}


def _catalogue_row(home, interpreter):
    """One read-only `ai_router.catalogue --check` run over the installed file."""
    path = home / 'mixed-models.json'
    counts = _catalogue_counts(home)
    if not path.is_file() or not counts['rows']:
        return _row('catalogue', WARN, 'the picker catalogue is missing or empty',
                    're-run the installer to seed it')
    if interpreter is None:
        return _row('catalogue', WARN,
                    '%d rows; check skipped without Python 3.14' % counts['rows'],
                    'install Python 3.14 and run --doctor again')
    release = _svc.current_release_dir(home)
    try:
        result = run([interpreter, '-m', 'ai_router.catalogue', '--check', str(path)],
                     cwd=str(release) if release is not None else None,
                     capture_output=True, text=True)
    except OSError:
        return _row('catalogue', WARN,
                    '%d rows; the check could not run' % counts['rows'],
                    're-run the installer to repair the release')
    if result.returncode != 0:
        lines = ((result.stdout or '') + (result.stderr or '')).strip().splitlines()
        detail = (lines[0] if lines else 'catalogue check failed')[:120]
        return _row('catalogue', WARN, '%d rows; %s' % (counts['rows'], detail),
                    're-run the installer to refresh the picker catalogue')
    return _row('catalogue', OK,
                '%d rows; ai_router.catalogue --check passed' % counts['rows'])


def _claude_drift(home, state):
    """('absent'|'nosnapshot'|'unknown'|'match'|'drift'|'switch', detail).

    The snapshot is the listing recorded at attach and the live answer comes
    from the running router, so drift shows as added or removed ids. A set
    tool-search hard switch fails the row rather than degrading quietly.
    """
    try:
        receipt = _diag._codex_config.read_receipt(home)
    except (OSError, ValueError):
        receipt = {}
    if not receipt and _diag._codex_config.receipt_path_for(home).exists():
        # read_receipt also degrades a shape-invalid document to {}, so the
        # file's existence is screened here to cover both cases.
        return 'unknown', 'the activation receipt is unreadable'
    entry = (receipt.get('clients', {}).get('claude')
             if isinstance(receipt, dict) else None)
    if not isinstance(entry, dict):
        return 'absent', 'Claude Code is not attached'
    switch = _diag._claude_config.switch_sources_at(entry.get('config_path'))
    if switch:
        return 'switch', 'tool search is off: %s sets %s' % (' and '.join(switch),
                                                             _diag._claude_config.DISABLE_KEY)
    snapshot = entry.get('listing')
    rows = snapshot.get('models') if isinstance(snapshot, dict) else None
    if not isinstance(rows, list):
        return 'nosnapshot', 'no listing snapshot recorded at attach'
    served = [row['id'] for row in rows if isinstance(row, dict)
              and isinstance(row.get('id'), str) and _ID_SHAPE.fullmatch(row['id'])]
    live_doc = listing(state) if isinstance(state, dict) else None
    if not isinstance(live_doc, dict) or not isinstance(live_doc.get('data'), list):
        return 'unknown', 'the router did not answer GET /v1/models'
    live = [row['id'] for row in live_doc['data'] if isinstance(row, dict)
            and isinstance(row.get('id'), str) and _ID_SHAPE.fullmatch(row['id'])]
    added = sorted(set(live) - set(served))
    removed = sorted(set(served) - set(live))
    if not added and not removed:
        return 'match', 'listing matches the attach snapshot (%d models)' % len(served)
    return 'drift', 'drift since attach: +%s -%s' % (
        ', '.join(added[:5]) or 'none', ', '.join(removed[:5]) or 'none')


def _doctor_rows(args, home, state):
    """Every doctor row, read-only and offline except the loopback health probe."""
    rows = []
    interpreter = _diag.find_python(args.python)
    rows.append(_row('runtime', OK if interpreter else FAIL,
                     'Python 3.14 available' if interpreter else 'no Python 3.14 found',
                     None if interpreter else 'install Python 3.14 or pass --python'))
    version = _diag.current_version(home)
    installed = version != '0.0.0'
    rows.append(_row('install', OK if installed else FAIL,
                     'release ' + version if installed
                     else 'no release under the router home',
                     None if installed else 'run the installer for this home'))
    serving = None
    if (installed and isinstance(state, dict)
            and isinstance(state.get('port'), int)
            and isinstance(state.get('token'), str)):
        try:
            body = _diag.health(state, timeout=5)
        except OSError:
            body = None
        serving = bool(body and body.get('status') == 'ok'
                       and body.get('version') == version)
    detail = ('serving ' + version if serving else
              'the service does not answer with the installed version'
              if installed else 'nothing installed to serve')
    rows.append(_row('service', OK if serving else FAIL, detail,
                     None if serving else
                     'run the installer again, then read logs/update.log'))
    keys = _diag._provider_defs()
    per_provider = {defn.id: keys.key_state(home, state, os.environ, defn,
                                            _diag._key_private)
                    for defn in keys.external_defs()}
    default = keys.default_id()
    for provider_id in sorted(per_provider):
        present, usable = per_provider[provider_id]
        if usable:
            row_status, detail, fix = OK, 'owner-only key usable', None
        else:
            row_status = FAIL if provider_id == default else WARN
            detail = ('key present but not owner-only readable' if present
                      else 'no key found')
            fix = 'open the key window: run the installer with --setup'
        rows.append(_row('key:' + provider_id, row_status, detail, fix))
    rows.append(_catalogue_row(home, interpreter))
    claude_state, claude_detail = _claude_drift(home, state)
    claude_fix = {'nosnapshot': 'run the installer with --setup to record the snapshot',
                  'switch': 'remove the variable, then restart Claude Code'}.get(claude_state)
    if claude_fix is None and claude_state not in ('match', 'absent'):
        claude_fix = 'check --status; restart Claude Code after a listing change'
    rows.append(_row('claude', FAIL if claude_state == 'switch'
                     else WARN if claude_fix else OK, claude_detail, claude_fix))
    sched_status, sched_detail = _scheduler_state(home)
    # A missing or unreadable carrier means automatic updates are not proven
    # to run, so the doctor fails rather than warns.
    rows.append(_row('scheduler',
                     OK if sched_status == 'current' else FAIL,
                     sched_detail,
                     None if sched_status == 'current' else
                     're-run the installer to re-render the scheduled command'))
    summary = _diag._update_summary(state)
    parked = sorted(v for v, count in summary['failures'].items()
                    if count >= _MAX_FAILURES)
    if summary['last_error']:
        rows.append(_row('update', WARN, 'last pass failed: ' + summary['last_error'],
                         'read logs/update.log; the updater parks a version '
                         'after three failed attempts'))
    elif parked:
        rows.append(_row('update', WARN,
                         'parked: ' + ', '.join(
                             '%s x%d' % (v, summary['failures'][v]) for v in parked),
                         'run the installer by hand to retry the parked version'))
    elif summary['last_check_at']:
        age = _age_hours(summary['last_check_at'])
        rows.append(_row('update', WARN if age is None or age > 12 else OK,
                         'last check ' + summary['last_check_at']
                         + ('' if age is None else ' (%.0f h ago)' % age),
                         'the timer runs every 4 hours; re-run the installer '
                         'if it is missing'))
    else:
        rows.append(_row('update', OK, 'no scheduled pass recorded yet'))
    return rows


def do_doctor(args):
    """Read-only health report: one row per component, exit 1 on any FAIL."""
    home = Path(args.home).expanduser()
    state = _diag._state.read(_diag._state.path(home))
    rows = _doctor_rows(args, home, state)
    failed = [row for row in rows if row['status'] == FAIL]
    if args.json:
        print(json.dumps({'ok': not failed, 'rows': rows},
                         indent=2, sort_keys=True))
    else:
        print('doctor: %d checks, %d FAIL' % (len(rows), len(failed)))
        for row in rows:
            print('%-18s %-4s %s' % (row['check'], row['status'], row['detail']))
            if row['status'] != OK and row['fix']:
                print('%-18s      Fix: %s' % ('', row['fix']))
    return 1 if failed else 0


def _support_document(doc, now=None):
    """Allowlisted bundle: booleans, enums, versions, counts and timestamps.

    Built by selection from the status document, never by copying it: a
    config path, a feed URL, a key or a log line has no field to travel in.
    The stored update error is mapped into the closed code set first.
    """
    def _mapping(value):
        return value if isinstance(value, dict) else {}

    update = _mapping(doc.get('update'))
    error = update.get('last_error')
    providers = _mapping(doc.get('providers'))
    clients = _mapping(doc.get('clients'))
    catalogue = _mapping(doc.get('catalogue'))

    def _stamp(value):
        return value if isinstance(value, str) and _STAMP.fullmatch(value) else None

    def _version(value):
        return value if isinstance(value, str) and _VERSION.fullmatch(value) else None

    def _enum(value, allowed):
        return value if value in allowed else None

    return {
        'schema': 1,
        'generated_at': now or _utc_stamp(),
        'platform': sys.platform,
        'install': {
            'installed': bool(doc.get('installed')),
            'version': _version(doc.get('version')),
            'channel': _enum(doc.get('channel'), ('stable', 'beta'))},
        'service': {'serving': (doc.get('serving')
                                if isinstance(doc.get('serving'), bool) else None)},
        'keys': {'present': bool(doc.get('key_present')),
                 'usable': bool(doc.get('key_usable'))},
        'providers': {str(pid): {'present': bool(_mapping(pair).get('key_present')),
                                 'usable': bool(_mapping(pair).get('key_usable'))}
                      for pid, pair in providers.items() if isinstance(pid, str)},
        'clients': {str(name): bool(_mapping(entry).get('attached'))
                    for name, entry in clients.items()
                    if name in _BUNDLE_CLIENTS},
        'update': {
            'last_check_at': _stamp(update.get('last_check_at')),
            'last_applied_version': _version(update.get('last_applied_version')),
            'last_error': error if error in _updater.ERROR_CODES else None,
            'failed_versions': len(_mapping(update.get('failures')))},
        'scheduler': _enum(doc.get('scheduler'),
                           ('current', 'legacy', 'missing', 'unknown')) or 'unknown',
        'catalogue': {'rows': (catalogue.get('rows')
                               if isinstance(catalogue.get('rows'), int) else 0)},
    }


def do_support(args):
    """Write the redacted support bundle and print only the path it wrote."""
    home = Path(args.home).expanduser()
    if not home.is_dir():
        raise SystemExit('router home not found: %s' % home)
    doc = _diag._status_document(home)
    doc['scheduler'] = _scheduler_state(home)[0]
    doc['catalogue'] = _catalogue_counts(home)
    payload = json.dumps(_support_document(doc), indent=2, sort_keys=True)
    logs = home / 'logs'
    try:
        logs.mkdir(exist_ok=True)
    except OSError:
        raise SystemExit('could not create the logs directory for the bundle')
    path = logs / ('support-%s.json' % time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))
    # Shared atomic writer (Plan 131): one owner for whole-file writes.
    _atomic.replace_text(path, payload + '\n', mode=0o600)
    print(str(path))
    return 0


def _release_key(name):
    try:
        return [int(part) for part in name.split('.')]
    except ValueError:
        return None


def do_rollback_list(args):
    """Read-only: list installed releases and the one `current` points at."""
    home = Path(args.home).expanduser()
    releases_dir = home / 'releases'
    releases = []
    if releases_dir.is_dir():
        releases = sorted(
            (p.name for p in releases_dir.iterdir()
             if p.is_dir() and not p.name.endswith('.partial')),
            key=lambda name: (_release_key(name) or [], name))
    current = _diag.current_version(home)
    if args.json:
        print(json.dumps({'current': current, 'releases': releases},
                         sort_keys=True))
    elif not releases:
        print('no releases installed under %s' % home)
    else:
        print('current: %s' % current)
        for name in releases:
            print('%s%s' % (name, ' (current)' if name == current else ''))
    return 0
