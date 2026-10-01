"""Two synthetic Codex turns across an isolated router restart; requires --live."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_router import catalogue, provider_defs, router, subscription_discovery, transport
from tools.appserver_probe import AppServer, AGENT_HANDOFFS, codex_bin, scrub_env

MAX_CALLS, MAX_INPUT, TIMEOUT = 2, 128 * 1024, 120


class Budget:
    def __init__(self, send):
        self.send, self.calls = send, 0
        self.deadline = time.monotonic() + TIMEOUT
        self.lock = threading.Lock()

    def __call__(self, conn, prepared, metrics):
        remaining = self.deadline - time.monotonic()
        if (remaining <= 0 or prepared.provider != provider_defs.OPENAI.id
                or transport.request_bytes(prepared) > MAX_INPUT):
            raise ValueError('restart probe route, time or input budget')
        with self.lock:
            if self.calls >= MAX_CALLS:
                raise ValueError('restart probe call budget')
            self.calls += 1
        conn.timeout = min(conn.timeout or remaining, remaining)
        if conn.sock is not None:
            conn.sock.settimeout(conn.timeout)
        return self.send(conn, prepared, metrics)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--model', default='gpt-6.1-sol')
    parser.add_argument('--codex', default=codex_bin())
    args = parser.parse_args(argv)
    if not args.live:
        parser.error('requires --live; never runs in the unit suite')
    version = subprocess.run([args.codex, '--version'], check=True, capture_output=True,
                             text=True, timeout=10).stdout.strip()
    client_version = re.search(r'\d+(?:\.\d+)+(?:[-+][\w.-]+)?', version).group()
    auth_path = Path.home() / '.codex/auth.json'
    auth = json.loads(auth_path.read_text())['tokens']
    headers = {'Authorization': 'Bearer ' + auth['access_token']}
    if auth.get('account_id'):
        headers['ChatGPT-Account-Id'] = auth['account_id']
    rows = subscription_discovery.fetch_native(headers, client_version)
    row = next((row for row in rows if row['slug'] == args.model), None)
    if row is None or 'low' not in {level['effort'] for level in
                                   row.get('supported_reasoning_levels', [])}:
        parser.error('requested native model must be advertised with low effort')
    metadata = {**catalogue.subscription_stub(args.model), **row, 'prefer_websockets': False}
    budget = Budget(transport.post_with_phases)
    refreshes, served, outcomes = [], [], []
    fetch = subscription_discovery.fetch_native

    def discover(request_headers, request_version='', router_token=None):
        refreshes.append({'client_version': request_version,
                          'authorization_present': any(
                              k.lower() == 'authorization' for k in request_headers)})
        if len(refreshes) > MAX_CALLS:
            raise ValueError('restart probe discovery budget')
        return fetch(request_headers, request_version, router_token)

    def observe(event, **fields):
        if event in ('request_completed', 'request_failed', 'request_rejected'):
            outcomes.append({key: fields[key] for key in
                             ('status', 'code', 'error_type') if key in fields})
        if event == 'request_completed' and fields.get('path') == '/responses':
            served.append(fields.get('served_model', 'unverified'))

    server = client = None
    passed, error, error_hint = False, None, None
    temporary = tempfile.TemporaryDirectory(prefix='scg-restart-probe-')
    try:
        with patch.object(transport, 'post_with_phases', budget), \
                patch.object(subscription_discovery, 'fetch_native', discover), \
                patch.object(router, 'log_event', observe):
            tmp = temporary.name
            home = Path(tmp)
            auth_copy = home / 'auth.json'
            auth_copy.touch(mode=0o600)
            shutil.copyfile(auth_path, auth_copy)
            models = home / 'models.json'
            models.write_text(json.dumps({'models': [metadata]}))
            state = {'port': 0, 'token': secrets.token_hex(24),
                     'openai_mode': 'subscription', 'openai_models': []}
            server = router.Router(dict(state))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            state['port'] = server.server_port
            url = f'http://127.0.0.1:{state["port"]}/{state["token"]}/backend-api/codex'
            config = {'model_provider': 'openai', 'model_catalog_json': str(models),
                      'openai_base_url': url, 'project_doc_max_bytes': 0,
                      'developer_instructions': 'Synthetic check. Reply with the requested marker only.',
                      'approval_policy': 'never', 'sandbox_mode': 'read-only',
                      'web_search': 'disabled', 'features.apps': False,
                      'features.memories': False, 'features.shell_tool': False,
                      'features.shell_snapshot': False, 'features.multi_agent': False,
                      'features.code_mode': False}
            command = [args.codex, 'app-server', '--stdio', '-c', 'mcp_servers={}']
            for key, value in config.items():
                command += ['-c', key + '=' + json.dumps(value)]
            client = AppServer(command, tmp, scrub_env(os.environ, AGENT_HANDOFFS,
                {'CODEX_HOME': tmp}), stderr=subprocess.PIPE, rpc_timeout=20)
            client.rpc('initialize', {'clientInfo': {'name': 'scg-restart-probe', 'version': '1'},
                                    'capabilities': {'experimentalApi': True}})
            thread = client.rpc('thread/start', {'model': args.model, 'cwd': tmp,
                'approvalPolicy': 'never', 'sandbox': 'read-only'})['thread']['id']
            for index, marker in enumerate(('RESTART_FIRST_OK', 'RESTART_RESUMED_OK')):
                if index:
                    server.shutdown()
                    server.server_close()
                    server = router.Router(dict(state))
                    threading.Thread(target=server.serve_forever, daemon=True).start()
                client.turn(thread, 'Reply exactly ' + marker + '.',
                    timeout=max(1, budget.deadline - time.monotonic()), marker=marker,
                    payload={'model': args.model, 'effort': 'low'})
            passed = (budget.calls == MAX_CALLS and len(refreshes) == MAX_CALLS
                      and all(r['client_version'] == client_version for r in refreshes)
                      and served == [args.model, args.model])
    except Exception as exc:
        error = type(exc).__name__
        error_hint = next((hint for hint in ('max_output_tokens', 'stream disconnected',
                                            'budget', 'marker', 'Address already in use')
                           if hint.lower() in str(exc).lower()), None)
    finally:
        if client is not None:
            client.close()
        if server is not None:
            server.shutdown()
            server.server_close()
        temporary.cleanup()
    print(json.dumps({'passed': passed, 'client': version, 'requested_model': args.model,
                      'effort': 'low', 'served_models': served, 'upstream_calls': budget.calls,
                      'call_cap': MAX_CALLS, 'input_byte_cap': MAX_INPUT,
                      'external_cost_cap_usd': 0,
                      'discovery': refreshes, 'outcomes': outcomes,
                      'error_type': error, 'error_hint': error_hint}))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
