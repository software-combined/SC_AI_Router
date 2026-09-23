#!/usr/bin/env python3
"""Explicit metadata-only check of the combined picker through a real Codex client."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_router.router import Router
from ai_router.runtime import ROUTER_HOME
from ai_router.state import read_strict, path as state_path
from tools.appserver_probe import AppServer


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', required=True, help='Exact client executable to check.')
    parser.add_argument('--installed', action='store_true',
                        help='Check the configured router instead of an isolated candidate.')
    parser.add_argument('--expect', action='append', default=[], help='Required picker model id.')
    args = parser.parse_args(argv)
    codex_home = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
    config = tomllib.loads((codex_home / 'config.toml').read_text())
    if config.get('model_catalog_json'):
        raise SystemExit('Remove the static catalogue override before testing live discovery.')
    version = subprocess.run([args.codex, '--version'], check=True, capture_output=True,
                             text=True, timeout=10).stdout.strip()
    router = None
    command = [args.codex]
    if not args.installed:
        state = read_strict(state_path(ROUTER_HOME))
        state.update(port=0, token=secrets.token_hex(24))
        router = Router(state)
        threading.Thread(target=router.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{router.server_port}/{state["token"]}/backend-api/codex'
        command += ['-c', 'openai_base_url=' + json.dumps(url)]
    client = None
    try:
        # One model/list RPC, no inference; client refresh retries have a 5-second
        # deadline. Stderr is drained without recording URLs or credentials.
        client = AppServer(command + ['app-server'], str(Path(__file__).resolve().parents[1]),
                           dict(os.environ), stderr=subprocess.PIPE, rpc_timeout=20)
        client.rpc('initialize', {'clientInfo': {'name': 'scg-discovery-probe', 'version': '1'},
                                 'capabilities': {'experimentalApi': True}})
        rows = client.rpc('model/list', {'includeHidden': False, 'limit': 100}).get('data', [])
        ids = [row.get('model', row.get('id', '')) for row in rows]
        external = [slug for slug in ids if '/' in slug]
        subscription = [slug for slug in ids if '/' not in slug]
        missing = sorted(set(args.expect) - set(ids))
        fresh = router is None or bool(getattr(router, '_subscription_snapshots', {}))
        passed = bool(subscription and external and not missing and fresh)
        print(json.dumps({'client': version, 'target': 'installed' if args.installed else 'candidate',
                          'passed': passed, 'subscription_models': subscription,
                          'external_models': external, 'missing': missing, 'inference_calls': 0}))
        return 0 if passed else 1
    except Exception as exc:
        print(json.dumps({'passed': False, 'error_type': type(exc).__name__}))
        return 1
    finally:
        if client is not None:
            client.close()
        if router is not None:
            router.shutdown()
            router.server_close()


if __name__ == '__main__':
    raise SystemExit(main())
