"""Bounded observations of one send; none of these facts grants retry authority."""
import re
import time
from dataclasses import replace
from functools import partial
from . import outcome

EFFORTS = frozenset(('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'))
RESPONSE_EVENTS = frozenset(('response.created', 'response.in_progress',
    'response.completed', 'response.failed', 'response.incomplete'))
MAX_REPORTS = 8
ERROR_TYPES = frozenset(('TimeoutError', 'ConnectionResetError', 'BrokenPipeError',
    'RemoteDisconnected', 'IncompleteRead', 'SSLError', 'SSLCertVerificationError',
    'ConnectionRefusedError', 'gaierror', 'OSError', 'ValueError', 'TypeError',
    'AttributeError', 'KeyError', 'HTTPException', 'other'))


def identifier(value):
    return value if isinstance(value, str) and re.fullmatch(
        r'[~A-Za-z0-9][A-Za-z0-9._/+:~\-]{0,127}', value) else None


def thread_id(value):
    return value if isinstance(value, str) and re.fullmatch(
        r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', value) else None


def client_threads(headers):
    return {'thread_id': thread_id(headers.get('thread-id')),
            'parent_thread_id': thread_id(headers.get('x-codex-parent-thread-id'))}


def requested_effort(payload):
    for key in ('reasoning', 'output_config'):
        source = payload.get(key)
        effort = source.get('effort') if isinstance(source, dict) else None
        if isinstance(effort, str) and effort in EFFORTS:
            return effort
    return None


def observe(notes, payload, source):
    record = notes.get('attempt_evidence') if isinstance(notes, dict) else None
    if isinstance(record, Attempt) and isinstance(payload, dict):
        record.report('model', payload.get('model'), source + '.model')
        if source.startswith('response'):
            reasoning = payload.get('reasoning')
            record.report('effort', reasoning.get('effort') if isinstance(reasoning, dict)
                          else None, source + '.reasoning.effort')
        metadata = payload.get('openrouter_metadata')
        endpoints = metadata.get('endpoints') if isinstance(metadata, dict) else None
        available = endpoints.get('available') if isinstance(endpoints, dict) else None
        for entry in available[:MAX_REPORTS] if isinstance(available, list) else ():
            if isinstance(entry, dict) and entry.get('selected') is True:
                record.report('endpoint', entry.get('provider'),
                              source + '.openrouter_metadata.endpoints.available.selected.provider')


def response_event(notes, event):
    if (isinstance(event, dict) and isinstance(event.get('type'), str)
            and event['type'] in RESPONSE_EVENTS):
        observe(notes, event.get('response'), event['type'] + '.response')


def phase(notes, name):
    record = notes.get('attempt_evidence')
    if isinstance(record, Attempt):
        record.phase(name)


def verdict(notes, settled):
    record = notes.get('attempt_evidence')
    if isinstance(record, Attempt):
        record.verdict(settled)


class Attempt(dict):
    """JSON-safe fields; monotonic clocks stay private to this request's owner."""

    def __init__(self, number, reason, prepared, metrics, timeout):
        context = getattr(prepared, 'context', None)
        slug = context.slug if context is not None else metrics.get('model')
        row = context.row if context is not None else None
        super().__init__(attempt=number, reason=reason, route=prepared.provider,
            protocol=metrics.get('protocol'), requested_model=identifier(metrics.get('model')),
            resolved_model=identifier(slug),
            upstream_model=identifier(getattr(row, 'upstream_id', '') or slug),
            requested_effort=metrics.get('reasoning_effort'), model_reports=[],
            effort_reports=[], endpoint_reports=[], model_status='unverified',
            effort_status='unverified', reports_limited=False, committed=False,
            timeout_s=timeout, outcome='unknown', phase='connect')
        self.started = self.phase_started = time.monotonic()
        self.last_data = self.ended = None
        self.observed = False

    def verdict(self, settled):
        if settled.category == outcome.CANCELLED:
            self['failure_phase'] = 'write'
        if not self.observed:
            self.update(outcome.facts(settled))
            self.observed = True

    def report(self, field, value, source):
        value = value if field == 'effort' and isinstance(value, str) and value in EFFORTS else (
            identifier(value) if field != 'effort' else None)
        if value is None:
            return
        reports = self[field + '_reports']
        entry = {'value': value, 'source': source}
        if entry in reports:
            return
        if len(reports) >= MAX_REPORTS:
            self['reports_limited'] = True
            return
        reports.append(entry)
        if field in ('model', 'effort'):
            values = {report['value'] for report in reports}
            expected = self['upstream_model' if field == 'model' else 'requested_effort']
            self[field + '_status'] = ('contradictory' if len(values) > 1 else
                'unverified' if expected is None else
                'provider_reported_match' if value == expected else 'mismatch')

    def phase(self, name):
        now = time.monotonic()
        self[self['phase'] + '_ms'] = round((now - self.phase_started) * 1000, 1)
        self['phase'], self.phase_started = name, now

    def failed(self, exc, phase=None):
        self['failure_phase'] = phase or self['phase']
        name = type(exc).__name__
        self['error_type'] = name if name in ERROR_TYPES else 'other'
        phase = (outcome.STREAM if self['phase'] == 'read' and self.get('http_status') == 200
                 else outcome.STATUS if self.get('http_status') is not None else outcome.SEND)
        self.verdict(replace(outcome.raised(exc, False, None, None), phase=phase))

    def finish(self):
        if self.ended is None:
            self.ended = time.monotonic()
            self['age_ms'] = round((self.ended - self.started) * 1000, 1)
            self['last_data_age_ms'] = (round((self.ended - self.last_data) * 1000, 1)
                                       if self.last_data is not None else None)

    def response(self, response):
        self['http_status'] = response.status
        self['headers_ms'] = round((time.monotonic() - self.phase_started) * 1000, 1)
        getheader = getattr(response, 'getheader', None)
        if getheader is not None:
            self.report('model', getheader('openai-model'), 'header.openai-model')
        return ObservedResponse(response, self)


class ObservedResponse:
    """Preserve the response; time actual read calls rather than parsed frames."""

    def __init__(self, response, record):
        self.response, self.record = response, record

    def __getattr__(self, name):
        value = getattr(self.response, name)
        return partial(self._read, value) if name in ('read', 'read1') else value

    def _read(self, method, *args, **kwargs):
        record = self.record
        record['phase'] = 'read'
        started = time.monotonic()
        try:
            chunk = method(*args, **kwargs)
        except BaseException as exc:
            record.failed(exc)
            raise
        finally:
            record['read_wait_ms'] = round(record.get('read_wait_ms', 0)
                                          + (time.monotonic() - started) * 1000, 1)
        if chunk:
            record.last_data = time.monotonic()
        return chunk
