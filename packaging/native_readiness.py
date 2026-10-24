"""Content-free setup checks; a healthy router alone is not a working assistant."""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_payload import load


def successful_reply(home, since, client):
    """Observe a successful reply after setup; never return request content."""
    protocol = 'responses' if client == 'codex' else 'messages'
    try:
        path = Path(home) / 'logs' / 'router.jsonl'
        with path.open('rb') as stream:
            stream.seek(max(0, path.stat().st_size - 5 * 1024 * 1024))
            lines = stream.read().splitlines()
    except OSError:
        return False
    for line in reversed(lines):
        try:
            row = json.loads(line)
            if (row.get('event') == 'request_completed' and
                    row.get('protocol') == protocol and
                    isinstance(row.get('status'), int) and 200 <= row['status'] < 300 and
                    datetime.fromisoformat(row['ts']).timestamp() >= since):
                return True
        except (ValueError, KeyError, TypeError, UnicodeError):
            continue
    return False


def plugins_available(client, names, run=subprocess.run, which=shutil.which):
    skills = load('agent_skills')
    path = skills.client_path()
    executable = which(client, path=path)
    if not executable:
        return False
    args = ['plugin', 'list']
    if client == 'codex':
        args += ['--marketplace', skills.MARKETPLACE]
    try:
        result = run([executable, *args, '--json'], capture_output=True,
                     text=True, timeout=30, env=dict(os.environ, PATH=path))
        data = json.loads(result.stdout)
        entries = data['installed'] if client == 'codex' else data
        identifiers = {entry.get('pluginId', entry.get('id')) for entry in entries}
        return result.returncode == 0 and all(
            name + '@' + skills.MARKETPLACE in identifiers for name in names)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return False


def check(home, source, status, progress, run=subprocess.run):
    skills = load('agent_skills')
    names = sorted(skills.plugin_sources(Path(source) / 'plugins'))
    clients = list(status.get('clients', {}))
    checks = {}
    for client in clients:
        cli = 'claude' if client == 'claude-desktop' else client
        if cli not in ('codex', 'claude'):
            continue
        checks[client] = {
            'reply_seen': successful_reply(home, progress.get('started', float('inf')), cli),
            'plugins_available': bool(names) and plugins_available(cli, names, run=run),
            'fresh_session_confirmed': client in progress.get('confirmed_clients', []),
        }
    ready = bool(checks) and status.get('serving') is True and all(
        all(facts.values()) for facts in checks.values())
    return {'ready': ready, 'clients': checks}
