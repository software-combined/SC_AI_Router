"""Stable Switch Codex entry point, copied into the router home.

Switch Codex.app runs this copy under the router's own Python, so the app
keeps working across updates and release pruning: it runs the current
release's packaging/codex_desktop_switch.py. A current release without Switch
Codex (after a rollback) gets one plain SCG Router message and nothing
changes. Self-contained on purpose: that older release may lack every other
Switch Codex module.
"""
import json
import runpy
import subprocess
import sys
from pathlib import Path

OLDER = 'Update SCG Router before using Switch Codex.'
BROKEN = 'Switch Codex could not start. Run SCG Router setup again.'


def release(home):
    """The current release directory, or None when the pointer is unreadable."""
    try:
        name = (home / 'current').read_text(encoding='utf-8').strip().split('/')[-1]
    except (OSError, ValueError):
        return None
    return home / 'releases' / name if name else None


def tell(message, icon, run=subprocess.run):
    """One SCG Router dialog whose only button is the safe one."""
    quote = lambda text: json.dumps(text, ensure_ascii=False)  # noqa: E731
    shown = '(POSIX file %s)' % quote(str(icon)) if icon.is_file() else 'note'
    script = ('display dialog %s with title "SCG Router" buttons {"Cancel"} default button '
              '"Cancel" cancel button "Cancel" with icon %s' % (quote(message), shown))
    try:
        run(['/usr/bin/osascript', '-e', script], capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        pass


def main(home=None, run=subprocess.run):
    home = Path(__file__).resolve().parent if home is None else Path(home)
    current = release(home)
    packaging = (current or home) / 'packaging'
    helper, icon = packaging / 'codex_desktop_switch.py', packaging / 'assets' / 'router-icon.png'
    if current is None or not helper.is_file():
        print(OLDER, file=sys.stderr)
        tell(OLDER, icon, run)
        return 1
    sys.argv = [str(helper), '--home', str(home)]
    try:
        runpy.run_path(str(helper), run_name='__main__')  # its own main() exits
    except Exception:
        print(BROKEN, file=sys.stderr)
        tell(BROKEN, icon, run)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
