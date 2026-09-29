"""Exclusive pair publication. Journals cover process crashes, not disk failure."""
import ctypes
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_records = _load('router_publish_records', 'claude_profile_records.py')
_winacl = _load('router_publish_acl', '../ai_router/winacl.py')
MANIFEST_NAME = re.compile(r'^\.claude-profile-transaction-([0-9a-f]{32})\.json$')
PAIR_PHASES = ('prepared', 'displaced', 'bundle-published',
               'record-published', 'committed', 'restoring')
class UnsafeManifest(ValueError):
    """A malformed or unowned journal; never expose its contents."""


def _fsync_dir(path):
    if os.name == 'nt':
        return
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def private(path):
    if os.name == 'nt':
        _winacl.require_owner_only(path, windows=True)
    else:
        path.chmod(0o700 if path.is_dir() else 0o600)


def flush(path, protect=False):
    paths = [path] + (list(path.rglob('*')) if path.is_dir() else [])
    for item in paths:
        _records.assert_ancestors(item)
        # POSIX descendants can be hard links to originals outside the profile.
        if protect and (os.name == 'nt' or item == path):
            private(item)
        if item.is_file():
            with item.open('rb') as stream:
                os.fsync(stream.fileno())
    for item in reversed(paths):
        if item.is_dir():
            _fsync_dir(item)


def _safe_path(root, relative):
    if not isinstance(relative, str) or relative in ('', '.'):
        raise UnsafeManifest('invalid-journal')
    path = Path(relative)
    if path.is_absolute() or any(
            not _records._rules.safe_component(part) for part in path.parts):
        raise UnsafeManifest('invalid-journal')
    result = Path(root) / path
    _records.assert_target(result, root)
    return result


def _relative(root, path):
    result = Path(path).relative_to(root).as_posix()
    _safe_path(root, result)
    return result


def file_state(path):
    _records.assert_ancestors(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('unsafe-artifact')
    return {'kind': 'file', 'mode': info.st_mode & 0o777,
            'size': info.st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def tree_state(path):
    _records.assert_ancestors(path)
    if not path.exists():
        return None
    if not path.is_dir():
        raise ValueError('unsafe-artifact')
    values = [['dir', '.', path.stat().st_mode & 0o777]]
    for item in sorted(path.rglob('*')):
        _records.assert_ancestors(item)
        relative = item.relative_to(path).as_posix()
        if item.is_dir():
            values.append(['dir', relative, item.stat().st_mode & 0o777])
        else:
            state = file_state(item)
            values.append(['file', relative, state['mode'], state['size'], state['sha256']])
    return values


def state(path, kind):
    return file_state(path) if kind == 'file' else tree_state(path)


def private_state(value):
    if os.name == 'nt':
        return value
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value, mode=0o600)
    return [value[0][:2] + [0o700]] + value[1:]


def restore_modes(path, expected):
    if isinstance(expected, dict):
        path.chmod(expected['mode'])
    elif expected is not None:
        for row in expected:
            (path / row[1]).chmod(row[2])


def saved_matches(value, expected):
    # A process can die halfway through tightening a displaced tree's modes.
    if value == expected or value == private_state(expected):
        return True
    if not isinstance(value, list) or not isinstance(expected, list) or len(value) != len(expected):
        return False
    return all(a[:2] == b[:2] and a[3:] == b[3:] and a[2] in (b[2], c[2])
               for a, b, c in zip(value, expected, private_state(expected)))


def move_new(source, target):
    """Atomic no-replace rename, including empty destination directories."""
    _records.assert_ancestors(source)
    _records.assert_ancestors(target)
    if os.name == 'nt':
        os.rename(source, target)
    else:
        libc = ctypes.CDLL(None, use_errno=True)
        if sys.platform == 'darwin':
            result = libc.renamex_np(os.fsencode(source), os.fsencode(target), 4)
        elif sys.platform.startswith('linux'):
            result = libc.renameat2(-100, os.fsencode(source), -100, os.fsencode(target), 1)
        else:
            raise OSError('exclusive-rename-unavailable')
        if result:
            code = ctypes.get_errno()
            raise OSError(code, 'exclusive-rename-failed')
    _fsync_dir(target.parent)


def _write_payload(root, name, payload):
    path = _safe_path(root, name)
    fd, tmp = tempfile.mkstemp(dir=str(root), prefix=name + '.', suffix='.tmp')
    tmp = Path(tmp)
    try:
        private(tmp)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            fd = None
            stream.write(json.dumps(payload, sort_keys=True))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        _fsync_dir(root)
    finally:
        if fd is not None:
            os.close(fd)
        tmp.unlink(missing_ok=True)
    return path


def _valid_state(value, kind, nullable=True):
    if value is None:
        return nullable
    if kind == 'file':
        return (isinstance(value, dict) and set(value) == {'kind', 'mode', 'size', 'sha256'}
                and value['kind'] == 'file' and type(value['mode']) is int
                and 0 <= value['mode'] <= 0o777 and type(value['size']) is int
                and value['size'] >= 0 and isinstance(value['sha256'], str)
                and re.fullmatch('[0-9a-f]{64}', value['sha256']) is not None)
    if not isinstance(value, list):
        return False
    seen = set()
    for row in value:
        if not isinstance(row, list) or len(row) not in (3, 5):
            return False
        root_row = row[:2] == ['dir', '.']
        if (not isinstance(row[1], str) or row[1] in seen
                or Path(row[1]).is_absolute() or (not root_row and not Path(row[1]).parts)
                or any(not _records._rules.safe_component(p) for p in Path(row[1]).parts)
                or type(row[2]) is not int or not 0 <= row[2] <= 0o777):
            return False
        seen.add(row[1])
        if row[0] == 'dir' and len(row) == 3:
            continue
        if row[0] != 'file' or len(row) != 5 or not _valid_state(
                dict(kind='file', mode=row[2], size=row[3], sha256=row[4]), 'file'):
            return False
    return bool(value) and value[0][:2] == ['dir', '.']


def validate(root, path, doc):
    match = MANIFEST_NAME.fullmatch(path.name)
    required = {'version', 'phase', 'session_id', 'record', 'bundle', 'stage', 'record_stage',
                'record_before', 'bundle_before', 'before', 'after', 'duplicates'}
    if (not match or path.parent != root or not isinstance(doc, dict)
            or set(doc) != required or type(doc['version']) is not int
            or doc['version'] != 2 or doc['phase'] not in PAIR_PHASES
            or not isinstance(doc['session_id'], str) or not doc['session_id']
            or '\x00' in doc['session_id']):
        raise UnsafeManifest('invalid-journal')
    paths = {key: _safe_path(root, doc[key]) for key in (
        'record', 'bundle', 'stage', 'record_stage', 'record_before', 'bundle_before')}
    record, bundle = paths['record'], paths['bundle']
    if not _records.valid_pair_paths(root, record, bundle, doc['session_id']):
        raise UnsafeManifest('invalid-journal')
    for key, expected in (
            ('record_before', '.' + record.name + '.before-' + match[1]),
            ('bundle_before', '.' + bundle.name + '.before-' + match[1]),
            ('record_stage', '.' + record.name + '.after-' + match[1])):
        if paths[key] != record.parent / ('.claude-profile-control-' + match[1]) / expected:
            raise UnsafeManifest('invalid-journal')
    if paths['stage'] != record.parent / (bundle.name + '.tmp-' + match[1]):
        raise UnsafeManifest('invalid-journal')
    for label in ('before', 'after'):
        value = doc[label]
        if not isinstance(value, dict) or set(value) != {'record', 'bundle'}:
            raise UnsafeManifest('invalid-journal')
        for key, kind in (('record', 'file'), ('bundle', 'tree')):
            if not _valid_state(value[key], kind, nullable=label == 'before'):
                raise UnsafeManifest('invalid-journal')
    if not isinstance(doc['duplicates'], list):
        raise UnsafeManifest('invalid-journal')
    seen = set(paths.values())
    for row in doc['duplicates']:
        if not isinstance(row, dict) or set(row) != {'record', 'bundle', 'record_before', 'bundle_before', 'before'}:
            raise UnsafeManifest('invalid-journal')
        duplicate = _safe_path(root, row['record'])
        duplicate_bundle = _safe_path(root, row['bundle'])
        if not _records.valid_pair_paths(root, duplicate, duplicate_bundle, doc['session_id']):
            raise UnsafeManifest('invalid-journal')
        for key, original in (('record', duplicate), ('bundle', duplicate_bundle)):
            backup = original.parent / ('.claude-profile-control-' + match[1]) / (
                '.' + original.name + '.before-' + match[1])
            if (_safe_path(root, row[key]) != original
                    or _safe_path(root, row[key + '_before']) != backup
                    or original in seen or backup in seen):
                raise UnsafeManifest('invalid-journal')
            seen.update((original, backup))
        if (not isinstance(row['before'], dict) or set(row['before']) != {'record', 'bundle'}
                or not _valid_state(row['before']['record'], 'file', False)
                or not _valid_state(row['before']['bundle'], 'tree')):
            raise UnsafeManifest('invalid-journal')
    return paths


def artifacts(root, doc):
    for row in [doc] + doc['duplicates']:
        for key, kind in (('bundle', 'tree'), ('record', 'file')):
            yield (_safe_path(root, row[key]), _safe_path(root, row[key + '_before']),
                   row['before'][key], kind)


def write_pair_manifest(store_root, record_target, bundle_target, record_text,
                        stage, before=None, duplicates=()):
    root, record, bundle = Path(store_root), Path(record_target), Path(bundle_target)
    token = Path(stage).name.rsplit('.tmp-', 1)[-1]
    if not re.fullmatch('[0-9a-f]{32}', token):
        raise UnsafeManifest('invalid-journal')
    current = {'record': file_state(record), 'bundle': tree_state(bundle)}
    if before is not None and current != before:
        raise ValueError('transaction target changed')
    controls = {p.parent / ('.claude-profile-control-' + token)
                for p in [record] + [Path(item['record']) for item in duplicates]}
    for control in controls:
        _records.assert_ancestors(control)
        control.mkdir(mode=0o700)
        private(control)
    record_stage = record.parent / ('.claude-profile-control-' + token) / (
        '.' + record.name + '.after-' + token)
    record_doc = json.loads(record_text)
    identifier = _records.session_id(record_doc)
    _write_payload(record_stage.parent, record_stage.name, record_doc)
    record_stage.chmod(current['record']['mode'] & 0o600 if current['record'] else 0o600)
    flush(record_stage)
    flush(stage)
    doc = dict(version=2, phase='prepared', session_id=identifier, record=_relative(root, record),
               bundle=_relative(root, bundle), stage=_relative(root, stage),
               record_stage=_relative(root, record_stage), before=current,
               after={'record': file_state(record_stage), 'bundle': tree_state(stage)},
               duplicates=[])
    for row, target in [(doc, record)] + [(item, Path(item['record'])) for item in duplicates]:
        target_bundle = bundle if row is doc else Path(row.get('bundle', target.with_suffix('')))
        if target.exists() and _records.session_id(_records.read_json(target)) != identifier:
            raise ValueError('record-id-conflict')
        if row is not doc:
            row = dict(record=_relative(root, target), bundle=_relative(root, target_bundle),
                       before=row['before'])
            doc['duplicates'].append(row)
        for key, item in (('record', target), ('bundle', target_bundle)):
            row[key + '_before'] = _relative(root, item.parent / ('.claude-profile-control-' + token) / (
                '.' + item.name + '.before-' + token))
    manifest = root / ('.claude-profile-transaction-' + token + '.json')
    validate(root, manifest, doc)
    return _write_payload(root, manifest.name, doc)


def update_pair_manifest(path, phase):
    doc = json.loads(path.read_text(encoding='utf-8'))
    validate(path.parent, path, doc)
    if phase not in PAIR_PHASES:
        raise UnsafeManifest('invalid-journal')
    doc['phase'] = phase
    return _write_payload(path.parent, path.name, doc)


def delete_checked(path, expected, kind):
    if state(path, kind) != expected:
        raise ValueError('transaction backup changed')
    if kind == 'tree':
        for child in sorted(path.rglob('*'), reverse=True):
            if child.is_dir():
                child.rmdir()
            else:
                child.unlink()
        path.rmdir()
    else:
        path.unlink()


def publish_pair(manifest, record_text):
    root = manifest.parent
    doc = json.loads(manifest.read_text(encoding='utf-8'))
    paths = validate(root, manifest, doc)
    if doc['phase'] != 'prepared' or json.loads(record_text) != json.loads(paths['record_stage'].read_text(encoding='utf-8')):
        raise UnsafeManifest('invalid-journal')
    for key, kind in (('record_stage', 'file'), ('stage', 'tree')):
        expected = doc['after']['record' if kind == 'file' else 'bundle']
        if state(paths[key], kind) != expected:
            raise ValueError('transaction stage changed')
    for target, backup, expected, kind in artifacts(root, doc):
        if state(target, kind) != expected or backup.exists():
            raise ValueError('transaction target changed')
        if expected is not None:
            if os.name == 'nt':
                flush(target, protect=True)
            move_new(target, backup)
            displaced = state(backup, kind)
            flush(backup, protect=True)
            if displaced != expected or target.exists():
                raise ValueError('transaction displaced generation changed')
    update_pair_manifest(manifest, 'displaced')
    move_new(paths['stage'], paths['bundle'])
    update_pair_manifest(manifest, 'bundle-published')
    move_new(paths['record_stage'], paths['record'])
    update_pair_manifest(manifest, 'record-published')
    # Revalidate every before-image and duplicate vacancy before committing.
    verify_committed(root, doc, paths)
    update_pair_manifest(manifest, 'committed')
    finish(root, manifest, doc, paths)
    return tuple(doc['before'][key] != doc['after'][key] for key in ('record', 'bundle'))


def verify_committed(root, doc, paths):
    for key, kind in (('record', 'file'), ('bundle', 'tree')):
        if state(paths[key], kind) != doc['after'][key]:
            raise ValueError('transaction target changed')
    for target, backup, expected, kind in artifacts(root, doc):
        if target not in (paths['record'], paths['bundle']) and target.exists():
            raise ValueError('transaction duplicate recreated')
        if expected is not None and not backup.exists() and doc['phase'] != 'committed':
            raise ValueError('transaction backup missing')
        if backup.exists() and state(backup, kind) != private_state(expected):
            raise ValueError('transaction backup changed')


def finish(root, manifest, doc, paths):
    doc = dict(doc, phase='committed')
    verify_committed(root, doc, paths)
    for _target, backup, expected, kind in artifacts(root, doc):
        if backup.exists():
            verify_committed(root, doc, paths)
            delete_checked(backup, private_state(expected), kind)
    for parent in {backup.parent for _, backup, _, _ in artifacts(root, doc)}:
        if parent.exists():
            parent.rmdir()
    manifest.unlink()
    _fsync_dir(root)
