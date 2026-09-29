"""Start or switch the attached Claude app without signing either profile out.

Only deploymentMode changes. Claude must finish quitting before the atomic
write, and the attachment is checked again afterwards to preserve app edits.
The installer owns attachment; this helper never creates or removes one.
"""
import argparse
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
_platform = _load('claude_desktop_platform')
_service = _load('service')
TITLE = 'SCG Router'
BUNDLE_ID = 'com.anthropic.claudefordesktop'
LAUNCHER_ID = 'com.softwarecombined.router.claude-switch'
ICON = Path(__file__).parent / 'assets' / 'router-icon.png'
DESTINATIONS = {'1p': 'your Claude subscription', '3p': 'OpenRouter'}
PROFILE_ACTIONS = ('start', 'switch')


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
        state = json.loads((Path(home) / 'mixed-router-state.json').read_text(encoding='utf-8'))
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


dialog_script = _platform.dialog_script


def _sync_context(home, third, profile_env=None):
    sync = _load('claude_profile_sync')
    env = dict(os.environ)
    if profile_env:
        env.update(profile_env)
    env['CLAUDE_USER_DATA_DIR'] = str(third)
    first, bound_third = sync.profile_roots(env, home=home)
    for root in (first, bound_third):
        sync._records.assert_ancestors(root)
    if (bound_third != third or first == third or first in third.parents
            or third in first.parents):
        raise ValueError('unsafe roots')
    return sync, env, (first, third)


def _sync_profiles(home, mode, third, profile_env=None):
    sync, env, _ = _sync_context(home, third, profile_env)
    return sync.sync_profiles(home, mode, env)


def _initialized(sync, roots):
    return all(root.is_dir() and all(
        sync._records.resolve_namespace(root / store, root, third_party=index == 1) is not None
        for store in sync.STORES) for index, root in enumerate(roots))


def _setup_only(context, current_mode):
    """True when sharing is not set up yet, so a switch may change only the mode.

    Refuses instead when switching away from the subscription while tasks are saved.
    """
    initialization_only = not _initialized(context[0], context[2])
    # Only the subscription profile can record the sharing binding, so a gateway
    # user must be able to reach it; a subscription user opens a Code task first.
    if initialization_only and current_mode == '1p' and any(
            context[0]._records.record_paths(root / store, include_irregular=True)
            for root in context[2] for store in context[0].STORES):
        raise SwitchError('Open a Code task in Claude, then try again.')
    return initialization_only


def _notice(message, platform_ops, run):
    print(message)
    try:
        platform_ops.show_message(message, sys.platform, run=run)
    except (OSError, subprocess.SubprocessError):
        pass


def _open(platform_ops, run):
    answer = platform_ops.open_app(sys.platform, run=run)
    if getattr(answer, 'returncode', 0) != 0:
        raise OSError('Claude did not open')


def _reopened(message, platform_ops, run):
    """Reopen Claude, which may have quit, so a refusal never leaves it closed."""
    try:
        _open(platform_ops, run)
    except (OSError, subprocess.SubprocessError):
        if 'Open Claude' not in message:
            message += ' Open Claude to continue.'
    return SwitchError(message)


def switch(home, *, run=subprocess.run, policy_check=None, action='switch',
           sync=None, platform_ops=None, profile_env=None):
    """Open Claude normally, or share saved tasks before switching profiles."""
    if action not in ('start', 'switch'):
        raise SwitchError('Unknown Claude action.')
    if _service.fcntl is None and _service.msvcrt is None:
        raise SwitchError('Claude could not be opened safely. Try again.')
    # The copy lock ends before mode publication. Hold this lock across the
    # whole transition so another launcher cannot copy using a stale mode.
    with _service.install_lock(home, '.claude-profile-switch.lock') as acquired:
        if not acquired:
            raise SwitchError('Claude is already opening or switching. Try again shortly.')
        return _run_action(home, run=run, policy_check=policy_check, action=action,
                           sync=sync, platform_ops=platform_ops, profile_env=profile_env)


def _run_action(home, *, run, policy_check, action, sync, platform_ops, profile_env):
    platform_ops = _platform if platform_ops is None else platform_ops
    config, before = attached_profile(home)
    if policy_check is None:
        policy_check = lambda: platform_ops.policy_disabled(
            sys.platform, run=run, profile=config.parent)
    current_mode = before['deploymentMode']
    if action == 'start':
        try:
            _open(platform_ops, run)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SwitchError('Claude could not open. Open Claude to continue.') from exc
        return current_mode
    mode = '1p' if current_mode == '3p' else '3p'
    try:
        context = _sync_context(home, config.parent, profile_env)
        if policy_check() is not False:
            raise SwitchError('Your organization manages how Claude connects. Contact your administrator.')
        _setup_only(context, current_mode)  # Refuse while Claude is still open.
        prompt = 'Switch Claude to %s? Claude will restart after sharing your saved tasks.'
        if not platform_ops.confirm(prompt % DESTINATIONS[mode], sys.platform, run=run):
            return None
        if platform_ops.request_stop(sys.platform, run=run) is not True:
            # Claude may have partly quit, so reopen it before refusing.
            raise _reopened('Claude did not close in time. Finish your work and try again.',
                            platform_ops, run)
    except (OSError, ValueError, subprocess.SubprocessError, SystemExit) as exc:
        raise SwitchError('Claude settings or status could not be checked. Try again.') from exc
    try:
        initialization_only, unshared = _share_and_select(
            home, config, current_mode, mode, run=run, policy_check=policy_check,
            sync=sync, platform_ops=platform_ops, profile_env=profile_env)
    except Exception as exc:
        # Claude has quit. Reopen it unchanged so a refusal or error never leaves it closed.
        message = (str(exc) if isinstance(exc, SwitchError)
                   else 'Claude tasks were not fully shared. Try again.')
        raise _reopened(message, platform_ops, run) from exc
    try:
        _open(platform_ops, run)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SwitchError('Claude is ready in %s. Open Claude to continue.'
                          % DESTINATIONS[mode]) from exc
    if initialization_only:
        _notice('Claude opened for setup only. No tasks were shared. Finish '
                'signing in and open a Code task before switching again.',
                platform_ops, run)
    elif unshared:
        _notice('%d saved %s could not be shared and stayed where %s.' % (
            unshared, 'task' if unshared == 1 else 'tasks',
            'it was' if unshared == 1 else 'they were'), platform_ops, run)
    return mode


def _share_and_select(home, config, current_mode, mode, *, run, policy_check, sync,
                      platform_ops, profile_env):
    """With Claude closed, share tasks and recheck every guard before saving the mode."""
    third = config.parent
    try:
        if platform_ops.is_running(sys.platform, run=run) is not False:
            raise SwitchError('Claude stayed open. Finish your work and try again.')
        current_config, current = attached_profile(home)
        if (current_config != config
                or current['deploymentMode'] != current_mode):
            raise SwitchError('Claude settings changed. Open Claude and try again.')
        if policy_check() is not False:
            raise SwitchError('Your organization manages how Claude connects. Contact your administrator.')
        context = _sync_context(home, third, profile_env)
    except (OSError, ValueError, subprocess.SubprocessError, SystemExit) as exc:
        raise SwitchError('Claude settings or status could not be checked. Try again.') from exc
    try:
        # Checked again now that Claude has quit; the answer decides what runs.
        initialization_only = _setup_only(context, current_mode)
        report = ({'failed': 0, 'pending': 0} if initialization_only else
                  (sync if sync is not None else _sync_profiles)(
                      home, current_mode, third, profile_env))
        if not isinstance(report, dict) or any(
                type(report.get(key)) is not int or report[key] < 0
                for key in ('failed', 'pending')):
            raise SwitchError('Claude tasks were not fully shared. Try again.')
        if report['failed']:
            raise SwitchError('Claude tasks were not fully shared. Try again.')
        if report['pending']:
            if 'account-binding-changed' in report.get('errors', []):
                raise SwitchError('Claude is signed in to a different account. '
                                  'Return to the account used for task sharing.')
            raise SwitchError('Some Claude tasks are waiting for Claude setup.')
    except SwitchError:
        raise
    except Exception as exc:
        raise SwitchError('Claude tasks were not fully shared. Try again.') from exc
    # Re-read after sync as well: preserve unrelated edits and refuse a new selection.
    latest_config, current = attached_profile(home)
    if latest_config != config or current['deploymentMode'] != current_mode:
        raise SwitchError('Claude settings changed. Open Claude and try again.')
    try:
        if policy_check() is not False:
            raise SwitchError('Your organization manages how Claude connects. Contact your administrator.')
        if platform_ops.is_running(sys.platform, run=run) is not False:
            raise SwitchError('Claude reopened. Finish your work and try again.')
    except (OSError, ValueError, subprocess.SubprocessError, SystemExit) as exc:
        raise SwitchError('Claude settings or status could not be checked. Try again.') from exc
    current['deploymentMode'] = mode
    try:
        _desktop.write_json(config, current)
    except OSError as exc:
        raise SwitchError('Claude settings could not be saved. Try again.') from exc
    unshared = report.get('unshared', 0)
    return initialization_only, unshared if type(unshared) is int and unshared > 0 else 0


def install_launcher(home, python, *, action='switch', applications=None,
                     run=subprocess.run):
    """Install an update-safe owned launcher for start or switch."""
    if action not in ('start', 'switch'):
        raise SwitchError('Unknown Claude action.')
    if sys.platform != 'darwin':
        return _platform.install_launcher(
            home, python, action=action, applications=applications, run=run)
    home = Path(home)
    try:
        _load('claude_profile_launch').helper_path(home)
    except SystemExit as exc:
        raise SwitchError('Update SCG Router before installing Switch Claude.') from exc
    name = 'Open Claude' if action == 'start' else 'Switch Claude'
    launcher_id = LAUNCHER_ID + ('.open' if action == 'start' else '')
    applications = Path(applications) if applications else Path.home() / 'Applications'
    target = applications / (name + '.app')
    info = target / 'Contents' / 'Info.plist'
    if target.exists():
        try:
            owned = (plistlib.loads(info.read_bytes()).get('CFBundleIdentifier')
                     == launcher_id)
        except (OSError, ValueError):
            owned = False
        if not owned:
            raise SwitchError(name + ' already exists. Contact your administrator.')
    applications.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=applications) as tmp:
        staged = Path(tmp) / (name + '.app')
        contents = staged / 'Contents'
        resources = contents / 'Resources'
        executable = contents / 'MacOS' / name
        resources.mkdir(parents=True)
        executable.parent.mkdir()
        iconset = Path(tmp) / 'router.iconset'
        iconset.mkdir()
        for size, icon_name in ((512, 'icon_512x512.png'), (1024, 'icon_512x512@2x.png')):
            run(['/usr/bin/sips', '-z', str(size), str(size), str(ICON), '--out',
                 str(iconset / icon_name)], check=True, capture_output=True, timeout=15)
        run(['/usr/bin/iconutil', '-c', 'icns', str(iconset), '-o',
             str(resources / 'router.icns')], check=True, capture_output=True, timeout=15)
        launch = home / 'claude_profile_launch.py'
        executable.write_text(
            '#!/bin/sh\nexec %s %s --action %s\n'
            % (shlex.quote(str(python)), shlex.quote(str(launch)), action))
        executable.chmod(0o755)
        (contents / 'Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': launcher_id, 'CFBundleName': name,
            'CFBundleExecutable': executable.name, 'CFBundlePackageType': 'APPL',
            'CFBundleIconFile': 'router.icns', 'LSUIElement': True,
        }))
        _desktop.atomic_write.replace_text(
            launch, Path(__file__).with_name('claude_profile_launch.py').read_text(encoding='utf-8'))
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
    parser.add_argument('--action', choices=('start', 'switch'),
                        default='switch')
    args = parser.parse_args(argv)
    try:
        switch(Path(args.home).expanduser(), action=args.action)
        return 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, SwitchError) else 'Claude could not be opened safely. Try again.'
        print(message, file=sys.stderr)
        try:
            _platform.show_message(message, sys.platform)
        except Exception:
            pass
        return 1


if __name__ == '__main__':
    sys.exit(main())
