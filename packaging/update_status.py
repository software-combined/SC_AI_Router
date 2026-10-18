"""Verified update facts, cache bindings and independent repair warnings.

Python 3.9-safe. Read-only summaries never persist state or contact a service.
"""
import calendar
import hashlib
import re
import time

ERROR_CODES = (
    'feed_unreachable', 'feed_invalid', 'feed_serial', 'feed_untrusted',
    'feed_signature', 'bundle_checksum', 'bundle_invalid', 'installer_timeout',
    'installer_failed', 'update_failed', 'download_signin_required',
)
COMPONENTS = ('controller', 'updater_launcher', 'scheduler', 'assistants', 'controls', 'controls_launchers')
MISSED_AFTER = 2 * 4 * 60 * 60 + 15 * 60


def version(value):
    return value if isinstance(value, str) and re.fullmatch(r'\d+(?:\.\d+){2,3}', value) else None


def stamp(value):
    return value if isinstance(value, str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', value) else None


def utc_now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def seconds(value):
    try:
        return calendar.timegm(time.strptime(value, '%Y-%m-%dT%H:%M:%SZ')) if stamp(value) else None
    except (ValueError, OverflowError):
        return None


def display_time(value):
    moment = seconds(value)
    return time.strftime('%d %b %Y %I:%M %p %Z', time.localtime(moment)) if moment is not None else 'Unknown'


def channel(home):
    value = (home / 'channel').read_text().strip() if (home / 'channel').exists() else 'stable'
    return 'beta' if value == 'beta' else 'stable'


def source(feed):
    return hashlib.sha256(feed.encode()).hexdigest()


def binding(state, feed, channel):
    record = state.get('latest_verified') if isinstance(state, dict) else None
    return (record if isinstance(record, dict) and version(record.get('version'))
            and record.get('channel') == channel and channel in ('stable', 'beta')
            and record.get('source') == source(feed) else None)


def verified(state, latest, feed, channel, etag, now=None):
    """Call only after signature, feed shape, origin and serial checks succeed."""
    if not version(latest.get('version')) or channel not in ('stable', 'beta'):
        raise ValueError('invalid verified update identity')
    state['latest_verified'] = dict(version=latest['version'], channel=channel,
        source=source(feed), etag=etag if isinstance(etag, str) and etag else None)
    state['last_successful_check_at'] = now or utc_now()


def components(state):
    values = state.get('component_repairs', {}) if isinstance(state, dict) else {}
    if not isinstance(values, dict):
        return {}
    return {key: value for key, value in values.items()
            if key in COMPONENTS and value in ('ready', 'failed', 'unknown')}


def _parts(value):
    values = tuple(map(int, value.split('.')))
    return values + (0,) * (4 - len(values))


def active_failures(failures, current):
    if not isinstance(failures, dict):
        return {}
    return {key: count for key, count in failures.items()
            if version(key) and type(count) is int and count > 0
            and (not version(current) or _parts(key) >= _parts(current))}


def failures(state, feed, channel):
    """Legacy counts stay conservative; new counts belong to one channel/source."""
    contexts = state.get('update_failure_context', {}) if isinstance(state, dict) else {}
    contexts = contexts if isinstance(contexts, dict) else {}
    counts = state.get('update_failures', {}) if isinstance(state, dict) else {}
    return {key: count for key, count in active_failures(counts, None).items()
            if key not in contexts or contexts[key] == dict(channel=channel, source=source(feed))}


def install_pending(state):
    return (isinstance(state, dict) and (state.get('installation_repair_required') is True
            or state.get('last_error') in ('installer_failed', 'installer_timeout')))


def cache_tag(state, current, feed, channel, etag):
    """An old unbound ETag or any pending failure cannot assert currentness."""
    record = binding(state, feed, channel)
    counts = failures(state, feed, channel)
    return (etag if record and record['version'] == current and etag
            and record.get('etag') == etag and not state.get('last_error')
            and not install_pending(state)
            and not active_failures(counts, current)
            and 'failed' not in components(state).values() else None)


def record(state, error=None, applied=None, repaired=False, now=None):
    """A skipped pass preserves failures; feed success cannot clear attachment failure."""
    state['last_check_at'] = now or utc_now()
    if install_pending(state) or error in ('installer_failed', 'installer_timeout'):
        state['installation_repair_required'] = True
    if repaired and not error:
        state.pop('installation_repair_required', None)
    if error is not None:
        streak = state.get('update_failure_streak', 0)
        streak = streak if type(streak) is int and streak >= 0 else 0
        if error:
            state['last_error'] = error if error in ERROR_CODES else 'update_failed'
            state['update_failure_streak'] = streak + 1
        elif repaired or state.get('last_error') != 'installer_failed':
            state.pop('last_error', None)
            state['update_failure_streak'] = 0
    if version(applied):
        state['last_applied_version'] = applied


def summary(state, current=None, feed=None, channel=None, now=None):
    """Only allowlisted facts reach status, controls and support output."""
    doc = state if isinstance(state, dict) else {}
    failed = (failures(doc, feed, channel) if feed is not None else
              active_failures(doc.get('update_failures'), None))
    known = binding(doc, feed, channel) if feed is not None else None
    error = doc.get('last_error')
    error = error if error in ERROR_CODES else None
    repairs = components(doc)
    available = bool(known and version(current) and _parts(known['version']) > _parts(current))
    last = seconds(doc.get('last_check_at'))
    overdue = last is not None and (time.time() if now is None else now) - last >= MISSED_AFTER
    parked = active_failures(failed, current)
    repair = bool(error or install_pending(doc) or parked or 'failed' in repairs.values() or overdue)
    streak = doc.get('update_failure_streak', 0)
    blocked = (install_pending(doc) or 'failed' in repairs.values()
               or any(count >= 3 for count in parked.values())
               or error not in (None, 'feed_unreachable', 'update_failed'))
    return dict(last_check_at=stamp(doc.get('last_check_at')),
        last_successful_check_at=stamp(doc.get('last_successful_check_at')) if known else None,
        last_applied_version=version(doc.get('last_applied_version')), last_error=error,
        failures=failed, latest_known_version=known['version'] if known else None,
        source=source(feed) if feed is not None else None,
        latest_known_channel=known['channel'] if known else None,
        installation_repair_required=install_pending(doc),
        component_repairs=repairs, missed_scheduled_checks=overdue,
        offer_repair=bool(repair and (blocked or overdue or type(streak) is int and streak >= 2)),
        required_action='repair' if repair else 'update' if available else None)
