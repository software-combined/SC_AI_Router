"""Verify a registry candidate through an isolated router (brief defect 9).

`models add --probe` used to probe before the candidate was routable: the
installed router only knows released rows, so the round trip always failed.
The preview-activate-verify-promote sequence instead boots a throwaway router
from the working tree (which already holds the preview row) with its own
home, port, token and picker catalogue, probes it with the desktop harness,
then tears it down. Billing and the desktop app make this owner-gated; with
no credential it fails closed before spending anything.
"""
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE_TOOL = ROOT / 'tools' / 'probe_codex_runtime.py'
ROUND_TRIP_MARKER = '"desktop_runtime_tool_round_trip": "passed"'
START_TIMEOUT = 60


def _free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class IsolatedRouter:
    """Throwaway router plus catalogue; close() always tears it down."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.process = None

    def __enter__(self):
        return self.boot()

    def __exit__(self, *exc):
        self.close()

    def boot(self):
        from .credentials import Credentials
        state = {'port': _free_port(), 'token': secrets.token_urlsafe(32),
                 'openai_models': []}
        try:
            Credentials(state, self.home).check()
        except (LookupError, PermissionError, ValueError, OSError) as exc:
            self.close()
            raise SystemExit(f'isolated probe has no OpenRouter credential: {exc}')
        state_path = self.home / 'mixed-router-state.json'
        fd = os.open(state_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(state, indent=2) + '\n')
        catalog = self.home / 'candidate-catalogue.json'
        merged = subprocess.run(
            [sys.executable, '-m', 'codex_router.catalogue', '--merge', str(catalog)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120)
        if merged.returncode != 0:
            self.close()
            raise SystemExit('isolated probe could not merge its catalogue')
        self.process = subprocess.Popen(
            [sys.executable, '-m', 'codex_router'],
            env={**os.environ, 'ROUTER_HOME': str(self.home)}, cwd=str(ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.state, self.catalog = state, catalog
        if not self._wait_healthy():
            self.close()
            raise SystemExit('isolated router failed to start; see '
                             f'{self.home / "logs" / "router.jsonl"}')
        return self

    def _wait_healthy(self):
        url = f"http://127.0.0.1:{self.state['port']}/{self.state['token']}/health"
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if response.status == 200 and json.load(response).get('status') == 'ok':
                        return True
            except (OSError, ValueError):
                pass
            time.sleep(0.5)
        return False

    def close(self):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=20)
            except subprocess.SubprocessError:
                self.process.kill()
            self.process = None
        self.tmp.cleanup()


def run_probe(slug, scope, _run=subprocess.run):
    """Desktop tool round trip through the isolated router; True on pass."""
    cmd = [sys.executable, str(PROBE_TOOL), slug,
           '--router-state', str(scope.home / 'mixed-router-state.json'),
           '--catalog', str(scope.catalog)]
    try:
        proc = _run(cmd, capture_output=True, text=True, timeout=150)
    except (OSError, subprocess.SubprocessError):
        return False
    return ROUND_TRIP_MARKER in (proc.stdout or '')


def verify(slug, _scope=IsolatedRouter, _run_probe=run_probe):
    """Boot an isolated router for the candidate and probe it. True on pass."""
    with _scope() as scope:
        return _run_probe(slug, scope)
