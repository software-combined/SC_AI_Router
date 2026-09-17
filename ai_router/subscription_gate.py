"""Picker gate for the ChatGPT subscription rows (Plan 178).

The picker catalogue is merged once, at client startup, so a subscription
row that upstream refuses is worse than useless: it stays selectable and
fails the turn. This leaf owns the evidence and the state that merge reads.

- Evidence rides turns the client already makes (see `subscription_watch`):
  no credential is stored and the router sends nothing of its own.
- `x-codex-*` usage headers, when present, are authoritative: a window at
  100% blocks that slug until its reported reset, any lower reading clears.
- A refused turn (429) or an auth refusal (401/403) blocks the slug for
  `REFUSAL_TTL_S`, refreshed by later refusals; a success clears it.
- `subscription_watch` acts on this evidence; the login a later recheck
  borrows is held here, in memory only.

State is one JSON document beside the router state, and a missing or
malformed document means "no gate": the behaviour before this leaf existed.
"""
import json
import threading
import time
from pathlib import Path

from . import provider_defs, subscription_roster
from .atomic_write import replace_json
from .events import log_event
from .transport import HOP_HEADERS

GATE_NAME = 'subscription-gate.json'
# The client path of a model turn; native service paths are not model turns.
CLIENT_PATH = '/responses'
CLEAR = ('clear',)
SOURCES = ('refusal', 'auth', 'headers')
REFUSAL_TTL_S = 60 * 60
EXPIRY_SLACK_S = 300
RESET_CAP_S = 7 * 24 * 60 * 60
# A reported reset longer than this is not a window any plan reports.
SECONDS_CAP = 10 * 365 * 24 * 60 * 60
PERCENT_HEADERS = ('x-codex-primary-used-percent', 'x-codex-secondary-used-percent')
RESET_HEADERS = ('x-codex-primary-resets-in-seconds',
                 'x-codex-secondary-resets-in-seconds')
_LOCK = threading.Lock()
_LOGIN = None


def path(home):
    """The gate document under one router home."""
    return Path(home) / GATE_NAME


def login():
    """Copy of the last subscription request headers, or None."""
    with _LOCK:
        return dict(_LOGIN) if _LOGIN else None


def forget_login():
    """Drop the remembered login; the gate no longer needs it."""
    global _LOGIN
    with _LOCK:
        _LOGIN = None


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _entry(raw):
    """One validated {source, since, until, probed} record, or None."""
    if not isinstance(raw, dict) or raw.get('source') not in SOURCES:
        return None
    since, probed, until = (raw.get('since'), raw.get('probed', 0),
                            raw.get('until'))
    if (not _number(since) or not _number(probed)
            or (until is not None and not _number(until))):
        return None
    return {'source': raw['source'], 'since': float(since),
            'probed': float(probed),
            'until': None if until is None else float(until)}


def read(home):
    """Validated gate document; {} when absent, unreadable or malformed."""
    try:
        doc = json.loads(path(home).read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict):
        return {}
    gate = {}
    for slug, raw in doc.items():
        entry = _entry(raw) if isinstance(slug, str) else None
        if entry is not None:
            gate[slug] = entry
    return gate


def blocked(home, now=None):
    """Subscription slugs the gate hides right now; expired rows drop out.

    A row with no `until` is an operator-pinned block: written by hand, it
    holds until someone clears it. The router itself always writes an expiry.
    """
    stamp = time.time() if now is None else now
    return frozenset(slug for slug, entry in read(home).items()
                     if slug in subscription_roster.SUBSCRIPTION_SLUGS
                     and (entry['until'] is None or entry['until'] > stamp))


def write(home, gate):
    """Persist one gate document; False when the home is unwritable."""
    try:
        replace_json(path(home), gate)
    except OSError as exc:
        log_event('subscription_gate_write_failed', reason=exc.__class__.__name__)
        return False
    return True


def headers_of(response):
    """Lowercased response headers; {} when the response cannot speak."""
    try:
        return {str(key).lower(): value for key, value in response.getheaders()}
    except (AttributeError, TypeError):
        return {}


def _bounded(value, ceiling):
    """Bounded float from one header value, or None."""
    try:
        number = float(str(value).strip().rstrip('%'))
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= ceiling else None


def usage_windows(headers):
    """[(used percent, seconds to reset)] from the usage header allowlist."""
    windows = []
    for percent_name, reset_name in zip(PERCENT_HEADERS, RESET_HEADERS):
        percent = _bounded(headers.get(percent_name), 1000)
        if percent is not None:
            windows.append((percent, _bounded(headers.get(reset_name), SECONDS_CAP)))
    return windows


def verdict(status, headers, now):
    """('block', source, until), ('clear',) or None for one upstream answer."""
    spent = [seconds for percent, seconds in usage_windows(headers)
             if percent >= 100]
    if spent:
        known = [seconds for seconds in spent if seconds is not None]
        # A spent window without a readable reset is bounded like a refusal:
        # an indefinite hide would outlive any evidence for it.
        until = now + (min(RESET_CAP_S, max(known)) if known else REFUSAL_TTL_S)
        return ('block', 'headers', until)
    if status in (401, 403):
        return ('block', 'auth', now + REFUSAL_TTL_S)
    if status == 429:
        return ('block', 'refusal', now + REFUSAL_TTL_S)
    return CLEAR if status < 400 else None


def _write_needed(current, entry, now):
    """True when this verdict changes what the gate would do on disk."""
    if current['source'] != entry['source']:
        return True
    if entry['until'] is None or current['until'] is None:
        return entry['until'] != current['until']
    if abs(entry['until'] - current['until']) < EXPIRY_SLACK_S:
        return False
    if entry['source'] == 'headers':
        return True
    # A same-source refusal extension only lands once the stored expiry is
    # well spent, so a busy session does not rewrite the picker every turn.
    return current['until'] - now <= REFUSAL_TTL_S // 2


def record(home, slug, change, now):
    """Store one verdict for a slug; True when the stored gate changed."""
    gate = read(home)
    current = gate.get(slug)
    if change == CLEAR:
        if current is None:
            return False
        source = current['source']
        del gate[slug]
    else:
        _, source, until = change
        entry = {'source': source, 'until': until,
                 'probed': current['probed'] if current is not None else 0,
                 'since': now if current is None or current['source'] != source
                 else current['since']}
        if current is not None and not _write_needed(current, entry, now):
            return False
        gate[slug] = entry
    if not write(home, gate):
        return False
    log_event('subscription_gate_changed', model=slug, source=source,
              blocked=change != CLEAR)
    if not gate:
        forget_login()
    return True


def remember_login(provider_id, headers):
    """Keep the last subscription request headers in memory only.

    The recheck speaks with the client's own login: these headers are never
    written to disk, never logged, replaced by the next turn, and dropped
    once the gate empties.
    """
    global _LOGIN
    if provider_id != provider_defs.OPENAI.id or not headers:
        return
    try:
        kept = {str(key): value for key, value in headers.items()
                if str(key).lower() not in HOP_HEADERS}
    except AttributeError:
        return
    if kept:
        with _LOCK:
            _LOGIN = kept
