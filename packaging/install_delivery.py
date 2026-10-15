"""One post-install delivery step, including same-version and desktop attaches."""
import importlib.util
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def _load(name):
    spec = importlib.util.spec_from_file_location(
        'router_delivery_' + name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clients(home, state):
    try:
        attached = _load('codex_config').read_receipt(home).get('clients', {})
    except FileNotFoundError:
        return _load('agent_skills').attached_clients(state)
    if not isinstance(attached, dict):
        raise ValueError('client receipts are unreadable')
    names = [name for name in ('codex', 'claude') if name in attached]
    if 'claude-desktop' in attached and 'claude' not in names:
        names.append('claude')
    return names


def _management(source, skills, state, attached, run):
    if not (source / '.codex-plugin/plugin.json').is_file():
        return
    # The router management plugin intentionally has its own marketplace.
    # It must not join or rename the existing SCG plugins marketplace.
    skills.MARKETPLACE = 'scg-router-management'
    with tempfile.TemporaryDirectory() as temporary:
        plugin = Path(temporary) / 'scg-openrouter'
        plugin.mkdir()
        for name in ('.codex-plugin', '.claude-plugin', 'skills'):
            shutil.copytree(source / name, plugin / name)
        skills.sync(state, plugin.parent, base=skills.shared_base() / 'router-management',
                    clients=attached, run=run)


def finish(home, run=subprocess.run):
    """Delivery failures stay separate from router health and are retryable."""
    home = Path(home)
    try:
        version = (home / 'current').read_text().strip()
        if Path(version).name != version:
            raise ValueError('invalid release pointer')
        source = home / 'releases' / version
        state = json.loads((home / 'mixed-router-state.json').read_text())
        attached = clients(home, state)
        skills = _load('agent_skills')
        print('agent skills: ' + skills.sync(state, source / 'plugins',
                                             clients=attached, run=run))
        _management(source, skills, state, attached, run)
        if (source / 'packaging/native_controller.py').is_file():
            _load('native_controller').install(home, source)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print('SCG setup tools need repair; open SCG Router to retry.')
