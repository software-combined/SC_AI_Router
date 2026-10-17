"""Hourly model-data refresh (Plan 099 residual, offline-testable).

The router starts the thread at boot (`__main__.py`) behind the feed's
models_url (Plan 099 Step 3).

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
from dataclasses import replace
from pathlib import Path
from .atomic_write import replace_text

from . import catalogue, model_prompt, registry

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
        for identifier in (model.slug, registry.upstream_id_for(model)):
            for part in identifier.split('/'):
                if not part or not all(c.isalnum() or c in '._-:~' for c in part):
                    raise SystemExit('model refresh: bad slug %r' % identifier)
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


# The import-time roster. apply() swaps registry.MODELS, so an overlay must
# be measured against the bundle rather than against whatever a previous
# apply left there, or one stale roster could hide the rows this release
# pinned from every later one.
BUNDLED = registry.MODELS


def _pin_release(row, bundled_by_slug):
    """Keep what this release pinned when a feed row names the same slug.

    The feed may add a row the bundle has never seen. It must not shrink or
    widen the effort list this release pinned, or a restart loads the older
    gate and refuses an effort the picker just offered. The release also owns
    its compaction limit and measured wire shapes; an older cache must not
    remove them or broaden the measurement to another model.
    """
    pinned = bundled_by_slug.get(row.slug)
    if pinned is None:
        return row
    if row.slug in catalogue.RETIRED_SLUGS:
        # Saved-session compatibility targets must not revert to an old cache.
        return pinned
    same_target = ((row.provider, registry.upstream_id_for(row)) ==
                   (pinned.provider, registry.upstream_id_for(pinned)))
    return replace(row, reasoning=pinned.reasoning,
                   default_reasoning=pinned.default_reasoning,
                   auto_compact_token_limit=pinned.auto_compact_token_limit,
                   observed_item_types=pinned.observed_item_types if same_target else ())


def overlay(bundled, cached):
    """Bundled rows first: the cache updates and extends, never rewrites.

    A cache written by an older release still names the id that release
    pinned and knows nothing about a row pinned since, so applying it whole
    resurrects a retired slug and hides the current one: the picker then
    offers a row the router refuses. The bundle stays authoritative for its
    own rows, the cache carries live data forward and may add rows the
    bundle has never seen, and a slug the bundle retired stays retired.
    A feed row for a bundled slug keeps that release's reasoning list and
    compaction limit and measured wire shapes.
    """
    retired = catalogue.RETIRED_SLUGS
    bundled_by_slug = {row.slug: row for row in bundled}
    merged = [_pin_release(row, bundled_by_slug) for row in cached
              if row.slug in bundled_by_slug or row.slug not in retired]
    known = {row.slug for row in merged}
    merged.extend(row for row in bundled if row.slug not in known)
    return tuple(merged)


def apply_fetched(models):
    """Apply one cached or fetched roster through the bundle-first overlay.

    Both paths land here: the boot cache and the hourly payload can each be
    written by a different release than the bundle being served, so neither
    may retire a pinned row or restore a retired one on its own.
    """
    apply(overlay(BUNDLED, models))


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
    # catalogue reads its own import-time snapshot for the picker merge and
    # the prompt's visible set, so it belongs to the same swap (Plan 125).
    catalogue.MODELS = models
    from . import capabilities
    capabilities.rebuild(models)


def check_pending(home):
    """Keep the new-model snapshot current; never disturb the refresh.

    Plan 135: the offer itself belongs to the updater's notify path, which
    queries the running router over loopback. This call keeps the seen-set
    honest, so a model that arrives through the refresh reads there as a
    difference instead of being seeded away silently by the first query.
    Any failure is ignored: the refresh outcome must not change.
    """
    try:
        model_prompt.pending(home)
    except Exception:
        pass


def start(models_url, home, _urlopen=urllib.request.urlopen):
    """Overlay cache at boot, then refresh hourly in a daemon thread."""
    if not models_url:
        return None
    cached = cached_models(home)
    if cached is not None:
        apply_fetched(cached)
        check_pending(home)
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
            if (Path(home) / 'download-auth.json').exists():
                # Download credentials belong to the independent updater.
                # A signed-feed checksum protects its cache; failure retains it.
                models = cached_models(home)
                if models is not None:
                    apply_fetched(models)
                    check_pending(home)
                continue
            models, etag = poll_once(models_url, home, etag, _urlopen)
            if models is not None:
                apply_fetched(models)
                check_pending(home)
            if etag:
                try:
                    replace_text(etag_path, etag + '\n')
                except OSError:
                    pass

    thread = threading.Thread(target=loop, daemon=True, name='model-refresh')
    thread.start()
    return thread
