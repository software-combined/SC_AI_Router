"""Native Claude identity, graceful lifecycle, dialogs and owned shortcuts.

The macOS lifecycle helpers also serve Switch Codex: `app` names the bundle
to find, quit and reopen, and defaults to Claude, the only app the Windows
and Linux paths know. `install_mac_app` builds the owned launcher apps:
Switch Claude, Open Claude and Switch Codex.
"""
import collections
import importlib.util
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_atomic = _load('router_claude_desktop_atomic', 'atomic_write.py')
_policy = _load('router_claude_desktop_policy', 'claude_desktop_policy.py')
_linux_identity = _load('router_claude_desktop_linux', 'desktop_linux.py')
TITLE = 'SCG Router'
ICON = Path(__file__).parent / 'assets' / 'router-icon.png'
BUNDLE_ID = 'com.anthropic.claudefordesktop'
APP_DESKTOP_ID = BUNDLE_ID
# `writers`: executable names that must belong to the verified app, since a
# stray copy could write the same profile while the switch runs.
App = collections.namedtuple('App', 'bundle_id writers')
CLAUDE = App(BUNDLE_ID, ('claude', 'claude-desktop', 'claude.exe'))


def dialog_script(message, confirm=False):
    quote = lambda value: json.dumps(str(value), ensure_ascii=False)
    buttons = '{"Cancel", "Continue"}' if confirm else '{"Cancel"}'
    return ('display dialog %s with title %s buttons %s default button "Cancel" '
            'cancel button "Cancel" with icon (POSIX file %s)'
            % (quote(message), quote(TITLE), buttons, quote(ICON)))


def _ps(value):
    return "'" + str(value).replace("'", "''") + "'"


def _windows_dialog(message, confirm):
    # Match client_dialog's bitmap icon and layout containers; constrain text width.
    return (
        "$ErrorActionPreference='Stop';Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$f=New-Object System.Windows.Forms.Form;$f.Text='SCG Router';"
        "$f.Icon=[System.Drawing.Icon]::FromHandle((New-Object System.Drawing.Bitmap %s).GetHicon());"
        "$f.AutoSize=$true;$f.AutoSizeMode='GrowAndShrink';"
        "$p=New-Object System.Windows.Forms.FlowLayoutPanel;"
        "$p.FlowDirection='TopDown';$p.WrapContents=$false;$p.AutoSize=$true;"
        "$p.Padding=New-Object System.Windows.Forms.Padding(12);"
        "$l=New-Object System.Windows.Forms.Label;$l.Text=%s;"
        "$l.MaximumSize=New-Object System.Drawing.Size(440,0);$l.AutoSize=$true;"
        "$r=New-Object System.Windows.Forms.FlowLayoutPanel;$r.AutoSize=$true;"
        "$r.FlowDirection='LeftToRight';$r.WrapContents=$false;"
        "%s$c=New-Object System.Windows.Forms.Button;$c.Text='Cancel';"
        "$c.AutoSize=$true;$c.DialogResult='Cancel';$r.Controls.Add($c);"
        "$f.CancelButton=$c;$p.Controls.Add($l);$p.Controls.Add($r);$f.Controls.Add($p);"
        "if($f.ShowDialog() -eq 'OK'){exit 0}else{exit 1}"
        % (_ps(ICON), _ps(message), (
            "$b=New-Object System.Windows.Forms.Button;$b.Text='Continue';"
            "$b.AutoSize=$true;$b.DialogResult='OK';$r.Controls.Add($b);"
        ) if confirm else ''))


def _run(command, run, timeout=5):
    return run(command, capture_output=True, text=True, timeout=timeout)


def _dialog(message, platform_name, confirm, run):
    if platform_name == 'darwin':
        argv = ['/usr/bin/osascript', '-e', dialog_script(message, confirm)]
    elif platform_name == 'win32':
        argv = ['powershell', '-NoProfile', '-Command', _windows_dialog(message, confirm)]
    else:
        argv = ['zenity', '--title', TITLE, '--window-icon', str(ICON),
                '--question' if confirm else '--info', '--text', str(message),
                '--ok-label', 'Continue' if confirm else 'Cancel']
        if confirm:
            argv += ['--cancel-label', 'Cancel']
    answer = _run(argv, run, 120)
    return answer.returncode == 0 and (platform_name != 'darwin' or not confirm
                                      or 'button returned:Continue' in answer.stdout)


def confirm(message, platform_name, run=subprocess.run):
    return _dialog(message, platform_name, True, run)


def show_message(message, platform_name, run=subprocess.run):
    return _dialog(message, platform_name, False, run)


def policy_disabled(platform_name, run=subprocess.run, *, profile=None):
    return _policy.policy_disabled(platform_name, profile)


def _json_command(script, run):
    answer = _run(['powershell', '-NoProfile', '-Command',
                   "$ErrorActionPreference='Stop';" + script], run)
    if answer.returncode:
        raise OSError('Claude identity could not be checked')
    try:
        return json.loads(answer.stdout)
    except ValueError as exc:
        raise OSError('Claude identity could not be checked') from exc


def app_identity(platform_name, run=subprocess.run, app=CLAUDE):
    if platform_name == 'linux':
        if app == CLAUDE:
            return _linux_identity.app_identity('claude')
        if (getattr(app, 'bundle_id', None) == 'com.openai.codex'
                and getattr(app, 'writers', None) == ()):
            return _linux_identity.app_identity('codex')
        raise OSError('only a known desktop app can be checked')
    if app != CLAUDE and platform_name != 'darwin':
        raise OSError('only the Mac knows this app')
    if platform_name == 'win32':
        return _json_command(
            "$a=@(Get-StartApps | Where-Object {$_.Name -eq 'Claude'});"
            "if($a.Count -ne 1 -or $a[0].AppID -notmatch '!'){throw 'identity'};"
            "$family,$id=$a[0].AppID.Split('!');"
            "$p=@(Get-AppxPackage | Where-Object {$_.PackageFamilyName -eq $family});"
            "if($p.Count -ne 1){throw 'identity'};"
            "$m=Get-AppxPackageManifest $p[0];"
            "$e=@($m.Package.Applications.Application | Where-Object {$_.Id -eq $id});"
            "if($e.Count -ne 1 -or -not $e[0].Executable){throw 'identity'};"
            "$exe=Join-Path $p[0].InstallLocation $e[0].Executable;"
            "if(-not (Test-Path -LiteralPath $exe -PathType Leaf)){throw 'identity'};"
            "@{root=$p[0].InstallLocation;exe=$exe;app=$a[0].AppID;"
            "user=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value} | ConvertTo-Json -Compress", run)
    if platform_name == 'darwin':
        # AppleScript's app-path lookup launches a closed Claude. Spotlight
        # resolves the bundle without undoing the stopped-app safety check.
        answer = _run(['/usr/bin/mdfind',
                       'kMDItemCFBundleIdentifier == "%s"' % app.bundle_id], run)
        roots = {Path(line) for line in answer.stdout.splitlines() if line}
        if answer.returncode or len(roots) != 1:
            raise OSError('Claude identity could not be checked')
        root = roots.pop()
        doc = plistlib.loads((root / 'Contents/Info.plist').read_bytes())
        if doc.get('CFBundleIdentifier') != app.bundle_id:
            raise OSError('Claude identity could not be checked')
        exe = root / 'Contents/MacOS' / doc['CFBundleExecutable']
    else:
        raise OSError('desktop identity is unsupported on this platform')
    if not exe.is_file() or not root.is_absolute():
        raise OSError('Claude identity could not be checked')
    return dict(root=str(root), exe=str(exe), user=str(os.getuid()))


def _snapshot(platform_name, identity, run):
    if platform_name == 'win32':
        rows = _json_command(
            "$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value;"
            "$rows=@(foreach($p in Get-CimInstance Win32_Process){"
            "if($p.SessionId -ne (Get-Process -Id $PID).SessionId){continue};"
            "$o=Invoke-CimMethod -InputObject $p -MethodName GetOwnerSid;"
            "if($o.ReturnValue -ne 0){throw 'owner'};"
            "if($o.Sid -eq $sid){@{pid=[int]$p.ProcessId;parent=[int]$p.ParentProcessId;"
            "user=$o.Sid;born=$p.CreationDate.ToString('o');exe=$p.ExecutablePath}}});"
            "ConvertTo-Json -InputObject $rows -Compress", run)
    else:
        command = ['/bin/ps', '-axo', 'pid=,ppid=,uid=,lstart=,stat=,comm=']
        if platform_name == 'linux':
            command = ['/bin/ps', '-ww', '-u', identity['user'], '-o',
                       'pid=,ppid=,uid=,lstart=,stat=,exe=']
        answer = _run(command, run)
        if answer.returncode:
            raise OSError('Claude status is unknown')
        rows = []
        for line in answer.stdout.splitlines():
            parts = line.split(None, 9)
            if len(parts) != 10:
                raise OSError('Claude status is unknown')
            if parts[8].startswith('Z'):
                continue  # Exited and waiting to be reaped, so it can no longer write.
            if platform_name == 'linux' and (not PurePosixPath(parts[9]).is_absolute()
                                            or parts[9].endswith(' (deleted)')):
                raise OSError('Claude status is unknown')
            rows.append(dict(pid=int(parts[0]), parent=int(parts[1]), user=parts[2],
                             born=' '.join(parts[3:8]), exe=parts[9]))
    if not isinstance(rows, list) or any(not r.get('born') or not r.get('exe') for r in rows):
        raise OSError('Claude status is unknown')
    return {r['pid']: r for r in rows if r['user'] == identity['user']}


def _writers(rows, identity, seen, platform_name, names=CLAUDE.writers):
    norm = (lambda s: s.replace('\\', '/').casefold()) if platform_name == 'win32' else str
    root, exe = norm(identity['root']).rstrip('/') + '/', norm(identity['exe'])
    browser_host = root + 'Contents/Helpers/chrome-native-host' if platform_name == 'darwin' else None
    for pid, old in seen.items():
        # A new parent is expected when a writer outlives the main app, and a new
        # executable alone is the same process after exec, so both stay tracked.
        # A new start time or user means the pid now belongs to another process.
        if pid in rows and any(rows[pid][k] != old[k] for k in ('born', 'user')):
            raise OSError('Claude identity changed')
    # Crash reporters write only crash reports and can outlive an app update by days.
    live = {p: r for p, r in rows.items() if 'crashpad_handler' not in norm(r['exe']).rsplit('/', 1)[-1]}
    for pid, row in live.items():
        path = norm(row['exe'])
        # Browser-owned native messaging hosts outlive Claude. Actual app
        # descendants still enter and remain in seen through the walk below.
        if path == exe or (platform_name != 'linux' and path.startswith(root)
                           and path != browser_host):
            seen[pid] = row
    while True:
        children = {pid: row for pid, row in live.items()
                    if row['parent'] in seen and pid not in seen}
        if not children:
            break
        seen.update(children)
    for pid, row in rows.items():
        if pid not in seen and norm(row['exe']).rsplit('/', 1)[-1].lower() in names:
            raise OSError('unverified Claude writer')
    return bool(set(rows).intersection(seen))


def is_running(platform_name, run=subprocess.run, app=CLAUDE):
    identity = app_identity(platform_name, run, app=app)
    return _writers(_snapshot(platform_name, identity, run), identity, {}, platform_name,
                    app.writers)


def request_stop(platform_name, run=subprocess.run, timeout=65, app=CLAUDE):
    identity = app_identity(platform_name, run, app=app)
    seen = {}
    if not _writers(_snapshot(platform_name, identity, run), identity, seen, platform_name,
                    app.writers):
        return True
    deadline = time.monotonic() + max(0, timeout)
    if platform_name == 'darwin':
        argv = ['/usr/bin/osascript', '-e', 'tell application id "%s" to quit' % app.bundle_id]
    elif platform_name == 'win32':
        roots = [str(pid) for pid, row in seen.items() if row['exe'] == identity['exe']]
        births = ';'.join('%s=%s' % (pid, _ps(seen[int(pid)]['born'])) for pid in roots)
        script = "$ErrorActionPreference='Stop';$births=@{%s};foreach($n in @(%s)){" % (births, ','.join(roots))
        script += '$c=Get-CimInstance -ClassName Win32_Process -Filter "ProcessId=$n";'
        script += "$o=Invoke-CimMethod -InputObject $c -MethodName GetOwnerSid;"
        script += "if($c.CreationDate.ToString('o') -ne $births[$n] -or $o.ReturnValue -ne 0 "
        script += "-or $o.Sid -ne %s){throw 'identity'};" % _ps(identity['user'])
        script += "$p=Get-Process -Id $n -ErrorAction Stop;"
        script += "if($p.Path -ne %s){throw 'identity'};" % _ps(identity['exe'])
        script += "$p.CloseMainWindow() | Out-Null}"
        argv = ['powershell', '-NoProfile', '-Command', script]
    else:
        if not confirm('Please quit Claude, then choose Continue.', platform_name, run):
            return False
        argv = None
    try:
        if argv and _run(argv, run, max(0.1, min(30, timeout))).returncode:
            return False
    except subprocess.TimeoutExpired:
        pass  # Claude may still close, for example after its own confirmation; the wait decides.
    while True:
        try:
            if not _writers(_snapshot(platform_name, identity, run), identity, seen,
                            platform_name, app.writers):
                return True
        except (OSError, subprocess.SubprocessError):
            pass  # Quitting processes can fail a check; only a clean one ends the wait.
        if time.monotonic() >= deadline:
            return False
        time.sleep(min(0.25, max(0, deadline - time.monotonic())))


def open_app(platform_name, run=subprocess.run, app=CLAUDE):
    identity = app_identity(platform_name, run, app=app)
    if platform_name == 'darwin':
        argv = ['/usr/bin/open', identity['root']]
    elif platform_name == 'win32':
        argv = ['powershell', '-NoProfile', '-Command',
                "$ErrorActionPreference='Stop';Start-Process " + _ps('shell:AppsFolder:' + identity['app'])]
    else:
        argv = ['gtk-launch', APP_DESKTOP_ID]
    answer = _run(argv, run, 10)
    if answer.returncode:
        raise subprocess.CalledProcessError(answer.returncode, 'open Claude')
    return answer


def _desktop_arg(value):
    # Desktop Entry escaping is two layers, not shell single-quote escaping.
    value = str(value).replace('%', '%%')
    for char in ('\\', '"', '`', '$'):
        value = value.replace(char, '\\' + char)
    return '"' + value.replace('\\', '\\\\') + '"'


def install_launcher(home, python, action='switch', applications=None,
                     run=subprocess.run, platform_name=None):
    platform_name = sys.platform if platform_name is None else platform_name
    home = Path(home)
    python = shutil.which(str(python)) or str(python)
    launch = home / 'claude_profile_launch.py'
    name = 'Open Claude' if action == 'start' else 'Switch Claude'
    marker = 'SCG Router Claude ' + action + ':' + str(home)
    if platform_name == 'win32':
        base = Path(os.environ.get('APPDATA') or str(Path.home() / 'AppData/Roaming'))
        applications = Path(applications) if applications else base / 'Microsoft/Windows/Start Menu/Programs'
        path = applications / ('SCG Router - ' + name + '.lnk')
        arguments = subprocess.list2cmdline([str(launch), '--home', str(home), '--action', action])
        script = ("$ErrorActionPreference='Stop';$w=New-Object -ComObject WScript.Shell;"
                  "$s=$w.CreateShortcut(%s);if(Test-Path -LiteralPath %s){"
                  "if($s.Description -ne %s -or $s.Arguments -ne %s){throw 'unowned launcher'}};"
                  "$s.TargetPath=%s;$s.Arguments=%s;$s.Description=%s;$s.IconLocation=%s;$s.Save()"
                  % tuple(map(_ps, (path, path, marker, arguments, python, arguments, marker, ICON))))
        applications.mkdir(parents=True, exist_ok=True)
        answer = _run(['powershell', '-NoProfile', '-Command', script], run, 15)
        if answer.returncode:
            raise OSError('unowned or unavailable Claude launcher')
    elif platform_name != 'darwin':
        base = Path(os.environ.get('XDG_DATA_HOME') or str(Path.home() / '.local/share'))
        applications = Path(applications) if applications else base / 'applications'
        path = applications / ('scg-router-claude-' + action + '.desktop')
        if path.exists() and ('X-SCG-Owner=' + marker + '\n') not in path.read_text(encoding='utf-8'):
            raise OSError('unowned Claude launcher')
        command = ' '.join((_desktop_arg(python), _desktop_arg(launch), '--action', action))
        applications.mkdir(parents=True, exist_ok=True)
        _atomic.replace_text(path, '[Desktop Entry]\nType=Application\nName=' + name +
                             '\nExec=' + command + '\nIcon=' + str(ICON) +
                             '\nTerminal=false\nX-SCG-Owner=' + marker + '\n', mode=0o755)
    else:
        return None
    _atomic.replace_text(launch, Path(__file__).with_name('claude_profile_launch.py').read_text(encoding='utf-8'), mode=0o755)
    return path


class NotOwned(Exception):
    """An app already at the target that this router did not build."""


def install_mac_app(target, bundle_id, python, home, launcher, extra=(), plist=None,
                    run=subprocess.run):
    """Build or refresh the owned macOS app at `target`, staged, then swapped in.

    Its executable runs `python <home>/<launcher> <extra...>`, and `launcher`,
    a sibling of this module, is copied into the router home first, so the
    app outlives updates and release pruning. `plist` adds Info.plist keys.
    An app at `target` with another bundle id raises NotOwned and stays.
    """
    target, home = Path(target), Path(home)
    if target.exists():
        try:
            owned = (plistlib.loads((target / 'Contents' / 'Info.plist').read_bytes())
                     .get('CFBundleIdentifier') == bundle_id)
        except (OSError, ValueError):
            owned = False
        if not owned:
            raise NotOwned(target.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        staged = Path(tmp) / target.name
        contents = staged / 'Contents'
        resources = contents / 'Resources'
        executable = contents / 'MacOS' / target.stem
        resources.mkdir(parents=True)
        executable.parent.mkdir()
        iconset = Path(tmp) / 'router.iconset'
        iconset.mkdir()
        for size, icon_name in ((512, 'icon_512x512.png'), (1024, 'icon_512x512@2x.png')):
            run(['/usr/bin/sips', '-z', str(size), str(size), str(ICON), '--out',
                 str(iconset / icon_name)], check=True, capture_output=True, timeout=15)
        run(['/usr/bin/iconutil', '-c', 'icns', str(iconset), '-o',
             str(resources / 'router.icns')], check=True, capture_output=True, timeout=15)
        launch = home / launcher
        executable.write_text('#!/bin/sh\nexec %s\n' % ' '.join(
            shlex.quote(str(part)) for part in (python, launch) + tuple(extra)))
        executable.chmod(0o755)
        (contents / 'Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': bundle_id, 'CFBundleName': target.stem,
            'CFBundleExecutable': executable.name, 'CFBundlePackageType': 'APPL',
            'CFBundleIconFile': 'router.icns', 'LSUIElement': True, **(plist or {}),
        }))
        _atomic.replace_text(launch, Path(__file__).with_name(launcher).read_text(encoding='utf-8'))
        if target.exists():
            # Only this product's bundle passes the ownership check above.
            shutil.copytree(staged, target, dirs_exist_ok=True)
        else:
            staged.rename(target)
    return target
