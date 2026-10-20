"""Owned, per-user application shortcuts for the retained native setup."""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_payload import load, metadata

BUNDLE_ID = 'com.softwarecombined.router.setup'
# Written after a successful removal. A running menu exits when it appears, and
# opening SCG Router shows setup again. Installing entry points clears it.
REMOVED = '.router-removed'
UNINSTALL_KEY = r'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SCG.Router'


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
    (home / REMOVED).unlink(missing_ok=True)
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
    helper = resources / 'control' / ('scg-router-menu.exe' if os.name == 'nt' else 'scg-router-menu')
    if helper.is_file():
        startup = load('desktop_startup')
        startup.configure(home, resources, None)


def remove(home, run=subprocess.run):
    """After a successful removal: stop the menu and remove this install's entry points."""
    home = Path(home)
    load('desktop_startup').remove(home)
    load('atomic_write').replace_text(home / REMOVED, 'removed\n')
    if sys.platform == 'win32':
        _windows_remove(home, run)


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


def _quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _start_menu():
    return Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Software Combined'


def _windows(home, resources, python, run):
    directory = _start_menu()
    directory.mkdir(parents=True, exist_ok=True)
    pythonw = Path(python).with_name('pythonw.exe')
    if not pythonw.is_file():
        raise ValueError('The bundled Windows setup application is incomplete.')
    launch, icon = home / 'native_launch.py', resources / 'router-icon.ico'
    script = "$ErrorActionPreference='Stop';$w=New-Object -ComObject WScript.Shell;"
    for name, arguments in (('SCG Router.lnk', [launch]),
                            ('Uninstall SCG Router.lnk', [launch, '--action', 'remove'])):
        script += ("$s=$w.CreateShortcut(%s);$s.TargetPath=%s;$s.Arguments=%s;"
                   "$s.WorkingDirectory=%s;$s.IconLocation=%s;$s.Save();"
                   % (_quote(directory / name), _quote(pythonw),
                      _quote(subprocess.list2cmdline([str(item) for item in arguments])),
                      _quote(home), _quote(icon)))
    # Settings > Apps lists this per-user entry; its Uninstall runs the same removal.
    values = (('DisplayName', 'SCG Router'), ('Publisher', 'Software Combined'),
              ('DisplayVersion', metadata(resources)['version']), ('DisplayIcon', icon),
              ('InstallLocation', home), ('UninstallString', subprocess.list2cmdline(
                  [str(pythonw), str(launch), '--action', 'remove'])))
    script += ("$k=%s;if((Test-Path -LiteralPath $k) -and (Get-ItemProperty -LiteralPath $k).InstallLocation"
               " -ne %s){throw 'ownership'};if(!(Test-Path -LiteralPath $k)){New-Item -Path $k | Out-Null};"
               % (_quote(UNINSTALL_KEY), _quote(home)))
    script += ''.join('Set-ItemProperty -LiteralPath $k -Name %s -Value %s;' % (_quote(name), _quote(value))
                      for name, value in values)
    script += ("foreach($n in 'NoModify','NoRepair'){New-ItemProperty -LiteralPath $k -Name $n "
               "-Value 1 -PropertyType DWord -Force | Out-Null}")
    run(['powershell', '-NoProfile', '-WindowStyle', 'Hidden', '-Command', script],
        check=True, capture_output=True, timeout=30)


def _windows_remove(home, run):
    """Remove only entries that point at this installation."""
    launch = str(home / 'native_launch.py')
    script = ("$ErrorActionPreference='Stop';$w=New-Object -ComObject WScript.Shell;"
              "foreach($p in @(%s,%s)){if((Test-Path -LiteralPath $p) -and "
              "$w.CreateShortcut($p).Arguments.Contains(%s)){Remove-Item -LiteralPath $p}};"
              "$k=%s;if((Test-Path -LiteralPath $k) -and (Get-ItemProperty -LiteralPath $k).InstallLocation"
              " -eq %s){Remove-Item -LiteralPath $k}"
              % (_quote(_start_menu() / 'SCG Router.lnk'), _quote(_start_menu() / 'Uninstall SCG Router.lnk'),
                 _quote(launch), _quote(UNINSTALL_KEY), _quote(home)))
    run(['powershell', '-NoProfile', '-WindowStyle', 'Hidden', '-Command', script],
        check=True, capture_output=True, timeout=30)
