"""Restore an absent Codex block under its active receipt, never recreate authority."""
import json
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_payload import load


def _notice(home, service, entry):
    event = entry.get('repair_notice')
    if isinstance(event, str) and re.fullmatch('[0-9a-f]{32}', event):
        try:
            service.notice.record_attachment(home, service.current_version(home), event)
            service.notice.show_pending(home)
        except (Exception, SystemExit):
            pass  # The receipt retains the event until a dialog can be offered.


def offer(home, service):
    """Present only after the installation lock has closed."""
    if any((Path(home) / name).exists() for name in ('.router-removed', 'codex-switch-pending.json')):
        return
    try:
        _notice(home, service, load('codex_config').codex_attachment(home))
    except (Exception, SystemExit):
        pass


def reconcile(home, service, *, apply=True):
    """Read-only preflight; applying a repair requires install.lock and repeats all checks."""
    home = Path(home)
    if any((home / name).exists() for name in ('.router-removed', 'codex-switch-pending.json')):
        return 'deferred'
    blocks, atomic = load('codex_switch_config'), load('atomic_write')
    codex, owned = blocks._codex, blocks._codex._owned
    receipt = codex.receipt_path_for(home)
    if not receipt.exists():
        return 'inactive'
    receipt_before = owned.read(receipt)
    doc = json.loads(receipt_before)
    if (not isinstance(doc, dict) or doc.get('version') != codex.RECEIPT_VERSION
            or not isinstance(doc.get('clients'), dict)):
        return 'conflict'
    entry = doc['clients'].get('codex')
    if entry is None:
        return 'inactive'
    if not isinstance(entry, dict) or not isinstance(entry.get('config_path'), str):
        return 'conflict'
    state = service._state.read(service._state.path(home))
    if not isinstance(state, dict):
        return 'conflict'
    if state.get('clients', 'codex' if state.get('client', 'codex') != 'none' else 'none') not in ('codex', 'both'):
        return 'inactive'
    saved, mode = entry.get('inserted_block'), entry.get('openai_mode')
    if (not isinstance(saved, str) or mode not in ('subscription', 'none')
            or not re.fullmatch('[0-9a-f]{64}', str(entry.get('previous_sha256', '')))):
        return 'conflict'
    owned.restore_evidence(entry, (codex.QUEUE_KEY, codex.EFFORTS_KEY))
    canonical = blocks.build(home, state, mode, 'model_catalog_json =' in saved, blocks.recorded(entry))
    without_picks = ''.join(line for line in saved.splitlines(keepends=True)
                            if codex._key(line) not in codex.PICK_KEYS)
    if without_picks.replace('\r\n', '\n') != canonical:
        return 'conflict'
    path = Path(entry['config_path'])
    if not path.is_absolute() or not path.parent.is_dir() or path.is_symlink() and not path.exists():
        return 'conflict'
    existed, before = path.exists(), codex._read_text(path)
    if codex.BEGIN in before or codex.END in before:
        owned.inspect(before, saved)
        return 'unchanged'
    proof = owned.inspect(before, saved, absent=True)
    health = service.health(state, timeout=1)
    if not health or health.get('status') != 'ok' or health.get('version') != service.current_version(home):
        return 'unhealthy'
    if not apply:
        return 'repairable'
    block = ''.join(line for line in saved.splitlines(keepends=True)
                    if codex._key(line) not in proof['picks'])
    after = block + '\n' + before
    updated = dict(entry, inserted_block=block, repair_notice=uuid.uuid4().hex)
    doc['clients']['codex'] = updated
    if existed:
        owned.write(path, before, after, atomic.replace_text)
    else:
        owned.inspect(after)
        atomic.replace_text(path, after, newline='', expected=None)
        if owned.read(path) != after:
            raise OSError('configuration readback failed')
    try:
        atomic.replace_text(receipt.resolve(), json.dumps(doc, indent=2) + '\n',
                            newline='', expected=receipt_before)
        if codex.codex_attachment(home) != updated:
            raise OSError('receipt readback failed')
        owned.inspect(owned.read(path), block)
    except (Exception, SystemExit):
        if existed:
            owned.write(path, after, before, atomic.replace_text)
        else:
            atomic.remove(path, expected=after)
        raise
    return 'repaired'
