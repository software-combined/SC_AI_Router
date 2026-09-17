"""Run the router: python3.14 -m ai_router"""
import signal
import threading
from . import activation, availability, model_refresh, provider_defs, subscription_probe
from .registry import external_slugs
from .router import Router
from .runtime import VERSION, ROUTER_HOME, configure_logging, load_state, log_event


def _region(state):
    region = state.get('openrouter_region', 'global')
    return region if provider_defs.valid_region(region) else 'global'




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
    try:
        key = server.credentials.key_for()
    except (LookupError, PermissionError, ValueError, OSError):
        key = None
    _models_url = _read_models_url(ROUTER_HOME, state)
    try:
        model_refresh.start(_models_url, ROUTER_HOME)
    except Exception:
        pass
    host = provider_defs.region_host(provider_defs.DEFAULT_EXTERNAL, region)
    if key and host:
        availability.restore(ROUTER_HOME, key, region)
        availability.refresh(host, key, ROUTER_HOME, region)
        availability.start(lambda: provider_defs.region_host(
            provider_defs.DEFAULT_EXTERNAL, _region(server.state)),
            lambda: server.credentials.key_for(),
            ROUTER_HOME, lambda: _region(server.state))
    # Subscription picker gate: recheck blocked rows every four hours.
    subscription_probe.start(ROUTER_HOME)
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
