"""Graphical setup and maintenance, running entirely on the bundled Python."""
import argparse
import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_payload import install_arguments, load, metadata, retained

ACTIONS = (('resume', 'Update or repair'), ('status', 'Check setup'),
           ('add', 'Connect another assistant'), ('key', 'Replace model key'),
           ('remove', 'Remove router'))
ASSISTANT_DOWNLOADS = {'codex': 'https://chatgpt.com/download/',
                       'claude': 'https://claude.com/download'}


def read_json(path):
    try:
        doc = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}
    if not isinstance(doc, dict):
        raise ValueError('The saved setup cannot be read. Contact Software Combined IT.')
    return doc


def environment(resources):
    """Find the packaged wrapper; it scopes GTK dependencies to its child."""
    env = dict(os.environ)
    gui = Path(resources) / 'gui'
    if gui.is_dir():
        env['PATH'] = str(gui / 'bin') + os.pathsep + env.get('PATH', '')
    return env


def _succeeded(result):
    output = getattr(result, 'stdout', '') or ''
    if isinstance(output, bytes):
        output = output.decode(errors='replace')
    return result.returncode == 0 and not any(line.startswith('deferred:') for line in output.splitlines())


def run_installer(resources, home, flags=(), run=subprocess.run):
    state = read_json(Path(home) / 'mixed-router-state.json')
    key, repair = '--setup' in flags, '--repair' in flags
    args = install_arguments(resources, home, state, key=key, repair=repair)
    # Flags from the graphical chooser replace, rather than combine with,
    # the previous selection. No unattended fallback can attach Codex.
    if '--clients' in flags:
        if '--choose-clients' in args:
            args.remove('--choose-clients')
        if '--clients' in args:
            index = args.index('--clients')
            del args[index:index + 2]
    args += [flag for flag in flags if flag not in ('--setup', '--repair')]
    if not key and not repair:
        attached = load('codex_config').read_receipt(home).get('clients', {})
        if '--desktop' not in args and 'claude-desktop' in attached:
            args.append('--desktop')
    env = environment(resources)
    env.update(ROUTER_NO_KEY_WINDOW='1', ROUTER_NO_CLIENT_CHOOSER='1')
    return run(args, capture_output=True, text=True, timeout=900, env=env)


def status(resources, home, run=subprocess.run):
    doc = metadata(resources)
    python = Path(resources) / 'runtime' / doc['runtime_exec']
    source = load('native_controller').launcher_source(home, Path(resources) / 'router')
    result = run([str(python), str(source / 'packaging/install.py'),
                  '--status', '--json', '--home', str(home)], capture_output=True,
                 text=True, timeout=30, env=environment(resources))
    if result.returncode:
        raise ValueError('The router status could not be checked.')
    facts = json.loads(result.stdout)
    progress = read_json(Path(home) / 'setup-progress.json')
    facts['onboarding'] = load('native_readiness').check(home, source, facts, progress, run)
    facts['downloads'] = {'access_ready': True, 'public': True}
    return facts


def _select(dialog):
    picked = dialog.dialog.ask()
    if picked is None or picked is dialog.dialog.CANCELLED:
        return None
    clients, desktop = dialog.dialog.plan(*picked)
    flags = ['--clients', clients]
    if desktop:
        flags.append('--desktop')
    return flags


def _missing_assistant(flags, dialog):
    skills = load('agent_skills')
    import shutil
    selected = flags[flags.index('--clients') + 1]
    clients = ['codex', 'claude'] if selected == 'both' else [selected]
    if '--desktop' in flags and 'claude' not in clients:
        clients.append('claude')
    for client in clients:
        if client == 'none' or shutil.which(client, path=skills.client_path()):
            continue
        label = 'Codex' if client == 'codex' else 'Claude Code'
        if client == 'claude' and '--desktop' in flags:
            label = 'Claude Code setup tools from Claude desktop’s Install page'
        if dialog.confirm('Install or open %s and sign in first.\n\n'
                          'Continue opens its download page. Open SCG Router again when it is ready.' % label):
            webbrowser.open(ASSISTANT_DOWNLOADS[client])
        return True
    return False


def _key(resources, home, replace=False, run=subprocess.run):
    state = read_json(Path(home) / 'mixed-router-state.json')
    if not replace:
        diagnostics = load('diagnostics')
        if not diagnostics._provider_defs().unhandled(Path(home), state, diagnostics._key_private):
            return
    if replace:
        result = run_installer(resources, home, ['--setup'])
        if not _succeeded(result):
            raise ValueError('The key window could not be prepared. Try setup again.')
        state = read_json(Path(home) / 'mixed-router-state.json')
    setup = state.get('setup', {})
    if not setup.get('nonce') or setup.get('expires', 0) <= time.time():
        return
    doc = metadata(resources)
    python = Path(resources) / 'runtime' / doc['runtime_exec']
    url = 'http://127.0.0.1:%s/%s/setup/%s' % (state['port'], state['token'], setup['nonce'])
    current = (Path(home) / 'current').read_text().strip()
    release = Path(home) / 'releases' / current
    result = run([str(python), '-m', 'ai_router.key_prompt', '--stdin',
                  '--clients', state.get('clients', 'codex')], input=url + '\n',
                 capture_output=True, text=True, timeout=900, cwd=release,
                 env=dict(environment(resources), ROUTER_HOME=str(home)))
    if result.returncode not in (0, 2):
        raise ValueError('The key window could not finish. Open SCG Router to try again.')


def _claude_on_openrouter(home, dialog):
    """Claude reaches OpenRouter only through Switch Claude, which asks first,
    restarts Claude and shares saved tasks; it does nothing when already there."""
    owner = load('claude_desktop_switch')
    try:
        if owner.switch(home, target='3p') is not None:
            return True
        dialog.message('Claude stays on your Claude subscription. To use OpenRouter models, '
                       'choose Claude, then OpenRouter, in the SCG Router menu.')
    except Exception as exc:
        dialog.message(str(exc) if isinstance(exc, owner.SwitchError)
                       else 'Claude could not be switched safely. Try again.')
    return False


def _check(resources, home, dialog):
    facts = status(resources, home)
    pending = facts['onboarding']['clients']
    if not facts.get('serving'):
        dialog.message('SCG Router needs repair. Open it again and choose Update or repair.')
        return
    update = facts.get('update', {})
    if update.get('required_action'):
        dialog.message('SCG Router is running, but updates need attention.\n\n'
            'Running version: %s\nLatest known for this channel: %s\nLast successful check: %s\n\n'
            'Choose Update or repair to continue.' % (facts.get('running_version') or 'Unknown',
            update.get('latest_known_version') or 'Unknown',
            load('update_status').display_time(update.get('last_successful_check_at'))))
        return
    if 'claude-desktop' in pending and _missing_assistant(
            ['--clients', 'none', '--desktop'], dialog):
        return
    if not pending or any(not row['plugins_available'] for row in pending.values()):
        dialog.message('Your assistant tools still need setup. Open SCG Router and choose Update or repair.')
        return
    progress = read_json(Path(home) / 'setup-progress.json')
    for client, checks in pending.items():
        if checks['fresh_session_confirmed'] and checks['reply_seen']:
            continue
        label = {'codex': 'Codex', 'claude': 'Claude Code',
                 'claude-desktop': 'Claude desktop'}[client]
        if client == 'claude-desktop' and not _claude_on_openrouter(home, dialog):
            return
        if not dialog.confirm(
                'To finish setup for %s:\n\n%s'
                'Choose an OpenRouter model and send a greeting. Use an enabled SC tool, '
                'such as SC documentation.\n\n'
                'Choose Continue only after you receive a reply and the SC tool works.'
                % (label, 'Choose Code and start a new task. ' if client == 'claude-desktop'
                   else 'Quit and reopen it, then start a new chat. ')):
            return
        if not load('native_readiness').successful_reply(home, progress['started'], client):
            dialog.message('A successful reply has not reached SCG Router yet. '
                           'Check your selected model, then open SCG Router and choose Check setup.')
            return
        confirmed = progress.setdefault('confirmed_clients', [])
        if client not in confirmed:
            confirmed.append(client)
        load('atomic_write').replace_json(Path(home) / 'setup-progress.json', progress)
    facts = status(resources, home)
    dialog.message('Ready. Your assistants are connected and updates are automatic.'
                   if facts['onboarding']['ready'] else
                   'Setup is saved. Open SCG Router and choose Check setup to finish.')


def _remove(resources, home, dialog, doc):
    try:  # Before anything closes: removal refuses while Codex is switched.
        load('codex_switch_config').refuse_switched(home)
    except SystemExit as exc:
        dialog.message(str(exc))
        return 0
    if not dialog.confirm('Remove SCG Router and restore your assistant settings? '
                          'Your key and saved settings will stay on this computer.'):
        return 0
    clients = load('codex_config').read_receipt(home).get('clients', {})
    if not load('repair_ui').close_assistants(home, removing=True):
        return 0
    python = resources / 'runtime' / doc['runtime_exec']
    source = load('native_controller').launcher_source(home, resources / 'router')
    with dialog.Progress('Removing SCG Router. If an update is running, removal waits for it '
                         'to finish. A message appears when removal is done.', button='OK'):
        result = subprocess.run([str(python), str(source / 'packaging/install.py'), '--home', str(home),
                                 '--uninstall'], capture_output=True, text=True, timeout=600,
                                env=environment(resources))
    if 'deferred:' in (result.stdout or ''):
        dialog.message('SCG Router is still updating, so nothing was removed. '
                       'Try again in a few minutes.')
        return 1
    if not _succeeded(result):
        dialog.message('SCG Router could not be removed safely. Contact Software Combined IT.')
        return result.returncode or 1
    reopen = [label for name, label in (('codex', 'Codex'), ('claude', 'Claude Code')) if name in clients]
    finish = ' Quit and reopen %s to finish.' % ' and '.join(reopen) if reopen else ''
    dialog.message('SCG Router was removed.%s\n\nYour model key and settings stay in %s, so setting '
                   'up SCG Router again keeps them. Delete that folder to remove them.' % (finish, home))
    return 0


def onboard(resources, home, action=None):
    dialog = load('native_dialog')
    existing = (home / 'current').exists() or (home / 'current').is_symlink()
    action = action or (dialog.choose('What would you like to do?', ACTIONS) if existing else 'resume')
    if action is None:
        return 0
    if action == 'signin':
        dialog.message('SCG Router downloads are public. No download sign-in is needed.')
        return 0
    if action == 'status':
        _check(resources, home, dialog)
        return 0
    if action == 'key':
        _key(resources, home, replace=True)
        return 0
    doc = metadata(resources)
    if action == 'remove':
        return _remove(resources, home, dialog, doc)
    flags = _select(dialog) if not existing or action == 'add' else ['--repair']
    if flags is None or ('--clients' in flags and _missing_assistant(flags, dialog)):
        return 0
    with dialog.Progress() as progress:
        permanent = retained(resources, home)
        python = permanent / 'runtime' / doc['runtime_exec']
        load('native_shortcuts').install(home, permanent, python)
        if not (home / 'channel').exists():
            load('atomic_write').replace_text(
                home / 'channel', ('stable' if existing else doc['channel']) + '\n')
        result = run_installer(permanent, home, flags)
    if not _succeeded(result):
        dialog.message('Setup could not finish. '
                       'Open SCG Router to try again, or contact Software Combined IT.')
        return 1
    try:
        permanent = load('native_resources').current(home)
        doc = metadata(permanent)
    except (OSError, ValueError, KeyError):
        pass
    source = permanent / 'router'
    load('native_controller').install(home, source)
    python = permanent / 'runtime' / doc['runtime_exec']
    load('native_shortcuts').install(home, permanent, python)
    load('native_resources').confirm_controls(home, permanent)
    load('desktop_menu').start(home, permanent)
    atomic = load('atomic_write')
    atomic.replace_json(home / 'setup-progress.json',
                        {'version': doc['version'], 'started': time.time(), 'confirmed_clients': []})
    if progress.cancelled:
        return 0
    _key(permanent, home)
    _check(permanent, home, dialog)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resources', type=Path, required=True)
    parser.add_argument('--home', type=Path, default=Path.home() / '.codex/mixed-model-router')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--action', choices=[key for key, _ in ACTIONS])
    args = parser.parse_args(argv)
    resources = args.resources.resolve()
    try:
        metadata(resources)
        os.environ.update(environment(resources))
        if args.status:
            print(json.dumps(status(resources, args.home)))
            return 0
        return onboard(resources, args.home, args.action)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        if args.status:
            return 1
        load('native_dialog').message('Setup needs attention. Open SCG Router to try again, '
                                      'or contact Software Combined IT.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
