"""Remove only this integration's settings, preserving unrelated Codex edits."""
import json
import os
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parent
receipt = json.loads((root / 'activation.json').read_text())
config = Path(receipt['config_path'])
before = config.read_text()
block = receipt['inserted_block']
if before.count(block) != 1:
    raise SystemExit('Router settings changed; leaving configuration untouched for manual review.')
updated = before.replace(block, '', 1)
temp = config.with_name('config.toml.mixed-router-restore')
fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as stream:
    stream.write(updated)
if config.read_text() != before:
    temp.unlink()
    raise SystemExit('Codex settings changed concurrently; retry the restore.')
os.replace(temp, config)
subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}/com.local.codex-mixed-model-router'], check=True)
print('OpenAI direct routing restored. Restart Codex to reload the original picker.')
