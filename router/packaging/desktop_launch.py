"""Stable menu launcher; retained setup resources survive inference rollback."""
import json
import re
import runpy
import sys
from pathlib import Path


def main():
    home = Path(__file__).resolve().parent
    name = (home / 'setup-current').read_text().strip()
    if not name or Path(name).name != name or (home / 'setup' / name).is_symlink():
        raise SystemExit('Open SCG Router setup again to restore the menu.')
    resources = home / 'setup' / name
    source = resources / 'router'
    try:
        version = (home / 'control-version').read_text().strip()
        candidate = home / 'control' / version
        bundled = json.loads((resources / 'installer.json').read_text())['version']
        if (re.fullmatch(r'\d+(?:\.\d+){2,3}', version) and not candidate.is_symlink()
                and tuple(map(int, version.split('.'))) >= tuple(map(int, bundled.split('.')))
                and (candidate / 'packaging/desktop_menu.py').is_file()):
            source = candidate
    except (OSError, ValueError, KeyError, TypeError):
        pass
    entry = source / 'packaging/desktop_menu.py'
    if not entry.is_file():
        raise SystemExit('Open SCG Router setup again to restore the menu.')
    sys.argv = [str(entry), '--home', str(home), '--resources', str(resources)] + sys.argv[1:]
    runpy.run_path(str(entry), run_name='__main__')


if __name__ == '__main__':
    main()
