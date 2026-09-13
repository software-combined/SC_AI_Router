"""Remove only this integration's settings, preserving unrelated Codex edits.

Runs only as a subprocess: the installer calls it with ROUTER_RESTORE_ONLY=1
to drop the managed block without touching the service. Importing this module
must stay inert -- an import-time run detaches the live router (2026-09-13),
so the body lives behind a __main__ guard and a test pins that it stays there.
"""
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(os.environ.get('ROUTER_HOME', Path.home() / '.codex' / 'mixed-model-router'))
    receipt = json.loads((root / 'activation.json').read_text())
    clients = receipt.get('clients', {})
    entry = clients.get('codex', receipt)
    config = Path(entry['config_path'])
    before = config.read_text()
    block = entry['inserted_block']
    if before.count(block) != 1:
        raise SystemExit('Router settings changed; leaving configuration untouched for manual review.')
    updated = before.replace(block, '', 1)
    # Global instructions are install-once: uninstall leaves them alone.
    temp = config.with_name('config.toml.mixed-router-restore')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(updated)
    if config.read_text() != before:
        temp.unlink()
        raise SystemExit('Codex settings changed concurrently; retry the restore.')
    os.replace(temp, config)
    if os.environ.get('ROUTER_RESTORE_ONLY') != '1':
        command = (['systemctl', '--user', 'stop', 'codex-mixed-model-router.service']
                   if sys.platform == 'linux' else
                   ['launchctl', 'bootout', f'gui/{os.getuid()}/com.local.codex-mixed-model-router'])
        subprocess.run(command, check=True)
    print('OpenAI direct routing restored. Restart Codex to reload the original picker.')


if __name__ == '__main__':
    main()
