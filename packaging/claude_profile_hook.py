"""Install and run the desktop's non-interactive session identity callback."""
import argparse
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path


def _load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_identity = _load('claude_profile_identity')
_desktop = _load('claude_desktop_config')
_config = _load('claude_config')
_atomic = _load('atomic_write')
RECEIPT = 'claude-profile-hook-receipt.json'


def _safe(path):
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError('unsafe callback path')


def install(home, python, env=None):
    home = Path(home)
    path = _config.settings_path(env)
    receipt_path = home / RECEIPT
    _safe(path)
    _safe(receipt_path)
    argv = [str(python), str(home / 'claude_profile_launch.py'),
            '--home', str(home), '--action', 'capture']
    command = subprocess.list2cmdline(argv) if os.name == 'nt' else shlex.join(argv)
    entry = {'hooks': [{'type': 'command', 'command': command, 'async': True, 'timeout': 5}]}
    doc = _config.read_settings(path)
    hooks = doc.setdefault('hooks', {})
    if not isinstance(hooks, dict) or not isinstance(hooks.setdefault('SessionStart', []), list):
        raise ValueError('invalid callback settings')
    entries = hooks['SessionStart']
    prior = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    if prior and prior['settings_path'] != str(path):
        raise ValueError('callback settings moved')
    if (prior and prior['inserted'] and prior['entry'] != entry
            and prior['entry'] in entries):
        entries[entries.index(prior['entry'])] = entry
    inserted = (prior['inserted'] if prior and prior['entry'] == entry
                else entry not in entries or bool(prior and prior['inserted']))
    if entry not in entries:
        entries.append(entry)
    # Record ownership before adding the exact entry; a retry or detach can
    # reconcile a crash without restoring unrelated user settings.
    _atomic.replace_json(receipt_path, {'settings_path': str(path),
                                      'entry': entry, 'inserted': inserted})
    _config.write_settings(path, doc)


def uninstall(home):
    receipt_path = Path(home) / RECEIPT
    if not receipt_path.exists() and not receipt_path.is_symlink():
        return
    _safe(receipt_path)
    receipt = json.loads(receipt_path.read_text())
    path = Path(receipt['settings_path'])
    _safe(path)
    if receipt['inserted'] and path.exists():
        doc = _config.read_settings(path)
        hooks = doc.get('hooks', {})
        entries = hooks.get('SessionStart', [])
        if receipt['entry'] in entries:
            entries.remove(receipt['entry'])
            if not entries:
                hooks.pop('SessionStart')
            if not hooks:
                doc.pop('hooks')
            _config.write_settings(path, doc)
    receipt_path.unlink()


def capture(event, env=None):
    env = os.environ if env is None else env
    if env.get('CLAUDE_CODE_ENTRYPOINT') != 'claude-desktop':
        return False
    profile = _desktop.profile_root(env) / 'Claude'
    guard = _identity._subscription_guard(profile)
    if not guard:
        return False
    # The native app publishes its focused record after starting the CLI.
    # Run asynchronously and bound the wait; never hold up a user's session.
    for attempt in range(20):
        if not _identity.same_guard(_identity._subscription_guard(profile), guard):
            return False
        if _identity.capture_subscription(profile, event, env):
            return True
        if attempt != 19:
            time.sleep(0.1)
    return False


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--home')
    parser.parse_args(argv)
    try:
        event = json.loads(sys.stdin.read(65536))
        if isinstance(event, dict):
            capture(event)
    except (OSError, ValueError, TypeError, KeyError, _identity.sqlite3.Error):
        pass  # A callback never blocks Claude or prints private task metadata.


if __name__ == '__main__':
    main()
