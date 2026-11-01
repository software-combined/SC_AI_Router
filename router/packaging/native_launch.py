"""Permanent SCG Router application entry point; never follows runtime rollback."""
import json
import re
import runpy
import sys
from pathlib import Path

home = Path(__file__).resolve().parent
name = (home / 'setup-current').read_text().strip()
if not name or Path(name).name != name or (home / 'setup' / name).is_symlink():
    raise SystemExit('SCG Router setup files are unavailable. Open the installer again.')
resources = home / 'setup' / name
entry_name = 'native_setup.py'
helper = resources / 'control' / ('scg-router-menu.exe' if sys.platform == 'win32' else 'scg-router-menu')
# native_shortcuts.REMOVED: after removal, SCG Router opens setup instead of the menu.
if helper.is_file() and not sys.argv[1:] and not (home / '.router-removed').exists():
    entry_name = 'desktop_menu.py'
source = resources / 'router'
try:
    version = (home / 'control-version').read_text().strip()
    candidate = home / 'control' / version
    bundled = json.loads((resources / 'installer.json').read_text())['version']
    if (re.fullmatch(r'\d+(?:\.\d+){2,3}', version) and not candidate.is_symlink()
            and tuple(map(int, version.split('.'))) >= tuple(map(int, bundled.split('.')))
            and (candidate / 'packaging' / entry_name).is_file()):
        source = candidate
except (OSError, ValueError, KeyError, TypeError):
    pass
entry = source / 'packaging' / entry_name
if not entry.is_file():
    raise SystemExit('SCG Router setup files are unavailable. Open the installer again.')
sys.argv = [str(entry), '--resources', str(resources), '--home', str(home)] + sys.argv[1:]
runpy.run_path(str(entry), run_name='__main__')
