"""Run the router: python3.14 -m ai_router"""
import signal
import threading
from . import activation, availability, model_refresh, provider_defs, registry as _registry
from .registry import external_slugs
from .router import Router
from .runtime import VERSION, ROUTER_HOME, configure_logging, load_state, log_event


def _region(state):
    region = state.get('openrouter_region', 'global')
    return region if provider_defs.valid_region(region) else 'global'


def _bedrock_region(state):
    region = state.get('bedrock_region', 'us-east-1')
    return region if provider_defs.valid_bedrock_region(region) else 'us-east-1'


def _provider_region(state, provider_id):
    defn = provider_defs.get(provider_id)
    if defn is not None and defn.regional:
        return _bedrock_region(state)
    return _region(state)




def _read_models_url(home, state):
    """Feed models URL: persisted file, else channel default (Plan 099 Step 3)."""
    try:
        from pathlib import Path as _Path
        url = (_Path(home) / 'models-url').read_text().strip()
        if url.startswith('https://'):
            return url
    except OSError:
        pass
    channel = 'beta' if (_Path(home) / 'channel').exists() and (_Path(home) / 'channel').read_text().strip() == 'beta' else 'stable'
    return f'https://dist.softwarecombined.com/{channel}/models.json'


def main():
    configure_logging()
    state = load_state()
    region = _region(state)
    log_event('router_started', version=VERSION, port=state['port'],
              external_models=len(external_slugs()), openrouter_region=region)
    server = Router(state, fileno=activation.inherited_listener())
    # Key-filtered availability behind `/models/user`: startup restore,
    # one immediate refresh, then every five minutes. Temporary failures
    # keep the last good snapshot; auth rejection clears it. Subscription
    # rows are unaffected: the snapshot only ever hides external rows.
    _models_url = _read_models_url(ROUTER_HOME, state)
    try:
        model_refresh.start(_models_url, ROUTER_HOME)
    except Exception:
        pass
    # Keep one loop per provider with registry rows, including keyless
    # providers whose first key may be saved while the service runs.
    for defn in provider_defs.external_defs():
        if not any(m.provider == defn.id for m in _registry.MODELS):
            continue
        try:
            key = server.credentials.key_for(defn.id)
        except (LookupError, PermissionError, ValueError, OSError):
            key = None
        host = provider_defs.host_for(defn.id, _provider_region(state, defn.id))
        if key and host:
            availability.restore(ROUTER_HOME, defn.id, key,
                                 _provider_region(state, defn.id))
            availability.refresh(defn.id, host, key, ROUTER_HOME,
                                 _provider_region(state, defn.id))
        availability.start(
            defn.id,
            lambda pid=defn.id: provider_defs.host_for(
                pid, _provider_region(server.state, pid)),
            lambda pid=defn.id: server.credentials.key_for(pid),
            ROUTER_HOME,
            lambda pid=defn.id: _provider_region(server.state, pid))
    signal.signal(signal.SIGTERM, lambda signum, frame: _start_drain_thread(server))
    server.serve_forever()


def _start_drain_thread(server):
    # Non-daemon: main returns after shutdown(), so only a joined thread
    # honors the drain deadline instead of dying with the interpreter.
    thread = threading.Thread(target=server.drain_and_exit, daemon=False)
    thread.start()
    return thread


if __name__ == '__main__':
    main()
