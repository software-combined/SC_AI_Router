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

from . import provider_defs
from .registry import by_slug

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

    def __init__(self, slug=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.slug = slug
        self.process = None

    def __enter__(self):
        return self.boot()

    def __exit__(self, *exc):
        self.close()

    def boot(self):
        from .credentials import Credentials
        entry = by_slug(self.slug) if isinstance(self.slug, str) else None
        provider_id = entry.provider if entry is not None else provider_defs.DEFAULT_EXTERNAL
        state = {'port': _free_port(), 'token': secrets.token_urlsafe(32),
                 'openai_models': []}
        try:
            Credentials(state, self.home).check(provider_id)
        except (LookupError, PermissionError, ValueError, OSError) as exc:
            self.close()
            raise SystemExit(f'isolated probe has no '
                             f'{provider_defs.label_for(provider_id)} credential: {exc}')
        state_path = self.home / 'mixed-router-state.json'
        fd = os.open(state_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(state, indent=2) + '\n')
        catalog = self.home / 'candidate-catalogue.json'
        merged = subprocess.run(
            [sys.executable, '-m', 'ai_router.catalogue', '--merge', str(catalog)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120)
        if merged.returncode != 0:
            self.close()
            raise SystemExit('isolated probe could not merge its catalogue')
        self.state, self.catalog = state, catalog
        return self._spawn()

    def _spawn(self):
        self.process = subprocess.Popen(
            [sys.executable, '-m', 'ai_router'],
            env={**os.environ, 'ROUTER_HOME': str(self.home)}, cwd=str(ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not self._wait_healthy():
            self.close()
            raise SystemExit('isolated router failed to start; see '
                             f'{self.home / "logs" / "router.jsonl"}')
        return self

    def restart(self):
        """Stop and boot again on the same home, port, token and catalogue.

        Acceptance uses this between compactions: schemas and state must
        survive a router restart, not just a compacted thread.
        """
        self._stop_child()
        return self._spawn()

    def _stop_child(self):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=20)
            except subprocess.SubprocessError:
                self.process.kill()
            self.process = None

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
        self._stop_child()
        self.tmp.cleanup()


def legs_for(slug, row=None):
    """Probe legs the registry row implies: tool and stream always run.

    The image leg runs when the row's modalities include image; the
    compaction leg runs when the row declares a context window. Unknown
    slugs probe the base legs only. Pure: names what would run, bills
    nothing. Pass `row` - the raw models.json dict - when the slug is not
    yet in the import-time registry (the add path writes the row before
    probing it); a non-dict falls back to the registry lookup.
    """
    entry = row if row is not None else (
        by_slug(slug) if isinstance(slug, str) else None)
    legs = ['tool', 'stream']
    if entry is None:
        return legs
    modalities = (entry.get('modalities') if isinstance(entry, dict)
                  else entry.modalities) or ()
    context_window = (entry.get('context_window') if isinstance(entry, dict)
                      else entry.context_window) or 0
    if 'image' in modalities:
        legs.append('image')
    if context_window > 0:
        legs.append('compact')
    return legs


def run_probe(slug, scope, _run=subprocess.run, row=None, _mkdtemp=None):
    """Implied legs through the isolated router; True when all pass.

    The probe refuses router legs without --codex-home (never the live
    Codex home), so the candidate always gets a disposable client home.
    """
    home = (_mkdtemp(prefix='candidate-codex-home-') if _mkdtemp is not None
            else tempfile.mkdtemp(prefix='candidate-codex-home-'))
    cmd = [sys.executable, str(PROBE_TOOL), slug,
           '--router-state', str(scope.home / 'mixed-router-state.json'),
           '--catalog', str(scope.catalog),
           '--codex-home', home]
    legs = legs_for(slug, row)
    if 'image' in legs:
        cmd.append('--image')
    if 'compact' in legs:
        cmd.append('--compact')
    try:
        proc = _run(cmd, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return False
    # A later leg (image/compact) can fail after the base marker is printed,
    # so the exit status is part of the pass contract, not just the marker.
    return proc.returncode == 0 and ROUND_TRIP_MARKER in (proc.stdout or '')


def verify(slug, _scope=IsolatedRouter, _run_probe=run_probe, row=None):
    """Boot an isolated router for the candidate and probe it. True on pass."""
    with _scope(slug) as scope:
        return _run_probe(slug, scope, row=row)


def main(argv=None):
    """Print the legs a probe would run; bill only with --probe --confirm."""
    args = list(sys.argv[1:] if argv is None else argv)
    probe = '--probe' in args
    confirm = '--confirm' in args
    slugs = [a for a in args if not a.startswith('-')]
    if len(slugs) != 1:
        raise SystemExit('usage: python3.14 -m ai_router.candidate SLUG '
                         '[--probe --confirm]')
    slug = slugs[0]
    legs = legs_for(slug)
    if not (probe and confirm):
        print(json.dumps({'slug': slug, 'legs': legs, 'billed': False,
                          'note': 'rerun with --probe --confirm to bill the legs'}))
        return 0
    passed = verify(slug)
    print(json.dumps({'slug': slug, 'legs': legs,
                      'result': 'passed' if passed else 'failed'}))
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
