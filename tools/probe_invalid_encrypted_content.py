"""Bounded live probe for the subscription encrypted-content retry.

This sends one synthetic guardian-shaped request containing an unreadable
reasoning blob. The router should reject the first upstream attempt with
``invalid_encrypted_content``, strip the blob on one retry, and complete the
turn. The probe reports structural event names only; it never prints the
router token, request body, response body, or model output.

Usage:
    python3.14 tools/probe_invalid_encrypted_content.py --home ~/.codex/mixed-model-router
"""
import argparse
import http.client
import json
import secrets
import time
from compression import zstd
from pathlib import Path
from urllib.parse import quote


DEFAULT_HOME = Path.home() / '.codex' / 'mixed-model-router'
DEFAULT_MODEL = 'codex-auto-review'
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_LOG_BYTES = 2 * 1024 * 1024
LOG_WAIT_S = 2.0


def _tool(name):
    return {
        'type': 'function',
        'name': name,
        'description': 'Synthetic live-probe tool.',
        'parameters': {
            'type': 'object',
            'properties': {'value': {'type': 'string'}},
            'required': ['value'],
            'additionalProperties': False,
        },
        'strict': True,
    }


def synthetic_payload(model=DEFAULT_MODEL, nonce='offline'):
    """One bounded request; the blob is deliberately unreadable."""
    return {
        'model': model,
        'stream': False,
        'reasoning': {'effort': 'low'},
        'max_output_tokens': 16,
        'metadata': {'probe_id': nonce},
        'tools': [_tool('probe_echo'), _tool('probe_lookup'), _tool('probe_finish')],
        'input': [
            {'type': 'reasoning', 'id': 'rs_probe',
             'encrypted_content': 'invalid-probe-blob'},
            {'type': 'message', 'role': 'user',
             'content': [{'type': 'input_text', 'text': 'Reply with OK.'}]},
        ],
    }


def request_body(model=DEFAULT_MODEL, nonce='offline'):
    raw = json.dumps(synthetic_payload(model, nonce),
                     separators=(',', ':')).encode()
    return zstd.compress(raw)


def read_state(home):
    state = json.loads((Path(home) / 'mixed-router-state.json').read_text())
    if (not isinstance(state, dict) or not isinstance(state.get('port'), int)
            or not isinstance(state.get('token'), str) or not state['token']):
        raise ValueError('invalid router state')
    return state


def post_once(state, body, timeout):
    """Send exactly one loopback request and return its HTTP status."""
    path = '/%s/backend-api/codex/responses' % quote(state['token'], safe='')
    conn = http.client.HTTPConnection('127.0.0.1', state['port'], timeout=timeout)
    try:
        conn.request('POST', path, body=body, headers={
            'Content-Type': 'application/json',
            'Content-Encoding': 'zstd',
            'Accept': 'application/json',
        })
        response = conn.getresponse()
        if len(response.read(MAX_RESPONSE_BYTES + 1)) > MAX_RESPONSE_BYTES:
            raise ValueError('response too large')
        return response.status
    finally:
        conn.close()


def read_new_events(log_path, offset):
    with Path(log_path).open('rb') as stream:
        stream.seek(offset)
        raw = stream.read(MAX_LOG_BYTES + 1)
    if len(raw) > MAX_LOG_BYTES:
        raise ValueError('log window too large')
    events = []
    for line in raw.splitlines():
        if line.strip():
            event = json.loads(line)
            if isinstance(event, dict):
                events.append(event)
    return events


def repair_sequence(events, model, request_bytes):
    """Return (passed, structural labels, ambiguous) for one request window."""
    def find(start, name, **fields):
        for index in range(start, len(events)):
            event = events[index]
            if event.get('event') != name or event.get('model') != model:
                continue
            if all(event.get(key) == value for key, value in fields.items()):
                return index
        return None

    starts = [index for index, event in enumerate(events)
              if event.get('event') == 'request_started'
              and event.get('model') == model
              and event.get('request_bytes') == request_bytes]
    if len(starts) != 1:
        return False, ['ambiguous_request_started'] if starts else [], bool(starts)
    started = starts[0]
    rejected = (None if started is None else find(
        started + 1, 'upstream_rejected', request_bytes=request_bytes,
        status=400, code='invalid_encrypted_content'))
    retry_started = (None if rejected is None else find(
        rejected + 1, 'annotation_retry', request_bytes=request_bytes,
        repair='reasoning_blobs',
        outcome='started'))
    retry_accepted = (None if retry_started is None else find(
        retry_started + 1, 'annotation_retry', request_bytes=request_bytes,
        repair='reasoning_blobs',
        outcome='accepted', status=200))
    completed = (None if retry_accepted is None else find(
        retry_accepted + 1, 'request_completed', request_bytes=request_bytes,
        status=200))
    steps = (
        (started, 'request_started'),
        (rejected, 'upstream_rejected'),
        (retry_started, 'annotation_retry:started'),
        (retry_accepted, 'annotation_retry:accepted'),
        (completed, 'request_completed'),
    )
    labels = [label for index, label in steps if index is not None]
    return all(index is not None for index, _ in steps), labels, False


def wait_for_sequence(log_path, offset, model, request_bytes,
                      timeout=LOG_WAIT_S):
    deadline = time.monotonic() + timeout
    while True:
        result = repair_sequence(
            read_new_events(log_path, offset), model, request_bytes)
        if result[0] or result[2] or time.monotonic() >= deadline:
            return result
        time.sleep(0.05)


def probe(home=DEFAULT_HOME, model=DEFAULT_MODEL, timeout=60.0):
    state = read_state(home)
    body = request_body(model, secrets.token_hex(8))
    log_path = Path(home) / 'logs' / 'router.jsonl'
    offset = log_path.stat().st_size
    status = post_once(state, body, timeout)
    passed, labels, _ = wait_for_sequence(
        log_path, offset, model, len(body))
    return {
        'pass': bool(passed and status == 200),
        'model': model,
        'http_status': status,
        'request_bytes': len(body),
        'events': labels,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--home', type=Path, default=DEFAULT_HOME)
    parser.add_argument('--model', default=DEFAULT_MODEL)
    parser.add_argument('--timeout', type=float, default=60.0)
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 120:
        raise SystemExit('timeout must be greater than 0 and at most 120 seconds')
    try:
        report = probe(args.home, args.model, args.timeout)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report = {'pass': False, 'error': type(exc).__name__}
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get('pass') else 1


if __name__ == '__main__':
    raise SystemExit(main())
