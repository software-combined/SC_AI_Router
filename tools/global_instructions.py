"""Own one reversible global Codex rules block, independent of model entries."""
import os
import tempfile
from pathlib import Path

BEGIN = '<!-- BEGIN codex-model-router subagent rules -->'
END = '<!-- END codex-model-router subagent rules -->'
BLOCK = f'''{BEGIN}
## Subagents and tool discovery

- Subagent availability comes from the active Codex runtime, not the selected model's provider. Do not claim that OpenRouter models cannot delegate merely because a subagent tool is absent from the initial tool list.
- When delegation is allowed and useful, inspect the available tools. If the subagent tool is deferred, use the runtime's tool discovery or search tool to find and load it, then read its returned schema before calling it. Use the actual tool names, model choices, and arguments exposed by this runtime; do not guess APIs or substitute a new user-visible task for a subagent.
- Missing tools and denied permission are different. This guidance does not override an explicit no-delegation instruction, tool restriction, approval requirement, or sandbox boundary. If discovery finds no callable subagent tool, or the runtime denies the call, report that concrete limitation and continue locally where possible.
- Delegate only a bounded, independent subtask when the benefit justifies the overhead. Give the child its scope, authority, evidence requirements, and stop condition; prevent concurrent writes to the same files. The parent remains responsible for verifying the result. Do not authorize recursive delegation unless the user permits it.
{END}

'''


def prepare(codex_home, previous=None):
    """Validate ownership before the installer changes configuration."""
    override = Path(codex_home) / 'AGENTS.override.md'
    path = (override if override.exists() and override.read_text().strip()
            else Path(codex_home) / 'AGENTS.md').resolve()
    before = path.read_text() if path.exists() else ''
    if previous:
        if str(path) != previous['path'] or before.count(previous['block']) != 1:
            raise SystemExit('Global subagent rules changed; leaving instructions untouched.')
        after = before.replace(previous['block'], BLOCK, 1)
    elif before.count(BLOCK) == 1:
        after = before  # Recover a completed write if receipt creation was interrupted.
    elif BEGIN in before or END in before:
        raise SystemExit('Unowned global subagent rules; leaving instructions untouched.')
    else:
        after = BLOCK + before
    return path, before, after, {'path': str(path), 'block': BLOCK}


def write(path, before, after):
    if before == after:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(after)
        current = path.read_text() if path.exists() else ''
        if current != before:
            raise SystemExit('Global instructions changed concurrently; retry installation.')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def restore(receipt):
    if not receipt:
        return
    path = Path(receipt['path'])
    before = path.read_text() if path.exists() else ''
    if receipt['block'] not in before and BEGIN not in before and END not in before:
        return  # A previous restore or the owner already removed the complete block.
    if before.count(receipt['block']) != 1:
        raise SystemExit('Global subagent rules changed; leaving instructions untouched.')
    write(path, before, before.replace(receipt['block'], '', 1))
