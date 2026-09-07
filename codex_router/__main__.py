"""Run the router: python3.14 -m codex_router"""
import signal
import threading
from . import activation
from .registry import openrouter_slugs
from .router import Router
from .runtime import VERSION, configure_logging, load_state, log_event


def main():
    configure_logging()
    state = load_state()
    log_event('router_started', version=VERSION, port=state['port'],
              openrouter_models=len(openrouter_slugs()))
    server = Router(state, fileno=activation.inherited_listener())
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
