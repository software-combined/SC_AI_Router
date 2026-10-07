"""Read recent request evidence: python3.14 -m ai_router.inspect_requests."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re

from . import outcome, request_evidence, state

STATUSES = ('unverified', 'provider_reported_match', 'mismatch', 'contradictory')
NUMBERS = ('attempt', 'timeout_s', 'http_status', 'connect_ms', 'send_ms', 'headers_ms',
           'read_wait_ms', 'age_ms', 'last_data_age_ms')
IDENTIFIERS = ('requested_model', 'resolved_model', 'upstream_model', 'route', 'protocol', 'outcome_code')
ENUMS = {'reason': ('initial', 'repair', 'stream_replay', 'helper_fallback'),
         'model_status': STATUSES, 'effort_status': STATUSES,
         'requested_effort': request_evidence.EFFORTS, 'outcome': outcome.CATEGORIES,
         'phase': ('connect', 'send', 'headers', 'read'),
         'failure_phase': ('connect', 'send', 'headers', 'read', 'write'),
         'error_type': request_evidence.ERROR_TYPES,
         'outcome_phase': outcome.PHASES, 'outcome_source': outcome.SOURCES,
         'terminal_source': ('upstream', 'router', 'client')}


def _attempt(row):
    clean = {k: request_evidence.identifier(row.get(k)) for k in IDENTIFIERS}
    clean.update({k: row.get(k) if isinstance(row.get(k), str) and row[k] in values else None
                  for k, values in ENUMS.items()})
    clean.update({k: row[k] for k in NUMBERS if type(row.get(k)) in (int, float)
                  and math.isfinite(row[k]) and row[k] >= 0})
    clean.update({k: row[k] for k in ('committed', 'reports_limited') if type(row.get(k)) is bool})
    decision = row.get('decision')
    clean['decision'] = decision if isinstance(decision, str) and re.fullmatch(
        r'(repair|stream_replay|helper_fallback):(approved|budget|committed|not_transient|'
        r'router_terminal|output|side_effects|ineligible|unchanged|refused|no_plan|not_subscription|'
        r'not_responses|disabled|not_helper|no_key|not_allowed)', decision) else None
    for field in ('model', 'effort', 'endpoint'):
        reports = row.get(field + '_reports')
        clean[field + '_reports'] = []
        for report in reports[:request_evidence.MAX_REPORTS] if isinstance(reports, list) else ():
            if not isinstance(report, dict):
                continue
            value = request_evidence.identifier(report.get('value'))
            source = report.get('source')
            if value and isinstance(source, str) and re.fullmatch(
                r'(?:header\.openai-model|(?:response(?:\.(?:created|in_progress|completed|failed|incomplete)\.response)?'
                r'|message_start\.message|message)\.(?:model|reasoning\.effort|'
                r'openrouter_metadata\.endpoints\.available\.selected\.provider))', source):
                clean[field + '_reports'].append({'value': value, 'source': source})
    return clean


def recent(home, *, request_id=None, model=None, since=None, until=None, identity='any',
           thread_id=None, parent_thread_id=None, limit=20):
    """At most four existing 5 MiB log tails; never consult auth, state or the network."""
    results, seen = [], set()
    for suffix in ('', '.1', '.2', '.3'):
        path = Path(home) / 'logs' / ('router.jsonl' + suffix)
        try:
            with path.open('rb') as stream:
                stream.seek(0, 2)
                offset = max(0, stream.tell() - 5 * 1024 * 1024)
                stream.seek(offset)
                lines = stream.read(5 * 1024 * 1024).splitlines()
                if offset: lines = lines[1:]
        except OSError:
            continue
        for line in reversed(lines):
            if len(line) > 128 * 1024:
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict) or row.get('event') != 'attempt_ledger': continue
                ident = row.get('request_id')
                if not isinstance(ident, str) or not re.fullmatch(r'[0-9a-f]{32}', ident): continue
                timestamp = datetime.fromisoformat(row['ts'])
                if timestamp.tzinfo is None: continue
            except (ValueError, KeyError, TypeError, RecursionError):
                continue
            if (ident in seen or request_id and ident != request_id or since and timestamp < since
                    or until and timestamp > until):
                continue
            seen.add(ident)
            threads = {key: request_evidence.thread_id(row.get(key))
                       for key in ('thread_id', 'parent_thread_id')}
            if (thread_id and threads['thread_id'] != thread_id
                    or parent_thread_id and threads['parent_thread_id'] != parent_thread_id):
                continue
            entries = row.get('attempt_evidence')
            attempts = [_attempt(value) for value in entries[:5] if isinstance(value, dict)] if isinstance(entries, list) else []
            if model and not any(model in (a['requested_model'], a['resolved_model'], a['upstream_model']) for a in attempts): continue
            if identity != 'any' and not any(a['model_status'] == identity for a in attempts): continue
            results.append({'ts': timestamp.isoformat(), 'request_id': ident, **threads,
                'router_version': request_evidence.identifier(row.get('router_version')),
                'operation': row.get('operation') if row.get('operation') in (
                    '/responses', '/responses/compact', '/v1/messages', '/v1/messages/count_tokens') else 'native_service',
                'outcome': row.get('outcome') if isinstance(row.get('outcome'), str) and row['outcome'] in outcome.CATEGORIES else 'unknown',
                'attempt_evidence': attempts})
            if len(results) >= limit: return results
    return results


def agent_summary(rows, model, effort, *, limit):
    """Reports from retained child turns, not an attestation or a completeness claim."""
    turns = [row for row in rows if row['operation'] == '/responses']
    pairs = [(row, attempt) for row in turns for attempt in row['attempt_evidence']]
    summary = {'coverage': 'retained_records_only', 'limit_reached': len(rows) >= limit, 'requests': len(turns),
               'helper_requests': len(rows) - len(turns), 'attempts': len(pairs)}
    for field, expected in (('model', model), ('effort', effort)):
        requested = 'requested_' + field
        statuses = [a[field + '_status'] for _, a in pairs]
        summary[field + '_reports'] = [dict(report, request_id=row['request_id'], attempt=a.get('attempt'))
            for row, a in pairs for report in a[field + '_reports']]
        mismatch = any(a[requested] is not None and a[requested] != expected for _, a in pairs)
        partial = (summary['limit_reached'] or not pairs or any(not row['attempt_evidence'] or row['outcome'] != 'success'
            for row in turns) or any(a[requested] is None or a.get('reports_limited') or not a[field + '_reports']
            for _, a in pairs))
        summary[field + '_status'] = ('contradictory' if 'contradictory' in statuses else
            'mismatch' if mismatch or 'mismatch' in statuses else
            'unverified' if partial or any(s != 'provider_reported_match' for s in statuses)
            else 'provider_reported_match')
    return summary


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            return parsed
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('timestamp must include a UTC offset')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=state.default_home())
    parser.add_argument('--request-id')
    parser.add_argument('--model')
    parser.add_argument('--thread-id')
    parser.add_argument('--parent-thread-id')
    parser.add_argument('--since', type=_timestamp)
    parser.add_argument('--until', type=_timestamp)
    parser.add_argument('--agent-summary', action='store_true',
                        help='Summarize exact child evidence; --model is expected, not a filter')
    parser.add_argument('--expected-effort', choices=sorted(request_evidence.EFFORTS))
    parser.add_argument('--minutes', type=int, default=60, help='Recent window; 0 reads all retained records')
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--identity', choices=('any', 'unverified', 'mismatch', 'contradictory'), default='any')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    if args.minutes < 0 or not 1 <= args.limit <= 100: parser.error('minutes must be nonnegative; limit must be 1–100')
    for value in (args.thread_id, args.parent_thread_id):
        if value is not None and request_evidence.thread_id(value) is None:
            parser.error('thread IDs must be canonical UUIDs')
    if args.since and args.until and args.until < args.since: parser.error('until must not precede since')
    if args.agent_summary and (not all((args.thread_id, args.parent_thread_id, args.since,
            args.until, args.model, args.expected_effort)) or args.request_id or args.identity != 'any'):
        parser.error('agent-summary needs child and parent IDs, since/until, model and expected-effort; no identity/request filter')
    rows = recent(args.home, request_id=args.request_id, model=None if args.agent_summary else args.model,
                  identity=args.identity, thread_id=args.thread_id, parent_thread_id=args.parent_thread_id,
                  until=args.until, limit=args.limit, since=args.since or (
                  datetime.now(timezone.utc) - timedelta(minutes=args.minutes) if args.minutes else None))
    if args.agent_summary:
        print(json.dumps({'summary': agent_summary(rows, args.model, args.expected_effort, limit=args.limit),
                          'records': rows}, indent=2))
        return 0
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(f"{datetime.fromisoformat(row['ts']).astimezone():%Y-%m-%d %H:%M:%S %Z}  {row['request_id']}  {row['outcome']}  v{row['router_version']} {row['operation']}")
            for a in row['attempt_evidence']:
                reports = ', '.join(r['value'] + ' [' + r['source'] + ']' for r in a['model_reports']) or 'unverified'
                print(f"  attempt {a.get('attempt', '?')} {a['reason']} {a['route']}/{a['protocol']}: {a['requested_model']} -> {a['upstream_model']}; {a['model_status']}: {reports}")
                effort = ', '.join(r['value'] for r in a['effort_reports']) or 'unverified'
                print(f"    outcome={a['outcome']} phase={a['failure_phase'] or a['phase']} error={a['error_type']} age={a.get('age_ms')}ms last-data={a.get('last_data_age_ms')}ms timeout={a.get('timeout_s')}s committed={a.get('committed')} decision={a['decision']}; effort requested={a['requested_effort']} reported={effort}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
