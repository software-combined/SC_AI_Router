"""Run the router: python3.14 -m codex_router"""
from .registry import openrouter_slugs
from .router import Router
from .runtime import VERSION, configure_logging, load_state, log_event


def main():
    configure_logging()
    state = load_state()
    log_event('router_started', version=VERSION, port=state['port'],
              openrouter_models=len(openrouter_slugs()))
    Router(state).serve_forever()


if __name__ == '__main__':
    main()
