"""Best-effort desktop notice after a router update (runs on Python 3.9+).

The installer records the new version once a healthy update lands, and the
installer CLI shows a dialog offering to restart the client (the picker is
read at startup, so a running Codex never sees the new models). "Quit and
reopen" quits the desktop app and launches it again: the macOS bundle
``com.openai.codex``, the Windows Store package ``OpenAI.Codex``, and the
Linux preview app ``chatgpt``. Linux only offers the restart when that app
is installed; on macOS and Windows the button is harmless without it, and
the dialog always carries "Later". Only one dialog is ever on screen: the
pid of the dialog we spawned is remembered, and a later notice is folded
into that dialog instead of stacking a second one. A dialog that dies at
once -- a service context with no display or session bus -- leaves the
notice pending instead of marking it shown, so a later run that can draw
one still shows it. Every failure is swallowed: the notice must never
block on the user or fail an update.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import importlib.util as _ilu
_spec = _ilu.spec_from_file_location(
    'router_atomic_write', Path(__file__).resolve().parent / 'atomic_write.py')
_atomic_write = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_atomic_write)

_spec = _ilu.spec_from_file_location(
    'router_notice_text', Path(__file__).resolve().parent / 'notice_text.py')
_text = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_text)
# Kept as a module name: the wording is pinned here by callers and tests.
_message = _text.message

NOTICE_FILE = 'update-notice.json'
CATALOGUE_FILE = 'mixed-models.json'
PICKER_BASELINE_FILE = 'picker-baseline.json'
TITLE = 'SCG Router'
DISMISS = 'Later'
REOPEN = 'Quit and reopen'
OK = 'OK'
CODEX_BUNDLE_ID = 'com.openai.codex'
WINDOWS_PACKAGE = 'OpenAI.Codex'
LINUX_APP = 'chatgpt'
PROBE_TIMEOUT = 5
# A dialog that cannot render exits within this grace (zenity without a
# display, notify-send without a session bus, osascript without a GUI).
# Long enough to catch that, short enough not to hold the updater.
PROBE_GRACE_S = 1.0
ICON = Path(__file__).resolve().parent / 'assets' / 'router-icon.png'
ICON_NAME = 'router-icon.png'

def _utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _home_icon(home):
    """A copy of the bundled icon that outlives this process, or None.

    The scheduled updater runs the installer from a temporary extraction
    that is gone by the time the user clicks the dialog, and a dialog whose
    icon file has vanished never appears at all. The router home persists,
    so the dialog points there; when the copy fails the caller draws no
    icon rather than a path that may disappear.
    """
    try:
        target = Path(home) / ICON_NAME
        target.write_bytes(ICON.read_bytes())
        return str(target)
    except OSError:
        return None


def _dialog_pid(doc):
    """The pid of the dialog we spawned, when it is a sane positive int."""
    if isinstance(doc, dict):
        pid = doc.get('pid')
        if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
            return pid
    return None


def _pid_alive(pid):
    """True only for a live process that is one of our dialogs.

    A recycled pid must never stand in for an open dialog, so the process
    command line has to carry the dialog title. False when unsure: the
    worst case is a second dialog, never a silently dropped notice. The
    probe is bounded: the scheduled updater waits on this process, so a
    wedged WMI or `ps` must not park a healthy install.
    """
    pid = _dialog_pid({'pid': pid})
    if pid is None:
        return False
    try:
        if sys.platform == 'win32':
            query = ('(Get-CimInstance Win32_Process -Filter "ProcessId=%d")'
                     '.CommandLine' % pid)
            out = subprocess.run(['powershell', '-NoProfile', '-Command',
                                  query], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True,
                                 timeout=PROBE_TIMEOUT)
        else:
            out = subprocess.run(['ps', '-p', str(pid), '-o', 'command='],
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True,
                                 timeout=PROBE_TIMEOUT)
        return TITLE in (out.stdout or '')
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def _picker_slugs(blob):
    """Picker slugs in a merged-catalogue blob, or None when unusable."""
    if not blob:
        return None
    try:
        doc = json.loads(blob)
        rows = doc.get('models') if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            return None
        return {str(row['slug']) for row in rows
                if isinstance(row, dict) and row.get('slug')}
    except (TypeError, ValueError):
        return None


def _read_blob(path):
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


def _picker_baseline(home):
    """Slugs left by the last install that reached the notice, or None."""
    try:
        doc = json.loads((Path(home) / PICKER_BASELINE_FILE).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(doc, list):
        return None
    return {str(slug) for slug in doc if isinstance(slug, str)}


def _remember_picker(home, slugs):
    """Record the picker this install leaves behind; best effort."""
    if slugs is None:
        return
    try:
        _atomic_write.replace_json(Path(home) / PICKER_BASELINE_FILE, sorted(slugs))
    except OSError:
        pass


def record(home, previous, version, clients=None):
    """Stage a restart notice when an update adds a picker row.

    The prompt is about the picker, not the version: a release that adds no
    selectable row is not worth a Codex restart, so the notice is staged
    only when the merged catalogue gained a slug since the last install
    that reached this point. That baseline is recorded per install rather
    than read from the pre-install file, so an attempt that merged rows and
    then failed still prompts when it is retried. A staged but unshown
    notice is refreshed with this version instead of left stale, and an
    unreadable catalogue or baseline keeps the earlier behaviour and
    stages the notice, so a home this comparison cannot read is never
    silently skipped. Returns True when a notice is staged. Fresh
    installs, reinstalls, and versions already shown return False; they
    record the picker they leave only when nothing is waiting to be
    announced, and rows that were found but not announced are never
    recorded, so a failed write is retried by the next install. The pid of
    a dialog an earlier version left open is carried over so the next
    show_pending() folds into it instead of stacking a second dialog.
    `clients` is the install run's attachment set when it knows one;
    without it the previous notice's set is kept, and a legacy install
    reads as Codex-only. A notice never affects installs.
    """
    try:
        path = Path(home) / NOTICE_FILE
        try:
            existing = json.loads(path.read_text())
        except (OSError, ValueError):
            existing = None
        picker = _picker_slugs(_read_blob(Path(home) / CATALOGUE_FILE))
        baseline = _picker_baseline(home)
        added = None if picker is None or baseline is None else picker - baseline
        if not previous or previous == version:
            # Fresh installs and reinstalls prompt nothing; record what they
            # leave behind so the next version compares against it.
            if not added:
                _remember_picker(home, picker)
            return False
        if isinstance(existing, dict) and existing.get('version') == version \
                and existing.get('shown'):
            _remember_picker(home, picker)
            return False
        pending = isinstance(existing, dict) and not existing.get('shown')
        if not pending and added is not None and not added:
            _remember_picker(home, picker)
            return False
        if not clients:
            # A scheduled update passes no --clients; the install recorded
            # the attachment set in the router state.
            try:
                state = json.loads((Path(home) / 'mixed-router-state.json').read_text())
                clients = state.get('clients')
            except (OSError, ValueError, AttributeError):
                clients = None
        doc = {'version': version, 'at': _utcnow(),
               'clients': _text.clients(clients) if clients
               else (existing if isinstance(existing, dict) else {}).get('clients', 'codex')}
        pid = _dialog_pid(existing)
        if pid:
            doc['pid'] = pid
        _atomic_write.replace_json(path, doc)
        # Only a staged notice marks rows as announced; a write that failed
        # leaves the baseline alone so the next install retries.
        _remember_picker(home, picker)
        return True
    except (OSError, ValueError):
        return False


def _darwin_script(message, icon, restart=True):
    """AppleScript for the dialog, restarting Codex when asked.

    The restart is the last thing the script does, so a failure to quit or
    relaunch can never take the dialog down with it. Strings stay raw
    UTF-8: AppleScript has no unicode escape, and the default json.dumps
    escaping would emit one for any accented path. A Claude-only install has
    no Codex app to reopen, so it gets the plain OK dialog.
    """
    quote = lambda text: json.dumps(text, ensure_ascii=False)  # noqa: E731
    icon_clause = (' with icon (POSIX file %s)' % quote(icon)
                   if icon else ' with icon note')
    if not restart:
        return ('display dialog %s buttons {"%s"} default button "%s" '
                'with title "%s"%s'
                % (quote(message), OK, OK, TITLE, icon_clause))
    return '\n'.join([
        'set answer to button returned of (display dialog %s with title "%s" '
        'buttons {"%s", "%s"} default button "%s" cancel button "%s"%s)'
        % (quote(message), TITLE, DISMISS, REOPEN, REOPEN, DISMISS,
           icon_clause),
        'if answer is "%s" then' % REOPEN,
        '  try',
        '    tell application id "%s" to quit' % CODEX_BUNDLE_ID,
        '    repeat 25 times',
        '      if application id "%s" is not running then exit repeat' % CODEX_BUNDLE_ID,
        '      delay 0.2',
        '    end repeat',
        '  end try',
        '  do shell script "open -b %s"' % CODEX_BUNDLE_ID,
        'end if',
    ])


def _windows_restart():
    """PowerShell that closes the Codex Store app and starts it again.

    The app is an MSIX package, so it is started through its package
    family identity rather than an executable path; `Get-StartApps` is the
    documented fallback for the launch identity. The quit is scoped to
    processes running out of that package: a host with only the Codex CLI
    must not lose it, and without a resolved identity nothing is quit.
    Everything is guarded: when the app cannot be found the dialog merely
    closes.
    """
    return (
        "try { "
        "$pkg = Get-AppxPackage -Name '%s' -ErrorAction SilentlyContinue; "
        "$aumid = $null; "
        "if ($pkg) { "
        "$entry = (Get-AppxPackageManifest $pkg).Package.Applications.Application "
        "| Select-Object -First 1; "
        "if ($entry) { $aumid = $pkg.PackageFamilyName + '!' + $entry.Id } }; "
        "if (-not $aumid) { "
        "$start = Get-StartApps | "
        "Where-Object { $_.Name -match '^(Codex|ChatGPT)' } | Select-Object -First 1; "
        "if ($start) { $aumid = $start.AppID } }; "
        "if ($pkg) { "
        "$root = $pkg.InstallLocation; "
        "$procs = @(Get-Process -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Path -and $_.Path.StartsWith($root, 'OrdinalIgnoreCase') }); "
        "foreach ($p in $procs) { try { [void]$p.CloseMainWindow() } catch { } }; "
        "Start-Sleep -Seconds 3; "
        "foreach ($p in $procs) { "
        "try { if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force } } catch { } }; "
        "if ($aumid) { Start-Process ('shell:AppsFolder\\' + $aumid) } } "
        "} catch { }" % WINDOWS_PACKAGE)


def _linux_command(message, icon=None, app=None, restart=True):
    """argv for the Linux dialog, quitting and relaunching the app.

    zenity reports the choice through its exit status, so the restart runs
    in the same detached shell the dialog is spawned from: the installer
    still never waits for the user. The dialog argv travels as positional
    parameters so no path or message is ever re-parsed by the shell.
    Without the desktop app installed the dialog is informational, exactly
    as before.
    """
    dialog = ['zenity', '--question' if app and restart else '--info',
              '--title=' + TITLE]
    if icon:
        dialog.append('--window-icon=' + icon)
    dialog.append('--text=' + message)
    if not (app and restart):
        return dialog + ['--ok-label=' + (DISMISS if restart else OK)]
    dialog += ['--ok-label=' + REOPEN, '--cancel-label=' + DISMISS]
    launch = ("if command -v setsid >/dev/null 2>&1; "
              "then setsid -f %(app)s; "
              "else nohup %(app)s >/dev/null 2>&1 & fi" % {'app': app})
    script = ('if "$@" >/dev/null 2>&1; then '
              'pkill -x %(app)s; sleep 2; %(launch)s; fi'
              % {'app': app, 'launch': launch})
    return ['sh', '-c', script, 'scg-router'] + dialog


def _windows_script(message, icon=None, restart=True):
    quoted = message.replace("'", "''")
    picture = ''
    if icon:
        picture = (
            "$p = New-Object System.Windows.Forms.PictureBox; "
            "$p.Image = [System.Drawing.Image]::FromFile('%s'); "
            "$p.SizeMode = 'StretchImage'; $p.Width = 64; $p.Height = 64; "
            "$f.Controls.Add($p); " % icon.replace("'", "''"))
    reopen = (
        "$r = New-Object System.Windows.Forms.Button; "
        "$r.Text = 'Quit and reopen'; $r.Dock = 'Bottom'; "
        "$r.Add_Click({ $f.Tag = 'reopen'; $f.Close() }); ")
    if restart:
        restart_block = ("if ($f.Tag -eq 'reopen') { %s }" % _windows_restart())
        buttons = ("$f.Controls.Add($l); $f.Controls.Add($b); $f.Controls.Add($r); ")
        dismiss = DISMISS
    else:
        reopen, restart_block = '', ''
        buttons = "$f.Controls.Add($l); $f.Controls.Add($b); "
        dismiss = OK
    return (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        "$f = New-Object System.Windows.Forms.Form; "
        "$f.Text = '%s'; $f.TopMost = $true; "
        "$f.StartPosition = 'CenterScreen'; $f.AutoSize = $true; "
        "$l = New-Object System.Windows.Forms.Label; "
        "$l.Text = '%s'; $l.AutoSize = $true; $l.Dock = 'Top'; "
        "%s"
        "$b = New-Object System.Windows.Forms.Button; "
        "$b.Text = '%s'; $b.Dock = 'Bottom'; "
        "$b.Add_Click({ $f.Close() }); "
        "%s"
        "%s"
        "[void]$f.ShowDialog(); "
        "%s" % (TITLE, quoted, picture, dismiss, reopen, buttons, restart_block)
    )


def dialog_command(version, platform_name=None, which=None, icon=None,
                   clients='codex', names=()):
    """argv for a one-shot dismissible restart dialog, or None.

    None means the platform is unknown or its dialog tool is missing, so
    the caller leaves the notice pending for a later GUI run. `which` and
    `icon` are injectable so tests never probe the host; the icon defaults
    to the bundled logo and is dropped when that asset is not installed.
    `clients` names the attached client(s): only a Codex install gets the
    app restart button, because that button relaunches the Codex app.
    `names` are the added models the dialog may list.
    """
    if platform_name is None:
        platform_name = sys.platform
    if which is None:
        which = shutil.which
    if icon is None and ICON.is_file():
        icon = str(ICON)
    clients = _text.clients(clients)
    restart = clients in ('codex', 'both')
    message = _message(version, clients, names)
    if platform_name == 'darwin':
        if which('osascript') is None:
            return None
        return ['osascript', '-e', _darwin_script(message, icon, restart)]
    if platform_name.startswith('linux'):
        if which('zenity') is not None:
            app = LINUX_APP if restart and which(LINUX_APP) is not None else None
            return _linux_command(message, icon, app, restart)
        if which('notify-send') is not None:
            return ['notify-send', TITLE, message]
        return None
    if platform_name == 'win32':
        powershell = which('powershell') or which('powershell.exe')
        if powershell is None:
            return None
        return [powershell, '-NoProfile', '-WindowStyle', 'Hidden',
                '-Command', _windows_script(message, icon, restart)]
    return None


def _spawn(cmd):
    """Launch the dialog detached and return its pid; never waits."""
    if sys.platform == 'win32':
        flags = (getattr(subprocess, 'DETACHED_PROCESS', 0)
                 | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                creationflags=flags)
    else:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                close_fds=True, start_new_session=True)
    return proc.pid


def _dialog_up(pid, pid_alive):
    """True when the spawned dialog is still running after a short grace."""
    time.sleep(PROBE_GRACE_S)
    return pid_alive(pid)


def show_pending(home, spawn=None, pid_alive=None):
    """Show the pending restart notice; True once it is shown.

    A missing dialog tool leaves the notice pending so a later GUI run
    retries; the file is marked shown only once the spawned dialog is still
    up after a short grace. While the dialog from an earlier version is
    still open, this notice is marked shown rather than stacked on top of
    it. Any failure returns False and never surfaces to the installer.
    `ROUTER_NO_NOTICE=1` silences the dialog for unattended installs and for
    tests that run the real CLI.
    """
    if os.environ.get('ROUTER_NO_NOTICE') == '1':
        return False
    if spawn is None:
        spawn = _spawn
    if pid_alive is None:
        pid_alive = _pid_alive
    try:
        path = Path(home) / NOTICE_FILE
        doc = json.loads(path.read_text())
        if not isinstance(doc, dict) or doc.get('shown'):
            return False
        version = doc.get('version')
        if not isinstance(version, str) or not version:
            return False
        cmd = dialog_command(version, icon=_home_icon(home) or '',
                             clients=doc.get('clients', 'codex'),
                             names=_text.pending_names(home))
        if cmd is None:
            return False
        shown = {'version': version, 'shown': True, 'at': _utcnow()}
        if cmd[0] == 'notify-send':
            # It exits once the notification daemon accepts or refuses the
            # notification, so the exit status is the delivery signal and
            # pid liveness says nothing.
            try:
                sent = subprocess.run(cmd, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL,
                                      timeout=PROBE_TIMEOUT)
            except (OSError, subprocess.SubprocessError):
                return False
            if sent.returncode:
                return False
            _atomic_write.replace_json(path, shown)
            return True
        pid = _dialog_pid(doc)
        if pid and pid_alive(pid):
            _atomic_write.replace_json(path, {'version': version, 'shown': True,
                                              'pid': pid, 'at': _utcnow()})
            return False
        pid = _dialog_pid({'pid': spawn(cmd)})
        if pid:
            if not _dialog_up(pid, pid_alive):
                return False
            shown['pid'] = pid
        _atomic_write.replace_json(path, shown)
        return True
    except (OSError, ValueError):
        return False
