"""The bounded four-hour recheck behind the subscription picker gate.

A blocked subscription slug has to be able to come back. Client turns are
the primary evidence (`subscription_watch`), so this worker only covers the
quiet case: it asks the subscription upstream once per blocked slug, at most
every four hours, with the login the client last presented. One attempt, no
retries, a short timeout and a bounded drain; a 200 clears the slug, a
refusal refreshes it, and anything else leaves the block alone.

The login lives in `subscription_gate` memory only. With no login seen (a
fresh process, or an install that never used the subscription) the pass
records itself and sends nothing.
"""
import http.client
import json
import threading
import time

from . import state as state_mod, subscription_gate, subscription_watch
from .events import log_event

PROBE_PERIOD_S = 20 * 60
PROBE_AGE_S = 4 * 60 * 60
PROBE_LIMIT = 5
PROBE_TIMEOUT_S = 20
PROBE_BODY_LIMIT = 64 * 1024
PROBE_OUTPUT_TOKENS = 16


def _prepared_probe(slug, login):
    """The subscription adapter's own target for one probe turn."""
    from .providers import SubscriptionProvider
    payload = {
        'model': slug, 'store': False, 'stream': True,
        'max_output_tokens': PROBE_OUTPUT_TOKENS,
        'input': [{'type': 'message', 'role': 'user',
                   'content': [{'type': 'input_text', 'text': 'ping'}]}]}
    body = json.dumps(payload).encode()
    return SubscriptionProvider().prepare(slug, subscription_gate.CLIENT_PATH,
                                          payload, body, dict(login), None)


def _drain(response):
    """Discard a bounded body so the probe's socket can close."""
    read = getattr(response, 'read', None)
    if read is None:
        return
    total = 0
    while total < PROBE_BODY_LIMIT:
        chunk = read(65536)
        if not chunk:
            return
        total += len(chunk)


def send_probe(prepared, connect=None):
    """(status, headers) for one probe POST; one attempt, short timeout."""
    connect = connect or http.client.HTTPSConnection
    conn = connect(prepared.host, timeout=PROBE_TIMEOUT_S)
    try:
        conn.request('POST', prepared.path, body=prepared.body,
                     headers=prepared.headers)
        response = conn.getresponse()
        status, headers = response.status, subscription_gate.headers_of(response)
        _drain(response)
        return status, headers
    finally:
        conn.close()


def due(gate, now):
    """Blocked slugs whose last probe attempt is at least PROBE_AGE_S old."""
    return [slug for slug, entry in sorted(gate.items())
            if now - entry['probed'] >= PROBE_AGE_S][:PROBE_LIMIT]


def probe(home, slug, now=None, connect=None, send=None):
    """One bounded recheck of a blocked slug; returns its outcome name."""
    stamp = time.time() if now is None else now
    login = subscription_gate.login()
    if not login:
        subscription_gate.record(home, slug, None, stamp, probed=stamp)
        return 'skipped'
    try:
        status, headers = (send or send_probe)(_prepared_probe(slug, login), connect)
    except Exception:  # noqa: BLE001 - a dead probe keeps the block
        subscription_gate.record(home, slug, None, stamp, probed=stamp)
        return 'unknown'
    change = subscription_gate.verdict(status, headers, stamp)
    outcome = ('ok' if change == subscription_gate.CLEAR
               else (change[1] if change else 'unknown'))
    if outcome == 'auth':
        # A login the upstream refuses is dead or belongs to another account:
        # never replay it, and let the next real turn remember a fresh one.
        subscription_gate.forget_login()
    log_event('subscription_probe', model=slug, outcome=outcome)
    if subscription_gate.record(home, slug, change, stamp, probed=stamp):
        subscription_watch.sync_catalogue(home)
    return outcome


def recheck(home, now=None, connect=None, send=None):
    """Probe every due blocked slug; [(slug, outcome)] for the attempts."""
    stamp = time.time() if now is None else now
    live = subscription_gate.blocked(home, stamp)
    # Only a live block with an expiry is worth a request: an expired entry
    # hides nothing, and a hand-pinned one holds until someone clears it.
    gate = {slug: entry for slug, entry in subscription_gate.read(home).items()
            if slug in live and entry['until'] is not None}
    return [(slug, probe(home, slug, stamp, connect, send))
            for slug in due(gate, stamp)]


def enabled(state):
    """True when this install rechecks at all: no subscription, no probe."""
    return (isinstance(state, dict)
            and state.get('openai_mode', 'subscription') != 'none'
            and state.get('subscription_probe') is not False)


def tick(home, now=None, connect=None, send=None):
    """One recheck pass for the install's current state; [] when disabled."""
    if not enabled(state_mod.read(state_mod.path(home))):
        return []
    return recheck(home, now, connect, send)


def start(home):
    """Daemon thread: one recheck pass every PROBE_PERIOD_S."""
    def loop():
        while True:
            time.sleep(PROBE_PERIOD_S)
            try:
                tick(home)
            except Exception as exc:  # noqa: BLE001 - the thread must survive
                log_event('subscription_probe_failed',
                          reason=exc.__class__.__name__)

    thread = threading.Thread(target=loop, daemon=True, name='subscription-probe')
    thread.start()
    return thread
