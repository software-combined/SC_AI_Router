"""Deliver the SCG agent skills with the router (Plan 179).

The router bundle carries the plugin trees. On every install the router
materialises a local marketplace from its own release and registers that path
with each attached client, so a machine needs no git account, no GitHub access
and no marketplace command typed by a person. A scheduled update spawns this
installer, so the same path refreshes the skills on every router release.

This module owns that work and nothing else. It never imports install.py:
callers pass the release's plugin directory in, which keeps the seam one-way.

Failures here must never fail a router install. Every entry point catches,
records one line, and continues.
"""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import importlib.util as _ilu
_spec = _ilu.spec_from_file_location(
    'router_agent_skills_atomic_write',
    Path(__file__).resolve().parent / 'atomic_write.py')
_atomic_write = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_atomic_write)

MARKETPLACE = 'scg-agent-plugins'
MARKER = '.router-owned'
SHARED = ('.local', 'share', 'scg-agent-plugins')
GIT_UPDATER_LABEL = 'com.softwarecombined.agent-plugins.update'
# Superseded plugin runners the router retires. Content-verified, never name-based.
LEGACY_RUNNERS = (
    'bd06fc556d4640f4dc4206209dd17fc41d4fcfd4904dc63d337ce55b9a88708b',
)
ENTRY_POLICY = {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'}


def shared_base(home=None):
    """The SCG plugin directory the git updater already uses."""
    return (Path(home) if home else Path.home()).joinpath(*SHARED)


def marketplace_root(base=None):
    return Path(base or shared_base()) / 'marketplace'


def _entry(name):
    return {'name': name, 'source': {'source': 'local', 'path': './plugins/' + name},
            'policy': dict(ENTRY_POLICY), 'category': 'Productivity'}


def plugin_names(plugins_dir):
    """Plugins in a release tree: a directory holding a Codex manifest."""
    root = Path(plugins_dir)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir()
                  if (p / '.codex-plugin' / 'plugin.json').is_file())


def _claim(root):
    """Claim the marketplace root before writing any content, atomically.

    Ownership must be established before the first content byte, so an
    interrupted first materialisation still carries the marker and the next
    run repairs it instead of refusing a tree it can no longer prove it
    created. The shared atomic writer leaves no temp behind when the write
    fails; a hard kill between its write and rename is the one residue the
    presence-based guard would still refuse.
    """
    marker = root / MARKER
    if marker.exists():
        return
    _atomic_write.replace_text(
        marker, 'Plan 179: written by the router installer\n')


def write_marketplace(root, plugins_dir):
    """Materialise the local marketplace. Returns the plugin names written.

    The router owns this directory. A non-empty root without our marker was
    written by something else, so it is left exactly as it is and refused.
    An absent or empty root is adopted, and ownership is claimed before any
    content is written so a partial first materialisation stays recoverable.
    """
    root = Path(root)
    names = plugin_names(plugins_dir)
    if not names:
        return []
    if root.exists() and not (root / MARKER).exists() and any(root.iterdir()):
        raise ValueError('marketplace root is not router-owned; left untouched')
    root.mkdir(parents=True, exist_ok=True)
    _claim(root)
    manifest = root / '.agents' / 'plugins' / 'marketplace.json'
    manifest.parent.mkdir(parents=True, exist_ok=True)
    # Stage each plugin, then swap it in. The manifest lands last, so an
    # interrupted copy never leaves a client reading a tree that the manifest
    # already advertises.
    for name in names:
        target = root / 'plugins' / name
        staging = root / 'plugins' / ('.tmp.' + name)
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(Path(plugins_dir) / name, staging)
        if target.exists():
            shutil.rmtree(target)
        os.replace(staging, target)
    manifest.write_text(json.dumps(
        {'name': MARKETPLACE, 'interface': {'displayName': 'Scg Agent Plugins'},
         'plugins': [_entry(n) for n in names]}, indent=2) + '\n')
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


def register(client, root, names, run=subprocess.run, which=shutil.which):
    """Register the local marketplace and install each plugin, tolerantly.

    Both clients are idempotent about an existing marketplace and an installed
    plugin, so a non-zero exit is counted rather than raised: a client that
    refuses one plugin must not cost the others or the router install.
    """
    if which(client) is None:
        return f'{client}: not installed', 1
    refused = 0
    for command in _commands(client, root, names):
        try:
            done = run(command, capture_output=True, text=True, timeout=180)
        except (OSError, subprocess.SubprocessError):
            refused += 1
            continue
        if done.returncode != 0:
            refused += 1
    return (f'{client}: {len(names)} plugin(s)'
            + (f', {refused} refused' if refused else ''), refused)


def retire_git_updater(base=None, run=subprocess.run, which=shutil.which):
    """Retire the git-backed plugin runner the router now replaces.

    Preserve, never delete: the runner moves to the next free `.migrated.<n>`
    and its LaunchAgent is unloaded. An unrecognised runner is left alone,
    because only a content-verified predecessor is ours to retire.
    """
    base = Path(base or shared_base())
    runner = base / 'updater.py'
    if not runner.is_file():
        return ''
    if hashlib.sha256(runner.read_bytes()).hexdigest() not in LEGACY_RUNNERS:
        return 'git updater: unrecognised, left in place'
    if which('launchctl'):
        run(['launchctl', 'bootout',
             f'gui/{os.getuid()}/{GIT_UPDATER_LABEL}'],
            capture_output=True, text=True)
    index = 0
    while (base / f'updater.py.migrated.{index}').exists():
        index += 1
    runner.rename(base / f'updater.py.migrated.{index}')
    plist = Path.home() / 'Library' / 'LaunchAgents' / (GIT_UPDATER_LABEL + '.plist')
    if plist.is_file():
        plist.rename(plist.with_name(plist.name + f'.migrated.{index}'))
    return f'git updater: retired to updater.py.migrated.{index}'


def sync(state, plugins_dir, base=None, run=subprocess.run, which=shutil.which):
    """One install's skills pass. Returns a short line for the install log."""
    clients = attached_clients(state)
    if not clients:
        return 'no attached client'
    try:
        root = marketplace_root(base)
        names = write_marketplace(root, plugins_dir)
        if not names:
            return 'bundle carries none'
        results = [register(c, root, names, run=run, which=which) for c in clients]
        notes = [line for line, _ in results]
        # Retire the git fallback only once the router's own channel works:
        # retiring it behind a failed registration would freeze updates twice.
        if any(refused == 0 for _, refused in results):
            notes.append(retire_git_updater(base=base, run=run, which=which))
        else:
            notes.append('git updater: kept (no client accepted)')
        return '; '.join(n for n in notes if n)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # A skills failure never fails the router install.
        return f'skipped ({type(exc).__name__})'
