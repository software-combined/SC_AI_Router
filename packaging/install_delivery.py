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


close_assistants = _load('repair_ui').close_assistants


def normalize_pointer(home):
    """Migrate only after the main job has loaded and verified its stable launcher."""
    if (home / 'current').is_symlink():
        service = _load('service')
        active = service.current_release_dir(home)
        if active is None or active.resolve() != (home / 'releases' / active.name).resolve():
            raise ValueError('unsupported legacy release pointer')
        service.swap_current(home, active)


def result(home, delivery, successful, cancelled=False):
    """Clear each warning only after this operation verifies its own component."""
    service, status = _load('service'), _load('update_status')
    state = service._state.read(service._state.path(home))
    if not isinstance(state, dict):
        return
    components = state.get('component_repairs')
    if not isinstance(components, dict):
        components = state['component_repairs'] = {}
    components['assistants'] = assistant_status(home, state, delivery.get('python'))
    if delivery.get('maintenance_done'):
        status.verified(state, delivery['latest'], delivery['feed'], status.channel(home), None)
    current = service.current_version(home)
    repaired = successful and components.get('assistants') == 'ready' and 'failed' not in components.values()
    status.record(state, error=None if cancelled else '' if successful else 'installer_failed',
                  applied=current if successful else None, repaired=repaired)
    service._write_state(home, state)


def assistant_status(home, state, python=None):
    report = _load('service').load('router_delivery_classification',
        Path(__file__).resolve().parents[1] / 'tools/classify_attachments.py').classify(home, python=python)
    entries = report.get('clients', {})
    if report.get('receipt') == 'readable' and entries:
        owned = all(row.get('classification') == 'owned' for row in entries.values())
        return 'ready' if owned else 'failed'
    elif report.get('receipt') == 'missing' and state.get('clients') == 'none':
        return 'ready'
    return 'failed' if report.get('receipt') == 'conflict' else 'unknown'


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


def maintain(home, source, state, python=None, backend=None):
    """Maintenance does not read or change any assistant attachment."""
    if not (source / 'packaging/native_controller.py').is_file():
        return None  # Older bundles and the small installer fixtures have no controller.
    components = state.get('component_repairs')
    if not isinstance(components, dict):
        components = state['component_repairs'] = {}
    service = _load('service')
    step = 'controller'
    selected = None
    try:
        selected = _load('native_controller').install(home, source).parent.parent
        components[step] = 'ready'
        step = 'updater_launcher'
        service.install_launcher(home, selected)
        if (selected / 'packaging/task_launch.py').is_file():
            service.install_task_launcher(home, selected)
        components[step] = 'ready'
        step = 'controls_launchers'
        copied = 0
        for name in ('native_launch.py', 'desktop_launch.py'):
            if (selected / 'packaging' / name).is_file():
                service._install_home_file(home, selected, name)
                copied += 1
        components[step] = 'ready' if copied == 2 else 'unknown'
        repair = getattr(backend, 'repair_updates', None)
        if repair is not None and (home / 'current').exists():
            step = 'scheduler'
            repair(python, home)
            components[step] = 'ready'
    except (OSError, ValueError, KeyError, TypeError, SystemExit, subprocess.SubprocessError):
        components[step] = 'failed'
        print('Automatic updates need repair; run the current public setup again.')
    try:
        service._write_state(home, state)
    except OSError:
        print('The maintenance result could not be saved; run setup again.')
    return selected


def prepare(home, tarball, latest, manifest, state, python, backend):
    """Verify independent maintenance before client discovery can refuse an update."""
    if 'packaging/native_controller.py' not in manifest.get('files', {}):
        return None
    with tempfile.TemporaryDirectory(prefix='scg-maintenance-') as temporary:
        source = Path(temporary)
        _load('service').safe_extract(tarball, source)
        _load('bundle').check_identity(latest['version'], manifest, source)
        return maintain(home, source, state, python, backend)


def finish(home, run=subprocess.run, native=None, fetch=None, *,
           maintenance_done=False, controller_source=None, python=None, backend=None):
    """Delivery failures stay separate from router health and are retryable."""
    home = Path(home)
    try:
        version = (home / 'current').read_text().strip()
        if Path(version).name != version:
            raise ValueError('invalid release pointer')
        source = home / 'releases' / version
        state = json.loads((home / 'mixed-router-state.json').read_text())
        if not maintenance_done:
            controller_source = maintain(home, source, state, python, backend)
        source = controller_source or source
        attached = clients(home, state)
        skills = _load('agent_skills')
        print('agent skills: ' + skills.sync(state, source / 'plugins',
                                             clients=attached, run=run))
        _management(source, skills, state, attached, run)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print('SCG setup tools need repair; open SCG Router to retry.')
    if native:
        _load('native_resources').deliver(home, native['latest'], native['feed'], fetch)


def run_install(args, install, *, run, fetch):
    """A refused attachment cannot suppress independent maintenance delivery."""
    delivery, rc = {}, None
    try:
        rc = install(delivery)
        return rc
    finally:
        if not args.dry_run:
            _record_install(Path(args.home).expanduser(), delivery, rc)
        if not args.dry_run and (rc == 0 or delivery.get('maintenance_done')):
            try:
                finish(Path(args.home).expanduser(), run=run, native=delivery or None,
                    fetch=fetch, maintenance_done=delivery.get('maintenance_done', False),
                    controller_source=delivery.get('controller_source'),
                    python=delivery.get('python'), backend=delivery.get('backend'))
            except (Exception, SystemExit):
                print('SCG setup tools need repair; open SCG Router to retry.')
            if delivery.get('maintenance_done'):
                try:
                    result(Path(args.home).expanduser(), delivery, rc == 0,
                           getattr(args, 'repair_cancelled', False))
                except (Exception, SystemExit):
                    print('The repair result could not be verified; run setup again.')


def _record_install(home, delivery, rc):
    """Only the health-verified core completion may claim installation success."""
    version = _load('update_status').version(delivery.get('installed_version'))
    if not version or _load('service').current_version(home) != version:
        return
    evidence = _load('update_reconcile')
    try:
        (home / 'logs').mkdir(exist_ok=True)
        with (home / 'logs/update.log').open('a', encoding='utf-8') as stream:
            stream.write('installed %s; health verified\n' % version)
        evidence.log(home, 'install', 'completed', version=version, status=0)
        if rc != 0:
            evidence.log(home, 'install', 'attachment_failed', status=rc if type(rc) is int else 1)
    except OSError:
        evidence.log(home, 'install', 'evidence_failed', status=1)
