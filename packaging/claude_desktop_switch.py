"""Switch the attached macOS Claude app without signing either profile out.

Only deploymentMode changes. Claude must finish quitting before the atomic
write, and the attachment is checked again afterwards to preserve app edits.
The installer owns attachment; this helper never creates or removes one.
"""
import argparse
import ctypes
import importlib.util
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _load(name):
    spec = importlib.util.spec_from_file_location(
        'router_switch_' + name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_desktop = _load('claude_desktop_config')
_receipts = _load('codex_config')
TITLE = 'SCG Router'
BUNDLE_ID = 'com.anthropic.claudefordesktop'
LAUNCHER_ID = 'com.softwarecombined.router.claude-switch'
ICON = Path(__file__).parent / 'assets' / 'router-icon.png'
DESTINATIONS = {'1p': 'your Claude subscription', '3p': 'OpenRouter'}


class SwitchError(Exception):
    """A message safe to show without paths, settings or credentials."""


def attached_profile(home):
    """Validate the receipt and effective gateway before trusting its path."""
    try:
        receipt = _receipts.read_receipt(home)['clients']['claude-desktop']
        path = Path(receipt['config_path'])
        snapshot = json.loads(receipt['inserted_block'])
        if (not path.is_absolute() or path.parent.name != 'configLibrary'
                or not isinstance(snapshot, dict)
                or not all(key in snapshot for key in _desktop.OWNED_KEYS)):
            raise ValueError('invalid attachment')
        profile = path.parent.parent
        if _desktop.applied_entry_path(profile).resolve() != path.resolve():
            raise ValueError('another configuration is selected')
        state = json.loads((Path(home) / 'mixed-router-state.json').read_text())
        entry = _desktop.read_entry(path)
        if any(entry.get(key) != value
               for key, value in _desktop.desired_values(state).items()):
            raise ValueError('gateway was changed')
        if entry.get('bootstrapUrl'):
            raise ValueError('managed setup')
        doc, config = _desktop.read_desktop_config(profile)
        if config is None or doc.get('deploymentMode') not in DESTINATIONS:
            raise ValueError('unknown selection')
        return config, doc
    except (OSError, ValueError, TypeError, KeyError, SystemExit) as exc:
        raise SwitchError('Claude is not connected to SCG Router. Run setup again.') from exc


def chooser_disabled():
    """Read the effective macOS preference, including managed preferences."""
    cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFPreferencesCopyAppValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    cf.CFPreferencesCopyAppValue.restype = ctypes.c_void_p
    cf.CFGetTypeID.argtypes = [ctypes.c_void_p]
    cf.CFGetTypeID.restype = ctypes.c_ulong
    cf.CFBooleanGetTypeID.restype = ctypes.c_ulong
    cf.CFBooleanGetValue.argtypes = [ctypes.c_void_p]
    cf.CFBooleanGetValue.restype = ctypes.c_bool
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    app = cf.CFStringCreateWithCString(None, BUNDLE_ID.encode(), 0x08000100)
    key = cf.CFStringCreateWithCString(None, b'disableDeploymentModeChooser', 0x08000100)
    value = None
    try:
        value = cf.CFPreferencesCopyAppValue(key, app)
        if not value:
            return False
        if cf.CFGetTypeID(value) != cf.CFBooleanGetTypeID():
            raise SwitchError('Claude settings could not be checked. Contact your administrator.')
        return bool(cf.CFBooleanGetValue(value))
    finally:
        for item in (value, key, app):
            if item:
                cf.CFRelease(item)


def dialog_script(message, confirm=False):
    quote = lambda value: json.dumps(str(value), ensure_ascii=False)
    buttons = '{"Cancel", "Switch"}' if confirm else '{"Cancel"}'
    return ('display dialog %s with title %s buttons %s default button "Cancel" '
            'cancel button "Cancel" with icon (POSIX file %s)'
            % (quote(message), quote(TITLE), buttons, quote(ICON)))


def _script(script, run, timeout):
    return run(['/usr/bin/osascript', '-e', script], capture_output=True,
               text=True, timeout=timeout)


def switch(home, *, run=subprocess.run, policy_check=chooser_disabled):
    """Return the selected mode, or None when cancelled; never force quit."""
    if sys.platform != 'darwin':
        raise SwitchError('Switch Claude is available on Mac.')
    config, before = attached_profile(home)
    mode = '1p' if before['deploymentMode'] == '3p' else '3p'
    try:
        if policy_check():
            raise SwitchError('Your organization manages how Claude connects. Contact your administrator.')
        prompt = ('Switch Claude to %s? Claude will restart. '
                  'Your conversations are kept separately.' % DESTINATIONS[mode])
        answer = _script(dialog_script(prompt, confirm=True), run, 120)
        if answer.returncode != 0 or 'button returned:Switch' not in answer.stdout:
            return None
        stopped = _script('\n'.join([
            'with timeout of 30 seconds',
            '  if application id "%s" is running then' % BUNDLE_ID,
            '    tell application id "%s" to quit' % BUNDLE_ID,
            '  end if',
            'end timeout',
            'repeat 120 times',
            '  if application id "%s" is not running then return "stopped"' % BUNDLE_ID,
            '  delay 0.25',
            'end repeat',
            'return "running"',
        ]), run, 65)
        if stopped.returncode != 0 or stopped.stdout.strip() != 'stopped':
            raise SwitchError('Claude stayed open. Finish your work and try again.')
        current_config, current = attached_profile(home)
        if (current_config != config
                or current['deploymentMode'] != before['deploymentMode']):
            raise SwitchError('Claude settings changed. Open Claude and try again.')
        if policy_check():
            raise SwitchError('Your organization manages how Claude connects. Contact your administrator.')
        current['deploymentMode'] = mode
        _desktop.write_json(config, current)
    except (OSError, subprocess.SubprocessError, SystemExit) as exc:
        raise SwitchError('Claude could not switch. Open Claude and try again.') from exc
    try:
        run(['/usr/bin/open', '-b', BUNDLE_ID], check=True,
            capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SwitchError('Claude switched to %s. Open Claude to continue.'
                          % DESTINATIONS[mode]) from exc
    return mode


def install_launcher(home, python, *, applications=None, run=subprocess.run):
    """Install an update-safe app in the user's Applications folder on macOS."""
    if sys.platform != 'darwin':
        return None
    home = Path(home)
    try:
        _load('claude_switch_launch').helper_path(home)
    except SystemExit as exc:
        raise SwitchError('Update SCG Router before installing Switch Claude.') from exc
    applications = Path(applications) if applications else Path.home() / 'Applications'
    target = applications / 'Switch Claude.app'
    info = target / 'Contents' / 'Info.plist'
    if target.exists():
        try:
            owned = plistlib.loads(info.read_bytes()).get('CFBundleIdentifier') == LAUNCHER_ID
        except (OSError, ValueError):
            owned = False
        if not owned:
            raise SwitchError('Switch Claude already exists. Contact your administrator.')
    applications.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=applications) as tmp:
        staged = Path(tmp) / 'Switch Claude.app'
        contents = staged / 'Contents'
        resources = contents / 'Resources'
        executable = contents / 'MacOS' / 'Switch Claude'
        resources.mkdir(parents=True)
        executable.parent.mkdir()
        iconset = Path(tmp) / 'router.iconset'
        iconset.mkdir()
        for size, name in ((512, 'icon_512x512.png'), (1024, 'icon_512x512@2x.png')):
            run(['/usr/bin/sips', '-z', str(size), str(size), str(ICON), '--out',
                 str(iconset / name)], check=True, capture_output=True, timeout=15)
        run(['/usr/bin/iconutil', '-c', 'icns', str(iconset), '-o',
             str(resources / 'router.icns')], check=True, capture_output=True, timeout=15)
        launch = home / 'claude_switch_launch.py'
        executable.write_text('#!/bin/sh\nexec %s %s\n'
                              % (shlex.quote(str(python)), shlex.quote(str(launch))))
        executable.chmod(0o755)
        (contents / 'Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': LAUNCHER_ID, 'CFBundleName': 'Switch Claude',
            'CFBundleExecutable': executable.name, 'CFBundlePackageType': 'APPL',
            'CFBundleIconFile': 'router.icns', 'LSUIElement': True,
        }))
        _desktop.atomic_write.replace_text(
            launch, Path(__file__).with_name('claude_switch_launch.py').read_text())
        if target.exists():
            # Only this product's bundle passes the ownership check above.
            shutil.copytree(staged, target, dirs_exist_ok=True)
        else:
            staged.rename(target)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', default=os.environ.get(
        'ROUTER_HOME', str(Path.home() / '.codex' / 'mixed-model-router')))
    args = parser.parse_args(argv)
    try:
        switch(Path(args.home).expanduser())
        return 0
    except SwitchError as exc:
        print(str(exc), file=sys.stderr)
        if sys.platform == 'darwin':
            try:
                _script(dialog_script(str(exc)), subprocess.run, 120)
            except (OSError, subprocess.SubprocessError):
                pass
        return 1


if __name__ == '__main__':
    sys.exit(main())
