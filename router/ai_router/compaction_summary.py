"""Bounded fast-model summaries for external compaction."""
import http.client
import json
import threading
import time

from . import (availability, compaction as comp, compaction_result,
               history_items, provider_defs, registry, transport)
from .capabilities import CANONICAL_ORDER
from .events import log_event as _log_event
from .registry import upstream_id_for

SUMMARY_OUTPUT_TOKENS, SUMMARY_RETRY_OUTPUT_TOKENS = 4000, 8000
SUMMARY_MODEL_SLUGS = ('xiaomi/mimo-v2.6-flash',
                       'deepseek/deepseek-v4.1-flash-1017')
SUMMARY_ATTEMPT_DEADLINE_S = 45
SUMMARY_TOTAL_DEADLINE_S = 75

def _bounded_call(func, bound, monotonic, on_timeout, *args, **kwargs):
    """Run one blocking network call with a real wall-clock bound."""
    state, done = {}, threading.Event()

    def run():
        try:
            state['value'] = func(*args, **kwargs)
        except BaseException as exc:
            state['error'] = exc
        done.set()

    threading.Thread(target=run, daemon=True).start()
    stop = time.monotonic() + _remaining_time(bound, monotonic)
    while not done.wait(min(0.05, max(0, stop - time.monotonic()))):
        if time.monotonic() >= stop:
            on_timeout()
            raise TimeoutError('Compaction summarizer deadline exceeded')
    if 'error' in state:
        raise state['error']
    return state['value']

def _summary_budgets(entry):
    ceiling = getattr(entry, 'max_output_tokens', SUMMARY_OUTPUT_TOKENS)
    if (isinstance(ceiling, int) and not isinstance(ceiling, bool)
            and ceiling > SUMMARY_OUTPUT_TOKENS):
        return (SUMMARY_OUTPUT_TOKENS,
                min(SUMMARY_RETRY_OUTPUT_TOKENS, ceiling))
    return (SUMMARY_OUTPUT_TOKENS,)

def summary_entries(provider_id, catalogue=None, allowed=None,
                    availability_snapshot=None, lookup=None):
    """Resolve eligible pinned rows from one registry generation.

    A None snapshot fails closed (summaries carry history). An empty
    dict asks only whether any summary row exists for the provider,
    which the candidate probe uses to decide its compaction leg.
    """
    exists_only = availability_snapshot is not None and not availability_snapshot
    if availability_snapshot is None:
        return []
    lookup_row = (catalogue.get if catalogue is not None
                  else (lookup or registry.by_slug))
    entries, missing = [], False
    for slug in SUMMARY_MODEL_SLUGS:
        if allowed is not None and slug not in allowed:
            continue
        if not exists_only and not availability.permitted(slug, availability_snapshot):
            continue
        entry = lookup_row(slug)
        if entry is None:
            missing = True
            continue
        if exists_only and getattr(entry, 'provider', None) != provider_id:
            continue  # existence question only: another provider's rows do not count
        if (getattr(entry, 'slug', None) != slug
                or getattr(entry, 'provider', None) != provider_id
                or upstream_id_for(entry) != slug
                or getattr(entry, 'provider_prefs', None) is not None
                or not isinstance(getattr(entry, 'max_output_tokens', None), int)
                or getattr(entry, 'max_output_tokens', 0) < SUMMARY_RETRY_OUTPUT_TOKENS):
            raise ValueError('Compaction summary registry row failed pin')
        entries.append(entry)
    if missing and entries:
        raise ValueError('Compaction summary registry row missing')
    return entries


def _elapsed_ms(started, monotonic):
    return round((monotonic() - started) * 1000, 3)


def _set_timeout(conn, timeout):
    sock = getattr(conn, 'sock', None)
    if sock is not None and hasattr(sock, 'settimeout'):
        sock.settimeout(timeout)


def _remaining_time(deadline, monotonic):
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError('Compaction summarizer deadline exceeded')
    return remaining


def _read_summary_body(conn, response, limit, deadline, monotonic):
    """Read a response while enforcing the one compaction deadline."""
    read1 = getattr(response, 'read1', None)
    if read1 is None:
        _set_timeout(conn, _remaining_time(deadline, monotonic))
        body = _bounded_call(response.read, deadline, monotonic, conn.close)
        _remaining_time(deadline, monotonic)
        if len(body) > limit:
            raise ValueError('upstream body exceeds %d bytes' % limit)
        return body
    chunks, total = [], 0
    while True:
        _set_timeout(conn, _remaining_time(deadline, monotonic))
        piece = _bounded_call(read1, deadline, monotonic, conn.close, 65536)
        _remaining_time(deadline, monotonic)
        if not piece:
            return b''.join(chunks)
        total += len(piece)
        if total > limit:
            raise ValueError('upstream body exceeds %d bytes' % limit)
        chunks.append(piece)


def _fetch_summary(provider, key, body, timeout, deadline, attempt_deadline,
                   monotonic, dispatched=None):
    """One summary request; every failure propagates for the caller to classify."""
    bound = min(deadline, attempt_deadline)
    _remaining_time(bound, monotonic)
    conn = http.client.HTTPSConnection(provider.host, timeout=timeout)
    try:
        req = json.dumps(body).encode()
        headers = dict(provider.defn.request_headers)
        headers.update({'Authorization': 'Bearer ' + key,
                        'Content-Type': 'application/json',
                        'Accept-Encoding': 'identity'})
        _remaining_time(bound, monotonic)
        _bounded_call(conn.connect, bound, monotonic, conn.close)
        _remaining_time(bound, monotonic)
        if dispatched is not None:
            dispatched.append(True)
        _bounded_call(conn.request, bound, monotonic, conn.close, 'POST',
                      provider.defn.path_for(provider_defs.RESPONSES, '/responses'),
                      body=req, headers=headers)
        _set_timeout(conn, _remaining_time(bound, monotonic))
        resp = _bounded_call(conn.getresponse, bound, monotonic, conn.close)
        _set_timeout(conn, _remaining_time(bound, monotonic))
        raw = _read_summary_body(
            conn, resp, transport.MAX_UPSTREAM_BODY, bound, monotonic)
        try:
            data = json.loads(raw)
        except ValueError:
            raise OSError('Summarizer returned invalid JSON')
        _remaining_time(bound, monotonic)
        return compaction_result.extract_summary(
            resp.status, data, expected_model=body['model'])
    finally:
        conn.close()


def summarize(provider, key, payload_items, catalogue=None, allowed=None,
              active_model=None, lookup=None, log=None, monotonic=None,
              availability_snapshot=None):
    """Return a bounded summary from MiMo Flash, then DeepSeek Flash."""
    lookup = lookup or registry.by_slug
    log = log or _log_event
    monotonic = monotonic or time.monotonic
    transcript = comp.transcript_for_summary(payload_items)
    prompt = comp.COMPACT_PROMPT + '\n\nConversation:\n' + transcript
    started = monotonic()
    deadline = started + SUMMARY_TOTAL_DEADLINE_S
    entries = summary_entries(
        provider.defn.id, catalogue, allowed, availability_snapshot, lookup)
    attempts = []
    def complete(outcome, summary='', summary_model=None):
        log('compaction_summary_complete',
            active_model=active_model,
            summary_model=summary_model or (entries[-1].slug if entries else None),
            outcome=outcome, elapsed_ms=_elapsed_ms(started, monotonic),
            summary_chars=len(summary), attempts=attempts)

    log('compaction_summary_start',
        active_model=active_model,
        summary_model=entries[0].slug if entries else None,
        transcript_chars=len(transcript))
    if not entries:
        complete('unavailable')
        raise ValueError('Compaction summary models unavailable')

    attempt = 0
    last_error = None
    for entry_index, entry in enumerate(entries):
        budgets = _summary_budgets(entry)
        levels = getattr(entry, 'reasoning', ())
        effort = min(levels, key=CANONICAL_ORDER.index) if levels else None
        for budget_index, budget in enumerate(budgets):
            attempt += 1
            remaining = deadline - monotonic()
            if remaining <= 0:
                attempts.append({'attempt': attempt,
                                 'summary_model': entry.slug,
                                 'max_output_tokens': budget, 'elapsed_ms': 0,
                                 'outcome': 'deadline', 'commitment': 'unsent'})
                complete('deadline', summary_model=entry.slug)
                raise TimeoutError('Compaction summarizer deadline exceeded')
            attempt_started = monotonic()
            attempt_deadline = min(
                attempt_started + SUMMARY_ATTEMPT_DEADLINE_S, deadline)
            timeout = attempt_deadline - attempt_started
            body = {'model': entry.slug,
                    'input': [history_items.user_message_item(prompt)],
                    'max_output_tokens': budget}
            if effort:
                # Never let default high effort burn the whole budget on reasoning.
                body['reasoning'] = {'effort': effort}
            dispatched = []

            def record(outcome, commitment):
                attempts.append({'attempt': attempt,
                                 'summary_model': entry.slug,
                                 'max_output_tokens': budget,
                                 'elapsed_ms': _elapsed_ms(attempt_started, monotonic),
                                 'outcome': outcome, 'commitment': commitment})

            try:
                summary = _fetch_summary(
                    provider, key, body, timeout, deadline, attempt_deadline,
                    monotonic, dispatched)
            except compaction_result.IncompleteSummary as exc:
                last_error = exc
                outcome = ('retry' if budget_index + 1 < len(budgets)
                           else 'fallback' if entry_index + 1 < len(entries)
                           else 'rejected')
                record(outcome, 'committed')
                if monotonic() >= deadline:
                    complete('deadline', summary_model=entry.slug)
                    raise TimeoutError(
                        'Compaction summarizer deadline exceeded') from exc
                continue
            except TimeoutError as exc:
                last_error = exc
                record('timeout', 'unknown' if dispatched else 'unsent')
                if dispatched:
                    complete('unknown', summary_model=entry.slug)
                    raise
                if monotonic() >= deadline:
                    complete('deadline', summary_model=entry.slug)
                    raise TimeoutError(
                        'Compaction summarizer deadline exceeded') from exc
                break
            except Exception:
                record('failed', 'unknown' if dispatched else 'unsent')
                complete('failed', summary_model=entry.slug)
                raise
            else:
                if monotonic() >= deadline:
                    complete('deadline', summary_model=entry.slug)
                    raise TimeoutError('Compaction summarizer deadline exceeded')
                record('completed', 'committed')
                complete('completed', summary, entry.slug)
                return summary

    complete('rejected' if isinstance(last_error, compaction_result.IncompleteSummary)
             else 'timeout', summary_model=entries[-1].slug)
    raise last_error
