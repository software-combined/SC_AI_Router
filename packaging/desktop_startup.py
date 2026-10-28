"""Owned, per-user menu startup; an explicit opt-out survives repair and updates."""
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_payload import OwnershipConflict, load, metadata

IDENTITY = 'com.softwarecombined.router.menu'


def enabled(home, *, platform_name=None):
    default = (platform_name or sys.platform) == 'win32'
    try:
        doc = json.loads((Path(home) / 'desktop-preferences.json').read_text())
        value = doc.get('autostart')
        return value if type(value) is bool else default
    except FileNotFoundError:
        return True
    except (OSError, ValueError, AttributeError):
        return default


def _owned(path, home, kind):
    if not path.exists():
        return
    if path.is_symlink():
        raise OwnershipConflict('Startup entry belongs to another application')
    if kind == 'darwin':
        matches = plistlib.loads(path.read_bytes()).get('SCGRouterHome') == str(home)
    else:
        matches = ('X-SCGRouterHome=' + str(home) + '\n') in path.read_text()
    if not matches:
        raise OwnershipConflict('Startup entry belongs to another application')


def windows_target(user_home=None):
    base = Path(os.environ.get('APPDATA') or Path(user_home or Path.home()) / 'AppData/Roaming')
    return base / 'Microsoft/Windows/Start Menu/Programs/Startup/SCG Router.lnk'


def _windows(home, python, on, user_home, run):
    target = windows_target(user_home)
    directory = target.parent
    directory.mkdir(parents=True, exist_ok=True)
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    arguments = subprocess.list2cmdline([str(home / 'desktop_launch.py'), '--autostart'])
    marker = IDENTITY + ':' + str(home)
    script = ("$ErrorActionPreference='Stop';$w=New-Object -ComObject WScript.Shell;"
              "$s=$w.CreateShortcut(%s);if((Test-Path -LiteralPath %s) -and "
              "$s.Description -ne %s){throw 'ownership'};" %
              (quote(target), quote(target), quote(marker)))
    if on:
        script += ('$s.TargetPath=%s;$s.Arguments=%s;$s.Description=%s;$s.Save()' %
                   (quote(python), quote(arguments), quote(marker)))
    else:
        script += 'if(Test-Path -LiteralPath %s){Remove-Item -LiteralPath %s}' % (quote(target), quote(target))
    run(['powershell', '-NoProfile', '-WindowStyle', 'Hidden', '-Command', script],
        check=True, capture_output=True, timeout=30,
        **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))


def configure(home, resources, on, *, platform_name=None, user_home=None, run=subprocess.run):
    # Installation takes its lock first; startup never acquires it in reverse.
    with load('service').install_lock(Path(home), '.desktop-startup.lock') as held:
        if not held:
            raise ValueError('SCG Router startup is already changing. Try again shortly.')
        return _configure(home, resources, enabled(home, platform_name=platform_name) if on is None else on,
                          platform_name=platform_name, user_home=user_home, run=run, save=on is not None)


def _configure(home, resources, on, *, platform_name=None, user_home=None, run=subprocess.run, save=True):
    home, resources = Path(home).resolve(), Path(resources).resolve()
    platform_name, user_home = platform_name or sys.platform, Path(user_home or Path.home())
    if type(on) is not bool or any(c in str(home) for c in '\r\n'):
        raise ValueError('Invalid menu preference')
    doc = metadata(resources)
    python = resources / 'runtime' / doc['runtime_exec']
    atomic = load('atomic_write')
    load('service')._install_home_file(home, Path(__file__).resolve().parents[1], 'desktop_launch.py')
    if platform_name == 'win32':
        python = python.with_name('pythonw.exe')
        if not python.is_file():
            raise ValueError('The bundled Windows setup application is incomplete.')
        _windows(home, python, on, user_home, run)
    else:
        if platform_name == 'darwin':
            target = user_home / 'Library/LaunchAgents' / (IDENTITY + '.plist')
            content = plistlib.dumps(dict(Label=IDENTITY, RunAtLoad=True,
                LimitLoadToSessionType='Aqua', SCGRouterHome=str(home),
                ProgramArguments=[str(python), str(home / 'desktop_launch.py'), '--autostart']))
        elif platform_name == 'linux':
            config = Path(os.environ.get('XDG_CONFIG_HOME') or user_home / '.config')
            if not config.is_absolute():
                raise ValueError('Invalid startup directory')
            target = config / 'autostart' / (IDENTITY + '.desktop')
            quote = load('native_shortcuts')._desktop_arg
            content = ('[Desktop Entry]\nType=Application\nName=SCG Router\nTerminal=false\n'
                       'Exec=%s %s --autostart\nX-SCGRouterHome=%s\n' %
                       (quote(python), quote(home / 'desktop_launch.py'), home)).encode()
        else:
            raise ValueError('Unsupported desktop')
        _owned(target, home, platform_name)
        if on:
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic.replace_text(target, content.decode())
        else:
            target.unlink(missing_ok=True)
    if save:
        atomic.replace_json(home / 'desktop-preferences.json', {'autostart': on})


def remove(home, *, user_home=None, platform_name=None, run=subprocess.run):
    """Remove only this install's startup entry after client restoration succeeds."""
    with load('service').install_lock(Path(home), '.desktop-startup.lock') as held:
        if not held:
            raise ValueError('SCG Router startup is already changing. Try again shortly.')
        _remove(home, user_home=user_home, platform_name=platform_name, run=run)
        load('atomic_write').replace_json(Path(home) / 'desktop-preferences.json', {'autostart': False})


def _remove(home, *, user_home=None, platform_name=None, run=subprocess.run):
    home, user_home = Path(home).resolve(), Path(user_home or Path.home())
    platform_name = platform_name or sys.platform
    if platform_name == 'win32':
        _windows(home, '', False, user_home, run)
        return
    target = (user_home / 'Library/LaunchAgents' / (IDENTITY + '.plist')
              if platform_name == 'darwin' else
              Path(os.environ.get('XDG_CONFIG_HOME') or user_home / '.config') /
              'autostart' / (IDENTITY + '.desktop'))
    try:
        _owned(target, home, platform_name)
    except ValueError:
        return  # Another installation owns it; removal has no authority here.
    target.unlink(missing_ok=True)
