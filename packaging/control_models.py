"""Authenticated model downloads belong to the updater, outside inference.

Only a checksum from an accepted signed feed can replace the local cache.
The serving router reads that cache without acquiring Microsoft credentials.
"""
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ORIGIN = 'https://dist.softwarecombined.com/'
INTERVAL_S = 3600


def _atomic():
    spec = importlib.util.spec_from_file_location(
        'router_control_models_atomic', Path(__file__).with_name('atomic_write.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def accept(home, document):
    """Caller has checked the feed signature and serial before accepting it."""
    url, digest = document.get('models_url'), document.get('models_sha256')
    if (not isinstance(url, str) or not url.startswith(ORIGIN) or
            '?' in url or '#' in url or not isinstance(digest, str) or
            not re.fullmatch('[0-9a-f]{64}', digest)):
        return False
    _atomic().replace_json(Path(home) / 'controlled-models.json',
                            {'url': url, 'sha256': digest})
    return True


def refresh(home, fetch, run=subprocess.run, now=None):
    home = Path(home)
    if not (home / 'download-auth.json').is_file():
        return False
    now = time.time() if now is None else now
    try:
        checked = float((home / 'controlled-models-check').read_text())
    except (OSError, ValueError):
        checked = 0
    if now - checked < INTERVAL_S:
        return False
    try:
        config = json.loads((home / 'controlled-models.json').read_text())
        url, digest = config['url'], config['sha256']
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if not isinstance(url, str) or not url.startswith(ORIGIN):
        return False
    try:
        body = fetch(url)
        if hashlib.sha256(body).hexdigest() != digest:
            return False
        result = run([sys.executable, '-c',
                      'import sys; from ai_router.model_refresh import validate; validate(sys.stdin.read())'],
                     input=body.decode('utf-8'), capture_output=True, text=True,
                     cwd=str(Path(__file__).resolve().parents[1]), timeout=30)
        if result.returncode:
            return False
    except (OSError, UnicodeError, subprocess.SubprocessError):
        # A model object cannot strand a newer release that repairs its source.
        # SignInRequired remains typed and reaches the updater's renewal path.
        return False
    atomic = _atomic()
    atomic.replace_text(home / 'models-cache.json', body.decode('utf-8'))
    atomic.replace_text(home / 'controlled-models-check', str(now) + '\n')
    return True
