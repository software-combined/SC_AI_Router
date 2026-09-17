"""Turn evidence and the picker rewrite behind the subscription gate.

`subscription_gate` owns the gate document and the verdict rules; this
module acts on them from the request path. `observe` reads the status and
the usage headers of a ChatGPT subscription turn the client already made,
and a change re-merges the picker catalogue at once, so the file is right
before the next client start.

`subscription_probe` is the quiet-case worker beside this one: the four-hour
recheck that asks the subscription upstream about a blocked slug when the
client is idle.
"""
import time

from . import provider_defs, subscription_gate, subscription_roster
from .events import log_event


def sync_catalogue(home):
    """Re-merge the picker catalogue for the gate; never raises."""
    try:
        # Key-filtered availability and the portco allowlist ride along, so
        # this rewrite never widens what the installed key may use.
        from . import availability
        key = availability.current_key(home)
        availability.sync_catalogue(home, availability.effective_ids(home, key))
    except Exception as exc:  # noqa: BLE001 - a gate write never fails a turn
        log_event('subscription_gate_sync_failed', reason=exc.__class__.__name__)


def observe(home, metrics, prepared, response):
    """Record one subscription turn's limit evidence; never raises.

    Only ChatGPT subscription model turns count (`home` is None for the
    credential stubs of the handler tests; a native path is not a turn).
    """
    try:
        model = metrics.get('model')
        if (not home or metrics.get('path') != subscription_gate.CLIENT_PATH
                or prepared.provider != provider_defs.OPENAI.id
                or model not in subscription_roster.SUBSCRIPTION_SLUGS):
            return
        now = time.time()
        change = subscription_gate.verdict(
            response.status, subscription_gate.headers_of(response), now)
        if change is not None and subscription_gate.record(home, model, change, now):
            sync_catalogue(home)
        # The login is only ever needed to recheck a blocked slug: holding it
        # while nothing is blocked serves nothing.
        if not subscription_gate.read(home):
            subscription_gate.forget_login()
    except Exception as exc:  # noqa: BLE001 - evidence never fails a turn
        log_event('subscription_gate_failed', reason=exc.__class__.__name__)
