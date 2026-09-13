#!/usr/bin/env python3
"""Refresh the SCG marketplace once and reinstall every installed, enabled plugin."""
import argparse
import configparser
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys

MARKETPLACE = 'scg-agent-plugins'
LABEL = 'com.softwarecombined.agent-plugins.update'
SOURCES = {
    'https://github.com/software-combined/SC_OpenRouter_adapter',
    'https://github.com/software-combined/SC_OpenRouter_adapter.git',
    'git@github.com:software-combined/SC_OpenRouter_adapter.git',
}
# Known previous runners, retired only after content is hash-verified:
# (label, home-relative path, accepted SHA-256s, path reused by shared runner).
# Includes the reviewed PR #3 runner at 4978604, alongside released versions.
LEGACY = (
    ('com.softwarecombined.agent-plugins.update',
     '.local/share/scg-agent-plugins/updater.py',
     ('704f610e262921e29040bf8848a20bc33968a59fd649b06aabd638e1f4bd4b56',
      '67819b4e806f76024a388cb2f697aeb4ba300c727f82b60eb10b7de7cea2f6ee',
      '8c06a8a7305e9b2d3344b66830834f07653acb9641c5035b769110e8ff353232',
      '4ded20ea2db5a42c4641ccdbb2845e3f21513644a2d01d5acfa787e77ed9f83a'), True),
    ('com.softwarecombined.subagents.update',
     '.local/share/scg-subagents/updater.py',
     ('3d4ebaba23349511892c2ae9c8b71c273e5910e91fe486dc89e470a6f343abfe',
      'd1f59bb0b669cb854b1921d4832b57dfb15be1c8c3e753c321a08472c3b50b2d'), False),
)


def cli(codex, *args):
    result = subprocess.run([codex, *args, '--json'], capture_output=True, text=True,
                            timeout=120, check=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                            env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    return json.loads(result.stdout)


def installed(codex):
    entries = cli(codex, 'plugin', 'list', '--marketplace', MARKETPLACE)['installed']
    return [p for p in entries if p.get('enabled')]


def verify_source(codex):
    entries = cli(codex, 'plugin', 'marketplace', 'list')['marketplaces']
    entry = next((m for m in entries if m['name'] == MARKETPLACE), {})
    source = entry.get('marketplaceSource', {})
    if source.get('sourceType') != 'git' or source.get('source') not in SOURCES:
        raise ValueError('SCG marketplace must use the approved software-combined/SC_OpenRouter_adapter Git source.')


def update(codex):
    plugins = installed(codex)
    if not plugins:
        return 'Skipped: no SCG plugins are installed and enabled.'
    verify_source(codex)
    cli(codex, 'plugin', 'marketplace', 'upgrade', MARKETPLACE)
    # A user can remove or disable plugins while the fetch runs.
    plugins = installed(codex)
    if not plugins:
        return 'Skipped: SCG plugins were disabled or uninstalled during refresh.'
    updated = []
    available = {p['pluginId']: p for p in plugins}
    for plugin in plugins:
        plugin_id = plugin['pluginId']
        if plugin_id not in available:
            continue
        result = cli(codex, 'plugin', 'add', plugin_id)
        available = {p['pluginId']: p for p in installed(codex)}
        current = available.get(plugin_id)
        if result.get('pluginId') != plugin_id or not current or current.get('version') != result.get('version'):
            raise ValueError('Plugin version readback did not match the installation result.')
        updated.append(plugin_id + ' ' + current['version'])
    return 'Installed ' + ', '.join(updated) + '; new Codex tasks load the refreshed plugins.'


def scheduler():
    spec = importlib.util.spec_from_file_location('scg_scheduling', Path(__file__).with_name('scheduling.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def backup(path):
    saved = path.with_name(path.name + '.migrated')
    if saved.exists():
        if saved.read_bytes() != path.read_bytes():
            raise ValueError('A different migration backup exists; preserve it and reconcile manually.')
        path.unlink()
    else:
        path.rename(saved)


def retire_legacy(migrate, scheduling, codex):
    """Preflight all old runners before retiring their native schedules."""
    planned = []
    home = Path.home()
    body = Path(__file__).read_bytes()
    for label, relative, digests, reused in LEGACY:
        script = home / relative
        if not script.exists() or script.read_bytes() == body:
            continue
        accepted = (digests,) if isinstance(digests, str) else digests
        if hashlib.sha256(script.read_bytes()).hexdigest() not in accepted:
            raise ValueError('Existing updater files differ; preserve them and arrange an explicit migration.')
        if not migrate:
            raise ValueError('An earlier updater is installed; re-run with --migrate.')
        files = [script]
        if sys.platform == 'darwin':
            files.append(home / 'Library/LaunchAgents' / (label + '.plist'))
            if files[1].exists():
                args = plistlib.loads(files[1].read_bytes()).get('ProgramArguments', [])
                if len(args) != 5 or args[1:3] != [str(script), 'run'] or args[3] != '--codex':
                    raise ValueError('Existing Mac service targets another runner; reconcile it explicitly.')
            job = label
        elif sys.platform == 'linux':
            units = Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config') / 'systemd/user'
            if not units.is_absolute():
                raise ValueError('XDG_CONFIG_HOME must be an absolute path.')
            job = 'scg-agent-plugins-update' if reused else 'scg-subagents-update'
            files.extend(units / (job + suffix) for suffix in ('.service', '.timer'))
            service = files[1]
            # Preserve custom schedules in backup, but do not retire a service
            # that no longer invokes the known updater.
            if service.exists():
                definition = configparser.ConfigParser(interpolation=None, strict=False)
                definition.read_string(service.read_text())
                args = shlex.split(definition.get('Service', 'ExecStart', fallback=''))
                args = [a.replace('%%', '%').replace('$$', '$') for a in args]
                if len(args) != 5 or args[1:3] != [str(script), 'run'] or args[3] != '--codex':
                    raise ValueError('Existing Linux service targets another runner; reconcile it explicitly.')
        elif sys.platform == 'win32':
            account, user = scheduling.windows_identity()
            job = ('SCGReviewUpdate-' if reused else 'SCGSubagentsUpdate-') + user
            existing = scheduling.run(['schtasks', '/query', '/tn', job, '/xml'])
            if existing.returncode == 0:
                expected = scheduling.windows_xml(Path(sys.executable).with_name('pythonw.exe'),
                                                  script, codex, user)
                if scheduling.task_contract(existing.stdout, (account, user)) != scheduling.task_contract(expected):
                    raise ValueError('Existing Windows task differs; reconcile it explicitly.')
                exported = script.with_name('update.task.xml')
                if not exported.exists() or scheduling.task_contract(exported.read_bytes()) != scheduling.task_contract(expected):
                    raise ValueError('Windows migration requires the matching saved task XML.')
                files.append(exported)
        else:
            raise ValueError('Scheduling supports macOS, Linux and Windows.')
        for path in files:
            saved = path.with_name(path.name + '.migrated')
            if path.exists() and saved.exists() and saved.read_bytes() != path.read_bytes():
                raise ValueError('A different migration backup exists; preserve it and reconcile manually.')
        planned.append((job, files))

    retired = []
    for job, files in planned:
        if sys.platform == 'darwin':
            service = f'gui/{os.getuid()}/{job}'
            scheduling.run(['launchctl', 'bootout', service])
            if scheduling.run(['launchctl', 'print', service]).returncode == 0:
                raise ValueError('Could not stop the earlier updater service.')
        elif sys.platform == 'linux':
            scheduling.run(['systemctl', '--user', 'disable', '--now', job + '.timer'])
            scheduling.run(['systemctl', '--user', 'stop', job + '.service'])
            for suffix in ('.timer', '.service'):
                if scheduling.run(['systemctl', '--user', 'is-active', job + suffix]).returncode == 0:
                    raise ValueError('Could not stop the earlier updater service.')
        else:
            existing = scheduling.run(['schtasks', '/query', '/tn', job, '/xml'])
            if existing.returncode == 0:
                scheduling.run(['schtasks', '/end', '/tn', job], check=True)
                scheduling.run(['schtasks', '/delete', '/tn', job, '/f'], check=True)
        # Keep the known runner until its definitions have moved, so a retry
        # can still identify and finish a partially completed migration.
        for path in reversed(files):
            if path.exists():
                backup(path)
        retired.append(job)
    return retired


def install(codex, migrate=False):
    if not installed(codex):
        raise ValueError('Install and enable an SCG plugin from its Git marketplace first.')
    verify_source(codex)
    scheduling = scheduler()
    if sys.platform == 'linux':
        scheduling.run(['systemctl', '--user', 'show-environment'], check=True)
    if sys.platform == 'win32' and not Path(sys.executable).with_name('pythonw.exe').is_file():
        raise ValueError('Windows scheduling requires pythonw.exe beside its interpreter.')
    retired = retire_legacy(migrate, scheduling, codex)
    message = scheduling.install(codex, Path(__file__), 'scg-review', LABEL)
    return message + retirement(retired)


def retirement(retired):
    if not retired:
        return ''
    return ' Retired earlier schedulers: ' + ', '.join(retired) + '; their files are kept as *.migrated.'


def main():
    if sys.stdout is None:
        sys.stdout = open(Path(__file__).with_name('update.log'), 'a', encoding='utf-8', buffering=1)
        sys.stderr = sys.stdout
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('run', 'install'))
    parser.add_argument('--migrate', action='store_true',
                        help='retire per-plugin schedulers installed by earlier releases')
    parser.add_argument('--codex', default=shutil.which('codex'))
    args = parser.parse_args()
    if args.migrate and args.command != 'install':
        parser.error('--migrate is only valid with install')
    try:
        if not args.codex or not Path(args.codex).is_absolute():
            raise ValueError('An absolute Codex CLI path is required.')
        message = install(args.codex, args.migrate) if args.command == 'install' else update(args.codex)
    except (OSError, ValueError, KeyError, TypeError, configparser.Error, subprocess.SubprocessError) as exc:
        # Do not copy CLI output or credential-helper diagnostics into scheduled logs.
        print(f'SCG update failed ({type(exc).__name__}); run the documented CLI steps to diagnose.', file=sys.stderr)
        return 1
    print(datetime.now(timezone.utc).isoformat(), message, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
