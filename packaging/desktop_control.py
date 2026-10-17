"""Redacted desktop status and allowlisted actions; configuration stays with its owners."""
import argparse
import contextlib
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_payload import load

DESTINATIONS = {
    'codex': [('subscription', 'ChatGPT + OpenRouter'), ('openrouter', 'OpenRouter only')],
    'claude': [('subscription', 'Claude subscription'), ('openrouter', 'OpenRouter')]}
MAINTENANCE = ('setup.status', 'setup.resume', 'setup.add', 'setup.key', 'setup.remove',
               'router.restart', 'updates.check', 'updates.install',
               'help.guide', 'help.support', 'startup.toggle')
ACTIONS = MAINTENANCE + tuple(client + '.' + action for client in DESTINATIONS
                             for action in ('subscription', 'openrouter', 'open'))


def version(value):
    return value if isinstance(value, str) and re.fullmatch(r'\d+(?:\.\d+){2,3}', value) else 'Unknown'


def snapshot(home):
    """No dialogs, model requests, credential values or private paths."""
    home = Path(home)
    installer = load('install')
    installer._sync_seams()
    raw = installer._diag._status_document(home)
    clients = []
    for client, receipt_name in (('codex', 'codex'), ('claude', 'claude-desktop')):
        if receipt_name not in raw.get('clients', {}):
            continue
        selected, subscription = None, True
        try:
            if client == 'codex':
                owner = load('codex_switch_config')
                entry = owner._codex.codex_attachment(home)
                owner.managed_block(entry)
                subscription = entry.get('openai_mode') != 'none'
                selected = ('openrouter' if owner.current(home) == owner.SWITCHED
                            or not subscription else 'subscription')
            else:
                _, doc = load('claude_desktop_switch').attached_profile(home)
                selected = 'subscription' if doc['deploymentMode'] == '1p' else 'openrouter'
        except (Exception, SystemExit):
            selected = None
        clients.append(dict(id=client, label='Codex' if client == 'codex' else 'Claude',
                            selected=selected, choices=[dict(id=key, label=label,
                            enabled=key != 'subscription' or subscription)
                            for key, label in DESTINATIONS[client]]))
    status = ('Running' if raw.get('serving') is True else
              'Router is not running' if raw.get('serving') is False else 'Status unknown')
    return dict(schema=1, status=status, version=version(raw.get('version')),
                clients=clients, autostart=load('desktop_startup').enabled(home))


def _installer(home, flags, run):
    controller = load('native_controller').installer(home)
    command = controller or Path(__file__).with_name('install.py')
    return run([sys.executable, str(command), '--home', str(home)] + list(flags),
               capture_output=True, text=True, timeout=900,
               **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))


def execute(home, resources, action, run=subprocess.run):
    """Fixed action names are the only mutation interface exposed to the shell."""
    if action not in ACTIONS:
        raise ValueError('Unknown desktop action')
    home, resources = Path(home), Path(resources)
    dialog = load('native_dialog')
    if action.startswith('setup.'):
        rc = load('native_setup').onboard(resources, home, action.split('.')[1])
        return dict(outcome='done' if rc == 0 else 'failed')
    if action.startswith(('codex.', 'claude.')):
        client, target = action.split('.')
        if client == 'codex':
            owner = load('codex_desktop_switch')
            if target == 'open':
                owner._platform.open_app(sys.platform, app=owner.CODEX)
                result = True
            else:
                result = owner.switch(home, target=('switched' if target == 'openrouter'
                                                     else 'switched_back'))
        else:
            owner = load('claude_desktop_switch')
            result = owner.switch(home, action='start' if target == 'open' else 'switch',
                                  target=None if target == 'open' else
                                  ('3p' if target == 'openrouter' else '1p'))
        return dict(outcome='cancelled' if result is None else 'done')
    if action == 'startup.toggle':
        startup = load('desktop_startup')
        with load('service').install_lock(home) as held:
            if not held:
                raise RuntimeError('Another router operation is in progress')
            startup.configure(home, resources, not startup.enabled(home))
        return dict(outcome='done')
    if action == 'help.guide':
        guide = resources / 'router/docs/troubleshooting.md'
        if sys.platform == 'darwin':
            command = ['open', str(guide)]
        elif sys.platform == 'win32':
            os.startfile(str(guide))
            return dict(outcome='done')
        else:
            command = ['xdg-open', str(guide)]
        run(command, check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return dict(outcome='done')
    if action in ('router.restart', 'updates.install') and not dialog.confirm(
            'Restart SCG Router? Running replies will finish first.' if action == 'router.restart'
            else 'Install the available SCG Router update? Your assistants may pause briefly.'):
        return dict(outcome='cancelled')
    flags = {'router.restart': ['--restart'], 'updates.install': ['--update'],
             'updates.check': ['--check-update', '--json'], 'help.support': ['--support']}[action]
    result = _installer(home, flags, run)
    if result.returncode:
        raise RuntimeError('Router action failed')
    if action == 'updates.check':
        available = json.loads(result.stdout).get('available')
        available = available if version(available) != 'Unknown' else None
        dialog.message('Version %s is available. Choose Install update in the menu.' % available
                       if available else 'SCG Router is up to date.')
        return dict(outcome='done', available=available)
    if action == 'help.support':
        dialog.message('A redacted support bundle was saved in your SCG Router folder.')
    return dict(outcome='done')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--resources', type=Path, required=True)
    parser.add_argument('--action', choices=ACTIONS)
    args = parser.parse_args(argv)
    try:
        # Owners can print diagnostics. Only the allowlisted response reaches the shell.
        with contextlib.redirect_stdout(io.StringIO()):
            result = execute(args.home, args.resources, args.action) if args.action else snapshot(args.home)
        print(json.dumps(result))
        return 0
    except (Exception, SystemExit) as exc:
        if args.action:
            safe = str(exc) if type(exc).__name__ == 'SwitchError' else (
                'SCG Router could not finish. Choose Set up or repair, then try again.')
            try:
                load('native_dialog').message(safe)
            except Exception:
                pass
        print(json.dumps(dict(outcome='failed', status='Needs attention')))
        return 1


if __name__ == '__main__':
    sys.exit(main())
