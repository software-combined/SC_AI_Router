"""The structured event log, as a leaf (Plan 165).

Owns the one logger the router writes to. It imports nothing from
`ai_router` at module level: the only local import is the call-time
`state.default_home` inside `configure_logging`, so any module may log
without pulling the boot composition root (and, through it, the registry
and the credential window) into its import graph.
"""
import json
import logging
import logging.handlers
import os
from datetime import datetime, timezone

# Keep the installed logger identity for existing log readers of either client.
LOG = logging.getLogger('codex_router')


def configure_logging(home=None):
    if home is None:
        # The one permitted function-local edge: resolving the default here
        # keeps `runtime.ROUTER_HOME` out of this module's import time.
        from .state import default_home
        home = default_home()
    (home / 'logs').mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(home / 'logs' / 'router.jsonl',
                                                   maxBytes=5 * 1024 * 1024, backupCount=3)
    handler.setFormatter(logging.Formatter('%(message)s'))
    LOG.addHandler(handler)
    LOG.setLevel(logging.DEBUG if os.environ.get('ROUTER_DEBUG') else logging.INFO)


def log_event(event, **fields):
    LOG.info(json.dumps({'ts': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                         'event': event, **fields}))
