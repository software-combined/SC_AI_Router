"""Owned, per-user application shortcuts for the retained native setup."""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_payload import load

BUNDLE_ID = 'com.softwarecombined.router.setup'


def _desktop_arg(value):
    text = str(value)
    if '\n' in text or '\r' in text:
        raise ValueError('unsafe shortcut path')
    for old, new in (('\\', '\\\\'), ('"', '\\"'), ('$', '\\$'), ('`', '\\`'), ('%', '%%')):
        text = text.replace(old, new)
    return '"' + text + '"'


def install(home, resources, python, run=subprocess.run):
    home, resources = Path(home), Path(resources)
    atomic = load('atomic_write')
    atomic.replace_text(home / 'setup-current', resources.name + '\n')
    atomic.replace_text(home / 'native_launch.py',
                        Path(__file__).with_name('native_launch.py').read_text())
    if sys.platform == 'darwin':
        load('claude_desktop_platform').install_mac_app(
            Path.home() / 'Applications' / 'SCG Router.app', BUNDLE_ID,
            str(python), home, 'native_launch.py', run=run)
    elif sys.platform == 'win32':
        _windows(home, resources, python, run)
    else:
        _linux(home, resources, python, atomic)


def _linux(home, resources, python, atomic):
    directory = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'applications'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (BUNDLE_ID + '.desktop')
    if target.exists() and ('X-SCGRouterHome=' + str(home)) not in target.read_text():
        raise ValueError('SCG Router shortcut belongs to another installation')
    icon = resources / 'router/packaging/assets/router-icon.png'
    text = ('[Desktop Entry]\nType=Application\nName=SCG Router\n'
            'Comment=Set up, check or repair SCG Router\nTerminal=false\n'
            'Exec=%s %s\nIcon=%s\nCategories=Utility;\nX-SCGRouterHome=%s\n'
            % (_desktop_arg(python), _desktop_arg(home / 'native_launch.py'), icon, home))
    atomic.replace_text(target, text)


def _windows(home, resources, python, run):
    directory = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Software Combined'
    directory.mkdir(parents=True, exist_ok=True)
    pythonw = Path(python).with_name('pythonw.exe')
    if not pythonw.is_file():
        raise ValueError('The bundled Windows setup application is incomplete.')
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    script = ("$ErrorActionPreference='Stop';"
              "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(%s);"
              "$s.TargetPath=%s;$s.Arguments=%s;$s.WorkingDirectory=%s;$s.IconLocation=%s;$s.Save()"
              % (quote(directory / 'SCG Router.lnk'), quote(pythonw),
                 quote(subprocess.list2cmdline([str(home / 'native_launch.py')])), quote(home),
                 quote(resources / 'router-icon.ico')))
    run(['powershell', '-NoProfile', '-WindowStyle', 'Hidden', '-Command', script],
        check=True, capture_output=True, timeout=30)
