"""Hourly model-data refresh (Plan 099 residual, offline-testable).

Wiring note: start() has no caller yet. The router keeps serving the
bundled registry until the first authenticated-update qualification wires
the thread behind models_url (Plan 099 Step 3); landing the module and its
contract first keeps that step to one call site.


Polls models_url with If-None-Match, validates through registry.load, and
swaps the live registry atomically on success; any failure keeps the current
registry and logs models_refresh_failed with the exception class name. The
bundled models.json is always first; a valid models-cache.json overlays it
at startup. No network in tests: fetch is injectable.
"""
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from .atomic_write import replace_text

from . import registry

LOG = logging.getLogger('codex_router')
CACHE_NAME = 'models-cache.json'
REFRESH_INTERVAL_S = 3600
REFRESH_JITTER_S = 300


def validate(text):
    """registry.load with the refresh-specific guards: capped list, slugs shaped."""
    models = registry.load(text)
    if len(models) > 200:
        raise SystemExit('model refresh: more than 200 models')
    for model in models:
        for part in model.slug.split('/'):
            if not part or not all(c.isalnum() or c in '._-:~' for c in part):
                raise SystemExit('model refresh: bad slug %r' % model.slug)
    return models


def _read(path):
    try:
        return Path(path).read_text()
    except OSError:
        return None


def cached_models(home):
    """Validated cache rows, or None when absent or invalid."""
    text = _read(Path(home) / CACHE_NAME)
    if not text:
        return None
    try:
        return validate(text)
    except SystemExit:
        return None


def fetch(url, etag, _urlopen=urllib.request.urlopen):
    """GET with ETag revalidation. Returns (status, body, etag)."""
    req = urllib.request.Request(url, headers={'If-None-Match': etag} if etag else {})
    try:
        with _urlopen(req, timeout=30) as response:
            return response.status, response.read(), response.headers.get('ETag', etag)
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return 304, b'', etag
        raise


def poll_once(models_url, home, etag, _urlopen=urllib.request.urlopen):
    """One refresh pass. Returns (models_or_None, etag); never raises."""
    try:
        status, body, etag = fetch(models_url, etag, _urlopen)
    except Exception as exc:  # noqa: BLE001 - any fetch failure keeps current
        LOG.info(json.dumps({'event': 'models_refresh_failed', 'reason': exc.__class__.__name__}))
        return None, etag
    if status == 304:
        return None, etag
    try:
        models = validate(body.decode())
    except (SystemExit, ValueError, UnicodeDecodeError) as exc:
        LOG.info(json.dumps({'event': 'models_refresh_failed', 'reason': exc.__class__.__name__}))
        return None, etag
    try:
        replace_text(Path(home) / CACHE_NAME, body.decode())
    except OSError as exc:
        LOG.info(json.dumps({'event': 'models_refresh_failed', 'reason': exc.__class__.__name__}))
        return None, etag
    return models, etag


def apply(models):
    """Swap the live registry and rebuild import-time derived maps.

    capabilities.* and claude.models_listing snapshot MODELS at import; a swap
    without a rebuild would serve new slugs with stale gates, so the swap and
    the rebuild travel together in capabilities.rebuild (Plan 125).
    """
    registry.MODELS = models
    registry.BY_SLUG = {m.slug: m for m in models}
    from . import capabilities
    capabilities.rebuild(models)


def start(models_url, home, _urlopen=urllib.request.urlopen):
    """Overlay cache at boot, then refresh hourly in a daemon thread."""
    if not models_url:
        return None
    cached = cached_models(home)
    if cached is not None:
        apply(cached)
    etag_path = Path(home) / 'models-etag'
    try:
        etag = etag_path.read_text().strip() or None
    except OSError:
        etag = None

    def loop():
        nonlocal etag
        import random
        while True:
            time.sleep(REFRESH_INTERVAL_S + random.uniform(0, REFRESH_JITTER_S))
            models, etag = poll_once(models_url, home, etag, _urlopen)
            if models is not None:
                apply(models)
            if etag:
                try:
                    replace_text(etag_path, etag + '\n')
                except OSError:
                    pass

    thread = threading.Thread(target=loop, daemon=True, name='model-refresh')
    thread.start()
    return thread
