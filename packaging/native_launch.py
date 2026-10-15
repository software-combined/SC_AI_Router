"""Permanent SCG Router application entry point; never follows runtime rollback."""
import runpy
import sys
from pathlib import Path

home = Path(__file__).resolve().parent
name = (home / 'setup-current').read_text().strip()
if not name or Path(name).name != name:
    raise SystemExit('SCG Router setup files are unavailable. Open the installer again.')
resources = home / 'setup' / name
entry = resources / 'router' / 'packaging' / 'native_setup.py'
if not entry.is_file():
    raise SystemExit('SCG Router setup files are unavailable. Open the installer again.')
sys.argv = [str(entry), '--resources', str(resources), '--home', str(home)]
runpy.run_path(str(entry), run_name='__main__')
