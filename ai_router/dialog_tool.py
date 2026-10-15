"""Find native dialog tools without importing the runtime (Python 3.9+)."""
import os
import re
import shutil
import sys
from pathlib import Path


def _retained(home):
    try:
        home = Path(home).expanduser().resolve()
        pointer = home / 'setup-current'
        if pointer.resolve().parent != home:
            return None
        name = pointer.read_text()
        if not re.fullmatch(r'\d+(?:\.\d+){2,3}-[0-9a-f]{16}\n?', name):
            return None
        base = home / 'setup'
        if base.resolve() != base:
            return None
        folder = (base / name.rstrip('\n')).resolve()
        wrapper = (folder / 'gui/bin/zenity').resolve()
        if (folder.is_relative_to(base) and wrapper.is_relative_to(folder)
                and wrapper.is_file() and os.access(wrapper, os.X_OK)):
            return str(wrapper)
    except (OSError, ValueError, RuntimeError):
        pass
    return None


def tool(platform_name=None, which=None, home=None):
    platform_name = sys.platform if platform_name is None else platform_name
    which = shutil.which if which is None else which
    if platform_name == 'darwin':
        return which('osascript')
    if platform_name == 'win32':
        return which('powershell') or which('powershell.exe')
    if platform_name.startswith('linux'):
        home = home or os.environ.get('ROUTER_HOME') or Path.home() / '.codex/mixed-model-router'
        return _retained(home) or which('zenity')
    return None
