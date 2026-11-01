"""Operator key provisioning (Plan 107 Stages 1-2, offline-capable).

Creates one per-person OpenRouter key with a monthly limit, assigns the
person's guardrail so the budget follows them across keys, and records an
audit row holding the key id, never the secret. Live run needs the
Management API key in the environment; tests inject fakes so no network,
no secret, and no real key ever touches a log or transcript.
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

KEYS_URL = 'https://openrouter.ai/api/v1/keys/'


def _request(url, method, token, payload=None, _urlopen=urllib.request.urlopen):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'Authorization': 'Bearer ' + token,
                                          'Content-Type': 'application/json'})
    with _urlopen(req, timeout=30) as response:
        return response.status, json.loads(response.read() or b'{}')


def create_key(email, machine, limit, management_key, _urlopen=urllib.request.urlopen):
    """POST one key named for the verified work email; returns (key_id, secret)."""
    status, body = _request(KEYS_URL, 'POST', management_key,
                            {'name': '%s/%s' % (email, machine), 'limit': limit,
                             'limit_reset': 'monthly'}, _urlopen)
    if status not in (200, 201):
        raise SystemExit('key creation failed with status %s' % status)
    data = body.get('data', body)
    try:
        return data['id'], data['key']
    except KeyError:
        raise SystemExit('key creation response missing id or secret')


def assign_guardrail(key_id, guardrail_id, management_key, _urlopen=urllib.request.urlopen):
    """Attach the person's guardrail; True on success."""
    status, _ = _request('https://openrouter.ai/api/v1/guardrails/%s' % guardrail_id,
                         'PUT', management_key, {'key_id': key_id}, _urlopen)
    return status in (200, 201, 204)


def provision(email, machine, limit, guardrail_id, install_token, codex_email,
              management_key, audit_path, _urlopen=urllib.request.urlopen):
    """Create, budget, and audit one key. Returns the secret once; never logs it."""
    key_id, secret = create_key(email, machine, limit, management_key, _urlopen)
    if guardrail_id and not assign_guardrail(key_id, guardrail_id, management_key, _urlopen):
        _request('%s%s' % (KEYS_URL, key_id), 'DELETE', management_key, None, _urlopen)
        raise SystemExit('guardrail assignment failed; unbudgeted key deleted')
    row = {'email': email, 'key_id': key_id, 'issued_at': int(time.time()),
           'install_token': install_token, 'codex_email': codex_email or ''}
    audit_path = Path(audit_path)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(row) + '\n')
    return secret


def revoke(key_id, management_key, _urlopen=urllib.request.urlopen):
    """Delete one key by id; True when it is gone."""
    status, _ = _request('%s%s' % (KEYS_URL, key_id), 'DELETE', management_key, None, _urlopen)
    return status in (200, 201, 204, 404)


def main(argv=None, _urlopen=urllib.request.urlopen):
    parser = argparse.ArgumentParser(description='Provision one per-person OpenRouter key.')
    parser.add_argument('--email', required=True, help='verified work email')
    parser.add_argument('--machine', required=True, help='machine label')
    parser.add_argument('--limit', type=float, required=True, help='spend limit')
    parser.add_argument('--guardrail', default='', help='guardrail id for the person')
    parser.add_argument('--install-token', default='', help='Plan 106 install token id')
    parser.add_argument('--codex-email', default='', help='Codex account email (reconciliation only)')
    parser.add_argument('--audit', required=True, help='audit log path (key ids, never secrets)')
    parser.add_argument('--revoke', default='', help='delete one key by id and exit')
    args = parser.parse_args(argv)
    management_key = os.environ.get('OPENROUTER_MANAGEMENT_KEY', '')
    if not management_key:
        raise SystemExit('set OPENROUTER_MANAGEMENT_KEY (Management API key, never a user key)')
    if args.revoke:
        ok = revoke(args.revoke, management_key, _urlopen)
        print('revoked' if ok else 'revoke failed')
        return 0 if ok else 1
    secret = provision(args.email, args.machine, args.limit, args.guardrail,
                       args.install_token, args.codex_email, management_key,
                       args.audit, _urlopen)
    # The secret goes to stdout once for the operator's direct machine write;
    # nothing else (no log, no audit row, no error text) may carry it.
    sys.stdout.write(secret + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
