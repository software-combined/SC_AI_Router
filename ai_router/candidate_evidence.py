"""Content-free candidate proof, shared by onboarding and the acceptance ledger."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

from . import registry, request_evidence
from .clients.registry import CLIENTS

ROOT = Path(__file__).resolve().parents[1]
KIND = 'model_routes_v1'
MAX_PROBE_CALLS = 12
FIELDS = frozenset(('kind', 'observed_at', 'model', 'provider', 'capability_fingerprint',
                    'runtime_fingerprint', 'router_version', 'router_revision', 'routes'))
ROUTE_FIELDS = frozenset(('protocol', 'client', 'client_version', 'requested_effort',
                         'served_models', 'served_efforts', 'calls', 'result', 'conformance'))


def timestamp(record):
    if 'observed_at' in record:
        value = datetime.fromisoformat(record['observed_at'])
        if value.tzinfo is None:
            raise ValueError('evidence timestamp needs a timezone')
        return value
    value, zone = record['date_aest'].rsplit(' ', 1)
    if zone not in ('AEST', 'AEDT'):
        raise ValueError('unknown evidence timezone')
    return datetime.strptime(value, '%Y-%m-%d %H:%M').replace(
        tzinfo=timezone(timedelta(hours=10 if zone == 'AEST' else 11)))


def latest(records):
    """A newer failure supersedes a pass; contradictory tied runs are unknown."""
    if not records:
        return None, 'missing'
    newest = max(map(timestamp, records))
    tied = [row for row in records if timestamp(row) == newest]
    if len({json.dumps(row, sort_keys=True) for row in tied}) != 1:
        return None, 'conflicting'
    return tied[0], None


def model(row):
    return registry.load(json.dumps([row]))[0] if isinstance(row, dict) else row


def capability_fingerprint(row):
    data = asdict(model(row))
    for key in ('display_name', 'vendor', 'tier', 'listed', 'priority'):
        data.pop(key)
    data['excluded_efforts'] = sorted(data['excluded_efforts'])
    data['upstream_id'] = data['upstream_id'] or data['slug']
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def runtime_fingerprint(root=ROOT):
    digest = hashlib.sha256()
    files = sorted((Path(root) / 'ai_router').rglob('*.py'))
    if not files:
        raise ValueError('candidate runtime is missing')
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode() + b'\0')
        digest.update(path.read_bytes())
    return digest.hexdigest()


def binding(row, root=ROOT):
    row = model(row)
    done = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root,
                          capture_output=True, text=True, timeout=10)
    revision = done.stdout.strip()
    return {'kind': KIND, 'observed_at': datetime.now(timezone.utc).isoformat(),
            'model': row.slug, 'provider': row.provider,
            'capability_fingerprint': capability_fingerprint(row),
            'runtime_fingerprint': runtime_fingerprint(root),
            'router_version': (Path(root) / 'packaging/VERSION').read_text().strip(),
            'router_revision': revision if re.fullmatch(r'[0-9a-f]{40}', revision) else None,
            'routes': []}


def _reports(value, effort=False):
    sources = ('response', 'message', 'message_start.message',
               *(event + '.response' for event in request_evidence.RESPONSE_EVENTS))
    allowed = {source + ('.reasoning.effort' if effort else '.model') for source in sources}
    if not effort:
        allowed.add('header.openai-model')
    return (isinstance(value, list) and len(value) <= 64
            and all(isinstance(report, dict) and set(report) == {'value', 'source'}
                    and report['source'] in allowed
                    and (report['value'] in request_evidence.EFFORTS if effort
                         else request_evidence.identifier(report['value']) is not None)
                    for report in value))


def validate(record):
    """Reject unknown fields so evidence cannot quietly turn into a transcript."""
    if not isinstance(record, dict) or set(record) != FIELDS or record['kind'] != KIND:
        raise ValueError('bad candidate evidence fields')
    timestamp(record)
    if (any(request_evidence.identifier(record[key]) is None
            for key in ('model', 'provider', 'router_version'))
            or any(not isinstance(record[key], str) or not re.fullmatch(r'[0-9a-f]{64}', record[key])
                   for key in ('capability_fingerprint', 'runtime_fingerprint'))
            or (record['router_revision'] is not None
                and not re.fullmatch(r'[0-9a-f]{40}', str(record['router_revision'])))
            or not isinstance(record['routes'], list) or len(record['routes']) > len(CLIENTS)):
        raise ValueError('bad candidate binding')
    for route in record['routes']:
        if not isinstance(route, dict) or set(route) != ROUTE_FIELDS:
            raise ValueError('bad candidate route fields')
        if (not any((route['client'], route['protocol']) == (c.id, c.protocol) for c in CLIENTS)
                or request_evidence.identifier(route['client_version']) is None
                or route['requested_effort'] not in request_evidence.EFFORTS
                or type(route['calls']) is not int or not 0 <= route['calls'] <= MAX_PROBE_CALLS
                or route['result'] not in ('pass', 'fail')
                or route['conformance'] not in ('pass', 'fail')
                or not _reports(route['served_models']) or not _reports(route['served_efforts'], True)):
            raise ValueError('bad candidate route evidence')
    if sum(route['calls'] for route in record['routes']) > MAX_PROBE_CALLS:
        raise ValueError('candidate call budget exceeded')
    return record


def problems(row, record, *, runtime=None, clients=None):
    """Every advertised route needs current proof; absent served facts stay unknown."""
    try:
        validate(record)
        row = model(row)
        runtime = runtime or runtime_fingerprint()
        if ((record['model'], record['provider']) != (row.slug, row.provider)
                or record['capability_fingerprint'] != capability_fingerprint(row)
                or record['runtime_fingerprint'] != runtime):
            return ['candidate changed']
        expected = {c.protocol: c.id for c in CLIENTS
                    if registry.row_serves(row, c.protocol)}
        routes = record['routes']
        if len(routes) != len(expected) or {r['protocol'] for r in routes} != set(expected):
            return ['missing or duplicate route']
        failures = []
        for route in routes:
            if (route['client'] != expected[route['protocol']]
                    or not re.fullmatch(r'\d+(?:\.\d+)+(?:[-+][A-Za-z0-9.]+)?', route['client_version'])
                    or (clients is not None and route['client_version'] != clients.get(route['client']))
                    or route['requested_effort'] not in row.reasoning
                    or route['result'] != 'pass' or route['conformance'] != 'pass'
                    or route['calls'] < 1
                    or any(r['value'] != (row.upstream_id or row.slug) for r in route['served_models'])
                    or any(r['value'] != route['requested_effort'] for r in route['served_efforts'])):
                failures.append(route['protocol'] + ': failed, stale or mismatched evidence')
        return failures
    except (ValueError, TypeError, KeyError, OSError):
        return ['missing or malformed candidate evidence']
