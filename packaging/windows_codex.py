"""Fresh Store identity and verified lifecycle policy for Windows Codex."""
import contextlib
import importlib.util
import ntpath
import time
import xml.etree.ElementTree as ET
from pathlib import Path

_spec = importlib.util.spec_from_file_location('router_windows_native',
    Path(__file__).with_name('windows_native.py'))
_native = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_native)
FAMILY = 'OpenAI.Codex_2p2nqsd0c76g0'
_bindings = None


def bindings():
    global _bindings
    if _bindings is None:
        _bindings = _native.Native()
    return _bindings  # Only API bindings are reused; never package identity or process facts.


def norm(value):
    return str(value).replace('\\', '/').casefold()


def identity(*, api=None):
    api = api or bindings()
    packages = api.packages(FAMILY)
    if len(packages) != 1:
        raise _native.NativeError('app_identity', 'app_unavailable')
    try:
        root = Path(api.package_path(packages[0])).resolve()
        applications = ET.fromstring((root / 'AppxManifest.xml').read_bytes()).findall(
            './{*}Applications/{*}Application')
        candidates = []
        for app in applications:
            relative = app.get('Executable', '').replace('\\', '/')
            if (not relative or ntpath.isabs(relative) or '..' in Path(relative).parts
                    or ntpath.basename(relative).casefold() not in ('chatgpt.exe', 'codex.exe')):
                continue
            exe = (root / relative).resolve()
            if root not in exe.parents:
                continue
            with exe.open('rb') as source:
                if source.read(2) != b'MZ':
                    continue
            aumid = FAMILY + '!' + app.get('Id', '')
            _native.app_uri(aumid)
            candidates.append(dict(root=str(root), exe=str(exe), app=aumid,
                family=FAMILY, package=packages[0], user=api.user(), session=api.session()))
        if len(candidates) == 1:
            return candidates[0]
    except _native.NativeError:
        raise
    except (OSError, ValueError, ET.ParseError):
        pass
    raise _native.NativeError('app_identity', 'invalid_identity')


def validate(expected, *, api=None):
    api = api or bindings()
    if (api.packages(FAMILY) != [expected['package']]
            or norm(api.package_path(expected['package'])) != norm(expected['root'])
            or api.user() != expected['user'] or api.session() != expected['session']):
        raise _native.NativeError('app_identity', 'package_changed')


def snapshot(identity, tracked, names, *, api=None, retention=None, terminate=False):
    """Query owners only for package trees, named writers and tracked processes."""
    api = api or bindings()
    with contextlib.ExitStack() as local:
        scope, pinned = retention if retention is not None else (local, {})
        return _snapshot(identity, tracked, names, api, scope, pinned, terminate)


def exited(api, handle):
    """Observe a failed first query's process exit without retrying identity reads."""
    deadline = time.monotonic() + 0.5
    while api.alive(handle):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.05, remaining))
    return True


def _snapshot(identity, tracked, names, api, scope, pinned, terminate):
    entries, facts, errors = api.entries(), {}, {}
    known = set(pinned)
    names = {name.casefold() for name in names} | {ntpath.basename(identity['exe']).casefold()}
    wanted = set(tracked)
    root = norm(identity['root']).rstrip('/') + '/'
    for row in entries:
        pid = row['pid']
        if row['name'].casefold() in names:
            wanted.add(pid)
        try:
            if pid not in pinned:
                if api.session(pid) != identity['session']:
                    if pid in tracked:
                        raise _native.NativeError('process_snapshot', 'identity_changed')
                    wanted.discard(pid)
                    continue
                handle = scope.enter_context(api.opened(pid, terminate=terminate))
                pinned[pid] = dict(handle=handle)
                try:
                    pinned[pid]['facts'] = api.facts(handle, pid)
                except OSError as error:
                    pinned[pid]['error'] = error
            pin = pinned[pid]
            if not api.alive(pin['handle']):
                continue
            if 'error' in pin:
                raise pin['error']
            fact = pin['facts']
            if fact['session'] != identity['session']:
                wanted.discard(pid)
                continue
            facts[pid] = dict(fact, parent=row['parent'])
            if fact['family'] == identity['family'] or norm(fact['exe']).startswith(root):
                wanted.add(pid)
        except OSError as error:
            errors[pid] = error  # Unrelated protected processes do not require owner access.
    while True:
        children = {r['pid'] for r in entries if r['parent'] in wanted} - wanted
        if not children:
            break
        for row in entries:
            if row['pid'] in children and row['pid'] in facts:
                parent = facts.get(row['parent']) or tracked.get(row['parent'])
                if parent is None or facts[row['pid']]['born'] < parent['born']:
                    raise _native.NativeError('process_snapshot', 'identity_changed')
        wanted.update(children)
    # Holding each process object prevents PID reuse while checking its parent metadata.
    fresh = {row['pid']: row for row in api.entries()}
    original = {row['pid']: row for row in entries}
    rows = {}
    for pid in wanted:
        try:
            pin = pinned.get(pid)
            if pin and not api.alive(pin['handle']):
                continue
            if pin and pid not in known and pid in original and fresh.get(pid) != original[pid]:
                raise _native.NativeError('process_snapshot', 'identity_changed')
            if pid in errors:
                if not pin and pid not in fresh:
                    continue
                raise errors[pid]
            if not pin or pin.get('facts', {}).get('session') != identity['session']:
                if pid in tracked and pid in fresh:
                    raise _native.NativeError('process_snapshot', 'identity_changed')
                continue  # A different desktop session cannot write this profile.
            if 'user' not in pin:
                pin['user'] = api.user(pin['handle'])
            current = dict(pin['facts'], user=pin['user'])
            if pid in tracked and any(current[k] != tracked[pid][k] for k in ('born', 'user')):
                raise _native.NativeError('process_snapshot', 'identity_changed')
            if current['user'] == identity['user']:
                rows[pid] = dict(current, parent=original.get(pid, tracked.get(pid, {})).get('parent', 0))
        except OSError:
            if pin:
                if not exited(api, pin['handle']):
                    raise
            elif pid in {r['pid'] for r in api.entries()}:
                raise
    return rows


def act(pin, row, api, *, terminate=False, windows=(), record=None):
    record = record if record is not None else {}
    handle = pin['handle']
    if not api.alive(handle):
        return
    if terminate:
        record['shutdown_started'] = True
        try:
            api.end(handle)  # Same verified handle; never reopen or terminate by PID.
        except OSError:
            if not exited(api, handle):
                raise
    else:
        for window, pid in windows:
            if pid == row['pid']:
                record['shutdown_started'] = True
                api.close_window(window, pid)


def stop(expected, select, *, api=None, allow_terminate=False, record=None):
    api, record = api or bindings(), record if record is not None else {}
    record['shutdown_started'] = False
    try:
        with contextlib.ExitStack() as retained:
            return _stop(expected, select, api, allow_terminate, record, (retained, {}))
    except OSError as error:
        if record.get('shutdown_started'):
            try:
                open_app(identity(api=api), api=api)
                record['recovery_open'] = True
            except OSError:
                record['recovery_open'] = False
                error.reopen_failed = True
        raise


def _stop(identity, select, api, allow_terminate, record, retention):
    seen = {}
    validate(identity, api=api)
    started = time.monotonic()
    def scan():
        before = time.monotonic()
        rows = snapshot(identity, seen, (), api=api, retention=retention, terminate=allow_terminate)
        elapsed = round((time.monotonic() - before) * 1000, 1)
        record['scan_count'] = record.get('scan_count', 0) + 1
        record['scan_max_ms'] = max(record.get('scan_max_ms', 0), elapsed)
        record['scan_total_ms'] = round(record.get('scan_total_ms', 0) + elapsed, 1)
        select(rows, seen)
        return {pid: rows[pid] for pid in seen.keys() & rows.keys()}
    rows = scan()
    windows = api.windows()
    pinned = retention[1]
    for row in rows.values():
        if norm(row['exe']) == norm(identity['exe']):
            act(pinned[row['pid']], row, api, windows=windows, record=record)
    grace, deadline = started + 5, started + 15
    ended = set()
    root_wait = grace
    while rows:
        now = time.monotonic()
        if now >= grace:
            if not allow_terminate:
                return False
            roots = {pid for pid, row in rows.items() if norm(row['exe']) == norm(identity['exe'])
                     and row['parent'] not in rows}
            targets = roots - ended
            if targets:
                root_wait = now + 0.5
            elif now >= root_wait:
                targets = rows.keys() - ended
            for pid in targets:
                act(pinned[pid], rows[pid], api, terminate=True, record=record)
                ended.add(pid)
        if now >= deadline:
            raise _native.NativeError('request_stop', 'still_running')
        time.sleep(min(0.1, deadline - now))
        rows = scan()
    record['quit_ms'] = round((time.monotonic() - started) * 1000, 1)
    validate(identity, api=api)
    return True


def open_app(identity, *, api=None):
    api = api or bindings()
    validate(identity, api=api)
    api.activate(identity['app'])
    deadline = time.monotonic() + 30
    while True:
        visible = {pid for _, pid in api.windows(visible=True)}
        rows = snapshot(identity, {}, (), api=api)
        if any(pid in visible and row['family'] == identity['family']
               and norm(row['exe']) == norm(identity['exe']) for pid, row in rows.items()):
            validate(identity, api=api)
            return
        if time.monotonic() >= deadline:
            raise _native.NativeError('app_open', 'window_unavailable')
        time.sleep(0.1)
