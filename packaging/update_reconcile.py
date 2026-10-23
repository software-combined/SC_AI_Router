"""Best-effort maintenance after an applying update releases nested install locks."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_payload import load


def log(home, task, event, **facts):
    """Callers supply closed-set outcomes, exception types and numeric exit codes."""
    try:
        directory = Path(home) / 'logs'
        directory.mkdir(exist_ok=True)
        with (directory / 'maintenance.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),
                                         task=task, event=event, **facts)) + '\n')
    except OSError:
        pass


def run(home, service):
    outcomes = {'attachment': 'deferred'}
    try:
        recovery, runtime = load('codex_recovery'), load('runtime_rebind')
        outcomes['attachment'] = _attachment(recovery, home, service, apply=False)
        outcomes['runtime'] = runtime.reconcile(home, apply=False)
        state = service._state.read(service._state.path(home))
        components = state.get('component_repairs', {}) if isinstance(state, dict) else {}
        components = components if isinstance(components, dict) else {}
        runtime_pending = outcomes['runtime'] in ('ready', 'failed') and components.get('scheduler') != outcomes['runtime']
        attention = _attention(home, service, outcomes['attachment'], apply=False)
        if 'repairable' in outcomes.values() or runtime_pending or attention:
            with service.install_lock(home) as held:
                if held:
                    outcomes['attachment'] = _attachment(recovery, home, service, apply=True)
                    _attention(home, service, outcomes['attachment'])
                    if outcomes['runtime'] == 'repairable' or runtime_pending:
                        outcomes['runtime'] = runtime.reconcile(home)
                else:
                    outcomes['attachment'] = 'deferred'
                    if outcomes['runtime'] == 'repairable':
                        outcomes['runtime'] = 'deferred'
        if outcomes['attachment'] in ('repaired', 'unchanged'):
            recovery.offer(home, service)
        log(home, 'reconcile', 'completed', **outcomes)
    except (Exception, SystemExit) as exc:
        outcomes['attachment'] = 'failed'
        log(home, 'reconcile', 'failed', error=type(exc).__name__)
    return outcomes


def _attachment(recovery, home, service, *, apply):
    try:
        return recovery.reconcile(home, service, apply=apply)
    except (SystemExit, ValueError, KeyError, TypeError):
        return 'conflict'
    except OSError as exc:
        return 'conflict' if type(exc).__name__ == 'ConcurrentChange' else 'failed'


def _attention(home, service, outcome, *, apply=True):
    if outcome not in ('repaired', 'unchanged', 'conflict', 'unhealthy', 'failed'):
        return
    state = service._state.read(service._state.path(home))
    if not isinstance(state, dict):
        return
    active = state.get('clients', 'codex' if state.get('client', 'codex') != 'none' else 'none')
    if active not in ('codex', 'both'):
        return
    components = state.get('component_repairs')
    if not isinstance(components, dict):
        components = state['component_repairs'] = {}
    verified = outcome in ('repaired', 'unchanged')
    status = load('install_delivery').assistant_status(home, state) if verified else 'failed'
    if components.get('assistants') != status:
        if apply:
            components['assistants'] = status
            service._write_state(home, state)
        return True
