"""Verify target Resources; Windows joins required installation completion."""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_payload import load, metadata, retained, target

MAX_BYTES = 250 * 1024 * 1024
HASH = re.compile('[0-9a-f]{64}')


def current(home):
    home = Path(home)
    name = (home / 'setup-current').read_text().strip()
    if not name or name in ('.', '..') or Path(name).name != name or (home / 'setup' / name).is_symlink():
        raise ValueError('Invalid setup pointer')
    return home / 'setup' / name


def for_version(home, version):
    """Find verified retained Resources when rollback kept a newer setup pointer."""
    version = load('update_status').version(version)
    base = Path(home) / 'setup'
    if not version or base.is_symlink():
        raise ValueError('Invalid retained resource version')
    for candidate in [base / version, *sorted(base.glob(version + '-*'))]:
        if candidate.is_symlink():
            continue
        try:
            if metadata(candidate)['version'] == version:
                return candidate
        except (OSError, ValueError, KeyError, TypeError):
            continue
    raise ValueError('Matching verified resources are unavailable')


def ready(home):
    try:
        doc = metadata(current(home))
        service = load('service')
        record = Path(home) / 'desktop-delivery.json'
        delivery = json.loads(record.read_text()) if record.exists() else {}
        failed = not isinstance(delivery, dict) or delivery.get('status') == 'failed'
        newer_core = load('bundle').newer(service.current_version(Path(home)), doc['version'])
        coherent = sys.platform != 'win32' or load('windows_installation').ready(home)
        return bool(doc.get('menu_sha256')) and not failed and not newer_core and coherent
    except (OSError, ValueError, KeyError, TypeError):
        return False


def descriptor(latest):
    rows = latest.get('native_resources', {})
    if not isinstance(rows, dict):
        raise ValueError('Invalid native resource map')
    row = rows.get(target())
    if row is None:
        return None
    if (not isinstance(row, dict) or row.get('version') != latest['version']
            or row.get('bundle_sha256') != latest['sha256']
            or not HASH.fullmatch(str(row.get('sha256', '')))
            or type(row.get('size')) is not int or not 0 < row['size'] <= MAX_BYTES
            or not isinstance(row.get('url'), str)):
        raise ValueError('Native resources do not match this release')
    return row


def download(url, destination, row, fetch=None):
    feed = load('feed')
    if not feed.trusted_origin(url):
        raise ValueError('Untrusted native resource origin')
    digest, size = hashlib.sha256(), 0
    if fetch is not None:
        import io
        source = io.BytesIO(fetch(url))
    else:
        source = feed.opener().open(feed._request(url), timeout=30)
    with source, Path(destination).open('wb') as output:
        while True:
            chunk = source.read(min(1024 * 1024, row['size'] - size + 1))
            if not chunk:
                break
            size += len(chunk)
            if size > row['size']:
                raise ValueError('Native resource archive is too large')
            digest.update(chunk)
            output.write(chunk)
    if size != row['size'] or digest.hexdigest() != row['sha256']:
        raise ValueError('Native resource checksum mismatch')


def unpack(archive, destination):
    """Portable data-only extraction, including internal runtime links, on Python 3.9+."""
    root = (Path(destination) / 'Resources').resolve()
    spec = importlib.util.spec_from_file_location('router_native_stage',
        Path(__file__).parent / 'native/native_stage.py')
    stage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stage)
    hardlinks = []
    with tarfile.open(archive, 'r:gz') as stream:
        names = stage._member_names(stream, links=True)
        if any(name != 'Resources' and not name.startswith('Resources/') for name in names):
            raise ValueError('Unexpected native resource archive root')
        for entry in stream.getmembers():
            path = Path(destination) / entry.name
            if path.resolve() != root and root not in path.resolve().parents:
                raise ValueError('Native resource path escapes its directory')
            if entry.isdir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if entry.issym() or entry.islnk():
                link = ((path.parent if entry.issym() else Path(destination)) / entry.linkname).resolve()
                if link != root and root not in link.parents:
                    raise ValueError('Native resource link escapes its directory')
                if entry.issym():
                    path.symlink_to(entry.linkname)
                else:
                    hardlinks.append((path, link))
            else:
                with stream.extractfile(entry) as source, path.open('xb') as output:
                    shutil.copyfileobj(source, output)
                path.chmod(0o755 if entry.mode & 0o111 else 0o644)
        for path, link in hardlinks:
            if not link.is_file() or root not in link.resolve().parents:
                raise ValueError('Invalid native runtime hard link')
            os.link(link, path)
    return root


def stage(home, latest, feed_url, fetch=None, *, resources=None):
    """Verify and retain required Resources without changing live entry points."""
    row = descriptor(latest)
    if resources is not None:
        doc = metadata(resources)
        if doc['sha256'] != latest['sha256'] or doc['version'] != latest['version'] or not doc.get('menu_sha256'):
            raise ValueError('Native resources have the wrong core identity')
        return retained(resources, home, repair=True)
    if row is None:
        raise ValueError('Required Windows resources are unavailable')
    with tempfile.TemporaryDirectory(prefix='scg-resources-') as temporary:
        archive = Path(temporary) / 'resources.tar.gz'
        download(load('feed').sibling_bundle(feed_url, row['url']), archive, row, fetch)
        resources = unpack(archive, temporary)
        doc = metadata(resources)
        if doc['sha256'] != row['bundle_sha256'] or doc['version'] != row['version'] or not doc.get('menu_sha256'):
            raise ValueError('Native resources have the wrong core identity')
        return retained(resources, home, repair=True)


def reconcile(home, latest, feed_url, fetch=None):
    """Caller holds the installation lock and has verified the channel document."""
    home = Path(home)
    if (home / '.router-removed').exists():
        return False
    row = descriptor(latest)
    if row is None or load('service').current_version(home) != latest['version']:
        return False
    if sys.platform == 'win32':
        return load('windows_installation').controls(home, latest, feed_url, fetch)
    previous = None
    try:
        previous = current(home)
        doc = metadata(previous)
        if doc.get('menu_sha256') and load('bundle').newer(doc['version'], row['version']):
            return False  # Preserve newer controls and any unresolved delivery warning.
        record = json.loads((home / 'desktop-delivery.json').read_text())
        if (doc.get('menu_sha256') and doc['sha256'] == row['bundle_sha256']
                and isinstance(record, dict) and record.get('status') == 'ready'
                and record.get('sha256') == row['sha256']):
            load('runtime_rebind').reconcile(home)
            return True
    except (OSError, ValueError, KeyError):
        pass
    pointer = home / 'setup-current'
    before = pointer.read_bytes() if pointer.exists() else None
    permanent = stage(home, latest, feed_url, fetch)
    doc = metadata(permanent)
    try:
        load('native_shortcuts').install(home, permanent, permanent / 'runtime' / doc['runtime_exec'])
        load('runtime_rebind').reconcile(home)
        if previous != permanent:
            load('desktop_menu').start(home, permanent, after_update=True)
    except (Exception, SystemExit):
        if before is None:
            pointer.unlink(missing_ok=True)
        else:
            load('atomic_write').replace_bytes(pointer, before)
        raise
    load('atomic_write').replace_json(home / 'desktop-delivery.json',
        dict(status='ready', version=row['version'], sha256=row['sha256']))
    print('SCG Router menu delivered')
    return True


def deliver(home, latest, feed_url, fetch=None):
    """Use the platform's completion boundary and retain safe failure status."""
    try:
        delivered = reconcile(home, latest, feed_url, fetch)
        if delivered:
            _record(home, 'ready')
        return delivered
    except (Exception, SystemExit) as error:
        if sys.platform == 'win32' and isinstance(error, SystemExit) and error.code == 0:
            return False  # The unchanged or restored cohort remains usable; retry quietly.
        load('atomic_write').replace_json(Path(home) / 'desktop-delivery.json',
                                         dict(status='failed'))
        _record(home, 'failed')
        print('SCG Router menu update needs repair. Check setup for routing status.')
        return False


def confirm_controls(home, resources):
    """Native setup calls this after installing shortcuts from verified Resources."""
    home, resources = Path(home), Path(resources)
    with load('service').install_lock(home) as held:
        if not held or current(home).resolve() != resources.resolve():
            return False
        doc = metadata(resources)
        if (not doc.get('menu_sha256') or load('bundle').newer(
                load('service').current_version(home), doc['version'])):
            return False
        load('atomic_write').replace_json(home / 'desktop-delivery.json',
                                          dict(status='ready', version=doc['version']))
        _record(home, 'ready', complete=True)
        return True


def _record(home, outcome, complete=False):
    try:
        service = load('service')
        state = service._state.read(service._state.path(Path(home)))
        if isinstance(state, dict):
            components = state.get('component_repairs')
            if not isinstance(components, dict):
                components = state['component_repairs'] = {}
            components['controls'] = outcome
            status = load('update_status')
            if (complete and components.get('assistants') == 'ready'
                    and all(value == 'ready' for value in status.components(state).values())
                    and state.get('last_applied_version') == service.current_version(Path(home))):
                error = '' if state.get('last_error') in ('installer_failed', 'installer_timeout') else None
                status.record(state, error=error, repaired=True)
            service._write_state(Path(home), state)
    except (OSError, ValueError, TypeError):
        pass  # A notice cannot fail a completed routing update.
