"""Deliver the SCG agent skills with the router (Plan 179).

The router bundle carries the plugin trees. On every install the router
materialises a local marketplace from its own release and registers that path
with each attached client, so a machine needs no git account, no GitHub access
and no marketplace command typed by a person. A scheduled update spawns this
installer, so the same path refreshes the skills on every router release.

Failures here must never fail a router install. Every entry point catches,
records one line, and continues.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

MARKETPLACE = 'scg-agent-plugins'
MARKER = '.router-owned'
SHARED = ('.local', 'share', 'scg-agent-plugins')
GIT_UPDATER_LABEL = 'com.softwarecombined.agent-plugins.update'
# Superseded plugin runners the router retires. Content-verified, never name-based:
# every git updater the plugins released, and one reviewed pre-release, oldest first.
LEGACY_RUNNERS = (
    '495aa84982f85b2f10e67727619b4b9c006124c3e94397a15cc3ca7df8a1cae2',
    '704f610e262921e29040bf8848a20bc33968a59fd649b06aabd638e1f4bd4b56',
    '8c06a8a7305e9b2d3344b66830834f07653acb9641c5035b769110e8ff353232',
    '67819b4e806f76024a388cb2f697aeb4ba300c727f82b60eb10b7de7cea2f6ee',
    '4ded20ea2db5a42c4641ccdbb2845e3f21513644a2d01d5acfa787e77ed9f83a',
    'bd06fc556d4640f4dc4206209dd17fc41d4fcfd4904dc63d337ce55b9a88708b',
    'f8bdfa551bca125ec8c5826a86b017814feefbd45dadb30fa7536d1562392a79',
    'b909d5c4c529310bb33373bdaaf22695ccaa20651ec688a011cedfc358c41fdd',
)
# The systemd user units the runner's scheduling.py installed on Linux.
GIT_UPDATER_UNITS = ('scg-agent-plugins-update', 'scg-subagents-update')
ENTRY_POLICY = {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'}
# The Git homes this marketplace had before the router carried it, matched
# lowercased. Only a Codex registration from one of these is ours to replace.
OLD_CODEX_SOURCE = re.compile(
    r'(https://github\.com/|git@github\.com:)software-combined/'
    r'(sc_ai|sc_ai_router|sc_unlimited_ai|sc_openrouter_adapter|sc_agent_plugins)(\.git)?/?')


def shared_base(home=None):
    """The SCG plugin directory the git updater already uses."""
    return (Path(home) if home else Path.home()).joinpath(*SHARED)


def _windows_codex_dirs(environ=None):
    """Windows desktop's bundled CLI directories, newest build first."""
    local = (os.environ if environ is None else environ).get('LOCALAPPDATA')
    if not local:
        return ()
    base = Path(local) / 'OpenAI' / 'Codex' / 'bin'
    try:
        builds = sorted((p for p in base.iterdir() if p.is_dir()),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return ()
    return tuple(str(p) for p in builds)


def _macos_codex_dirs():
    """Desktop installs can supply Codex without a separate terminal install."""
    dirs = []
    for root in (Path.home() / 'Applications', Path('/Applications')):
        for app in ('ChatGPT.app', 'Codex.app'):
            for relative in ('Contents/Resources/codex-cli/bin', 'Contents/Resources'):
                folder = root / app / relative
                if (folder / 'codex').is_file():
                    dirs.append(str(folder))
    return tuple(dirs)


def client_path(environ=None, os_name=None):
    """Find client CLIs and their helpers in scheduled jobs and desktop setup."""
    # ponytail: fixed common dirs; a client under a version manager (nvm, fnm)
    # still needs its bin dir on the scheduled job's PATH.
    env = os.environ if environ is None else environ
    dirs = [d for d in env.get('PATH', '').split(os.pathsep) if d]
    extra = (str(Path.home() / '.local' / 'bin'),)
    if (os.name if os_name is None else os_name) == 'nt':
        extra += _windows_codex_dirs(env)
    else:
        # Admin-owned on macOS and Linux. On Windows they would be drive-root
        # folders any local account can create, so a planted client could run.
        extra += ('/opt/homebrew/bin', '/usr/local/bin')
        if sys.platform == 'darwin':
            extra += _macos_codex_dirs()
    return os.pathsep.join(dirs + [d for d in extra if d not in dirs])


def marketplace_root(base=None):
    return Path(base or shared_base()) / 'marketplace'


def _entry(name):
    return {'name': name, 'source': {'source': 'local', 'path': './plugins/' + name},
            'policy': dict(ENTRY_POLICY), 'category': 'Productivity'}


def plugin_sources(plugins_dir):
    """Find plugins in flat releases and domain folders; refuse duplicate names."""
    sources = {}
    for manifest in sorted(Path(plugins_dir).glob('**/.codex-plugin/plugin.json')):
        plugin = manifest.parent.parent
        if plugin.name in sources:
            raise ValueError('duplicate plugin name: ' + plugin.name)
        sources[plugin.name] = plugin
    return sources


def write_marketplace(root, plugins_dir):
    """Materialise the local marketplace. Returns the plugin names written.

    The router owns this directory. A non-empty root without our marker was
    written by something else, so it is left exactly as it is and refused.
    """
    root = Path(root)
    sources = plugin_sources(plugins_dir)
    names = sorted(sources)
    if not names:
        return []
    if root.exists() and not (root / MARKER).exists() and any(root.iterdir()):
        raise ValueError('marketplace root is not router-owned; left untouched')
    # Claim the root before any content, so a first copy cut short still
    # carries the marker and the next run repairs it instead of refusing it.
    # Only the marker's presence counts, so a plain write leaves no gap.
    root.mkdir(parents=True, exist_ok=True)
    (root / MARKER).write_text('Plan 179: written by the router installer\n')
    manifest = root / '.agents' / 'plugins' / 'marketplace.json'
    claude = root / '.claude-plugin' / 'marketplace.json'
    manifest.parent.mkdir(parents=True, exist_ok=True)
    claude.parent.mkdir(parents=True, exist_ok=True)
    # Stage each plugin, then swap it in. The manifests land last, so an
    # interrupted copy never leaves a client reading a tree that a manifest
    # already advertises.
    for name in names:
        target = root / 'plugins' / name
        staging = root / 'plugins' / ('.tmp.' + name)
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(sources[name], staging)
        if target.exists():
            shutil.rmtree(target)
        os.replace(staging, target)
    manifest.write_text(json.dumps(
        {'name': MARKETPLACE, 'interface': {'displayName': 'Scg Agent Plugins'},
         'plugins': [_entry(n) for n in names]}, indent=2) + '\n')
    # Claude Code reads only its own manifest, and requires an owner there.
    claude.write_text(json.dumps(
        {'name': MARKETPLACE, 'owner': {'name': 'Software Combined'},
         'plugins': [{'name': n, 'source': './plugins/' + n} for n in names]},
        indent=2) + '\n')
    return names


def attached_clients(state):
    """Clients this host is attached to, from the resolved installer state."""
    clients = state.get('clients', 'codex')
    if clients == 'both':
        return ['codex', 'claude']
    return [] if clients == 'none' else [clients]


def _commands(client, root, names):
    if client == 'codex':
        return ([['codex', 'plugin', 'marketplace', 'add', str(root)]] +
                [['codex', 'plugin', 'add', f'{n}@{MARKETPLACE}'] for n in names])
    if client == 'claude':
        return ([['claude', 'plugin', 'marketplace', 'add', str(root)]] +
                [['claude', 'plugin', 'install', f'{n}@{MARKETPLACE}'] for n in names])
    return []


def _ascii(text):
    """Escape what ASCII cannot hold.

    The installer prints the skills line, and on Windows that stdout can be a
    pipe in the ANSI code page: one character it cannot encode, such as a
    client's glyph or a non-ASCII home path, would fail the install.
    """
    return text.encode('ascii', 'backslashreplace').decode('ascii')


def _one_line(value, limit=200):
    """The first non-blank line of a message or command output, bounded.

    Only the first line: a client's cause chain below it can quote a config
    value, keys included. Control characters never reach the log, and the
    bound applies after ASCII escaping.
    """
    first = next((s for s in str(value or '').splitlines() if s.strip()), '')
    text = ''.join(c if c.isprintable() else ' ' for c in first)
    return _ascii(' '.join(text.split()))[:limit]


def _client_json(call, command):
    """A client's `--json` answer, or None when it cannot give one."""
    try:
        return json.loads(call(command).stdout)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return None


def _old_codex_source(call):
    """True when Codex holds this marketplace name from an old Git home.

    Codex refuses to add the router's copy under a name it already holds from
    another source, and its `plugin add` then keeps installing the stale Git
    snapshot. Removing that registration keeps each plugin's enabled setting
    and cache, so the add that follows re-points the same plugins. Any source
    this cannot positively identify is left alone.
    """
    listing = _client_json(call, ['codex', 'plugin', 'marketplace', 'list', '--json'])
    try:
        for entry in listing['marketplaces']:
            if entry.get('name') == MARKETPLACE:
                source = entry['marketplaceSource']
                return (source['sourceType'] == 'git' and
                        OLD_CODEX_SOURCE.fullmatch(source['source'].lower()) is not None)
    except (LookupError, TypeError, AttributeError):
        pass
    return False


def _switched_off(client, call):
    """Plugin ids a person turned off in this client.

    Both clients' install commands turn a plugin back on, so running them on
    every router update undid that choice. These plugins are skipped instead,
    and refresh on the first update after they are turned back on.
    """
    try:
        if client == 'codex':
            entries = _client_json(call, ['codex', 'plugin', 'list', '--marketplace',
                                          MARKETPLACE, '--json'])['installed']
            key = 'pluginId'
        else:
            entries = _client_json(call, ['claude', 'plugin', 'list', '--json'])
            key = 'id'
        return {entry[key] for entry in entries if entry.get('enabled') is False}
    except (LookupError, TypeError, AttributeError):
        return set()


def register(client, root, names, run=subprocess.run, which=shutil.which):
    """Register the local marketplace and install each plugin, tolerantly.

    Both clients are idempotent about an existing marketplace and an installed
    plugin, so a non-zero exit is counted rather than raised: a client that
    refuses one plugin must not cost the others or the router install. Each
    refusal keeps the command and the client's own error line, so the install
    log names the failure instead of only counting it.
    """
    path = client_path()
    executable = which(client, path=path)
    if executable is None:
        return f'{client}: not installed', 1
    env = dict(os.environ, PATH=path)

    def call(command):
        # The resolved path, not the bare name: on Windows an npm client is
        # `codex.cmd`, which `which` finds but CreateProcess cannot start.
        return run([executable, *command[1:]], capture_output=True, text=True,
                   timeout=180, env=env)

    # Read before any change: removing the old Codex source hides its plugins.
    disabled = _switched_off(client, call)
    off = {n for n in names if f'{n}@{MARKETPLACE}' in disabled}
    commands = _commands(client, root, [n for n in names if n not in off])
    if client == 'codex' and _old_codex_source(call):
        commands.insert(0, ['codex', 'plugin', 'marketplace', 'remove', MARKETPLACE])
    refused = 0
    failures = []
    moved = False
    for command in commands:
        label = _one_line(' '.join(command))
        try:
            done = call(command)
        except (OSError, subprocess.SubprocessError) as exc:
            refused += 1
            failures.append(f'{label}: {type(exc).__name__}: {_one_line(exc)}')
            continue
        if done.returncode != 0:
            refused += 1
            detail = _one_line(done.stderr) or _one_line(done.stdout)
            failures.append(f'{label}: exit {done.returncode}'
                            + (f': {detail}' if detail else ''))
        elif command[2:4] == ['marketplace', 'remove']:
            moved = True
    line = f'{client}: {len(names)} plugin(s)'
    if off:
        line += f', {len(off)} left disabled'
    if moved:
        line += ', old Git source removed'
    if refused:
        line += f', {refused} refused'
        if failures:
            line += ' [' + '; '.join(failures) + ']'
    return line, refused


def retire_git_updater(base=None, run=subprocess.run, which=shutil.which):
    """Retire the git-backed plugin runner the router now replaces.

    Preserve, never delete: the runner moves to the next free `.migrated.<n>`,
    its LaunchAgent is unloaded, and on Linux its systemd timer is disabled,
    its service is stopped and failures cleared, and both units move aside;
    a refused scheduler operation keeps the files for a later retry. Left
    enabled, the timer would fail every day against the moved runner. Routers
    before 1.0.2 moved a Linux runner but left its units enabled, so units beside an already
    moved, content-verified runner are retired too. An unrecognised runner
    is left alone, because only a content-verified predecessor is ours.
    """
    base = Path(base or shared_base())
    runner = base / 'updater.py'
    units = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'systemd' / 'user'
    timers = [name + '.timer' for name in GIT_UPDATER_UNITS
              if (units / (name + '.timer')).is_file()]
    if runner.is_file():
        if _digest(runner) not in LEGACY_RUNNERS:
            return 'git updater: unrecognised, left in place'
        index = 0
        while (base / f'updater.py.migrated.{index}').exists():
            index += 1
        line = f'git updater: retired to updater.py.migrated.{index}'
    else:
        moved = [int(path.name.rsplit('.', 1)[1])
                 for path in base.glob('updater.py.migrated.*')
                 if path.name.rsplit('.', 1)[1].isdigit()
                 and _digest(path) in LEGACY_RUNNERS]
        if not (timers and moved):
            return ''
        index = max(moved)
        line = f'git updater: Linux schedule retired beside updater.py.migrated.{index}'
    systemctl = bool(timers) and which('systemctl')
    if timers and not systemctl:
        return 'git updater: Linux schedule retirement pending (systemctl unavailable)'
    if systemctl:
        services = [name + '.service' for name in GIT_UPDATER_UNITS
                    if (units / (name + '.service')).is_file()]
        commands = [['disable', '--now', *timers]]
        if services:
            # A timer stop leaves its service running or marked failed.
            commands.append(['stop', *services])
        commands.append(['reset-failed', *timers, *services])
        for command in commands:
            if run(['systemctl', '--user', *command], capture_output=True, text=True).returncode:
                if command[0] == 'reset-failed':
                    # Stopped units may already be unloaded, so reset refuses them.
                    state = run(['systemctl', '--user', 'show', '-p', 'ActiveState',
                                 '--value', *timers, *services], capture_output=True, text=True)
                    if state.returncode == 0 and state.stdout.split() == ['inactive'] * (len(timers) + len(services)):
                        continue
                return f'git updater: Linux schedule retirement pending (systemctl {command[0]} failed)'
    if runner.is_file():
        if which('launchctl'):
            run(['launchctl', 'bootout',
                 f'gui/{os.getuid()}/{GIT_UPDATER_LABEL}'],
                capture_output=True, text=True)
        runner.rename(base / f'updater.py.migrated.{index}')
        plist = Path.home() / 'Library' / 'LaunchAgents' / (GIT_UPDATER_LABEL + '.plist')
        if plist.is_file():
            plist.rename(plist.with_name(plist.name + f'.migrated.{index}'))
    existing = [units / (name + kind) for name in GIT_UPDATER_UNITS
                for kind in ('.timer', '.service') if (units / (name + kind)).is_file()]
    slot = index
    while any(unit.with_name(unit.name + f'.migrated.{slot}').exists() for unit in existing):
        slot += 1
    for unit in existing:
        unit.rename(unit.with_name(unit.name + f'.migrated.{slot}'))
    if systemctl:
        run(['systemctl', '--user', 'daemon-reload'], capture_output=True, text=True)
    return line


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sync(state, plugins_dir, base=None, run=subprocess.run, which=shutil.which, clients=None):
    """One install's skills pass. Returns a short line for the install log."""
    clients = attached_clients(state) if clients is None else clients
    if not clients:
        return 'no attached client'
    try:
        root = marketplace_root(base)
        names = write_marketplace(root, plugins_dir)
        if not names:
            return 'bundle carries none'
        results = [register(c, root, names, run=run, which=which) for c in clients]
        notes = [line for line, _ in results]
        # The git updater only ever refreshes Codex, so retire it only once
        # Codex runs from the router's copy: retiring it behind a failed or
        # absent Codex registration would freeze Codex's plugin updates.
        if 'codex' in clients:
            if results[clients.index('codex')][1] == 0:
                notes.append(retire_git_updater(base=base, run=run, which=which))
            else:
                notes.append('git updater: kept (Codex did not accept)')
        summary = '; '.join(n for n in notes if n)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # A skills failure never fails the router install. Keep one line, but
        # carry the cause and the marketplace path so a wedged or partial
        # marketplace is diagnosable from the install log alone.
        detail = _one_line(exc) or type(exc).__name__
        summary = f'skipped ({type(exc).__name__}: {detail}) at {marketplace_root(base)}'
    return _ascii(summary)
