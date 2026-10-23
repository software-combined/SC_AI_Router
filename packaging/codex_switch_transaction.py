"""Pending-marker transactions, proof and guarded rollback of owned Codex settings."""
import importlib.util
import json
from pathlib import Path


def _load(name):
    spec = importlib.util.spec_from_file_location("router_codex_transaction_" + name,
        Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_blocks = _load("codex_switch_config")
_receipts = _load("codex_config")
_atomic = _load("atomic_write")
SWITCHED, SWITCHED_BACK = _blocks.SWITCHED, _blocks.SWITCHED_BACK
MARKER = "codex-switch-pending.json"
NOT_PROVEN = "The ChatGPT app (Codex) could not use the new settings, so nothing changed."
FAILED = "The ChatGPT app (Codex) could not be switched. Try again."
UNFINISHED = "An earlier switch could not be finished. Contact your administrator."


class SwitchError(Exception):
    """A user-safe failure without settings or paths."""


def _files(home, entry):
    """config.toml and the receipt as they stand, or None when unreadable."""
    try:
        return tuple(path.read_text() if path.exists() else None for path in (
            Path(entry['config_path']), _receipts.receipt_path_for(home)))
    except OSError:
        return None


def _apply(home, entry, target, prove, root, *, reopen=None, before_restore=None):
    """Write `target` with a pending marker, prove it, and undo it on any failure."""
    marker = home / MARKER
    try:
        # Carry the current pick without claiming added user settings.
        entry = _blocks.rollback_entry(entry)
        before = _files(home, entry)
        _atomic.replace_json(marker, {'to': target, 'entry': entry})
    except SystemExit as exc:
        raise SwitchError(_blocks.EDITED) from exc
    except OSError as exc:
        raise SwitchError(FAILED) from exc
    try:
        _blocks.switch(home, target)
        if target == SWITCHED and prove(root) is not True:
            raise SwitchError(NOT_PROVEN)
        if reopen is not None:
            reopen()
    except (Exception, SystemExit) as exc:
        # Undo only a write: a switch that refused first changed nothing.
        if before is None or _files(home, entry) != before:
            try:
                _restore(home, entry, target, before_restore)
            except (Exception, SystemExit):
                raise SwitchError(UNFINISHED) from exc  # the marker stays for the next run
        _clear(marker)
        if isinstance(exc, SwitchError):
            raise
        raise SwitchError(_blocks.EDITED if isinstance(exc, SystemExit) else FAILED) from exc
    _clear(marker)


def _recover(home, prove, root, *, reopen=None, before_restore=None):
    """Settle a pending switch, rolling back an unproven or unopened connection."""
    marker = home / MARKER
    if not marker.exists():
        return
    try:
        pending = json.loads(marker.read_text())
        entry, target = pending['entry'], pending['to']
        written = _blocks.current(home) == target
        if not (written and (target == SWITCHED_BACK or prove(root) is True)):
            _restore(home, entry, target, before_restore)
        if reopen is not None:
            reopen()
    except (Exception, SystemExit) as exc:
        if reopen is not None:
            try:
                _restore(home, entry, target, before_restore)
                _clear(marker)
            except (Exception, SystemExit):
                raise SwitchError(UNFINISHED) from exc
            raise SwitchError(FAILED) from exc
        raise SwitchError(UNFINISHED) from exc
    _clear(marker)


def _clear(marker):
    """A marker left behind is settled by the next run, so removal may fail."""
    try:
        marker.unlink()
    except OSError:
        pass


def _restore(home, entry, target, before_restore):
    if before_restore is not None:
        before_restore()  # Refuse rollback until any newly launched app has exited.
    _blocks.restore(home, entry, target)
