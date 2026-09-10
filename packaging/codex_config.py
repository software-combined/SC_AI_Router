"""Codex client activation adapter (Plan 063). Python 3.9-safe helper.

Owns Codex block generation, selected-model preservation, and activation
receipt handling. Loaded through the installer's explicit file-import
pattern and shipped in the release bundle. No runtime/protocol import
from this helper.
"""
import hashlib
import json
import os
from pathlib import Path

BEGIN = '# BEGIN local mixed model picker'
END = '# END local mixed model picker'

# Atomic text writer, injected by install.py via service.load() (Plan 123):
# no spec_from_file_location copy lives here, so direct spec-loads of this
# file (portability/receipt tests) only need it when replacing blocks.
_atomic_write = None


def _replace_text(path, text):
    """Atomic sibling write through the injected helper."""
    if _atomic_write is None:  # pragma: no cover - install.py always injects
        raise RuntimeError('atomic writer not injected; load via install.py')
    _atomic_write.replace_text(path, text)


def build_block(home, state, mode):
    """Managed Codex config block for this install and subscription mode."""
    # Forward slashes: a TOML basic string treats backslashes as escapes, so
    # a native Windows path would make the whole config unreadable to Codex.
    catalog_line = f'model_catalog_json = "{Path(home).as_posix()}/mixed-models.json"\n'
    url = f'http://127.0.0.1:{state["port"]}/{state["token"]}/backend-api/codex'
    if mode == 'none':
        return (BEGIN + '\n'
                'model_provider = "scg_router"\n'
                + catalog_line +
                'approvals_reviewer = "user"\n'
                '[model_providers.scg_router]\n'
                'name = "SC router"\n'
                f'base_url = "{url}"\n'
                'wire_api = "responses"\n'
                + END + '\n')
    return (BEGIN + '\n'
            f'openai_base_url = "{url}"\n'
            + catalog_line + END + '\n')


def preserve_picker_selection(config_path, previous_block, block):
    """Carry owner-chosen picker lines across managed block rewrites.

    The installer owns the connection lines (base URL, catalogue) but the
    owner picks `model` / `model_reasoning_effort` inside the same marked
    block. A plain rewrite would silently reset that choice on every
    update, so re-emit those lines from the previous owned block.
    """
    if not previous_block:
        return block
    try:
        before = Path(config_path).read_text() if Path(config_path).exists() else ''
    except OSError:
        return block
    if previous_block not in before:
        return block
    keep = [line for line in previous_block.splitlines()
            if line.startswith('model = ') or line.startswith('model_reasoning_effort = ')]
    if not keep:
        return block
    lines = block.splitlines()
    lines[-1:-1] = keep
    return '\n'.join(lines) + '\n'


def replace_config_block(config_path, block, previous_block=None):
    """Insert or replace the marked block; refuse hand-edited markers."""
    config_path = Path(config_path)
    before = config_path.read_text() if config_path.exists() else ''
    if previous_block and previous_block in before:
        if before.count(previous_block) != 1:
            raise SystemExit('config block was edited by hand; run tools/disable.py first')
        after = before.replace(previous_block, block, 1)
    elif BEGIN in before or END in before:
        raise SystemExit('config block was edited by hand; run tools/disable.py first')
    else:
        after = block + '\n' + before
    home = config_path.parent
    if not config_path.exists():
        home.mkdir(parents=True, exist_ok=True)
    _replace_text(config_path, after)
    try:
        os.chmod(config_path, 0o600)
    except OSError:
        pass
    return before


RECEIPT_VERSION = 2


def read_receipt(home):
    """Versioned activation record: {version, clients: {name: attachment}}.

    Legacy flat receipts (config path plus block, no version) import as the
    `codex` attachment without losing restore information; nothing is
    rewritten on read.
    """
    receipt_path = Path(home) / 'activation.json'
    if not receipt_path.exists():
        return {}
    doc = json.loads(receipt_path.read_text())
    if not isinstance(doc, dict):
        return {}
    if doc.get('version') == RECEIPT_VERSION and isinstance(doc.get('clients'), dict):
        return doc
    if 'inserted_block' in doc and 'config_path' in doc:
        entry = {k: doc[k] for k in ('config_path', 'inserted_block', 'global_instructions',
                                     'openai_mode', 'previous_sha256') if k in doc}
        return {'version': RECEIPT_VERSION, 'clients': {'codex': entry}}
    return {}


def write_receipt(home, config_path, block, rules_receipt, mode, before='', client='codex'):
    """Record one client attachment; existing attachments are preserved."""
    receipt_path = Path(home) / 'activation.json'
    doc = read_receipt(home) or {'version': RECEIPT_VERSION, 'clients': {}}
    entry = {'config_path': str(config_path), 'inserted_block': block,
             'openai_mode': mode,
             'previous_sha256': hashlib.sha256(before.encode()).hexdigest()}
    if rules_receipt:
        # Legacy installs recorded the managed global-instructions block;
        # install-once starters record nothing, so the key stays absent.
        entry['global_instructions'] = rules_receipt
    doc.setdefault('clients', {})[client] = entry
    receipt_path.write_text(json.dumps(doc, indent=2) + '\n')
    try:
        os.chmod(receipt_path, 0o600)
    except OSError:
        pass


def codex_attachment(home):
    """The codex attachment, or {} when never attached."""
    return read_receipt(home).get('clients', {}).get('codex', {})


def drop_client(home, client):
    """Forget one attachment; returns True when anything was removed.

    Removes the receipt file itself when no attachments remain, so a
    fully detached home reads the same as a never-attached one.
    """
    doc = read_receipt(home)
    clients = doc.get('clients', {})
    if client not in clients:
        return False
    del clients[client]
    receipt_path = Path(home, 'activation.json')
    if clients:
        receipt_path.write_text(json.dumps(doc, indent=2) + '\n')
    else:
        try:
            receipt_path.unlink()
        except OSError:
            pass
    return True
