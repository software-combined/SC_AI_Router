"""Renewal notice: retain a pending request when no graphical session exists."""
import importlib.util
import json
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
    if not dialog.dialog.tool():
        return False
    _load('atomic_write').replace_json(marker, {'shown': now})
    try:
        if not dialog.confirm('Sign in again to keep SCG Router downloads working. '
                              'Your assistants can keep using the saved setup.\n\n'
                              'Continue opens Microsoft sign-in with your work account.'):
            return False
        _load('download_auth').signin(home)
        return True
    except (OSError, RuntimeError, ValueError):
        dialog.message('Download sign-in did not finish. '
                       'Open SCG Router and choose Sign in for downloads to try again.')
        return False
