"""Retire a shared task deleted in one profile instead of copying it back.

A private router-home ledger remembers, after each clean sync, a digest of both
copies of every task the two profiles hold. A remembered task later missing from
one profile was deleted there, so the other copy moves to its store's trash while
it still matches; an edited copy is kept and shared again. Any doubt keeps the
copy. Nothing is hard-deleted or logged. Callers stop Claude and hold both locks.
"""
import hashlib
import importlib.util
import json
import os
import re
import uuid
from pathlib import Path


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_records = _load('router_ledger_records', 'claude_profile_records.py')
_transaction = _load('router_ledger_transaction', 'claude_profile_transaction.py')
_atomic = _load('router_ledger_atomic', 'atomic_write.py')
_publish = _transaction._publish
LEDGER = '.claude-profile-control-ledger.json'
TRASH = '.claude-profile-control-trash'
JOURNAL = 'retire.json'
KINDS = (('record', 'file'), ('bundle', 'tree'))
DIGEST = re.compile('[0-9a-f]{64}')


def _read(home, accounts):
    """This account pair's entries; anything unreadable or foreign means none."""
    try:
        doc = _records._identity._read_object(Path(home) / LEDGER)
    except (OSError, ValueError):
        return {}
    stores = doc.get('stores')
    if (not accounts or doc.get('version') != 1 or doc.get('accounts') != accounts
            or not isinstance(stores, dict)):
        return {}
    for entries in stores.values():
        if not isinstance(entries, dict) or not all(
                isinstance(pair, list) and len(pair) == 2
                and all(isinstance(value, str) and DIGEST.fullmatch(value) for value in pair)
                for pair in entries.values()):
            return {}
    return stores


def _write(home, accounts, stores):
    try:
        _atomic.replace_json(Path(home) / LEDGER,
                             {'version': 1, 'accounts': accounts, 'stores': stores})
    except OSError:
        pass  # The old ledger stays; it only retires copies that still match it.


def _state(store_root, record):
    """One copy's paths within its store and its record and bundle generations."""
    bundle = _records.bundle_path(record, store_root)
    return {'record': record.relative_to(store_root).as_posix(),
            'bundle': bundle.relative_to(store_root).as_posix(),
            'before': {'record': _publish.file_state(record),
                       'bundle': _publish.tree_state(bundle)}}


def _digest(state):
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


def record_shared(home, accounts, scopes, exclude=()):
    """After a clean sync, remember each task both profiles hold once each.

    `scopes` pairs each store's (store root, account folder) in the first- and
    third-party profiles. A task in `exclude`, the sync's blocked keys, is never
    remembered and so never retired."""
    if not accounts:
        return
    stores = {}
    for sides in scopes:
        store = sides[0][0].name
        if (store, None) in exclude:
            continue
        try:
            copies = [_records.group_records(root, account=account) for root, account in sides]
        except (OSError, ValueError):
            continue
        entries = stores.setdefault(store, {})
        for identifier in sorted(set(copies[0]) & set(copies[1])):
            paths = [found[identifier] for found in copies]
            if (store, identifier) in exclude or any(len(found) != 1 for found in paths):
                continue
            try:
                entries[identifier] = [_digest(_state(root, found[0]))
                                       for (root, _account), found in zip(sides, paths)]
            except (OSError, ValueError):
                continue
    if stores != _read(home, accounts):
        _write(home, accounts, stores)


def retire_deleted(home, accounts, scopes):
    """Before the sync passes, retire unchanged copies of tasks deleted elsewhere.

    Returns (retired, errors); an error code marks a trash entry that could not
    be put back safely and stays in place for inspection."""
    ledger, retired, errors, changed = _read(home, accounts), 0, [], False
    for sides in scopes:
        try:
            for store_root, _account in sides:
                _recover_trash(store_root)
        except (OSError, ValueError, TypeError):
            errors.append('retire-conflict')
            continue
        entries = ledger.get(sides[0][0].name, {})
        try:
            copies = _copies(sides) if entries else None
        except (OSError, ValueError, TypeError):
            copies = None
        if copies is None:
            continue
        present = [set(entries) & set(found) for found in copies]
        # A profile that lost every shared task was reset or signed out, not
        # tidied one task at a time: keep the other profile's copies.
        reset = [len(entries) > 1 and not found for found in present]
        for identifier, digests in sorted(entries.items()):
            where = [identifier in found for found in present]
            if not any(where):
                del entries[identifier]
                changed = True
                continue
            if all(where) or reset[where.index(False)]:
                continue
            keep = where.index(True)
            try:
                done = _retire(sides[keep][0], identifier,
                               copies[keep][identifier], digests[keep])
            except (OSError, ValueError, TypeError):
                errors.append('retire-conflict')
                continue
            if done:
                del entries[identifier]
                changed, retired = True, retired + 1
    if changed:
        _write(home, accounts, ledger)
    return retired, errors


def _copies(sides):
    """Each side's account-wide copies, or None while any of them is in doubt."""
    result = []
    for store_root, account in sides:
        # An interrupted transfer can hold a displaced record; restore it first.
        problems = []
        _transaction.recover_store(store_root, problems, account=account)
        found = _records.group_records(store_root, account=account)
        # An unreadable record may be a task that only looks deleted.
        listed = len(_records.record_paths(store_root, True, account=account))
        if problems or listed != sum(map(len, found.values())):
            return None
        result.append(found)
    return result


def _retire(store_root, identifier, paths, digest):
    """Journal an unchanged copy, then move its record and then its bundle."""
    trash, doc = store_root / TRASH, None
    entry = trash / uuid.uuid4().hex
    try:
        state = _state(store_root, paths[0])
        if len(paths) != 1 or _digest(state) != digest:
            return False  # Changed since it was shared: the edit wins.
        doc = dict(state, version=1, phase='prepared', session_id=identifier)
        _records.assert_target(trash, store_root)
        trash.mkdir(mode=0o700, exist_ok=True)
        entry.mkdir(mode=0o700)
        _publish.private(entry)
        _publish._fsync_dir(trash)
        _publish._write_payload(entry, JOURNAL, doc)
        for key, kind in KINDS:
            before, path = doc['before'][key], store_root / doc[key]
            if before is None:
                continue
            if _publish.state(path, kind) != before:
                raise ValueError('copy changed')
            _publish.move_new(path, entry / path.name)
            if _publish.state(entry / path.name, kind) != before:
                raise ValueError('copy changed')
        _publish._write_payload(entry, JOURNAL, dict(doc, phase='retired'))
        return True
    except (OSError, ValueError):
        if doc is not None and entry.is_dir():
            _restore(store_root, entry, doc)
        return False


def _restore(store_root, entry, doc):
    """Put an unfinished retirement back; raise and keep it when that is unsafe."""
    for key, kind in reversed(KINDS):
        origin = _publish._safe_path(store_root, doc[key])
        saved = entry / origin.name
        if not os.path.lexists(saved):
            continue
        if _publish.state(saved, kind) != doc['before'][key]:
            raise ValueError('retire-conflict')
        # Never replaces: a recreated original refuses the move instead.
        _publish.move_new(saved, origin)
    if {path.name for path in entry.iterdir()} - {JOURNAL}:
        raise ValueError('retire-conflict')
    (entry / JOURNAL).unlink(missing_ok=True)
    entry.rmdir()
    _publish._fsync_dir(entry.parent)


def _recover_trash(store_root):
    """Undo retirements a crash interrupted; finished entries stay as trash."""
    trash = store_root / TRASH
    _records.assert_target(trash, store_root)
    if not os.path.lexists(trash):
        return
    for entry in sorted(trash.iterdir()):
        if not os.path.lexists(entry / JOURNAL):
            continue  # A crash before the journal: nothing was moved.
        doc = _journal(store_root, entry)
        if doc['phase'] == 'prepared':
            _restore(store_root, entry, doc)


def _journal(store_root, entry):
    _records.assert_ancestors(entry / JOURNAL)
    doc = _records._identity._read_object(entry / JOURNAL)
    before = doc.get('before')
    if (set(doc) != {'version', 'phase', 'session_id', 'record', 'bundle', 'before'}
            or doc['version'] != 1 or doc['phase'] not in ('prepared', 'retired')
            or not isinstance(before, dict) or set(before) != {'record', 'bundle'}
            or not _publish._valid_state(before['record'], 'file', False)
            or not _publish._valid_state(before['bundle'], 'tree')
            or not isinstance(doc['session_id'], str)):
        raise ValueError('retire-conflict')
    record, bundle = (_publish._safe_path(store_root, doc[key]) for key in ('record', 'bundle'))
    if not _records.valid_pair_paths(store_root, record, bundle, doc['session_id']):
        raise ValueError('retire-conflict')
    return doc
