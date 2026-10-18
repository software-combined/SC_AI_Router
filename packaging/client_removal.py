"""Preflight every attachment, then detach with retryable, receipt-owned edits.

No cross-client rollback: completed restores remain complete. A later failure
keeps the service running and leaves each remaining attachment's receipt.
"""
import hashlib
import importlib.util
from pathlib import Path


def _load(name):
    spec = importlib.util.spec_from_file_location('router_remove_' + name,
                                                Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_json = _load('owned_json')
_atomic = _load('atomic_write')
LABELS = {'codex': 'Codex', 'claude': 'Claude Code', 'claude-desktop': 'Claude desktop'}


def read(path):
    try:
        with Path(path).open(newline='') as stream:
            return stream.read()
    except FileNotFoundError:
        return None


def entry_path(entry):
    path = entry.get('config_path') if isinstance(entry, dict) else None
    if not isinstance(path, str) or not Path(path).is_absolute():
        raise _json.Conflict('damaged_receipt')
    return Path(path)


def _snapshot(entry, keys, legacy_keys=()):
    previous = _json.snapshot(entry.get('inserted_block'), ())
    if legacy_keys and 'written' not in entry and set(previous) == set(legacy_keys):
        return previous
    return _json.snapshot(entry.get('inserted_block'), keys)


def saved_values(entry, keys, legacy_keys=()):
    try:
        return _snapshot(entry, keys, legacy_keys)
    except _json.Conflict:
        raise SystemExit('Assistant connection conflict: damaged_receipt.') from None


def json_plan(home, client, entry):
    """The same narrow proof serves standalone detach and all-client removal."""
    path = entry_path(entry)
    owner = _load('claude_config' if client == 'claude' else 'claude_desktop_config')
    previous = _snapshot(entry, owner.OWNED_KEYS, getattr(owner, 'LEGACY_KEYS', ()))
    written = entry.get('written')
    if written is None:  # Legacy receipts retain the connection in router state.
        state = _json.document((Path(home) / 'mixed-router-state.json').read_text())
        if not isinstance(state.get('port'), int) or not isinstance(state.get('token'), str):
            raise _json.Conflict('damaged_receipt')
        written = (owner.desired_env(home, state) if client == 'claude'
                   else owner.desired_values(state))
    if (not isinstance(written, dict) or set(written) != set(owner.OWNED_KEYS)
            or any(not isinstance(value, str) for value in written.values())):
        raise _json.Conflict('damaged_receipt')
    if any(value is not None and not isinstance(value, str) for value in previous.values()):
        raise _json.Conflict('damaged_receipt')
    if 'written' not in entry:
        written = {key: value for key, value in written.items() if key in previous}
    if client == 'claude' and owner.FIRST_PARTY_KEY in previous:
        written = dict(written, **{owner.FIRST_PARTY_KEY: '1'})
    before = read(path)
    after = _json.restore(before if before is not None else '{}',
                          ('env',) if client == 'claude' else (), written, previous)
    files = [(path, before, after if before is not None else None)]
    if client == 'claude-desktop':
        if path.parent.name != 'configLibrary' or 'deploymentMode' not in previous:
            raise _json.Conflict('damaged_receipt')
        config = path.parents[1] / 'claude_desktop_config.json'
        old = read(config)
        if old is not None:
            doc = _json.document(old)
            # A selection made after attachment belongs to the person.
            updated = (_json.restore(old, (), {'deploymentMode': '3p'}, previous)
                       if doc.get('deploymentMode') == '3p' else old)
            files.append((config, old, updated))
    return files


def apply(files):
    for path, before, after in files:
        target = path.resolve()
        if before != after:
            _atomic.replace_text(target, after, newline='', expected=before)
        else:
            _atomic.check_unchanged(target, before)
        if path.resolve() != target or read(path) != after:
            raise _atomic.ConcurrentChange('Settings changed concurrently; retry removal.')


def detach_json(home, client, receipts, entry=None):
    current = receipts.read_receipt(home).get('clients', {}).get(client)
    if current is None:
        return
    if entry is not None and entry != current:
        raise _json.Conflict('receipt_changed')
    apply(json_plan(home, client, current))
    receipts.drop_client(home, client, expected=current)


def preflight(home, receipts):
    path = receipts.receipt_path_for(home)
    raw = read(path)
    if raw is not None:
        doc = _json.document(raw)
        if path.is_symlink() or not (doc.get('version') == 2 and isinstance(doc.get('clients'), dict)
                or isinstance(doc.get('config_path'), str) and isinstance(doc.get('inserted_block'), str)):
            raise _json.Conflict('damaged_receipt')
    entries = receipts.read_receipt(home).get('clients', {})
    if set(entries) - LABELS.keys():
        raise _json.Conflict('unsupported_attachment')
    _load('codex_switch_config').refuse_switched(home)
    _load('claude_profile_hook').removal_plan(home)
    plans, paths = [], set()
    for client, entry in entries.items():
        try:
            if client == 'codex':
                before, after = receipts.removal_plan(entry_path(entry), entry)
                files = [(entry_path(entry), before, after)]
            else:
                files = json_plan(home, client, entry)
            targets = {path.resolve() for path, _, _ in files}
            if paths & targets:
                raise _json.Conflict('ambiguous_settings_path')
            paths.update(targets)
            plans.append((client, entry, files))
        except (OSError, ValueError, SystemExit) as exc:
            code = str(exc) if isinstance(exc, _json.Conflict) else 'ownership_conflict'
            raise SystemExit('%s removal conflict: %s. No assistants were detached.'
                             % (LABELS[client], code)) from None
    return plans


def remove_all(home, receipts, restore_codex):
    """All ownership checks precede every detach; service lifetime stays outside."""
    plans = preflight(home, receipts)
    removed = []
    for client, entry, files in plans:
        try:
            if receipts.read_receipt(home).get('clients', {}).get(client) != entry:
                raise _json.Conflict('receipt_changed')
            if client == 'codex':
                before = files[0][1]
                restore_codex(hashlib.sha256(before.encode()).hexdigest(), entry)
            else:
                apply(files)
                receipts.drop_client(home, client, expected=entry)
            removed.append(LABELS[client])
        except (OSError, ValueError, SystemExit):
            remaining = [LABELS[name] for name, _, _ in plans if LABELS[name] not in removed]
            raise SystemExit('Removal incomplete. Removed: %s. Remaining: %s. '
                             'Router services left running; retry removal.'
                             % (', '.join(removed) or 'none', ', '.join(remaining))) from None
    return removed
