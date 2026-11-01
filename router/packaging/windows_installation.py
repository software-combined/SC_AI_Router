"""One required Windows installation: verified completion or explicit recovery."""
import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_payload import load

_tasks = load('service').load('router_installation_tasks',
    Path(__file__).parent / 'platforms/windows_tasks.py')
TASKS = _tasks.NAMES

JOURNAL = 'installation-pending.json'
RECEIPT = 'installed-cohort.json'
LAUNCHERS = ('router_launch.py', 'update_launch.py', 'express_launch.py',
             'task_launch.py', 'native_launch.py', 'desktop_launch.py')
FILES = ('current', 'control-version', 'setup-current', *LAUNCHERS,
         'desktop-delivery.json', '.router-removed', RECEIPT)


def prepare(home, source, latest, feed, fetch=None, *, resources=None):
    """Retain every required payload before cancellation or activation can change anything."""
    supplied = os.environ.get('SCG_NATIVE_RESOURCES')
    if resources is None and supplied:
        try:
            doc = load('native_payload').metadata(supplied)
            if doc['version'] == latest['version'] and doc['sha256'] == latest['sha256']:
                resources = supplied
        except (OSError, ValueError, KeyError):
            pass
    native = load('native_resources')
    resources = native.stage(home, latest, feed, fetch, resources=resources)
    installer = load('native_controller').install(home, source, activate=False, allow_rollback=True)
    if installer.parent.parent.name != latest['version']:
        raise ValueError('Required controller version did not match')
    if any(not (installer.parent / ('update_launch.py' if name == 'express_launch.py' else name)).is_file()
           for name in LAUNCHERS):
        raise ValueError('Required Windows launchers are unavailable')
    row = native.descriptor(latest)
    return dict(source=installer.parent.parent, resources=resources, version=latest['version'],
                resource_sha256=row['sha256'] if row else None, started=False)


def activate(home, prepared, backend):
    try:
        begin(home, prepared['version'], backend)
    except OSError:
        defer(home, prepared['version'])
    except SystemExit as error:
        if isinstance(error.__context__, (OSError, subprocess.SubprocessError)):
            defer(home, prepared['version'])
        raise
    prepared['started'] = True
    source = Path(prepared['source'])
    load('native_controller').install(home, source, allow_rollback=True)
    service = load('service')
    service.install_launcher(home, source)
    service.install_task_launcher(home, source)
    for name in ('native_launch.py', 'desktop_launch.py'):
        service._install_home_file(home, source, name)
    native = load('native_payload').metadata(prepared['resources'])
    return str(Path(prepared['resources']) / 'runtime' / native['runtime_exec'])


def defer(home, version, code='update_failed'):
    """An untouched or fully restored installation needs a retry, not repair."""
    service = load('service')
    if version not in service.update_failures(home):
        service.record_update_failure(home, version)  # Express defers to the regular cadence.
    state = service._state.read(service._state.path(home))
    load('update_status').record(state, error=code)
    service._write_state(home, state)
    load('update_reconcile').log(home, 'installation', 'deferred', version=version, status=0)
    print('deferred: required Windows files could not finish; updates will retry automatically')
    raise SystemExit(0)


def controls(home, latest, feed, fetch=None):
    """Unchanged checks repair required controls through the same transaction."""
    if ready(home):
        return True
    service = load('service')
    platforms = service.load('router_controls_platforms', Path(__file__).parent / 'platforms/__init__.py')
    backend = platforms.select('win32', service, service.run)
    prepared = None
    try:
        source = service.current_release_dir(home)
        prepared = prepare(home, source, latest, feed, fetch)
        python = activate(home, prepared, backend)
        backend.install(python, home, backend._state(home), source, None)
        complete(home, prepared, backend)
        return True
    except (Exception, SystemExit):
        if prepared and prepared.get('started') and restore(home, backend) != 'restored':
            raise
        defer(home, latest['version'])


def _read(home, name):
    path = home / name
    if path.is_symlink():
        if name != 'current':
            raise ValueError('Unsafe installation entry')
        return (load('service').current_version(home) + '\n').encode()
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _encode(value):
    return base64.b64encode(value).decode('ascii') if value is not None else None


def _decode(value):
    if value is not None and not isinstance(value, str):
        raise ValueError('Invalid installation recovery data')
    return base64.b64decode(value, validate=True) if value is not None else None


def _hash(value):
    return hashlib.sha256(value).hexdigest() if value is not None else None


def _journal(home):
    before = (home / JOURNAL).read_bytes()
    doc = json.loads(before)
    if (not isinstance(doc, dict) or doc.get('format') != 1
            or not load('update_status').version(doc.get('target'))
            or not isinstance(doc.get('files'), dict) or set(doc['files']) != set(FILES)
            or type(doc.get('restored')) is not bool):
        raise ValueError('Invalid installation recovery record')
    for value in doc['files'].values():
        _decode(value)
    return doc, before


def _attention(home, failed):
    service = load('service')
    state = service._state.read(service._state.path(home))
    if isinstance(state, dict):
        if failed:
            state['installation_repair_required'] = True
        else:
            state.setdefault('component_repairs', {}).update({name: 'ready' for name in
                ('controller', 'updater_launcher', 'scheduler', 'controls', 'controls_launchers')})
            load('update_status').record(state, error='', repaired=True)
        service._write_state(home, state)


def pending(home):
    return (Path(home) / JOURNAL).exists()


def reconcile(home, service):
    """Outer regular/Express maintenance retries only a pending journal, without waiting."""
    home = Path(home)
    if sys.platform != 'win32' or not pending(home) or (home / '.router-removed').exists():
        return 'inactive'
    with service.install_lock(home) as held:
        if not held:
            return 'deferred'
        platforms = service.load('router_installation_platforms', Path(__file__).parent / 'platforms/__init__.py')
        return restore(home, platforms.select('win32', service, service.run))


def begin(home, version, backend):
    """Caller holds install.lock; all candidate payloads are already retained."""
    home = Path(home)
    if pending(home):
        doc, before = _journal(home)
        if not doc['restored']:
            raise ValueError('Installation restoration is pending')
        # A restored but historically mixed baseline may advance to a coherent candidate.
        for name in FILES:
            if _read(home, name) != _decode(doc['files'][name]):
                raise ValueError('Restored installation changed')
        doc['tasks'] = backend.snapshot_cohort(home)
        doc['shortcuts'] = load('native_shortcuts').snapshot(home)
        doc.update(target=version, restored=False)
        load('atomic_write').replace_json(home / JOURNAL, doc, expected=before)
        return
    if not load('update_status').version(version):
        raise ValueError('Invalid installation identity')
    previous = load('service').current_version(home)
    tasks = backend.snapshot_cohort(home)
    shortcuts = load('native_shortcuts').snapshot(home)
    load('atomic_write').replace_json(home / JOURNAL, dict(format=1,
        target=version, previous=previous, files={name: _encode(_read(home, name)) for name in FILES},
        tasks=tasks, shortcuts=shortcuts, restored=False))


def parts(home):
    """Fresh versions and launchers; never discover or persist Codex package paths."""
    home, service = Path(home), load('service')
    version = service.current_version(home)
    source = service.current_release_dir(home)
    installer = load('native_controller').installer(home)
    resources = load('native_resources').current(home)
    native = load('native_payload').metadata(resources)
    if (not load('update_status').version(version) or installer is None
            or installer.parent.parent.name != version or native['version'] != version
            or (source / 'packaging/VERSION').read_text().strip() != version
            or (installer.parent / 'VERSION').read_text().strip() != version):
        raise ValueError('Installation versions do not match')
    control = installer.parent.parent
    hashes = {}
    for name in LAUNCHERS:
        origin = 'update_launch.py' if name == 'express_launch.py' else name
        expected = (control / 'packaging' / origin).read_bytes()
        actual = _read(home, name)
        if actual is None or actual.replace(b'\r\n', b'\n') != expected.replace(b'\r\n', b'\n'):
            raise ValueError('Installation launcher does not match')
        hashes[name] = _hash(actual)
    shortcuts = load('native_shortcuts').fingerprint(home)
    if shortcuts.get('version') != version:
        raise ValueError('Windows entry-point version did not match')
    return dict(format=1, version=version, bundle_sha256=native['sha256'], launchers=hashes,
                shortcuts=shortcuts), resources, native


def ready(home):
    home = Path(home)
    try:
        if pending(home) or (home / '.router-removed').exists():
            return False
        receipt = json.loads((home / RECEIPT).read_text(encoding='utf-8'))
        actual, _, _ = parts(home)
        state = load('service')._state.read(load('service')._state.path(home))
        components = load('update_status').components(state)
        return receipt == actual and all(components.get(name) == 'ready' for name in
            ('controller', 'updater_launcher', 'scheduler', 'controls', 'controls_launchers'))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def complete(home, prepared, backend):
    home = Path(home)
    doc, before = _journal(home)
    resources = Path(prepared['resources'])
    native = load('native_payload').metadata(resources)
    python = resources / 'runtime' / native['runtime_exec']
    if doc['target'] != native['version'] or load('service').current_version(home) != doc['target']:
        raise ValueError('Installation target did not match')
    if not backend.ensure_serving(home, backend._state(home), doc['target']):
        raise ValueError('Installation health did not match')
    load('native_shortcuts').install(home, resources, python)
    load('native_shortcuts').verify(home, resources, python)
    backend.preserve_cohort(home, doc['tasks'], str(python))
    if not backend.runtime_matches(str(python), home):
        raise ValueError('Installation tasks did not match')
    load('atomic_write').replace_json(home / 'desktop-delivery.json',
        dict(status='ready', version=native['version'], sha256=prepared.get('resource_sha256')))
    actual, _, _ = parts(home)
    load('atomic_write').replace_json(home / RECEIPT, actual)
    if not ready_after_commit(home, actual):
        raise ValueError('Installation receipt did not match')
    _attention(home, False)
    load('atomic_write').remove(home / JOURNAL, expected=before)
    prepared['completed'] = True
    load('bundle').prune_releases(home, doc['target'], doc['previous'], backend.pinned_release(home))
    if _decode(doc['files']['setup-current']) != _read(home, 'setup-current'):
        load('desktop_menu').start(home, resources, after_update=True)


def ready_after_commit(home, receipt):
    # The journal deliberately remains until all completion readback succeeds.
    try:
        return json.loads((home / RECEIPT).read_text(encoding='utf-8')) == receipt == parts(home)[0]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def restore(home, backend):
    """Never kill an updater; retain both runtimes and journal on incomplete recovery."""
    home = Path(home)
    try:
        doc, before = _journal(home)
        if not doc['restored']:
            for legacy in (False, True):
                if backend._task_state(TASKS[0], home, legacy=legacy) is not None:
                    backend._task_state(TASKS[0], home, 'disable', legacy=legacy)
                    backend._end_router(home, 180, legacy=legacy)
            atomic = load('atomic_write')
            for name in FILES:
                wanted, actual = _decode(doc['files'][name]), _read(home, name)
                if wanted == actual:
                    continue
                if wanted is None:
                    atomic.remove(home / name, expected=actual)
                else:
                    atomic.replace_bytes(home / name, wanted, expected=actual)
            load('native_shortcuts').restore(home, doc['shortcuts'])
            backend.restore_cohort(home, doc['tasks'])
            for name in FILES:
                if _read(home, name) != _decode(doc['files'][name]):
                    raise ValueError('Installation restoration did not match')
            active = any(rows[TASKS[0]] and rows[TASKS[0]]['active']
                         for rows in doc['tasks'].values())
            if active and not backend.ensure_serving(home, backend._state(home), doc['previous']):
                raise ValueError('Restored Router health did not match')
            doc['restored'] = True
            atomic.replace_json(home / JOURNAL, doc, expected=before)
        # A previously mixed installation is preserved, but never certified coherent.
        if doc['previous'] != '0.0.0' and not ready_after_commit(home, json.loads(
                _decode(doc['files'][RECEIPT]) or b'null')):
            try:
                receipt, resources, native = parts(home)
                python = resources / 'runtime' / native['runtime_exec']
                expected = _tasks.pythonw(str(python))
                if (any(not (doc['tasks']['current'][name] or doc['tasks']['legacy'][name]) for name in TASKS)
                        or any(row and row['executable'] != expected
                               for scope in doc['tasks'].values() for row in scope.values())):
                    raise ValueError('Previous runtime bindings did not match')
                load('native_shortcuts').verify(home, resources, python, legacy=True)
            except (Exception, SystemExit):
                _attention(home, True)
                return 'restored_mixed'
            load('atomic_write').replace_json(home / RECEIPT, receipt)
        _attention(home, doc['previous'] == '0.0.0')
        (home / JOURNAL).unlink()
        return 'restored'
    except (Exception, SystemExit):
        _attention(home, True)
        load('update_reconcile').log(home, 'installation', 'restore_failed', status=1)
        return 'failed'
