"""Validate complete local journals before recovery of an interrupted sync."""
import importlib.util
import json
from pathlib import Path


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_publish = _load('router_transaction_publish', 'claude_profile_publish.py')
MANIFEST_NAME = _publish.MANIFEST_NAME
PAIR_PHASES = _publish.PAIR_PHASES
write_pair_manifest = _publish.write_pair_manifest
publish_pair = _publish.publish_pair
update_pair_manifest = _publish.update_pair_manifest
file_state = _publish.file_state
tree_state = _publish.tree_state


def _preflight(root, doc, paths):
    """No mutation until every artifact has a possible owned generation."""
    for target, backup, before, kind in _publish.artifacts(root, doc):
        current, saved = _publish.state(target, kind), _publish.state(backup, kind)
        if saved is not None and (before is None or not _publish.saved_matches(saved, before)):
            raise ValueError('transaction backup changed')
        canonical = target in (paths['record'], paths['bundle'])
        key = 'record' if kind == 'file' else 'bundle'
        after = doc['after'][key] if canonical else None
        if not canonical and current is not None and saved is not None:
            raise ValueError('transaction duplicate recreated')
        allowed = (None, before, after)
        if doc['phase'] == 'restoring':
            allowed += (_publish.private_state(before),)
        if current not in allowed and not (doc['phase'] == 'restoring'
                                          and _publish.saved_matches(current, before)):
            raise ValueError('transaction target changed')
        if before is not None and saved is None and not _publish.saved_matches(current, before):
            raise ValueError('transaction backup missing')
    for key, kind, result in (('stage', 'tree', 'bundle'),
                              ('record_stage', 'file', 'record')):
        staged = _publish.state(paths[key], kind)
        if staged is not None and staged != doc['after'][result]:
            raise ValueError('transaction stage changed')
        current = _publish.state(paths[result], kind)
        if staged is None and current != doc['after'][result]:
            # During rollback, the published generation has already been
            # removed only after its original was restored successfully.
            if doc['phase'] != 'restoring':
                raise ValueError('transaction stage missing')
        if staged is not None and current == doc['after'][result] and (
                current != doc['before'][result]):
            raise ValueError('transaction ownership conflict')
        if doc['phase'] == 'prepared' and staged is None:
            raise ValueError('transaction ownership conflict')
        if doc['phase'] == 'displaced' and result == 'record' and staged is None:
            raise ValueError('transaction ownership conflict')
        if doc['phase'] in ('bundle-published', 'record-published') and result == 'bundle' and staged is not None:
            raise ValueError('transaction ownership conflict')
        if doc['phase'] == 'record-published' and staged is not None:
            raise ValueError('transaction ownership conflict')


def _record_ownership(root, doc, paths):
    candidates = [paths['record'], paths['record_stage'], paths['record_before']]
    for row in doc['duplicates']:
        candidates.extend(_publish._safe_path(root, row[key]) for key in ('record', 'record_before'))
    for candidate in candidates:
        if candidate.exists():
            value = _publish._records.read_json(candidate)
            if _publish._records.session_id(value) != doc['session_id']:
                raise ValueError('transaction ownership conflict')


def recover_manifest(root, path, doc):
    paths = _publish.validate(root, path, doc)
    _record_ownership(root, doc, paths)
    if doc['phase'] == 'committed':
        if paths['stage'].exists() or paths['record_stage'].exists():
            raise ValueError('transaction ownership conflict')
        _publish.finish(root, path, doc, paths)
        return 1
    _preflight(root, doc, paths)
    update_pair_manifest(path, 'restoring')
    for target, backup, before, kind in _publish.artifacts(root, doc):
        current = _publish.state(target, kind)
        canonical = target in (paths['record'], paths['bundle'])
        key = 'record' if kind == 'file' else 'bundle'
        stage = paths['record_stage' if kind == 'file' else 'stage'] if canonical else None
        if (canonical and current == doc['after'][key]
                and (current != before or (backup.exists() and not stage.exists()))):
            _publish.move_new(target, stage)
            if _publish.state(stage, kind) != doc['after'][key]:
                raise ValueError('transaction displaced generation changed')
            current = None
        if backup.exists():
            if current is not None:
                raise ValueError('transaction target changed')
            _publish.move_new(backup, target)
            current = _publish.state(target, kind)
        if before is not None and _publish.saved_matches(current, before):
            _publish.restore_modes(target, before)
        if _publish.state(target, kind) != before:
            raise ValueError('transaction restore failed')
    # Originals are back. Recheck all of them before discarding staged output.
    for target, _backup, before, kind in _publish.artifacts(root, doc):
        if _publish.state(target, kind) != before:
            raise ValueError('transaction target changed')
    for key, kind, result in (('stage', 'tree', 'bundle'),
                              ('record_stage', 'file', 'record')):
        if paths[key].exists():
            _publish.delete_checked(paths[key], doc['after'][result], kind)
    for parent in {backup.parent for _, backup, _, _ in _publish.artifacts(root, doc)}:
        if parent.exists():
            parent.rmdir()
    path.unlink()
    _publish._fsync_dir(root)
    return 1


def recover_store(store_root, errors=None, blocked=None, *, account=None):
    """Report only closed-set codes; retain ambiguous or unowned artifacts."""
    root = Path(store_root)
    _publish._records.assert_ancestors(root)
    if not root.is_dir():
        return 0
    recovered = 0
    for path in sorted(root.iterdir()):
        if not MANIFEST_NAME.fullmatch(path.name):
            continue
        doc = None
        try:
            if not _publish._records._rules.regular(path):
                raise _publish.UnsafeManifest('invalid-journal')
            _publish._records.assert_ancestors(path)
            _publish._winacl.require_owner_only(path)
            doc = json.loads(path.read_text(encoding='utf-8'))
            _publish.validate(root, path, doc)
            if account is not None:
                accounts = {root / target.relative_to(root).parts[0]
                            for target, _, _, _ in _publish.artifacts(root, doc)}
                if account not in accounts:
                    continue
                if accounts != {account}:
                    raise _publish.UnsafeManifest('cross-account-journal')
        except (OSError, ValueError, TypeError, KeyError):
            if errors is not None:
                errors.append('invalid-journal')
            if blocked is not None:
                blocked.add(None)
            continue
        try:
            recovered += recover_manifest(root, path, doc)
        except (OSError, ValueError, TypeError):
            if errors is not None:
                errors.append('recovery-conflict')
            if blocked is not None:
                blocked.add(doc['session_id'])
            if errors is None:
                raise
    return recovered
