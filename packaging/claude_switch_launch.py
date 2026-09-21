"""Stable Switch Claude app entry point; follow the installed release pointer."""
import runpy
import sys
from pathlib import Path


def helper_path(home):
    try:
        name = (home / 'current').read_text().strip().split('/')[-1]
    except OSError:
        raise SystemExit('SCG Router needs setup again before switching Claude.')
    helper = home / 'releases' / name / 'packaging' / 'claude_desktop_switch.py'
    if not name or not helper.is_file():
        raise SystemExit('This SCG Router version does not include Switch Claude.')
    return helper


def main():
    home = Path(__file__).resolve().parent
    helper = helper_path(home)
    sys.argv = [str(helper), '--home', str(home)]
    runpy.run_path(str(helper), run_name='__main__')


if __name__ == '__main__':
    main()
