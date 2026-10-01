"""Bounded real-client onboarding; invoked only by ai_router.candidate."""
import argparse
from datetime import datetime, timezone
from functools import partial
import json
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_router import candidate_evidence as evidence, inspect_requests, provider_defs, registry, transport
from ai_router.atomic_write import replace_text
from ai_router.clients.registry import CLIENTS
from tools import appserver_probe, probe_claude_code

MAX_CALLS, MAX_INPUT, MAX_OUTPUT = evidence.MAX_PROBE_CALLS, 512 * 1024, 65536
CODEX = appserver_probe.codex_bin()


class Budget:
    """One probe budget for request attempts and compaction helper attempts."""
    def __init__(self, home, send, *, max_output=MAX_OUTPUT):
        if type(max_output) is not int or not 0 < max_output <= MAX_OUTPUT:
            raise ValueError('candidate probe output budget')
        self.home, self.send, self.calls = home, send, 0
        self.max_output = max_output
        self.lock = threading.Lock()

    def __call__(self, conn, prepared, metrics):
        self.reserve(prepared)
        return self.send(conn, prepared, metrics)

    def reserve(self, prepared):
        if not provider_defs.is_external(prepared.provider) or transport.request_bytes(prepared) > MAX_INPUT:
            raise ValueError('candidate probe route or input budget')
        payload = json.loads(prepared.body)
        output = payload.get('max_output_tokens', payload.get('max_tokens'))
        if type(output) is not int or not 0 < output <= self.max_output:
            raise ValueError('candidate probe output budget')
        with self.lock:
            if self.calls >= MAX_CALLS:
                raise ValueError('candidate probe call budget')
            self.calls += 1
            replace_text(self.home / 'probe-calls', str(self.calls))

    def summary(self, send, provider, key, body, *args, **kwargs):
        prepared = transport.Prepared(provider.host, '', {}, json.dumps(body).encode(),
                                      {}, provider.defn.id)
        self.reserve(prepared)
        return send(provider, key, body, *args, **kwargs)


def call_count(home):
    try:
        return int((home / 'probe-calls').read_text())
    except FileNotFoundError:
        return 0


def serve(home, max_output=MAX_OUTPUT):
    # This isolated process deliberately omits background catalogue refresh.
    # The runtime handler, preparation, attempt ownership and credentials are real.
    from ai_router.router import Router
    from ai_router.runtime import configure_logging, load_state
    from ai_router import availability, compaction_summary
    configure_logging()
    budget = Budget(home, transport.post_with_phases, max_output=max_output)
    transport.post_with_phases = budget
    compaction_summary._fetch_summary = partial(budget.summary, compaction_summary._fetch_summary)
    server = Router(load_state())
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(
        target=server.shutdown, daemon=True).start())
    try:
        # Compaction requires the same key-filtered permissions as production.
        # This one metadata read cannot rewrite the candidate capability rows.
        availability.refresh(provider_defs.region_host(provider_defs.DEFAULT_EXTERNAL, 'global'),
                             server.credentials.key_for(), home)
        server.serve_forever()
    finally:
        server.server_close()


def version(binary):
    if not binary:
        return None
    try:
        done = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=10)
        found = re.search(r'\d+(?:\.\d+)+(?:[-+][A-Za-z0-9.]+)?', done.stdout)
        return found.group() if done.returncode == 0 and found else None
    except (OSError, subprocess.SubprocessError):
        return None


def codex(row, home, catalog):
    with tempfile.TemporaryDirectory(prefix='candidate-codex-home-') as folder:
        cmd = [sys.executable, str(ROOT / 'tools/probe_codex_runtime.py'), row.slug,
               '--router-state', str(home / 'mixed-router-state.json'),
               '--catalog', str(catalog), '--codex-home', folder,
               '--effort', row.default_reasoning]
        if 'image' in row.modalities and not row.drop_images:
            cmd.append('--image')
        if row.context_window > 0:
            cmd.append('--compact')
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            return done.returncode == 0 and '"desktop_runtime_tool_round_trip": "passed"' in done.stdout
        except (OSError, subprocess.SubprocessError):
            return False


def attempts(home, protocol):
    return [attempt for request in inspect_requests.recent(home, limit=100)
            for attempt in request['attempt_evidence'] if attempt['protocol'] == protocol]


def probe(row, home, catalog):
    record = evidence.binding(row)
    checked = subprocess.run(
        [sys.executable, '-m', 'unittest', 'tests.test_model_route_conformance'],
        cwd=ROOT, capture_output=True, timeout=120)
    if checked.returncode:
        return record
    for client in CLIENTS:
        if not provider_defs.get(row.provider).serves(client.protocol):
            continue
        before = attempts(home, client.protocol)
        before_calls = call_count(home)
        client_version = version(CODEX if client.id == 'codex' else probe_claude_code.CLAUDE_BIN)
        passed = False
        if client_version and client.id == 'codex':
            passed = codex(row, home, catalog)
        elif client_version:
            result = probe_claude_code.probe(home, row.slug, read_count=2,
                effort=None if row.default_reasoning == 'none' else row.default_reasoning,
                max_budget_usd=0.25, expected_model=row.upstream_id or row.slug)
            passed = result['pass']
        # The client can exit just before the router's final ledger flush.
        time.sleep(0.1)
        seen = attempts(home, client.protocol)
        seen = seen[:max(0, len(seen) - len(before))]
        target = [a for a in seen if a['resolved_model'] == row.slug]
        reports = lambda name: [report for a in target for report in a[name + '_reports']]
        record['routes'].append({'protocol': client.protocol, 'client': client.id,
            'client_version': client_version or 'unverified',
            'requested_effort': row.default_reasoning,
            'served_models': reports('model'), 'served_efforts': reports('effort'),
            'calls': call_count(home) - before_calls, 'conformance': 'pass',
            'result': 'pass' if passed and target and client_version else 'fail'})
    if evidence.runtime_fingerprint() != record['runtime_fingerprint']:
        for route in record['routes']:
            route['result'] = 'fail'
    record['observed_at'] = datetime.now(timezone.utc).isoformat()
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--max-output', type=int, default=MAX_OUTPUT)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--catalog', type=Path)
    parser.add_argument('--model')
    args = parser.parse_args(argv)
    if args.serve:
        serve(args.home, args.max_output)
        return 0
    row = registry.by_slug(args.model)
    if row is None:
        parser.error('candidate is not in the registry')
    record = probe(row, args.home, args.catalog)
    print(json.dumps(record))
    return 1 if evidence.problems(row, record) else 0


if __name__ == '__main__':
    raise SystemExit(main())
