"""Renewal notice: retain a pending request when no graphical session exists."""
import importlib.util
import json
import subprocess
import time
from pathlib import Path


def _load(name):
    spec = importlib.util.spec_from_file_location(
        'router_download_notice_' + name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def show(home, now=None):
    home = Path(home)
    now = time.time() if now is None else now
    marker = home / 'download-notice.json'
    try:
        previous = json.loads(marker.read_text()).get('shown', 0)
    except (OSError, ValueError, AttributeError):
        previous = 0
    if isinstance(previous, (int, float)) and now - previous < 86400:
        return False
    dialog = _load('native_dialog')
    try:
        answer = dialog.confirm_result('Sign in again to keep SCG Router downloads working. '
                                       'Your assistants can keep using the saved setup.\n\n'
                                       'Continue opens Microsoft sign-in with your work account.', home)
        if answer is None:
            return False
        _load('atomic_write').replace_json(marker, {'shown': now})
        if not answer:
            return False
        _load('download_auth').signin(home)
        return True
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        try:
            dialog.message('Download sign-in did not finish. '
                           'Open SCG Router and choose Sign in for downloads to try again.')
        except (OSError, subprocess.SubprocessError):
            pass
        return False
