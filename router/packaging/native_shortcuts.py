"""Owned, per-user application shortcuts for the retained native setup."""
import os
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_payload import OwnershipConflict, load, metadata

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
    load('service')._install_home_file(home, Path(__file__).resolve().parents[1], 'native_launch.py')
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
        raise OwnershipConflict('SCG Router shortcut belongs to another installation')
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
        check=True, capture_output=True, timeout=30,
        **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))


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
        check=True, capture_output=True, timeout=30,
        **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))


_REGISTRY_NAMES = ('DisplayName', 'Publisher', 'DisplayVersion', 'DisplayIcon',
                   'InstallLocation', 'UninstallString', 'NoModify', 'NoRepair')
_LINK_READ = r"""
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$request=[Console]::In.ReadToEnd() | ConvertFrom-Json
$shell=New-Object -ComObject WScript.Shell
$reply=@{}
foreach($row in $request) {
    $reply[$row.name]=$null
    if(Test-Path -LiteralPath $row.path) {
        $link=$shell.CreateShortcut($row.path)
        $target=[IO.Path]::GetFullPath($link.TargetPath)
        if($link.Arguments -cne $row.arguments -or ($row.marker -and $link.Description -cne $row.marker) -or
           !$target.StartsWith($row.root,[StringComparison]::OrdinalIgnoreCase) -or
           ($row.target -and $target -ine $row.target -and $target -ine $row.alternative) -or
           [IO.Path]::GetFileName($target) -notin @('python.exe','pythonw.exe')) {throw 'ownership'}
        $reply[$row.name]=[Convert]::ToBase64String([IO.File]::ReadAllBytes($row.path))
    }
}
$reply | ConvertTo-Json -Compress
"""


def _cohort_links(home):
    directory = _start_menu()
    startup = load('desktop_startup')
    launch = home / 'native_launch.py'
    root = str(home / 'setup') + os.sep
    return [dict(name='open', path=str(directory / 'SCG Router.lnk'), marker='', root=root,
                 arguments=subprocess.list2cmdline([str(launch)])),
            dict(name='remove', path=str(directory / 'Uninstall SCG Router.lnk'), marker='', root=root,
                 arguments=subprocess.list2cmdline([str(launch), '--action', 'remove'])),
            dict(name='startup', path=str(startup.windows_target()), root=root,
                 marker=startup.IDENTITY + ':' + str(home),
                 arguments=subprocess.list2cmdline([str(home / 'desktop_launch.py'), '--autostart']))]


def _valid_registry(home, values):
    if values is None:
        return
    if (not isinstance(values, dict) or set(values) - set(_REGISTRY_NAMES)
            or os.path.normcase(str(Path(str(values.get('InstallLocation'))).resolve()))
            != os.path.normcase(str(Path(home).resolve()))):
        raise ValueError('Invalid SCG Router registration snapshot')
    for name, value in values.items():
        if type(value) is not (int if name in ('NoModify', 'NoRepair') else str):
            raise ValueError('Invalid SCG Router registration value')


def _registry_snapshot(home):
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY.split(':\\', 1)[1])
    except FileNotFoundError:
        return None
    values = {}
    with key:
        for name in _REGISTRY_NAMES:
            try:
                value, kind = winreg.QueryValueEx(key, name)
            except FileNotFoundError:
                continue
            wanted = winreg.REG_DWORD if name in ('NoModify', 'NoRepair') else winreg.REG_SZ
            if kind != wanted:
                raise ValueError('Unsupported SCG Router registration value')
            values[name] = value
    _valid_registry(home, values)
    return values


def _read_links(rows, run):
    import base64
    import json
    absent = True
    for row in rows:
        try:
            mode = Path(row['path']).lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise ValueError('Unsafe SCG Router shortcut')
        absent = False
    if absent:
        links = {row['name']: None for row in rows}
    else:
        result = run(['powershell', '-NoProfile', '-NonInteractive', '-Command', _LINK_READ],
                     input=json.dumps(rows), capture_output=True, text=True, encoding='utf-8',
                     check=True, timeout=30,
                     **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
        links = json.loads(result.stdout)
    if not isinstance(links, dict) or set(links) != {'open', 'remove', 'startup'}:
        raise ValueError('Invalid SCG Router shortcut snapshot')
    for value in links.values():
        if value is not None:
            if not isinstance(value, str):
                raise ValueError('Invalid SCG Router shortcut data')
            base64.b64decode(value, validate=True)
    return links


def snapshot(home, run=subprocess.run):
    home = Path(home).resolve()
    return dict(links=_read_links(_cohort_links(home), run), registry=_registry_snapshot(home),
                startup_on=load('desktop_startup').enabled(home, platform_name='win32'))


def verify(home, resources, python, run=subprocess.run, *, legacy=False):
    """Read back the exact retained runtime before installation completion."""
    home, resources = Path(home).resolve(), Path(resources).resolve()
    pythonw = str(Path(python).with_name('pythonw.exe'))
    rows = [dict(row, target=pythonw) for row in _cohort_links(home)]
    if legacy:
        rows[-1]['alternative'] = str(python)
    links = _read_links(rows, run)
    on = load('desktop_startup').enabled(home, platform_name='win32')
    values = _registry_snapshot(home)
    if (links['open'] is None or links['remove'] is None or (links['startup'] is not None) != on
            or values is None or values.get('DisplayVersion') != metadata(resources)['version']
            or values.get('UninstallString') != subprocess.list2cmdline(
                [pythonw, str(home / 'native_launch.py'), '--action', 'remove'])
            or values.get('DisplayIcon') != str(resources / 'router-icon.ico')):
        raise ValueError('Installed Windows entry points did not match')


def fingerprint(home):
    """Read sealed entry-point bytes without PowerShell; startup remains user-controlled."""
    import hashlib
    import json
    home = Path(home).resolve()
    rows = _cohort_links(home)[:2]
    values = _registry_snapshot(home)
    return dict(version=values.get('DisplayVersion') if values else None,
                links={row['name']: hashlib.sha256(Path(row['path']).read_bytes()).hexdigest() for row in rows},
                registry=hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest())


def _registry_restore(home, before):
    import winreg
    _valid_registry(home, before)
    current = _registry_snapshot(home)
    path = UNINSTALL_KEY.split(':\\', 1)[1]
    if before is None:
        if current is not None:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                names = {winreg.EnumValue(key, i)[0] for i in range(winreg.QueryInfoKey(key)[1])}
            if names - set(_REGISTRY_NAMES):
                raise ValueError('SCG Router registration changed')
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    else:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
            for name in _REGISTRY_NAMES:
                if name in before:
                    kind = winreg.REG_DWORD if name in ('NoModify', 'NoRepair') else winreg.REG_SZ
                    winreg.SetValueEx(key, name, 0, kind, before[name])
                elif current and name in current:
                    winreg.DeleteValue(key, name)
    if _registry_snapshot(home) != before:
        raise ValueError('Restored SCG Router registration did not match')


def restore(home, before, run=subprocess.run):
    """Caller holds install.lock; restore fixed owned entries, never preferences."""
    import base64
    import tempfile
    home = Path(home).resolve()
    if (not isinstance(before, dict) or set(before) != {'links', 'registry', 'startup_on'}
            or not isinstance(before['links'], dict) or set(before['links']) != {'open', 'remove', 'startup'}
            or type(before['startup_on']) is not bool):
        raise ValueError('Invalid SCG Router shortcut snapshot')
    _valid_registry(home, before['registry'])
    saved = {}
    for name, value in before['links'].items():
        if value is not None and not isinstance(value, str):
            raise ValueError('Invalid SCG Router shortcut data')
        saved[name] = base64.b64decode(value, validate=True) if value is not None else None
    # Inspect saved links away from the real entry points before publishing any byte.
    with tempfile.TemporaryDirectory() as temporary:
        rows = _cohort_links(home)
        for row in rows:
            path = Path(temporary) / (row['name'] + '.lnk')
            row['path'] = str(path)
            if saved[row['name']] is not None:
                path.write_bytes(saved[row['name']])
        if _read_links(rows, run) != before['links']:
            raise ValueError('Invalid saved SCG Router shortcut')
    current = snapshot(home, run)  # Refuse a foreign entry before any write.
    changed_preference = before['startup_on'] != current['startup_on']
    atomic = load('atomic_write')
    for row in _cohort_links(home):
        name, path = row['name'], Path(row['path'])
        if changed_preference and name == 'startup':
            continue
        value = current['links'][name]
        expected = base64.b64decode(value, validate=True) if value is not None else None
        if saved[name] == expected:
            continue
        if saved[name] is None:
            atomic.remove(path, expected=expected)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic.replace_bytes(path, saved[name], expected=expected)
    _registry_restore(home, before['registry'])
    if changed_preference:
        load('desktop_startup').configure(home, load('native_resources').current(home), None)
    after = snapshot(home, run)
    for name in saved:
        if not (changed_preference and name == 'startup') and after['links'][name] != before['links'][name]:
            raise ValueError('Restored SCG Router shortcut did not match')
