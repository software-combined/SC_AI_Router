"""Platform dialogs behind the first-run key window (Plan 139).

One place owns how each OS asks for the key, the subscription choice for the
client(s) this install serves (Codex, Claude Code, or both) and the starter,
and how it reports a plain message. `ai_router.key_prompt` owns the flow on
top of it. The key is written by the dialog tool to stdout; it is never
passed in argv, the environment, a file or a log.

The copy and the icon follow the popup style rule in `AGENTS.md` section 4a,
shared with the update notice.
"""
import json
import subprocess
import sys
from pathlib import Path

from . import dialog_tool, provider_defs

TITLE = 'SCG Router'
ICON = Path(__file__).resolve().parents[1] / 'packaging' / 'assets' / 'router-icon.png'
MODES = {'I have one': 'subscription', 'No subscription': 'none'}
STARTERS = {'Everyday help': 'general', 'Coding help': 'dev'}
CLIENTS = ('codex', 'claude', 'both', 'none')
TIMEOUT_S = 900  # matches ai_router.setup.SETUP_TTL_S

def key_prompt(provider_id=None):
    """Key prompt for one provider; checked wording only when it checks."""
    defn = provider_defs.get(provider_id) or provider_defs.OPENROUTER
    checked = ('checked before it is saved' if defn.key_info_shape != 'none'
               else 'saved as you paste it; the first request checks it')
    return f'Paste the {defn.label} key you were given. It is {checked}, and kept only on this computer.'


KEY_PROMPT = key_prompt()
CODEX_QUESTION = 'Do you also use a ChatGPT subscription on this computer?'
CLAUDE_QUESTION = 'Do you also use a Claude subscription for Claude Code?'
STARTER_QUESTION = 'How should Codex write for you by default?'


def clients(value):
    return value if value in CLIENTS else 'codex'


def icon():
    """The bundled product icon, or None when the asset is not installed."""
    return str(ICON) if ICON.is_file() else None


def questions(which='codex'):
    """(field, question, answers) in the order the dialog asks them.

    A service-only install asks only for the key; the starter follows the Codex question.
    """
    which = clients(which)
    asked = []
    if which in ('codex', 'both'):
        asked.append(('mode', CODEX_QUESTION, tuple(MODES)))
    if which in ('claude', 'both'):
        asked.append(('claude_mode', CLAUDE_QUESTION, tuple(MODES)))
    if which in ('codex', 'both'):
        asked.append(('profile', STARTER_QUESTION, tuple(STARTERS)))
    return asked


def tool(platform_name=None, which=None):
    """Path to this platform's dialog tool, or None when there is no GUI."""
    return dialog_tool.tool(platform_name, which)


def _quote(text):
    return json.dumps(text, ensure_ascii=False)


def _icon_clause():
    return ' with icon (POSIX file %s)' % _quote(icon()) if icon() else ''


def _macos_script(which='codex', provider_id=None):
    """One AppleScript run: the key, then each question in order."""
    clause = _icon_clause()
    lines = ['set k to text returned of (display dialog %s default answer "" '
             'buttons {"Cancel", "Continue"} default button "Continue" '
             'with title "%s" with hidden answer%s)'
             % (_quote(key_prompt(provider_id)), TITLE, clause)]
    collected = ['k']
    for index, (_field, question, answers) in enumerate(questions(which)):
        var = 'a%d' % index
        buttons = '{%s}' % ', '.join('"%s"' % answer
                                     for answer in reversed(answers))
        lines.append('set %s to button returned of (display dialog %s '
                     'buttons %s default button "%s" with title "%s"%s)'
                     % (var, _quote(question), buttons, answers[0], TITLE, clause))
        collected.append(var)
    # text returned of display dialog drops trailing newlines, so a blank
    # key box would shift every later answer by one line; ask AppleScript
    # for an explicit separator character instead of a literal.
    lines.append('set line_break to ASCII character 10')
    lines.append('return ' + ' & line_break & '.join(collected))
    return '\n'.join(lines)


def combo_name(index):
    """The PowerShell variable holding answer `index`; one owner for it."""
    return '$c%d' % index


def _labelled(index, prompt, answers):
    """PowerShell that adds one labelled combo box to the layout panel."""
    label, combo = '$l%d' % index, combo_name(index)
    return ("%s = New-Object System.Windows.Forms.Label; %s.AutoSize = $true; "
            "%s.Margin = New-Object System.Windows.Forms.Padding(0, 8, 0, 2); "
            "%s.Text = '%s'; $p.Controls.Add(%s); "
            "%s = New-Object System.Windows.Forms.ComboBox; "
            "%s.DropDownStyle = 'DropDownList'; "
            "%s.Items.AddRange(@('%s')); %s.SelectedIndex = 0; "
            "%s.Width = 420; $p.Controls.Add(%s); "
            % (label, label, label, label, prompt.replace("'", "''"), label,
               combo, combo, combo,
               "', '".join(answer.replace("'", "''") for answer in answers),
               combo, combo, combo))


def _windows_script(which='codex', provider_id=None):
    """One WinForms form: product icon, masked key and each question.

    Every control goes into an explicit top-down FlowLayoutPanel. WinForms
    gives a control added straight to a Form the default Location (0, 0), so
    without a layout container the whole dialog stacks in the top-left
    corner: the key box and both buttons end up hidden behind the label and
    the operator cannot type or submit. macOS and Linux are unaffected,
    because osascript and zenity lay their own dialogs out.
    """
    picture = ''
    if icon():
        picture = ("$i = $null; try { $i = [System.Drawing.Image]::FromFile('%s') } "
                   "catch { }; if ($i) { $pic = New-Object "
                   "System.Windows.Forms.PictureBox; $pic.Image = $i; "
                   "$pic.Size = New-Object System.Drawing.Size(48, 48); "
                   "$pic.SizeMode = 'Zoom'; "
                   "$pic.Margin = New-Object System.Windows.Forms.Padding(0, 0, 0, 8); "
                   "$p.Controls.Add($pic) }; "
                   % icon().replace("'", "''"))
    asked = questions(which)
    boxes = ''.join(_labelled(index, question, answers)
                    for index, (_f, question, answers) in enumerate(asked))
    output = '[Console]::Out.Write($k.Text' + ''.join(
        ' + "`n" + %s.SelectedItem' % combo_name(index)
        for index in range(len(asked))) + ')'
    return (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        "[System.Windows.Forms.Application]::EnableVisualStyles(); "
        "$f = New-Object System.Windows.Forms.Form; $f.Text = '%s'; "
        "$f.TopMost = $true; $f.StartPosition = 'CenterScreen'; "
        "$f.FormBorderStyle = 'FixedDialog'; $f.MaximizeBox = $false; "
        "$f.MinimizeBox = $false; $f.AutoSize = $true; "
        "$f.AutoSizeMode = 'GrowAndShrink'; "
        "$f.Padding = New-Object System.Windows.Forms.Padding(14); "
        "$p = New-Object System.Windows.Forms.FlowLayoutPanel; "
        "$p.FlowDirection = 'TopDown'; $p.WrapContents = $false; "
        "$p.AutoSize = $true; $p.AutoSizeMode = 'GrowAndShrink'; $p.Dock = 'Fill'; "
        "%s"
        "$t = New-Object System.Windows.Forms.Label; $t.AutoSize = $true; "
        "$t.MaximumSize = New-Object System.Drawing.Size(420, 0); "
        "$t.Margin = New-Object System.Windows.Forms.Padding(0, 0, 0, 6); "
        "$t.Text = '%s'; $p.Controls.Add($t); "
        "$k = New-Object System.Windows.Forms.TextBox; $k.Width = 420; "
        "$k.UseSystemPasswordChar = $true; $p.Controls.Add($k); "
        "%s"
        "$r = New-Object System.Windows.Forms.FlowLayoutPanel; "
        "$r.FlowDirection = 'LeftToRight'; $r.WrapContents = $false; "
        "$r.AutoSize = $true; $r.AutoSizeMode = 'GrowAndShrink'; "
        "$r.Margin = New-Object System.Windows.Forms.Padding(0, 12, 0, 0); "
        "$b = New-Object System.Windows.Forms.Button; $b.Text = 'Save and connect'; "
        "$b.AutoSize = $true; "
        "$b.Add_Click({ $f.Close() }); $r.Controls.Add($b); "
        "$c = New-Object System.Windows.Forms.Button; $c.Text = 'Cancel'; "
        "$c.AutoSize = $true; "
        "$c.Add_Click({ $f.Tag = 'cancel'; $f.Close() }); $r.Controls.Add($c); "
        "$p.Controls.Add($r); $f.Controls.Add($p); "
        "$f.AcceptButton = $b; $f.CancelButton = $c; "
        "$f.Add_Shown({ $f.Activate(); $k.Focus() }); "
        "[void]$f.ShowDialog(); if ($f.Tag -eq 'cancel') { exit 2 }; "
        "%s" % (TITLE, picture, key_prompt(provider_id).replace("'", "''"), boxes, output))


def _zenity_argv(tool_path, which='codex', provider_id=None):
    defn = provider_defs.get(provider_id) or provider_defs.OPENROUTER
    argv = [tool_path, '--forms', '--title=' + TITLE, '--text=' + key_prompt(provider_id)]
    if icon():
        argv.append('--window-icon=' + icon())
    argv.append('--add-password=%s key' % defn.label)
    for _field, question, answers in questions(which):
        argv.append('--add-combo=' + question)
        argv.append('--combo-values=' + '|'.join(answers))
    return argv + ['--separator=	']


def argv(tool_path, platform_name, which='codex', provider_id=None):
    """The command that shows the key dialog on this platform."""
    if platform_name == 'darwin':
        return [tool_path, '-e', _macos_script(which, provider_id)]
    if platform_name == 'win32':
        return [tool_path, '-NoProfile', '-WindowStyle', 'Hidden',
                '-Command', _windows_script(which, provider_id)]
    return _zenity_argv(tool_path, which, provider_id)


def collect(tool_path, platform_name=None, run=None, which='codex',
            provider_id=None):
    """Choices from the platform dialog, or None when the operator cancels.

    OSError means the dialog itself could not be used, so the caller falls
    back to the loopback page. The answer order matches `questions()`.
    """
    if platform_name is None:
        platform_name = sys.platform
    if run is None:
        run = subprocess.run
    result = run(argv(tool_path, platform_name, which, provider_id),
                 stdout=subprocess.PIPE,
                 stderr=subprocess.PIPE, text=True, timeout=TIMEOUT_S)
    if (platform_name.startswith('linux') and result.returncode == 1) \
            or (platform_name == 'win32' and result.returncode == 2):
        # zenity without a display (SSH, headless) also exits 1; that is not
        # a cancel, so the caller can fall back to the loopback page.
        if 'cannot open display' in (result.stderr or '').lower():
            raise OSError('the key dialog has no display')
        return None
    if result.returncode:
        stderr = result.stderr or ''
        # AppleScript reports cancel as error -128, and macOS spells it
        # "cancelled" in some versions; match either, since a missed cancel
        # is treated as a dialog failure and opens the browser fallback.
        if 'User cancel' in stderr or '(-128)' in stderr:
            return None
        raise OSError('the key dialog did not complete')
    asked = questions(which)
    parts = (result.stdout or '').split('\t' if platform_name.startswith('linux')
                                        else '\n')
    if not platform_name.startswith('linux') and parts and parts[-1] == '':
        # osascript ends its return value with a newline; the blank key case
        # keeps its leading empty field, so only the trailing one is dropped.
        parts.pop()
    if len(parts) != 1 + len(asked):
        raise OSError('the key dialog returned the wrong number of answers')
    fields = {'key': parts[0].strip()}
    for (field, _question, _answers), raw in zip(asked, parts[1:]):
        table = STARTERS if field == 'profile' else MODES
        value = table.get(raw.strip())
        if value is None:
            raise OSError('the key dialog returned an unknown choice')
        fields[field] = value
    return fields


def message_argv(tool_path, message, platform_name):
    """The command that shows a plain native message."""
    clause = _icon_clause()
    if platform_name == 'darwin':
        return [tool_path, '-e', 'display dialog %s buttons {"OK"} '
                'default button "OK" with title "%s"%s'
                % (_quote(message), TITLE, clause)]
    if platform_name == 'win32':
        picture = ''
        if icon():
            picture = ("try { Add-Type -AssemblyName System.Drawing; "
                       "$i = [System.Drawing.Image]::FromFile('%s') } catch { $i = $null }; "
                       % icon().replace("'", "''"))
        return [tool_path, '-NoProfile', '-WindowStyle', 'Hidden', '-Command',
                "Add-Type -AssemblyName System.Windows.Forms; " + picture +
                "[void][System.Windows.Forms.MessageBox]::Show('%s', '%s')"
                % (message.replace("'", "''"), TITLE)]
    argv_ = [tool_path, '--info', '--title=' + TITLE]
    if icon():
        argv_.append('--window-icon=' + icon())
    return argv_ + ['--text=' + message]


def message(tool_path, text, platform_name=None, run=None):
    """Best-effort native message; a missing dialog tool is not an error."""
    if platform_name is None:
        platform_name = sys.platform
    if run is None:
        run = subprocess.run
    try:
        run(message_argv(tool_path, text, platform_name),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    except (OSError, subprocess.SubprocessError):
        pass
