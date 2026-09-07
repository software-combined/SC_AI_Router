"""Run the router: python3.14 -m codex_router"""
import json
from .router import STATE, Router

state = json.loads(STATE.read_text())
Router(state).serve_forever()
