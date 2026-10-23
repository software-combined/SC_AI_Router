"""The client chooser: two questions, one answer per client surface.

Runs on the installer's Python 3.9 with no router imports, next to the
update notice and the first-run key window, and follows the same popup
style (AGENTS.md 4a): the title `SCG Router`, the bundled icon, plain
language, a single selection and Continue/Cancel on both questions.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    'router_dialog_tool', Path(__file__).resolve().parents[1] / 'ai_router/dialog_tool.py')
_tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tool)

TITLE = 'SCG Router'
ICON = Path(__file__).resolve().parent / 'assets' / 'router-icon.png'
TIMEOUT_S = 300
CANCELLED = object()

# ChatGPT's app and terminal share one attachment, so its surface answer
# only shapes the confirmation line.
ASSISTANTS = (('chatgpt', 'ChatGPT'), ('claude', 'Claude'), ('both', 'Both'))
SURFACES = (('app', 'Desktop app'), ('terminal', 'Terminal'), ('both', 'Both'))
ASSISTANT_QUESTION = 'Which AI assistant do you use?'
SURFACE_QUESTION = 'Where do you use it?'
PLANS = {('chatgpt', 'app'): ('codex', False),
         ('chatgpt', 'terminal'): ('codex', False),
         ('chatgpt', 'both'): ('codex', False),
         ('claude', 'app'): ('none', True),
         ('claude', 'terminal'): ('claude', False),
         ('claude', 'both'): ('claude', True),
         ('both', 'app'): ('codex', True),
         ('both', 'terminal'): ('both', False),
         ('both', 'both'): ('both', True)}
CONFIRM = {('chatgpt', 'app'): 'The Codex app will use this router.',
           ('chatgpt', 'terminal'): 'Codex in the terminal will use this router.',
           ('chatgpt', 'both'): 'The Codex app and terminal will use this router.',
           ('claude', 'app'): 'The Claude app will use this router.',
           ('claude', 'terminal'): 'Claude Code in the terminal will use this router.',
           ('claude', 'both'): 'The Claude app and Claude Code will use this router.',
           ('both', 'app'): 'The Codex and Claude apps will use this router.',
           ('both', 'terminal'): 'Codex and Claude Code will use this router.',
           ('both', 'both'): 'Codex, Claude Code and the Claude app will use this router.'}
NO_TOOL_NOTE = 'The selection window is unavailable. Setup will use Codex.'
# The same absence on an explicit --choose-clients run attaches nothing, so
# that path must not promise a client.
NO_TOOL_EXPLICIT_NOTE = 'The selection window is unavailable; nothing was attached.'
NO_ANSWER_NOTE = 'No apps were selected.'


def plan(assistant, surface):
    """(clients, desktop) for one answered pair; KeyError means a bad answer."""
    return PLANS[(assistant, surface)]


def tool(platform_name=None, which=None, home=None):
    """This platform's dialog tool, or None when the machine has no GUI."""
    return _tool.tool(platform_name, which, home)


def _quote(text):
    return json.dumps(text, ensure_ascii=False)


def _icon():
    return str(ICON) if ICON.is_file() else None


def _labels(items):
    return [label for _key, label in items]


def _macos_script(question, items, labels):
    """A native popup menu keeps both questions to two action buttons."""
    return ('ObjC.import("AppKit");\n'
            'function run() {\n'
            '    var app = $.NSApplication.sharedApplication;\n'
            '    app.setActivationPolicy($.NSApplicationActivationPolicyAccessory);\n'
            '    var alert = $.NSAlert.alloc.init;\n'
            '    alert.messageText = %s;\n'
            '    alert.window.title = %s;\n'
            '    alert.informativeText = %s;\n'
            '    alert.icon = $.NSImage.alloc.initWithContentsOfFile(%s);\n'
            '    var picker = $.NSPopUpButton.alloc.initWithFramePullsDown('
            '$.NSMakeRect(0, 0, 260, 26), false);\n'
            '    picker.addItemsWithTitles(%s);\n'
            '    picker.sizeToFit;\n'
            '    picker.selectItemAtIndex(0);\n'
            '    alert.accessoryView = picker;\n'
            '    alert.addButtonWithTitle(%s);\n'
            '    alert.addButtonWithTitle(%s).keyEquivalent = "\\u001b";\n'
            '    app.activateIgnoringOtherApps(true);\n'
            '    if (alert.runModal !== $.NSAlertFirstButtonReturn) return "";\n'
            '    return ObjC.unwrap(picker.titleOfSelectedItem);\n'
            '}\n' % (_quote(TITLE), _quote(TITLE), _quote(question),
                     _quote(str(ICON)), _quote(_labels(items)), *map(_quote, labels)))


def _windows_script(question, items, labels):
    """One PowerShell question: a small list with Continue and Cancel.

    Every control sits in a layout panel: WinForms gives a control added
    straight to a form the location (0, 0), so a flat script stacks the
    list and both buttons in the corner (found live on Windows).
    """
    icon = _icon()
    icon_line = ("$f.Icon = [System.Drawing.Icon]::FromHandle("
                 "(New-Object System.Drawing.Bitmap '%s').GetHicon()); "
                 % icon.replace("'", "''")) if icon else ''
    choices = ','.join("'%s'" % label.replace("'", "''")
                       for label in _labels(items))
    return ("Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
            "$f = New-Object System.Windows.Forms.Form; "
            "$f.AutoSize = $true; $f.AutoSizeMode = 'GrowAndShrink'; $f.StartPosition = 'CenterScreen'; "
            "$f.Text = '%s'; %s"
            "$p = New-Object System.Windows.Forms.FlowLayoutPanel; "
            "$p.FlowDirection = 'TopDown'; $p.WrapContents = $false; "
            "$p.AutoSize = $true; $p.Dock = 'Fill'; "
            "$p.Padding = New-Object System.Windows.Forms.Padding(12); "
            "$l = New-Object System.Windows.Forms.Label; "
            "$l.Text = '%s'; $l.AutoSize = $true; $l.MaximumSize = '640,0'; "
            "$b = New-Object System.Windows.Forms.ListBox; "
            "@(%s) | ForEach-Object { [void]$b.Items.Add($_) }; "
            "$b.Width = [Math]::Min(640, [Math]::Max(260, (($b.Items | ForEach-Object { "
            "[System.Windows.Forms.TextRenderer]::MeasureText([string]$_, $b.Font).Width "
            "} | Measure-Object -Maximum).Maximum + 32))); "
            "$b.Height = [Math]::Min(8, $b.Items.Count) * $b.ItemHeight + 6; $b.HorizontalScrollbar = $true; "
            "$b.SelectionMode = 'One'; $b.SelectedIndex = 0; "
            "$r = New-Object System.Windows.Forms.FlowLayoutPanel; "
            "$r.FlowDirection = 'LeftToRight'; $r.WrapContents = $false; "
            "$r.AutoSize = $true; "
            "$ok = New-Object System.Windows.Forms.Button; $ok.Text = '%s'; "
            "$ok.AutoSize = $true; $ok.DialogResult = 'OK'; "
            "$c = New-Object System.Windows.Forms.Button; $c.Text = '%s'; "
            "$c.AutoSize = $true; $c.DialogResult = 'Cancel'; "
            "$r.Controls.Add($ok); $r.Controls.Add($c); "
            "$p.Controls.Add($l); $p.Controls.Add($b); $p.Controls.Add($r); "
            "$f.Controls.Add($p); $f.AcceptButton = $ok; "
            "$f.CancelButton = $c; "
            "if ($f.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) "
            "{ exit 2 }; Write-Output $b.SelectedItem"
            % (TITLE, icon_line, question.replace("'", "''"), choices,
               *(label.replace("'", "''") for label in labels)))


def _zenity_argv(tool_path, question, items, labels):
    argv = [tool_path, '--list', '--radiolist', '--title=' + TITLE,
            '--text=' + question, '--column=', '--column=', '--print-column=2',
            '--ok-label=' + labels[0], '--cancel-label=' + labels[1]]
    if _icon():
        argv.append('--window-icon=' + _icon())
    for index, label in enumerate(_labels(items)):
        argv += ['TRUE' if index == 0 else 'FALSE', label]
    return argv


def argv(tool_path, platform_name, question, items, *, labels=('Continue', 'Cancel')):
    """The command that asks one single-select question on this platform."""
    if platform_name == 'darwin':
        return [tool_path, '-l', 'JavaScript', '-e', _macos_script(question, items, labels)]
    if platform_name == 'win32':
        return [tool_path, '-NoProfile', '-WindowStyle', 'Hidden', '-Command',
                _windows_script(question, items, labels)]
    return _zenity_argv(tool_path, question, items, labels)


def answer(platform_name, stdout, items):
    """The chosen item's key, or None when nothing usable came back."""
    text = (stdout or '').strip()
    for key, label in items:
        if text == label:
            return key
    return None


def ask(platform_name=None, tool_path=None, run=None):
    """Return two choices, CANCELLED for cancellation, or None on failure."""
    if platform_name is None:
        platform_name = sys.platform
    if tool_path is None:
        tool_path = tool(platform_name)
    if tool_path is None:
        return None
    if run is None:
        run = subprocess.run
    picked = []
    for question, options in ((ASSISTANT_QUESTION, ASSISTANTS),
                              (SURFACE_QUESTION, SURFACES)):
        try:
            result = run(argv(tool_path, platform_name, question, options),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, timeout=TIMEOUT_S,
                         **({'creationflags': 0x08000000} if platform_name == 'win32' else {}))
        except (OSError, subprocess.SubprocessError):
            return None
        cancel_code = 0 if platform_name == 'darwin' else (
            2 if platform_name == 'win32' else 1)
        if result.returncode == cancel_code and not (result.stdout or '').strip():
            return CANCELLED
        if result.returncode:
            return None
        picked.append(answer(platform_name, result.stdout, options))
        if picked[-1] is None:
            return None
    return tuple(picked)


def maybe_ask(args, home, platform_name=None, tool_path=None, run=None,
              attached=False):
    """Ask on a fresh interactive install, or when --choose-clients is passed.

    Explicit flags, --dry-run, an unattended run and the suppression variable
    all leave the choice alone; nothing here ever blocks an install. `home` is
    the install home and `attached` says whether it already serves a client:
    the installer owns that receipt, so this module never names its file.
    """
    if args.dry_run or os.environ.get('ROUTER_NO_CLIENT_CHOOSER') == '1':
        return False
    if args.clients is not None or args.client is not None or args.desktop:
        return False
    if not args.choose_clients:
        if not sys.stdin.isatty() or attached:
            return False
    if tool_path is None:
        tool_path = tool(platform_name, home=home)
    if tool_path is None:
        print(NO_TOOL_NOTE if not args.choose_clients else NO_TOOL_EXPLICIT_NOTE)
        return False
    selection = ask(platform_name, tool_path, run)
    if selection is CANCELLED:
        args.clients = 'none'
        args.desktop = False
        args.client_choice_cancelled = True
        print(NO_ANSWER_NOTE)
        return False
    if selection is None:
        print(NO_TOOL_NOTE if not args.choose_clients else NO_TOOL_EXPLICIT_NOTE)
        return False
    args.clients, args.desktop = plan(*selection)
    print(CONFIRM[selection])
    return True
