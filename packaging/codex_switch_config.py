"""Switch Codex's managed config blocks, rebuilt from the activation receipt.

Codex desktop 26.917.51856 and later disables Send once the ChatGPT allowance
runs out, but only while its active provider needs OpenAI sign-in, and the
default subscription block keeps Codex on its built-in provider. Switch Codex
writes one of two other variants between the same markers:

- `switched`, root keys only: the active provider becomes `scg_router`, which
  needs no OpenAI sign-in and marks every request with the route header, and
  the picker reads the routed-only list. `openai_base_url` stays, so threads
  started on the built-in provider still resume through the router, and
  approvals stay with the person, as in every managed block.
- `switched_back`: the default block plus `scg_router` with sign-in required,
  so threads started while switched still resume.

The Codex receipt entry records the variant beside the block it describes
(`variant`, absent until the first switch) and every attach rebuilds the
recorded one: an update never switches Codex either way, and a never-switched
install keeps today's default block byte for byte. `current`, `switch` and
`restore` are the Switch Codex API. Detach, uninstall and rollback refuse
while Codex is switched: Switch Codex moves Codex back to the ChatGPT
subscription first, so neither detach nor uninstall does that silently, and
an older release may have no way to switch back.

Python 3.9-safe, stdlib only and inert on import: the installer, the remover
and Switch Codex load it by path.
"""
import importlib.util
import json
from pathlib import Path

DEFAULT, SWITCHED, SWITCHED_BACK = 'default', 'switched', 'switched_back'
VARIANTS = (DEFAULT, SWITCHED, SWITCHED_BACK)
PROVIDER = 'scg_router'
# The router owns these two names (ai_router/codex_route.HEADER and
# ai_router/routed_models.NAME). The installer never imports the router
# package, so these are copies and a test pins each one to its owner.
HEADER = 'x-scg-codex-route'
ROUTED_LIST = 'routed-models.json'

# Plain wording (AGENTS.md section 4a): Switch Codex shows these as they are.
SWITCHED_REFUSAL = ('Codex is switched to OpenRouter models. Open Switch Codex and '
                    'switch back to your ChatGPT subscription, then try again.')
NOT_CONNECTED = 'Codex is not connected to SCG Router. Run setup again.'
EDITED = ('Codex settings were changed by hand, so SCG Router left them '
          'unchanged. Contact your administrator.')


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_HERE = Path(__file__).resolve().parent
_codex = _load('router_switch_codex_config', _HERE / 'codex_config.py')
_atomic = _load('router_switch_atomic_write', _HERE / 'atomic_write.py')
_codex._atomic_write = _atomic


def recorded(entry):
    """The variant a Codex receipt entry records; a missing one means never switched."""
    variant = (entry or {}).get('variant', DEFAULT)
    if variant not in VARIANTS:
        raise SystemExit(EDITED)
    return variant


def build(home, state, mode, static_catalogue, variant):
    """The managed block for `variant`; the default is codex_config's own block."""
    block = _codex.build_block(home, state, mode, static_catalogue)
    if variant == DEFAULT:
        return block
    # The URL codex_config.build_block writes; a test pins the two together.
    url = 'http://127.0.0.1:%s/%s/backend-api/codex' % (state['port'], state['token'])
    provider = ('model_providers.%s = { name = "SC router", base_url = "%s", '
                'wire_api = "responses", requires_openai_auth = ' % (PROVIDER, url))
    if variant == SWITCHED:
        return ''.join((
            _codex.BEGIN + '\n',
            'openai_base_url = "%s"\n' % url,
            'model_provider = "%s"\n' % PROVIDER,
            # Forward slashes, as in codex_config: TOML reads backslashes as escapes.
            'model_catalog_json = "%s/%s"\n' % (Path(home).as_posix(), ROUTED_LIST),
            # Attach moves the owner's own line into the receipt, and this
            # route refuses the ChatGPT model an automatic reviewer would use.
            'approvals_reviewer = "user"\n',
            provider + 'false, http_headers = { "%s" = "routed" } }\n' % HEADER,
            _codex.END + '\n'))
    if 'model_providers.%s.' % PROVIDER in block:
        # The no-subscription block already defines the provider, sign-in off;
        # a second definition would make the whole file unreadable.
        return block
    return block.replace(_codex.END, provider + 'true }\n' + _codex.END, 1)


def current(home):
    """This install's variant, or None when Codex is not attached."""
    entry = _codex.codex_attachment(home)
    return recorded(entry) if entry.get('inserted_block') else None


def refuse_switched(home):
    """Stop a detach, uninstall or rollback while Codex is switched.

    An unreadable receipt proves no switch: rollback, the recovery path, never
    read it before, and the other callers keep their own receipt checks.
    """
    try:
        variant = current(home)
    except (OSError, ValueError):
        return
    if variant == SWITCHED:
        raise SystemExit(SWITCHED_REFUSAL)


def managed_block(entry):
    """The managed block as config.toml holds it now, latest model pick included.

    A block edited by hand, missing or doubled refuses, as `switch` does.
    """
    config_path = Path(entry['config_path'])
    text = config_path.read_text() if config_path.exists() else ''
    live = _codex.live_block(text, entry['inserted_block'])
    if text.count(live) != 1:
        raise SystemExit(EDITED)
    return live


def switch(home, variant):
    """Rewrite Codex's managed block as `variant` and record it in the receipt.

    Only `switched` and `switched_back` can be set. config.toml is replaced
    atomically, then the receipt; when the receipt cannot be written the
    config is put back as it was. The owner's model pick is carried, as on
    every attach. The caller holds the installer lock (`service.install_lock`)
    so an update cannot interleave. Refuses with a plain SystemExit when Codex
    is not attached or its managed block was edited by hand.
    """
    if variant not in (SWITCHED, SWITCHED_BACK):
        raise ValueError('Switch Codex sets %s or %s, not %r'
                         % (SWITCHED, SWITCHED_BACK, variant))
    entry = _codex.codex_attachment(home)
    if not entry.get('inserted_block'):
        raise SystemExit(NOT_CONNECTED)
    recorded(entry)  # refuses a variant this release does not know
    config_path = Path(entry['config_path'])
    live = managed_block(entry)
    state = json.loads((Path(home) / 'mixed-router-state.json').read_text())
    # Updates never pass --static-catalogue, so neither does a switch.
    block = build(home, state, entry.get('openai_mode'), False, variant)
    block = _codex.preserve_picker_selection(config_path, live, block)
    block = _codex.seed_picker_selection(config_path, live, block)
    original, removed = _codex.replace_config_block(config_path, block, live)
    record = dict(entry, inserted_block=block, variant=variant)
    if removed:  # owner root lines, kept with earlier ones as attach_config does
        kept = (entry.get('reviewer') or {}).get('removed') or []
        record['reviewer'] = {'removed': kept + removed}
    try:
        _codex.write_client_receipt(home, 'codex', record)
    except BaseException:
        _atomic.replace_text(config_path, original)
        raise


def restore(home, previous, variant):
    """Undo `switch(home, variant)`: the block and entry go back to `previous`.

    `previous` is the Codex receipt entry from before the switch. The switch
    may have written neither file, only config.toml, or both, so the block
    between the markers may be the old one, the recorded one or the one the
    switch builds; anything else is a hand edit and refuses, as `switch` does.
    """
    config_path = Path(previous['config_path'])
    text = config_path.read_text() if config_path.exists() else ''
    state = json.loads((Path(home) / 'mixed-router-state.json').read_text())
    for block in (previous['inserted_block'],
                  _codex.codex_attachment(home).get('inserted_block'),
                  build(home, state, previous.get('openai_mode'), False, variant)):
        live = _codex.live_block(text, block)
        if live and text.count(live) == 1:
            break
    else:
        raise SystemExit(EDITED)
    kept = (previous.get('reviewer') or {}).get('removed') or []
    # Owner root lines the switch set aside go back with the old block;
    # restore_reviewer skips any key that block sets itself.
    moved = [line for line in ((_codex.codex_attachment(home).get('reviewer') or {})
                               .get('removed') or []) if line not in kept]
    if live != previous['inserted_block']:
        _, removed = _codex.replace_config_block(config_path, previous['inserted_block'], live)
        if removed:
            previous = dict(previous, reviewer={'removed': kept + removed})
    if moved:
        text = config_path.read_text()
        _atomic.replace_text(config_path, _codex.restore_reviewer(text, {'removed': moved}))
    _codex.write_client_receipt(home, 'codex', previous)
