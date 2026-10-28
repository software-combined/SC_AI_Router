"""Desktop identity, lifecycle, dialogs and owned shortcuts; `app` defaults to Claude."""
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
_windows_identity = _load('router_desktop_windows', 'desktop_windows.py')
_windows_codex = _load('router_windows_codex', 'windows_codex.py')
_windows_dialogs = _load('router_windows_dialog', 'windows_dialog.py')
_dialogs = _load('router_client_dialog', 'client_dialog.py')
TITLE = 'SCG Router'
ICON = Path(__file__).parent / 'assets' / 'router-icon.png'
BUNDLE_ID = 'com.anthropic.claudefordesktop'
APP_DESKTOP_ID = BUNDLE_ID
# `writers`: executable names that must belong to the verified app, since a
# stray copy could write the same profile while the switch runs.
App = collections.namedtuple('App', 'bundle_id writers')
CLAUDE = App(BUNDLE_ID, ('claude', 'claude-desktop', 'claude.exe'))


def dialog_script(message, confirm=False, labels=('Continue', 'Cancel')):
    # The last label is the safe action; a confirmation's action is the default.
    quote = lambda value: json.dumps(str(value), ensure_ascii=False)
    safe = quote(labels[-1])
    default = quote(labels[0]) if confirm else safe
    buttons = '{%s, %s}' % (safe, default) if confirm else '{%s}' % safe
    return ('display dialog %s with title %s buttons %s default button %s '
            'cancel button %s with icon (POSIX file %s)'
            % (quote(message), quote(TITLE), buttons, default, safe, quote(ICON)))


def _ps(value):
    return "'" + str(value).replace("'", "''") + "'"


_windows_dialog = _windows_dialogs.script

def _run(command, run, timeout=5, platform_name=None):
    flags = {'creationflags': 0x08000000} if (platform_name or sys.platform) == 'win32' else {}
    return run(command, capture_output=True, text=True, timeout=timeout, **flags)


def _dialog(message, platform_name, confirm, run, tool_path=None, detailed=False,
            labels=('Continue', 'Cancel')):
    if platform_name == 'darwin':
        argv = [tool_path or '/usr/bin/osascript', '-e', dialog_script(message, confirm, labels)]
    elif platform_name == 'win32':
        argv = [tool_path or 'powershell', '-NoProfile', '-Command', _windows_dialog(message, confirm, labels)]
    else:
        argv = [tool_path or _dialogs.tool(platform_name) or 'zenity',
                '--title', TITLE, '--window-icon', str(ICON), '--width=460',
                '--question' if confirm else '--info', '--text', str(message),
                '--ok-label', labels[0] if confirm else labels[-1]]
        if confirm:
            argv += ['--cancel-label', labels[1]]
    answer = _run(argv, run, 120, platform_name)
    if detailed:
        return answer
    return answer.returncode == 0 and (platform_name != 'darwin' or not confirm
                                      or 'button returned:' + labels[0] in answer.stdout)


def confirm(message, platform_name, run=subprocess.run, *, home=None):
    if platform_name == 'win32' and home is not None:
        return _windows_dialogs.show(message, home, True, run)
    return _dialog(message, platform_name, True, run)


def show_message(message, platform_name, run=subprocess.run, *, home=None):
    if platform_name == 'win32' and home is not None:
        return _windows_dialogs.show(message, home, False, run, labels=('OK',))
    return _dialog(message, platform_name, False, run, labels=('OK',))


def policy_disabled(platform_name, run=subprocess.run, *, profile=None):
    return _policy.policy_disabled(platform_name, profile)


error_facts = _windows_identity.error_facts
_json_command = _windows_identity.json_command


def timed(record, stage, operation):
    started = time.monotonic()
    try:
        return operation()
    finally:
        record.setdefault('stages_ms', {})[stage] = round((time.monotonic() - started) * 1000, 1)


def app_identity(platform_name, run=subprocess.run, app=CLAUDE):
    if platform_name == 'linux':
        if app == CLAUDE:
            return _linux_identity.app_identity('claude')
        if (getattr(app, 'bundle_id', None) == 'com.openai.codex'
                and getattr(app, 'writers', None) == ()):
            return _linux_identity.app_identity('codex')
        raise OSError('only a known desktop app can be checked')
    if platform_name == 'win32':
        if app.bundle_id == 'com.openai.codex':
            return _windows_codex.identity()
        return _windows_identity.identity(app.bundle_id,
            lambda script: _json_command(script, run, timeout=30, operation='app_identity'))
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


def _snapshot(platform_name, identity, run, *, tracked=(), names=(), timeout=60):
    if platform_name == 'win32':
        if identity.get('family') == _windows_codex.FAMILY:
            return _windows_codex.snapshot(identity, tracked, names)
        rows = _json_command(_windows_identity.snapshot_script(identity, tracked, names), run, timeout=timeout)
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
    if platform_name == 'win32':
        names = tuple(name.casefold() for name in names) + (exe.rsplit('/', 1)[-1],)
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
        if (path == exe or (path.startswith(root) and path != browser_host)
                or identity.get('family') and row.get('family') == identity['family']):
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
    return _writers(_snapshot(platform_name, identity, run, names=app.writers), identity, {}, platform_name,
                    app.writers)


def _checked_identity(platform_name, run, app, expected):
    if platform_name == 'win32' and expected and expected.get('family') == _windows_codex.FAMILY:
        _windows_codex.validate(expected)
        return expected
    identity = app_identity(platform_name, run, app=app)
    if expected is not None and identity != expected:
        raise OSError('desktop app identity changed')
    return identity


def request_stop(platform_name, run=subprocess.run, timeout=65, app=CLAUDE, *, identity=None,
                 allow_terminate=False, record=None):
    identity = _checked_identity(platform_name, run, app, identity)
    if platform_name == 'win32' and identity.get('family') == _windows_codex.FAMILY:
        return _windows_codex.stop(identity, lambda rows, seen: _writers(
            rows, identity, seen, platform_name, app.writers), allow_terminate=allow_terminate,
            record=record)
    seen = {}
    if not _writers(_snapshot(platform_name, identity, run, names=app.writers), identity, seen, platform_name,
                    app.writers):
        return True
    deadline = time.monotonic() + max(0, timeout)
    if platform_name == 'darwin':
        argv = ['/usr/bin/osascript', '-e', 'tell application id "%s" to quit' % app.bundle_id]
    elif platform_name == 'win32':
        argv = _windows_identity.close_command(identity, seen)
    else:
        name = 'Codex' if app.bundle_id == 'com.openai.codex' else 'Claude'
        if not confirm('Please quit %s, then choose Continue.' % name, platform_name, run):
            return False
        argv = None
    try:
        if argv and _run(argv, run, max(0.1, min(30, timeout)), platform_name).returncode:
            return False
    except subprocess.TimeoutExpired:
        pass  # Claude may still close, for example after its own confirmation; the wait decides.
    probe_error = None
    while True:
        try:
            if not _writers(_snapshot(platform_name, identity, run, tracked=seen, names=app.writers,
                            timeout=min(60, max(0.1, deadline - time.monotonic()))), identity, seen,
                            platform_name, app.writers):
                return True
            probe_error = None
        except (OSError, subprocess.SubprocessError) as exc:
            probe_error = exc  # A clean subsequent scan can still confirm shutdown.
        if time.monotonic() >= deadline:
            if isinstance(probe_error, _windows_identity.QueryError):
                try:
                    open_app(platform_name, run=run, app=app, identity=identity)
                except (OSError, subprocess.SubprocessError):
                    pass
                raise probe_error
            return False
        time.sleep(min(0.25, max(0, deadline - time.monotonic())))


def open_app(platform_name, run=subprocess.run, app=CLAUDE, *, identity=None):
    identity = _checked_identity(platform_name, run, app, identity)
    if platform_name == 'darwin':
        argv = ['/usr/bin/open', identity['root']]
    elif platform_name == 'win32':
        if identity.get('family') == _windows_codex.FAMILY:
            return _windows_codex.open_app(identity)
        argv = ['powershell', '-NoProfile', '-Command',
                "$ErrorActionPreference='Stop';Start-Process " + _ps(
                    _windows_codex._native.app_uri(identity['app']))]
    else:
        argv = ['gtk-launch', identity['desktop_id']]
    answer = _run(argv, run, 10, platform_name)
    if answer.returncode:
        raise subprocess.CalledProcessError(answer.returncode, 'open Claude')
    return answer


def running_names(root, run):
    """Basenames, never arguments or paths, of surviving POSIX app processes."""
    try:
        answer = run(['/bin/ps', '-axo', 'comm='], capture_output=True, text=True, timeout=5)
        prefix = str(root).rstrip('/') + '/'
        return sorted(Path(line).name for line in answer.stdout.splitlines()
                      if line.startswith(prefix))
    except Exception:
        return None


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
        answer = _run(['powershell', '-NoProfile', '-Command', script], run, 15, platform_name)
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
