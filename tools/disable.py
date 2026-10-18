"""Remove only this integration's settings, preserving unrelated Codex edits.

Runs only as a subprocess: the installer calls it with ROUTER_RESTORE_ONLY=1
to drop the managed block without touching the service. Importing this module
must stay inert -- an import-time run detaches the live router (2026-09-13),
so the body lives behind a __main__ guard and a test pins that it stays there.
"""
import importlib.util as _ilu
import json
import os
import subprocess
import sys
from pathlib import Path


def _packaging(name):
    """One installer module (the Codex activation adapter or its switch blocks)."""
    spec = _ilu.spec_from_file_location(
        'router_' + name,
        Path(__file__).resolve().parents[1] / 'packaging' / (name + '.py'))
    module = _ilu.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    root = Path(os.environ.get('ROUTER_HOME', Path.home() / '.codex' / 'mixed-model-router'))
    receipt = json.loads((root / 'activation.json').read_text())
    clients = receipt.get('clients', {})
    entry = clients.get('codex', receipt)
    # A switched Codex runs on the router's own provider: Switch Codex moves
    # it back to the ChatGPT subscription first, so a detach never does that
    # silently.
    _packaging('codex_switch_config').refuse_switched(root)
    config = Path(entry['config_path'])
    codex_config = _packaging('codex_config')
    before, updated = codex_config.removal_plan(config, entry)
    # Global instructions are install-once: uninstall leaves them alone.
    codex_config._owned.write(config, before, updated, _packaging('atomic_write').replace_text)
    # The Switch Codex app leaves with the attachment (never while switched:
    # that refused above). The restore already stands, so a stuck app only warns.
    try:
        _packaging('codex_switch_app').remove(root)
    except OSError:
        print('Switch Codex could not be removed; delete it from Applications.')
    if os.environ.get('ROUTER_RESTORE_ONLY') != '1':
        command = (['systemctl', '--user', 'stop', 'codex-mixed-model-router.service']
                   if sys.platform == 'linux' else
                   ['launchctl', 'bootout', f'gui/{os.getuid()}/com.local.codex-mixed-model-router'])
        subprocess.run(command, check=True)
    print('OpenAI direct routing restored. Restart Codex to reload the original picker.')


if __name__ == '__main__':
    main()
