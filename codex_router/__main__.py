"""Run the router: python3.14 -m codex_router"""
from .router import Router
from .runtime import configure_logging, load_state

configure_logging()
Router(load_state()).serve_forever()
