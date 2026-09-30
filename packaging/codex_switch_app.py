"""The Switch Codex app, kept in step with the Codex attachment on a Mac.

`codex_switch_offer.APP` names where it lives. Every attach and update builds
or refreshes it when this install may need it: macOS, Codex attached in
subscription mode, and either the installed ChatGPT app at or above
`codex_switch_offer.AFFECTED_FROM` or Codex switched right now, so older
Codex builds see nothing new. Otherwise an app this router owns is removed,
but never while Codex is switched, because it is the way back. Detach and
uninstall remove it through tools/disable.py, which refuses while switched.

The app runs `LAUNCHER`, a copy in the router home, under the router's own
Python, so updates and release pruning never break it. It belongs to this
router when its bundle id is `BUNDLE_ID` and it names this router home, so
another home (a test's, say) never removes it. A failed build or removal
prints one plain line and never fails an install.

Python 3.9-safe, stdlib only and inert on import.
"""
import importlib.util
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

BUNDLE_ID = 'com.softwarecombined.router.codex-switch'
LAUNCHER = 'codex_switch_launch.py'
HOME_KEY = 'SCGRouterHome'


def _load(name):
    spec = importlib.util.spec_from_file_location(
        'router_codex_app_' + name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_offer = _load('codex_switch_offer')
_platform = _load('claude_desktop_platform')
_receipts = _load('codex_config')
_blocks = _load('codex_switch_config')


def _owner(home):
    return str(Path(home).resolve())


def _switched(home):
    """True while Codex is switched, and when that cannot be told: keep the way back."""
    try:
        return _blocks.current(home) == _blocks.SWITCHED
    except (OSError, ValueError, SystemExit):
        return True


def wanted(home):
    """True when this install should carry the app; macOS is the caller's check."""
    entry = _receipts.codex_attachment(home)
    if not entry.get('inserted_block') or entry.get('openai_mode') == 'none':
        return False
    affected = _offer._version(_offer.AFFECTED_FROM)
    return _switched(home) or (_offer.installed() or ()) >= affected


def remove(home):
    """Remove the app when it is this router's own; True when it was removed."""
    app = Path(_offer.APP)
    try:
        info = plistlib.loads((app / 'Contents' / 'Info.plist').read_bytes())
    except (OSError, ValueError):
        return False
    if info.get('CFBundleIdentifier') != BUNDLE_ID or info.get(HOME_KEY) != _owner(home):
        return False
    shutil.rmtree(app)
    return True


def sync(home, python, platform_name=None, run=subprocess.run):
    """Build, refresh or remove the app to match this install. Never raises."""
    if (platform_name or sys.platform) != 'darwin':
        return
    try:
        if wanted(home):
            # Only into the home this process runs for: a caller that moved
            # HOME after `APP` was named (a test) never writes the real one.
            if Path.home() in Path(_offer.APP).parents:
                _platform.install_mac_app(_offer.APP, BUNDLE_ID, python, home, LAUNCHER,
                                          plist={HOME_KEY: _owner(home)}, run=run)
        elif not _switched(home):
            remove(home)
    except _platform.NotOwned:
        print('Codex connected; Switch Codex could not be installed. Switch Codex '
              'already exists. Contact your administrator.')
    except Exception:
        print('Codex connected; Switch Codex could not be set up. Run setup again to retry.')
