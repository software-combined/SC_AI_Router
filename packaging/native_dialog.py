"""Native setup dialogs, sharing the router's title, icon and two actions."""
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path


def _load(name):
    spec = importlib.util.spec_from_file_location(
        'router_native_dialog_' + name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dialog = _load('client_dialog')
platform = _load('claude_desktop_platform')
TITLE, ICON = dialog.TITLE, dialog.ICON


def choose(question, options, run=subprocess.run):
    tool = dialog.tool()
    if not tool:
        raise OSError('The setup window is unavailable.')
    result = run(dialog.argv(tool, sys.platform, question, options),
                 capture_output=True, text=True, timeout=300)
    return dialog.answer(sys.platform, result.stdout, options) if result.returncode == 0 else None


def message(text):
    return platform.show_message(text, sys.platform)


def confirm(text):
    return platform.confirm(text, sys.platform)


def confirm_result(text, home=None, run=subprocess.run):
    """True means Continue, False means Cancel, None means no presentation."""
    tool = dialog.tool(home=home)
    if not tool or (sys.platform.startswith('linux') and not (
            os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))):
        return None
    try:
        result = platform._dialog(text, sys.platform, True, run, tool, detailed=True)
    except (OSError, subprocess.SubprocessError):
        return None
    stdout, stderr = result.stdout or '', result.stderr or ''
    if sys.platform == 'darwin':
        if result.returncode == 0 and 'button returned:Continue' in stdout:
            return True
        if result.returncode == 1 and re.search(r'\(-128\)\s*$', stderr):
            return False
    elif result.returncode == 0:
        return True
    elif result.returncode == 1 and not stderr.strip():
        return False
    return None


class Progress:
    """Keep Cancel available without terminating an in-progress service swap."""
    def __init__(self):
        self.process = None
        self.cancelled = False

    def __enter__(self):
        text = ('Setting up SCG Router. This can take a few minutes.\n\n'
                'Cancel closes setup after the current step finishes.')
        if sys.platform == 'darwin':
            args = ['/usr/bin/osascript', '-e', platform.dialog_script(text)]
        elif sys.platform == 'win32':
            args = ['powershell', '-NoProfile', '-WindowStyle', 'Hidden',
                    '-Command', platform._windows_dialog(text, False)]
        else:
            args = [dialog.tool(), '--progress', '--pulsate', '--auto-close',
                    '--title=' + TITLE, '--window-icon=' + str(ICON),
                    '--text=' + text, '--cancel-label=Cancel']
        self.process = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, stdin=subprocess.PIPE)
        return self

    def __exit__(self, *_):
        self.cancelled = self.process.poll() is not None
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.communicate()
