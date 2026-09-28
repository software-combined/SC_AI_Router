"""Project provider diagnostics without changing conversation or message IDs."""
import hashlib
import importlib.util
import io
import json
import os
import stat
import tempfile
from pathlib import Path


def _load_publish():
    spec = importlib.util.spec_from_file_location(
        'router_history_publish', Path(__file__).resolve().parent / 'claude_profile_publish.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_publish = _load_publish()


def portable_history(text):
    """Foreign request IDs are not evidence of an Anthropic response.

    Native resumption rejected a foreign response ID in the synthetic probe.
    Keep its request metadata under a provider-specific name without changing
    message IDs or conversation content. The original file remains recoverable.
    """
    output, changed = [], False
    for line in io.StringIO(text):
        if not line.strip():
            output.append(line)
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError('invalid transcript row')
        message = row.get('message')
        identifier = message.get('id') if isinstance(message, dict) else None
        if (row.get('type') == 'assistant' and not row.get('isApiErrorMessage')
                and isinstance(identifier, str)
                and identifier and not identifier.startswith('msg_') and row.get('requestId')):
            if 'providerRequestId' in row and row['providerRequestId'] != row['requestId']:
                raise ValueError('conflicting provider diagnostic')
            row['providerRequestId'] = row.pop('requestId')
            output.append(json.dumps(row, ensure_ascii=False) + '\n')
            changed = True
        else:
            output.append(line)
    return ''.join(output) if changed else text


def _identity(info):
    return {'device': info.st_dev, 'inode': info.st_ino, 'size': info.st_size,
            'mtime_ns': info.st_mtime_ns}


def _same_identity(left, right):
    return _identity(left) == right


def _snapshot(path):
    """Read one unchanged, singly-linked regular file without following links."""
    path = Path(path)
    _publish._records.assert_ancestors(path)
    try:
        listed = path.lstat()
    except FileNotFoundError:
        return None, None, None
    if not stat.S_ISREG(listed.st_mode) or listed.st_nlink != 1:
        raise ValueError('unsafe history file')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(str(path), flags)
    try:
        opened = os.fstat(fd)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                or not _same_identity(opened, _identity(listed))):
            raise ValueError('changed history file')
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        finished = os.fstat(fd)
    finally:
        os.close(fd)
    current = path.lstat()
    if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
            or not _same_identity(finished, _identity(opened))
            or not _same_identity(current, _identity(finished))):
        raise ValueError('changed history file')
    data = b''.join(chunks)
    return ({'kind': 'file', 'mode': current.st_mode & 0o777, 'size': len(data),
             'sha256': hashlib.sha256(data).hexdigest()}, data, _identity(current))


def _present(path):
    try:
        Path(path).lstat()
        return True
    except FileNotFoundError:
        return False


def _private_match(actual, expected):
    return actual == expected or actual == _publish.private_state(expected)


def _write_new(path, data):
    path = Path(path)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            fd = None
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if fd is not None:
            os.close(fd)
    _publish.private(path)
    _publish.flush(path, protect=True)


def _write_journal(path, document):
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp',
                                     dir=str(path.parent))
    temporary = Path(temporary)
    try:
        _publish.private(temporary)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            fd = None
            stream.write(json.dumps(document, sort_keys=True, separators=(',', ':')) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        _publish.flush(temporary, protect=True)
        _publish.move_new(temporary, path)
    finally:
        if fd is not None:
            os.close(fd)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_journal(path, target, backup, stage):
    state, raw, _ = _snapshot(path)
    if state is None or (os.name != 'nt' and state['mode'] != 0o600):
        raise ValueError('invalid history journal')
    try:
        document = json.loads(raw.decode('utf-8'))
    except (UnicodeError, ValueError) as exc:
        raise ValueError('invalid history journal') from exc
    expected = {'version', 'target', 'backup', 'stage', 'before', 'after',
                'identity', 'stage_identity'}
    identity = document.get('identity') if isinstance(document, dict) else None
    stage_identity = document.get('stage_identity') if isinstance(document, dict) else None
    if (not isinstance(document, dict) or set(document) != expected
            or document['version'] != 1 or document['target'] != target.name
            or document['backup'] != backup.name or document['stage'] != stage.name
            or not _publish._valid_state(document['before'], 'file', False)
            or not _publish._valid_state(document['after'], 'file', False)
            or not isinstance(identity, dict)
            or set(identity) != {'device', 'inode', 'size', 'mtime_ns'}
            or any(type(value) is not int or value < 0 for value in identity.values())
            or not isinstance(stage_identity, dict)
            or set(stage_identity) != {'device', 'inode', 'size', 'mtime_ns'}
            or any(type(value) is not int or value < 0
                   for value in stage_identity.values())):
        raise ValueError('invalid history journal')
    return document


def _write_done(path, journal, document):
    _write_journal(path, {'version': 1, 'journal': journal.name,
        'before': document['before'], 'after': document['after'],
        'identity': document['identity'], 'stage_identity': document['stage_identity']})


def _validate_done(path, journal, backup, stage, document):
    state, raw, _ = _snapshot(path)
    expected = {'version': 1, 'journal': journal.name,
        'before': document['before'], 'after': document['after'],
        'identity': document['identity'], 'stage_identity': document['stage_identity']}
    backup_state, _, backup_identity = _snapshot(backup)
    if (state is None or (os.name != 'nt' and state['mode'] != 0o600)
            or json.loads(raw.decode('utf-8')) != expected
            or _present(stage) or not _private_match(backup_state, document['before'])
            or backup_identity != document['identity']):
        raise ValueError('invalid history completion')


def _resume(target, journal, backup, stage, done):
    document = _read_journal(journal, target, backup, stage)
    before, after, identity, stage_identity = (
        document['before'], document['after'], document['identity'],
        document['stage_identity'])
    target_state, _, target_identity = _snapshot(target)
    backup_state, _, backup_identity = _snapshot(backup)
    stage_state, _, current_stage_identity = _snapshot(stage)
    if stage_state is not None and (
            stage_state != after or current_stage_identity != stage_identity):
        raise ValueError('changed history stage')
    if backup_state is not None and (
            not _private_match(backup_state, before) or backup_identity != identity):
        raise ValueError('changed history backup')
    if backup_state is None:
        if (target_state is None or not _private_match(target_state, before)
                or target_identity != identity):
            raise ValueError('changed history source')
        _publish.private(target)
        _publish.flush(target, protect=True)
        target_state, _, target_identity = _snapshot(target)
        if (not _private_match(target_state, before) or target_identity != identity):
            raise ValueError('changed history source')
        _publish.move_new(target, backup)
        backup_state, _, backup_identity = _snapshot(backup)
        if (not _private_match(backup_state, before) or backup_identity != identity):
            raise ValueError('changed history backup')
        target_state = None
    if target_state is not None:
        _, _, current_target_identity = _snapshot(target)
        if (target_state == after and current_target_identity == stage_identity
                and stage_state is None):
            _write_done(done, journal, document)
            return 'repaired'
        raise ValueError('competing history write')
    if stage_state is None:
        raise ValueError('missing history stage')
    try:
        _publish.move_new(stage, target)
    except OSError as exc:
        if _present(target):
            raise ValueError('competing history write') from exc
        raise
    _publish.flush(target, protect=True)
    final_state, _, final_identity = _snapshot(target)
    backup_state, _, backup_identity = _snapshot(backup)
    if (final_state != after or final_identity != stage_identity
            or not _private_match(backup_state, before)
            or backup_identity != identity):
        raise ValueError('changed history repair')
    _write_done(done, journal, document)
    return 'repaired'


def _generation(identity, state):
    seed = json.dumps([state['sha256'], identity], sort_keys=True,
                      separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(seed).hexdigest()


def _transaction_paths(target, key):
    prefix = '.' + target.name + '.history-repair-' + key
    return tuple(target.with_name(prefix + suffix) for suffix in
                 ('.journal', '.original', '.stage', '.done'))


def _recover_transactions(target):
    stem = '.' + target.name + '.history-repair-'
    journals, artifacts = [], []
    known = set()
    for item in target.parent.iterdir():
        if item.name.startswith(stem):
            artifacts.append(item.name)
            suffix = next((value for value in ('.journal', '.original', '.stage', '.done')
                           if item.name.endswith(value)), None)
            key = item.name[len(stem):-len(suffix)] if suffix else ''
            if len(key) != 64 or any(char not in '0123456789abcdef' for char in key):
                raise ValueError('unowned history artifact')
            paths = _transaction_paths(target, key)
            known.update(path.name for path in paths)
            if suffix == '.journal':
                journals.append((key, paths))
    if any(item.name.startswith(stem) and item.name not in known
           for item in target.parent.iterdir()):
        raise ValueError('unowned history artifact')
    journal_names = {paths[0].name for _, paths in journals}
    if any(name not in journal_names and name not in {
            path.name for _, paths in journals for path in paths[1:]}
            for name in artifacts):
        raise ValueError('unowned history artifact')
    pending = []
    for _, (journal, backup, stage, done) in journals:
        document = _read_journal(journal, target, backup, stage)
        if _present(done):
            _validate_done(done, journal, backup, stage, document)
        else:
            pending.append((journal, backup, stage, done))
    if len(pending) > 1:
        raise ValueError('ambiguous history recovery')
    if pending:
        _resume(target, *pending[0])
        return True
    return False


def repair_file(path):
    """Repair one stopped-client JSONL file and retain its private original.

    A deterministic sibling journal makes the two no-replace renames resumable.
    Ambiguous or competing state is left intact and rejected for caller review.
    """
    target = Path(path).absolute()
    _publish._records.assert_ancestors(target)
    if _recover_transactions(target):
        return 'repaired'
    before, raw, identity = _snapshot(target)
    if before is None:
        raise ValueError('missing history source')
    try:
        projected = portable_history(raw.decode('utf-8')).encode('utf-8')
    except UnicodeError as exc:
        raise ValueError('invalid history encoding') from exc
    if projected == raw:
        return 'unchanged'
    key = _generation(identity, before)
    journal, backup, stage, done = _transaction_paths(target, key)
    if any(_present(item) for item in (journal, backup, stage, done)):
        raise ValueError('unowned history artifact')
    current, current_raw, current_identity = _snapshot(target)
    if current != before or current_raw != raw or current_identity != identity:
        raise ValueError('changed history source')
    _write_new(stage, projected)
    after, staged, stage_identity = _snapshot(stage)
    if staged != projected or _present(journal) or _present(backup) or _present(done):
        raise ValueError('changed history artifacts')
    _write_journal(journal, {'version': 1, 'target': target.name,
        'backup': backup.name, 'stage': stage.name, 'before': before,
        'after': after, 'identity': identity, 'stage_identity': stage_identity})
    return _resume(target, journal, backup, stage, done)
