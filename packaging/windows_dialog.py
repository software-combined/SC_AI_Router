"""Verified native Windows dialogs; legacy script retained for installer callers."""
import importlib.util
import json
import subprocess
from pathlib import Path

ICON = Path(__file__).parent / 'assets/router-icon.png'


def _load(name):
    spec = importlib.util.spec_from_file_location('router_windows_dialog_' + name,
        Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def command(home, mode, text, labels):
    resources = _load('native_resources').current(home)
    metadata = _load('native_payload').metadata(resources, 'windows/x86_64')
    helper = resources / 'control/scg-router-menu.exe'
    icon = resources / 'router/packaging/assets/router-icon.png'
    if not metadata.get('menu_sha256') or not icon.is_file():
        raise OSError('The switch window is unavailable')
    request = json.dumps(dict(text=text, labels=list(labels)), ensure_ascii=False) + '\n'
    return [str(helper), mode, str(icon)], request


def show(text, home, confirm, run=subprocess.run, *, labels=('Continue', 'Cancel')):
    args, request = command(home, '--dialog', text, labels if confirm else labels[-1:])
    result = run(args, input=request, capture_output=True, text=True, encoding='utf-8',
                 timeout=120, creationflags=0x08000000)
    markers = [line for line in (result.stdout or '').splitlines()
               if line.startswith('SCG_ROUTER_DIALOG_RESULT=')]
    if result.returncode == 0 and markers == ['SCG_ROUTER_DIALOG_RESULT=accept']:
        return True
    if result.returncode == 1 and markers == ['SCG_ROUTER_DIALOG_RESULT=cancel']:
        return False
    raise _load('windows_native').NativeError('confirmation', 'invalid_response', result.returncode)


def progress(home, text, button):
    args, request = command(home, '--progress', text, (button,))
    child = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, text=True, encoding='utf-8', creationflags=0x08000000)
    try:
        child.stdin.write(request)
        child.stdin.flush()
    except OSError:
        child.terminate()
        child.communicate(timeout=5)
        raise
    return child


def _ps(value):
    return "'" + str(value).replace("'", "''") + "'"


def script(message, confirm, labels=('Continue', 'Cancel')):
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
        "%s$c=New-Object System.Windows.Forms.Button;$c.Text=%s;"
        "$c.AutoSize=$true;$c.DialogResult='Cancel';$r.Controls.Add($c);"
        "$f.CancelButton=$c;$p.Controls.Add($l);$p.Controls.Add($r);$f.Controls.Add($p);"
        "if($f.ShowDialog() -eq 'OK'){'SCG_ROUTER_DIALOG_RESULT=accept';exit 0}"
        "else{'SCG_ROUTER_DIALOG_RESULT=cancel';exit 1}"
        % (_ps(ICON), _ps(message), (
            "$b=New-Object System.Windows.Forms.Button;$b.Text=%s;"
            "$b.AutoSize=$true;$b.DialogResult='OK';$r.Controls.Add($b);"
        ) % _ps(labels[0]) if confirm else '', _ps(labels[-1])))
