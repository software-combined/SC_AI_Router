"""Interactive maintenance uses the existing graceful assistant-close flow."""
import importlib.util
import subprocess
import sys
from pathlib import Path


def _load(name):
    spec = importlib.util.spec_from_file_location('router_repair_' + name,
                                                Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def close_assistants(home, run=subprocess.run, *, removing=False):
    """Explicit repair/removal only. Scheduled updates never call this helper."""
    entries = _load('codex_config').read_receipt(home).get('clients', {})
    labels = {'codex': 'Codex', 'claude': 'Claude Code', 'claude-desktop': 'Claude desktop'}
    if not isinstance(entries, dict) or set(entries) - labels.keys():
        raise SystemExit('Assistant connection conflict: damaged_receipt.')
    if removing:
        # Removal restores settings with apps open; only Claude on OpenRouter must
        # close first, because its connection is written while it is closed.
        entries = {name: entry for name, entry in entries.items()
                   if name == 'claude-desktop' and _on_openrouter(home)}
    if not entries:
        return True
    names = ', '.join(labels[name] for name in labels if name in entries)
    dialog, platform = _load('native_dialog'), _load('claude_desktop_platform')
    if removing:
        question = ('Removal will switch Claude desktop back to your Claude subscription.\n\n'
                    'Choose Continue to close Claude after its work finishes. '
                    'Choose Cancel to keep SCG Router.')
    else:
        question = ('Update or repair will refresh settings for %s.\n\n'
                    'Close any active terminal sessions first. Choose Continue to close desktop apps '
                    'after their work finishes. Choose Cancel to leave setup for later.' % names)
    if dialog.confirm_result(question, home) is not True:
        return False
    apps = []
    if 'codex' in entries:
        apps.append(_load('codex_desktop_switch').CODEX)
    if 'claude-desktop' in entries:
        apps.append(platform.CLAUDE)
    for app in apps:
        try:
            running = platform.is_running(sys.platform, run=run, app=app)
        except (OSError, subprocess.SubprocessError):
            name = 'Codex' if app.bundle_id == 'com.openai.codex' else 'Claude'
            if dialog.confirm_result('Please quit %s before continuing. If you only use it '
                    'in a terminal, close those sessions. Choose Continue after it is closed.' % name, home) is not True:
                return False
            continue
        if running and platform.request_stop(sys.platform, run=run, app=app) is not True:
            dialog.message('Your assistant is still open. Finish its work, then run setup again.')
            return False
    return True


def _on_openrouter(home):
    """True unless Claude is known to be on the subscription, so an unreadable state closes it."""
    switch = _load('claude_desktop_switch')
    try:
        return switch.attached_profile(home)[1]['deploymentMode'] != '1p'
    except switch.SwitchError:
        return True
