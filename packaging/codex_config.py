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

# Codex desktop preferences this installer owns, in the config's [desktop]
# table the client writes itself through config/batchWrite: Max in, Ultra out.
DESKTOP_TABLE = '[desktop]'
QUEUE_KEY = 'followUpQueueMode'
EFFORTS_KEY = 'enabled-reasoning-efforts'
QUEUE_VALUE = 'steer'
CLIENT_DEFAULT_EFFORTS = ('low', 'medium', 'high', 'xhigh', 'ultra', 'persistent')
EFFORT_ORDER = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max',
                'ultra', 'persistent')

# The model a fresh install starts on, install-once for the same reason.
DEFAULT_MODEL = 'deepseek/deepseek-v4.1-flash'
DEFAULT_MODEL_EFFORT = 'max'
# Root keys Codex writes for the owner's pick, in the shape the client uses.
PICK_KEYS = ('model', 'model_reasoning_effort')

# Atomic text writer, injected by install.py via service.load() (Plan 123):
# no spec_from_file_location copy lives here, so direct spec-loads of this
# file (portability/receipt tests) only need it when replacing blocks.
_atomic_write = None


def _replace_text(path, text):
    """Atomic sibling write through the injected helper."""
    if _atomic_write is None:  # pragma: no cover - install.py always injects
        raise RuntimeError('atomic writer not injected; load via install.py')
    _atomic_write.replace_text(path, text)


def build_block(home, state, mode, static_catalogue=False):
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
                # Dotted keys, not a [table]: owner keys after END stay root.
                'model_providers.scg_router.name = "SC router"\n'
                f'model_providers.scg_router.base_url = "{url}"\n'
                'model_providers.scg_router.wire_api = "responses"\n'
                + END + '\n')
    return (BEGIN + '\n'
            f'openai_base_url = "{url}"\n'
            + (catalog_line if static_catalogue else '')
            + 'approvals_reviewer = "user"\n' + END + '\n')


def _read_text(path):
    """Config text, or '' when the file is missing."""
    path = Path(path)
    return path.read_text() if path.exists() else ''


def _insert_root_lines(block, extra):
    """Block text with root keys placed before any table it declares."""
    lines = block.splitlines()
    at = next((index for index, line in enumerate(lines)
               if line.strip().startswith('[')), len(lines) - 1)
    lines[at:at] = extra
    return '\n'.join(lines) + '\n'


def managed_efforts(existing=None):
    """Managed effort list: the client's own entries, Max in, Ultra out."""
    entries = [lv for lv in (existing or CLIENT_DEFAULT_EFFORTS) if lv != 'ultra']
    if 'max' not in entries:
        entries.append('max')
    return ([lv for lv in EFFORT_ORDER if lv in entries]
            + [lv for lv in entries if lv not in EFFORT_ORDER])


def _desktop_table(lines):
    """(header index, end index, ambiguous) for the [desktop] table."""
    heads = [index for index, line in enumerate(lines)
             if line.split('#', 1)[0].strip().replace(' ', '') == DESKTOP_TABLE]
    if len(heads) > 1:
        return None, None, True
    if not heads:
        return None, None, False
    rest = [index for index in range(heads[0] + 1, len(lines))
            if lines[index].strip().startswith('[')]
    return heads[0], (rest[0] if rest else len(lines)), False


def _key(line):
    """The key one assignment line sets, unquoted."""
    return line.split('=', 1)[0].strip().strip('"\'')


def _key_line(lines, start, end, key):
    """Line index of one key inside a table; 'duplicate' when repeated."""
    hits = [index for index in range(start + 1, end) if _key(lines[index]) == key]
    if len(hits) > 1:
        return 'duplicate'
    return hits[0] if hits else None


def _read_value(line):
    """One assignment's value: names, a quoted string, else None.

    None means the line is not a single-line literal this module can
    rewrite (a multi-line array, say), and every caller refuses on it.
    """
    raw = line.split('=', 1)[1].split('#', 1)[0].strip()
    if raw.startswith('[') and raw.endswith(']'):
        return [part.strip().strip('"\'') for part in raw[1:-1].split(',')
                if part.strip()]
    if len(raw) > 1 and raw[:1] in ('"', "'") and raw.endswith(raw[:1]):
        return raw[1:-1]
    return None


def _render(key, value):
    """One assignment line in the shape the client's own writer emits."""
    if isinstance(value, (list, tuple)):
        return key + ' = [' + ', '.join('"%s"' % item for item in value) + ']'
    return key + ' = ' + json.dumps(value)


def desktop_preferences(text, previous=None):
    """(text, record) with the managed desktop preferences applied.

    The record holds the values written and the values they replaced (None
    when a key was absent; a `previous` record carried from an earlier
    attach wins). A table or value this module cannot rewrite safely
    refuses the edit with (text, {}): a second definition, or a value
    misread out of a multi-line literal, would leave the config unreadable.
    """
    lines = text.splitlines()
    header, end, ambiguous = _desktop_table(lines)
    found = {} if header is None else {
        key: _key_line(lines, header, end, key) for key in (QUEUE_KEY, EFFORTS_KEY)}
    current = {key: _read_value(lines[index]) for key, index in found.items()
               if isinstance(index, int)}
    if ambiguous or 'duplicate' in found.values() or None in current.values():
        return text, {}
    written = {QUEUE_KEY: QUEUE_VALUE,
               EFFORTS_KEY: managed_efforts(current.get(EFFORTS_KEY))}
    record = {'written': written,
              'previous': previous or {key: current.get(key) for key in written}}
    if header is None:
        lines.append(DESKTOP_TABLE)
        end = len(lines)
    for key, value in written.items():
        index = found.get(key)
        if index is None:
            lines.insert(end, _render(key, value))
            end += 1
        else:
            lines[index] = _render(key, value)
    return '\n'.join(lines) + '\n', record


def restore_desktop(text, record):
    """Put back the values an attach replaced; later owner edits stay.

    Only a value still equal to the managed one is restored, and a table
    the attach created is dropped again once it holds nothing else.
    """
    written = (record or {}).get('written') or {}
    previous = (record or {}).get('previous') or {}
    if not written:
        return text
    lines = text.splitlines()
    header, end, ambiguous = _desktop_table(lines)
    if header is None or ambiguous:
        return text
    for key, value in written.items():
        index = _key_line(lines, header, end, key)
        if not isinstance(index, int):
            continue
        current = _read_value(lines[index])
        if current is None:
            continue
        same = (list(current) == list(value) if isinstance(value, list)
                else current == value)
        if not same:
            continue
        if previous.get(key) is None:
            del lines[index]
            end -= 1
        else:
            lines[index] = _render(key, previous[key])
    if not any('=' in line for line in lines[header + 1:end]):
        del lines[header]
    return '\n'.join(lines) + '\n' if text.endswith('\n') else '\n'.join(lines)


def restore_reviewer(text, record):
    """Re-add the owner root lines removed at attach (the receipt's reviewer record).

    Lines land before the first table header, so they come back as root keys
    (appending would nest them under a trailing table): one per key, the
    latest recorded, never over a key already at root.
    """
    lines = text.splitlines()
    at = next((index for index, line in enumerate(lines)
               if line.strip().startswith('[')), len(lines))
    present = {_key(line) for line in lines[:at] if '=' in line}
    latest = {_key(line): line for line in (record or {}).get('removed') or []}
    removed = [line for key, line in latest.items() if key not in present]
    if not removed:
        return text
    lines[at:at] = removed
    joined = '\n'.join(lines)
    return joined + '\n' if text.endswith('\n') or not text else joined


def seed_picker_selection(config_path, previous_block, block):
    """Seed the default model into a fresh managed block, install-once.

    A config that already names a model keeps it: a second root-level
    `model` key would make the whole file unreadable.
    """
    if _picks(block):
        return block
    text = _read_text(config_path)
    if previous_block:
        text = text.replace(previous_block, '', 1)
    if any(_key(line) in PICK_KEYS for line in text.splitlines() if '=' in line):
        return block
    return _insert_root_lines(block, [_render('model', DEFAULT_MODEL),
                                      _render('model_reasoning_effort',
                                              DEFAULT_MODEL_EFFORT)])


def _without_picks(block):
    """Block lines minus the owner's model pick, which Codex rewrites."""
    return [line for line in block.splitlines()
            if line.split('=', 1)[0].strip() not in ('model', 'model_reasoning_effort')]


def _picks(text):
    """The model lines in one region, one per key: {key: line}.

    A repeated key keeps its last line, so a config that carries a stale
    duplicate is rewritten with a single definition rather than refused.
    """
    picks = {}
    for line in text.splitlines():
        key = _key(line)
        if '=' not in line or key not in PICK_KEYS:
            continue
        picks[key] = line
    return picks


def live_block(text, recorded):
    """The managed block as this config now holds it.

    Codex rewrites the owner's model pick inside the block, so the copy in
    the receipt goes stale; that live region is the one an update replaces
    and a detach removes. Only that drift is accepted: any other change
    keeps the recorded block, so the hand-edit refusal still stands.
    """
    if recorded and recorded in text:
        return recorded
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        return recorded
    live = text[text.index(BEGIN):text.index(END) + len(END) + 1]
    if _without_picks(live) != _without_picks(recorded or ''):
        return recorded
    return live


def attach_config(config_path, block, previous=None):
    """Insert the managed block and apply the managed desktop preferences.

    `previous` is the codex attachment in the receipt; its desktop record
    keeps the owner's original values across updates. Returns (block,
    before, desktop, reviewer) for the receipt, where reviewer holds every
    owner root line an attach has removed, carried across updates.
    """
    recorded = (previous or {}).get('inserted_block')
    previous_block = live_block(_read_text(config_path), recorded)
    block = preserve_picker_selection(config_path, previous_block, block)
    block = seed_picker_selection(config_path, previous_block, block)
    before, removed = replace_config_block(config_path, block, previous_block)
    current = _read_text(config_path)
    carried = ((previous or {}).get('desktop') or {}).get('previous')
    updated, desktop = desktop_preferences(current, carried)
    if desktop and updated != current:
        _replace_text(config_path, updated)
    elif not desktop:
        print('Codex [desktop] preferences skipped: table ambiguous or repeated')
    kept = (((previous or {}).get('reviewer')) or {}).get('removed') or []
    reviewer = {'removed': kept + removed} if removed else (previous or {}).get('reviewer')
    return block, before, desktop, reviewer


def default_mode(config_path=None):
    """Install-time default when neither the flag nor stored state speaks.

    Codex keeps its own login beside its configuration. A readable store
    with no ChatGPT tokens (an API-key-only or signed-out client) means
    this install serves no subscription, so the picker never offers rows
    that cannot run. Only the presence of that block is read, never a
    token value, and a missing or unreadable store keeps the historical
    default: an unknown client is not a subscription-less one.
    """
    path = (Path.home() / '.codex' / 'config.toml' if config_path is None
            else Path(config_path))
    try:
        doc = json.loads((path.parent / 'auth.json').read_text())
    except (OSError, ValueError):
        return 'subscription'
    if not isinstance(doc, dict):
        return 'subscription'
    tokens = doc.get('tokens')
    return 'subscription' if isinstance(tokens, dict) and tokens else 'none'


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
        before = _read_text(config_path)
    except OSError:
        return block
    if previous_block not in before:
        return block
    # Spacing- and indent-insensitive: Codex may rewrite the line's shape.
    picks = _picks(previous_block)
    if not picks:
        return block
    return _insert_root_lines(block, list(picks.values()))


def replace_config_block(config_path, block, previous_block=None):
    """Insert or replace the marked block; refuse hand-edited markers.

    Returns (before, removed): the prior config text and the owner root
    lines dropped for uniqueness, so the receipt can restore them on detach.
    """
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
    # A second root definition of a block key makes the config unreadable, so owner
    # root copies are dropped for detach to restore; owner table lines stay.
    owned = {_key(line) for line in block.splitlines() if '=' in line}
    head, _, tail = after.partition(block)
    removed = []

    def _root_unique(text):
        kept, rooted = [], True
        for line in text.splitlines(keepends=True):
            rooted = rooted and not line.strip().startswith('[')
            if rooted and '=' in line and _key(line) in owned:
                removed.append(line.rstrip('\r\n'))
            else:
                kept.append(line)
        return ''.join(kept)
    after = _root_unique(head) + block + _root_unique(tail)
    home = config_path.parent
    if not config_path.exists():
        home.mkdir(parents=True, exist_ok=True)
    _replace_text(config_path, after)
    try:
        os.chmod(config_path, 0o600)
    except OSError:
        pass
    return before, removed


RECEIPT_VERSION = 2
RECEIPT_NAME = 'activation.json'


def read_receipt(home):
    """Versioned activation record: {version, clients: {name: attachment}}.

    Legacy flat receipts (config path plus block, no version) import as the
    `codex` attachment without losing restore information; nothing is
    rewritten on read.
    """
    receipt_path = receipt_path_for(home)
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


def parse_snapshot(text):
    """Prior-values dict from a receipt snapshot; {} when not a JSON object."""
    try:
        previous = json.loads(text)
    except ValueError:
        return {}
    return previous if isinstance(previous, dict) else {}


def receipt_path_for(home):
    """The one activation receipt under a router home (single-name owner)."""
    return Path(home) / RECEIPT_NAME


def write_client_receipt(home, client, entry):
    """Record one client attachment; other attachments are preserved."""
    # The single activation.json writer (Plan 095): entry builders stay in
    # each adapter, this function stays dumb. Always stamps the version so
    # a fresh single-client home reads back as attached, never legacy.
    doc = read_receipt(home) or {'version': RECEIPT_VERSION, 'clients': {}}
    doc['version'] = RECEIPT_VERSION
    doc.setdefault('clients', {})[client] = entry
    receipt_path = receipt_path_for(home)
    _replace_text(receipt_path, json.dumps(doc, indent=2) + '\n')
    try:
        os.chmod(receipt_path, 0o600)
    except OSError:
        pass


def write_receipt(home, config_path, block, rules_receipt, mode, before='',
                  client='codex', desktop=None, variant=None, reviewer=None):
    """Record one client attachment; existing attachments are preserved."""
    entry = {'config_path': str(config_path), 'inserted_block': block,
             'openai_mode': mode,
             'previous_sha256': hashlib.sha256(before.encode()).hexdigest()}
    if desktop:
        # Managed Codex desktop preferences: the values written and the
        # values they replaced, so tools/disable.py can put them back.
        entry['desktop'] = desktop
    if variant:
        entry['variant'] = variant  # the Switch Codex block (codex_switch_config)
    if reviewer:
        # Owner root lines set aside because the block sets the same key,
        # restored by tools/disable.py one per key.
        entry['reviewer'] = reviewer
    if rules_receipt:
        # Legacy installs recorded the managed global-instructions block;
        # install-once starters record nothing, so the key stays absent.
        entry['global_instructions'] = rules_receipt
    write_client_receipt(home, client, entry)


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
    receipt_path = receipt_path_for(home)
    if clients:
        _replace_text(receipt_path, json.dumps(doc, indent=2) + '\n')
    else:
        try:
            receipt_path.unlink()
        except OSError:
            pass
    return True
