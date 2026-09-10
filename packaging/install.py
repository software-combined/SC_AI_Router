#!/usr/bin/env python3
"""Install the Codex model router. Runs on Python 3.9+; finds 3.14 for the router itself.

Shared launchd/plist/feed helpers live in packaging/service.py. This
module owns first install, explicit upgrade, rollback and uninstall only.
"""
import argparse
import hashlib
import io
import json
import os
import runpy
import secrets
import subprocess
import time
import webbrowser
import shutil
import sys
import tarfile
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import importlib.util
_spec = importlib.util.spec_from_file_location(
    'packaging.service',
    Path(__file__).resolve().parent / 'service.py')
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)
_plat_spec = importlib.util.spec_from_file_location(
    'router_platforms', Path(__file__).resolve().parent / 'platforms' / '__init__.py')
_platforms = importlib.util.module_from_spec(_plat_spec)
_plat_spec.loader.exec_module(_platforms)
_cfg_spec = importlib.util.spec_from_file_location(
    'router_codex_config', Path(__file__).resolve().parent / 'codex_config.py')
_codex_config = importlib.util.module_from_spec(_cfg_spec)
_cfg_spec.loader.exec_module(_codex_config)
_claude_spec = importlib.util.spec_from_file_location(
    'router_claude_config', Path(__file__).resolve().parent / 'claude_config.py')
_claude_config = importlib.util.module_from_spec(_claude_spec)
_claude_spec.loader.exec_module(_claude_config)
_desktop_spec = importlib.util.spec_from_file_location(
    'router_claude_desktop_config', Path(__file__).resolve().parent / 'claude_desktop_config.py')
_desktop_config = importlib.util.module_from_spec(_desktop_spec)
_desktop_spec.loader.exec_module(_desktop_config)
_diag_spec = importlib.util.spec_from_file_location(
    'router_diagnostics', Path(__file__).resolve().parent / 'diagnostics.py')
_diag = importlib.util.module_from_spec(_diag_spec)
_diag_spec.loader.exec_module(_diag)
_linux = _platforms._linux_mod().systemd
_upd_spec = importlib.util.spec_from_file_location(
    'router_updater', Path(__file__).resolve().parent / 'updater.py')
_updater = importlib.util.module_from_spec(_upd_spec)
_upd_spec.loader.exec_module(_updater)
# One shared service module: tests patch install_mod._svc attrs and the
# updater must see the same object. Bound once at load; _sync_seams keeps
# the function seams fresh per call.
_updater.bind(svc=_svc)
PLATFORM = sys.platform
# Re-exported for tests (installed bundles have no packaging/ package).
# _patch_attrs(test, run/health/wait_*/...) patches install_mod attrs; the
# call sites below read them via _svc so swaps take effect. Immutable values
# copy directly.
FEED_URL = _svc.FEED_URL
MIN_PYTHON = _svc.MIN_PYTHON
LABEL = _svc.LABEL
UPDATE_LABEL = _svc.UPDATE_LABEL
DEFAULT_OPENAI_MODELS = _svc.DEFAULT_OPENAI_MODELS
channel_feed = _svc.channel_feed
check_serial = _svc.check_serial
ensure_state = _svc.ensure_state
install_lock = _svc.install_lock
_write_state = _svc._write_state
fetch = _svc.fetch
fetch_feed = _svc.fetch_feed
feed_serial = _svc.feed_serial
github_route_prefix = _svc.RELEASES_PREFIX
find_python = _svc.find_python
install_launcher = _svc.install_launcher
main_plist_needs_reload = _svc.main_plist_needs_reload
same_interpreter = _svc.same_interpreter
ensure_updater = _svc.ensure_updater
loaded_updater_release = _svc.loaded_updater_release
_update_failures = _svc.update_failures
_record_update_failure = _svc.record_update_failure
_clear_update_failures = _svc.clear_update_failures
reload_main_service = _svc.reload_main_service
render_plist = _svc.render_plist
render_update_plist = _svc.render_update_plist
restart_service = _svc.restart_service
safe_extract = _svc.safe_extract
swap_current = _svc.swap_current
current_release_dir = _svc.current_release_dir
current_version = _svc.current_version
write_plist = _svc.write_plist
# Patchable seams: tests override these on install_mod via _patch_attrs.
run = _svc.run
health = _svc.health
wait_version = _svc.wait_version
ensure_serving = _svc.ensure_serving


SUPPORTED_PLATFORMS = ('darwin', 'linux', 'win32')


def require_supported_platform():
    if PLATFORM not in SUPPORTED_PLATFORMS:
        raise SystemExit(
            f'Platform {PLATFORM} is not supported by this installer yet; '
            'no files were changed.')


def platform_backend():
    """Backend for this platform, or None when unsupported.

    None no longer means macOS: every caller must refuse it explicitly.
    Tests drive other platforms by patching PLATFORM before calling in.
    """
    return _platforms.select(PLATFORM, _svc, run)


def restart_router(home):
    platform_backend().restart(home)


def stop_router(home):
    platform_backend().stop(home)


def verify_sha256(data, want):
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise SystemExit('bundle checksum mismatch')
    return True


def newer(a, b):
    return tuple(int(x) for x in a.split('.')) > tuple(int(x) for x in b.split('.'))


def check_manifest(release_dir, manifest):
    for name, want in manifest['files'].items():
        got = hashlib.sha256((release_dir / name).read_bytes()).hexdigest()
        if got != want:
            raise SystemExit('bundle manifest mismatch: ' + name)


def check_identity(version, manifest_doc, release_dir):
    """Fail closed when feed, manifest and bundled marker disagree.

    The updater waits on the feed version and /health reports the manifest
    version, so any mismatch strands the install in a failed-health loop.
    """
    manifest_version = manifest_doc.get('version')
    try:
        marker = (release_dir / 'packaging' / 'VERSION').read_text().strip()
    except OSError:
        marker = None
    if manifest_version != version or marker != version:
        raise SystemExit(
            f'release identity mismatch: feed={version} '
            f'manifest={manifest_version} marker={marker}')


def self_test(python, release_dir):
    # Bundle smoke: the runtime import closure must load from the extraction.
    # Full discover cannot run here: repo tests reference files outside the bundle.
    result = run([python, '-c',
                       'from ai_router import catalogue, registry; assert registry.MODELS'],
                      cwd=str(release_dir), capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise SystemExit('bundle self-test failed')


def _clear_current(home):
    current = home / 'current'
    try:
        if current.is_symlink() or current.is_file():
            current.unlink()
    except OSError:
        pass


def ensure_credentials(home, state, env=None):
    env = os.environ if env is None else env
    if env.get('OPENROUTER_API_KEY', '').strip():
        return
    if (home / 'openrouter.key').exists():
        return
    if state.get('opencode_auth') and Path(state['opencode_auth']).exists():
        return
    key_file = home / 'openrouter.key'
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        platform_backend().protect_secret(key_file)
    except SystemExit:
        try:
            key_file.unlink()
        except OSError:
            pass
        raise
    print(f'Paste your OpenRouter key into {key_file} (owner-only file) and re-run the installer')
    raise SystemExit(3)


def install_bundle(home, version, tarball, manifest_doc, python):
    releases = home / 'releases'
    releases.mkdir(parents=True, exist_ok=True)
    partial = releases / (version + '.partial')
    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir()
    safe_extract(tarball, partial)
    try:
        check_manifest(partial, manifest_doc)
        check_identity(version, manifest_doc, partial)
        self_test(python, partial)
        write_catalogue(home, partial, python)
    except (SystemExit, OSError):
        shutil.rmtree(partial, ignore_errors=True)
        raise
    final = releases / version
    if final.exists():
        shutil.rmtree(final)
    partial.rename(final)
    install_launcher(home, final)
    previous = swap_current(home, final)
    return previous


def write_catalogue(home, release_dir, python):
    # Seed the picker file the config block points at; refresh owns it after.
    result = run([python, '-m', 'ai_router.catalogue', '--merge', str(home / 'mixed-models.json')],
                      cwd=str(release_dir), capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit('catalogue merge failed')


_preserve_picker_selection = _codex_config.preserve_picker_selection
replace_config_block = _codex_config.replace_config_block


def _restore_owned_config(home):
    """Detach an active client via the single owned remover path.

    Runs the matching tools/disable.py with ROUTER_RESTORE_ONLY=1: exact
    owned-block plus guidance restore with atomic temp and concurrent-edit
    checks. The machine result decides; success text alone never passes.
    """
    disable = Path(__file__).resolve().parents[1] / 'tools' / 'disable.py'
    result = run([sys.executable, str(disable)], capture_output=True, text=True,
                 env={**os.environ, 'ROUTER_HOME': str(home),
                      'ROUTER_RESTORE_ONLY': '1'})
    print((result.stdout or '')[-2000:])
    if result.returncode != 0:
        print((result.stderr or '')[-2000:])
        raise SystemExit('configuration restore failed; refusing the client change')
    # The remover restores files but keeps the receipt; a detached client
    # must not leave a claim to settings it no longer owns.
    _codex_config.drop_client(home, 'codex')


def do_rollback(args):
    """Point current at a previously installed release and verify it serves.
    Only releases still present under home/releases can be restored; the feed
    carries the latest bundle only, so there is nothing to download a
    rollback from. The feed serial is never touched.
    """
    _sync_seams()
    home = Path(args.home).expanduser()
    if args.dry_run:
        print(f'would roll back to {args.version} under {home}')
        return 0
    platform_backend().check(home)
    target = home / 'releases' / args.version
    if not target.is_dir() or not (target / 'packaging' / 'VERSION').exists():
        raise SystemExit(f'version {args.version} is not installed under {home}')
    current = current_version(home)
    if current == args.version:
        print(f'up to date {current}')
        return 0
    try:
        state = json.loads((home / 'mixed-router-state.json').read_text())
    except (OSError, ValueError):
        raise SystemExit(f'router state is missing or unreadable under {home}')
    previous = swap_current(home, target)
    restart_router(home)
    if not wait_version(state, args.version):
        if previous is not None:
            swap_current(home, home / 'releases' / previous)
            print(f'rollback to {args.version} failed health check; restored {previous}')
        else:
            _clear_current(home)
            print(f'rollback to {args.version} failed health check; no previous release')
        restart_router(home)
        raise SystemExit(1)
    print(f'rolled back to {args.version}; health ok; restart Codex to load the router')
    return 0


def _sync_seams():
    """Mirror _patch_attrs swaps from install_mod onto _svc call sites."""
    global run, health, wait_version, ensure_serving
    run, health, wait_version, ensure_serving = (
        _svc.run, _svc.health, _svc.wait_version, _svc.ensure_serving)
    _updater.bind(svc=_svc, newer=newer, verify_sha256=verify_sha256,
                  sync_seams=_sync_seams)
    _diag.bind(find_python=find_python, health=health,
               current_version=current_version, feed_url=FEED_URL,
               route_prefix=github_route_prefix, codex_config=_codex_config)


def do_install(args, _fetch=fetch, _run=None):
    if _run is not None:
        _svc.run = _run
    _sync_seams()
    if args.version:
        return do_rollback(args)
    home = Path(args.home).expanduser()
    python = find_python(args.python)
    if python is None:
        if args.install_python and sys.platform == 'darwin' and not args.dry_run:
            run(['brew', 'install', 'python@3.14'], check=True)
            python = find_python(args.python)
        if python is None:
            remedy = ('install Python 3.14 from python.org (py -V:3.14) or pass --python'
                      if PLATFORM == 'win32' else 'brew install python@3.14')
            print(f'No Python 3.14 found: {remedy}')
            raise SystemExit(2)
    feed = args.feed or channel_feed(home)
    latest = json.loads(_fetch(feed).decode())
    serial = check_serial(home, latest, pinned=bool(args.feed))
    if not newer(latest['version'], current_version(home)):
        print(f"up to date {current_version(home)}")
        return 0
    if args.dry_run:
        print(f'would fetch {feed}; interpreter {python}')
        print('would verify, unpack, self-test, swap current, restart, write config')
        return 0
    backend = platform_backend()
    backend.check(home)
    tarball = _fetch(latest['url'])
    if latest.get('sha256'):
        verify_sha256(tarball, latest['sha256'])
    manifest_doc = {'files': {}}
    with tarfile.open(fileobj=io.BytesIO(tarball), mode='r') as tar:
        try:
            manifest_doc = json.loads(tar.extractfile('MANIFEST.json').read())
        except KeyError:
            raise SystemExit('bundle has no MANIFEST.json')
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Plan 057 Stage 2: harden the home before any token or key is minted
    # inside it (never widen-then-narrow); POSIX no-op, mode 0700 owns it.
    backend.protect_secret(home)
    (home / 'logs').mkdir(exist_ok=True)
    # --feed is one-shot: it selects this run's source only. Never pin it,
    # or one local test would freeze every future scheduled update on it.
    minted_state = not (home / 'mixed-router-state.json').exists()
    state = ensure_state(home)
    # The state file carries the loopback token: on failure unlink only a
    # file this run minted, never a pre-existing live token.
    try:
        backend.protect_secret(home / 'mixed-router-state.json')
    except SystemExit:
        if minted_state:
            (home / 'mixed-router-state.json').unlink(missing_ok=True)
        raise
    # Absence in legacy state means Codex, not service-only.
    client = args.client or state.get('client', 'codex')
    if client not in ('codex', 'none'):
        raise SystemExit('client must be codex or none')
    if state.get('client', 'codex') != client:
        state['client'] = client
        _write_state(home, state)
    # --clients selects attachments; --client none stays service-only.
    # Unset means the legacy Codex-only path below. `both` keeps the Codex
    # attach and adds Claude; `claude` attaches Claude without touching
    # Codex settings.
    clients = args.clients
    if clients is None and client == 'none':
        clients = 'none'
    if clients is None:
        clients = 'codex'
    if clients not in ('codex', 'claude', 'both', 'none'):
        raise SystemExit('clients must be codex, claude, both, or none')
    if client == 'none' and clients != 'none':
        raise SystemExit('--client none conflicts with --clients %s' % clients)
    if args.client == 'codex' and args.clients == 'claude':
        raise SystemExit('--client codex conflicts with --clients claude: '
                         'use --clients both to keep the Codex attachment')
    claude_mode = args.claude_mode
    if claude_mode is None:
        claude_mode = state.get('claude_mode', state.get('anthropic_mode', 'subscription'))
    if claude_mode not in ('subscription', 'none'):
        raise SystemExit('claude_mode must be subscription or none')
    if state.get('claude_mode') != claude_mode:
        state['claude_mode'] = claude_mode
        _write_state(home, state)
    if args.anthropic_mode is not None and args.anthropic_mode != state.get('anthropic_mode'):
        state['anthropic_mode'] = args.anthropic_mode
        _write_state(home, state)
    mode = args.openai_mode or state.get('openai_mode', 'subscription')
    if mode not in ('subscription', 'none'):
        raise SystemExit('openai_mode must be subscription or none')
    if state.get('openai_mode') != mode:
        state['openai_mode'] = mode
        _write_state(home, state)
    setup_url = None
    if args.setup:
        # First-run window: the router boots keyless on this single-use link
        # and the operator pastes one key there instead of into the terminal.
        # TTL mirrors ai_router.setup.SETUP_TTL_S; kept literal so the
        # 3.9-compatible installer never imports the router package.
        state['setup'] = {'nonce': secrets.token_urlsafe(32),
                          'expires': int(time.time()) + 15 * 60}
        _write_state(home, state)
        setup_url = (f"http://127.0.0.1:{state['port']}/{state['token']}"
                     f"/setup/{state['setup']['nonce']}")
    try:
        ensure_credentials(home, state)
    except SystemExit as exc:
        if exc.code != 3 or setup_url is None:
            raise
    # No idle gate. A version swap is a pointer write plus a TERM: launchd
    # owns the listening socket, so new connections queue for the incoming
    # process while the outgoing one finishes the requests it already
    # accepted (ai_router.router.drain_and_exit). Waiting for inflight to
    # reach zero delayed every update on a machine that is actually in use,
    # and bought nothing that the drain does not already guarantee.
    catalog_path = home / 'mixed-models.json'
    before_catalog = catalog_path.read_bytes() if catalog_path.exists() else None
    previous = install_bundle(home, latest['version'], tarball, manifest_doc, python)
    try:
        backend.install(python, home, state, current_release_dir(home), previous)
        healthy = wait_version(state, latest['version'])
    except (OSError, subprocess.CalledProcessError, SystemExit) as exc:
        # SystemExit is caught on purpose: reload and launcher failures raise it,
        # and letting it through here skipped the rollback below entirely.
        # Say why before rolling back: a backend refusal (task registration,
        # group policy) is otherwise indistinguishable from a health timeout.
        print(f'service start failed: {exc}')
        healthy = False
    if not healthy:
        if before_catalog is None:
            catalog_path.unlink(missing_ok=True)
        else:
            catalog_path.write_bytes(before_catalog)
        if previous:
            swap_current(home, home / 'releases' / previous)
            # TERM, not bootout: KeepAlive restarts the old release.
            # bootout would unload the service and strand a busy machine.
            restart_router(home)
            rolled_back = f'rolled back to {previous}: new version failed health check'
            if backend.rollback_serving_ok(home, state, previous):
                print(rolled_back)
            else:
                # A TERM cannot revive a job that is not loaded, so never report
                # a clean rollback over a router that is not actually serving.
                print(f'{rolled_back}; router is NOT serving on port '
                      f'{state["port"]}, run the installer again')
        else:
            if current_release_dir(home) == home / 'releases' / latest['version']:
                _clear_current(home)
            stop_router(home)
            print('new version failed health check; inspect the service logs')
        raise SystemExit(1)
    previous_receipt = _codex_config.codex_attachment(home)
    if clients == 'none' and previous_receipt.get('inserted_block'):
        # Never silently detach an active Codex configuration: restore the
        # exact owned settings first, or refuse when the block was edited.
        _restore_owned_config(home)
        previous_receipt = _codex_config.codex_attachment(home)
    if clients == 'none':
        detach_claude(home)
        prune_releases(home, latest['version'], previous,
                       backend.pinned_release(home))
        if not args.feed:
            (home / 'feed-serial').write_text(str(serial) + '\n')
        backend.start_updates(home)
        print(f"installed {latest['version']}; health ok; service-only, no client changes")
        return 0
    if claude_mode == 'none' and clients in ('claude', 'both'):
        raise SystemExit('claude_mode is none: re-run with --claude-mode subscription '
                         'to attach Claude Code, or select --clients codex')
    if clients in ('claude', 'both'): attach_claude(home, state)
    if args.desktop: _desktop_config.attach(home, state, _codex_config)
    # A selection without Claude never silently detaches it: only an
    # explicit service-only install or uninstall drops attachments.
    if clients == 'claude':
        # Claude-only: the shared service is up; Codex settings untouched.
        if not args.feed:
            (home / 'feed-serial').write_text(str(serial) + '\n')
        backend.start_updates(home)
        print(f"installed {latest['version']}; health ok; Claude Code attached")
        return 0
    config_path = Path.home() / '.codex' / 'config.toml'
    block = _codex_config.build_block(home, state, mode)
    block = _preserve_picker_selection(config_path, previous_receipt.get('inserted_block'), block)
    release = current_release_dir(home)
    guidance = runpy.run_path(str(release / 'tools' / 'global_instructions.py'))
    rules_path, rules_before, rules_after, rules_receipt = guidance['prepare'](
        config_path.parent, previous_receipt.get('global_instructions'))
    stamp = time.strftime('%Y%m%d-%H%M%S', time.gmtime())
    (home / f'config-before-{stamp}.toml').write_bytes(
        (config_path.read_text() if config_path.exists() else '').encode())
    try:
        os.chmod(home / f'config-before-{stamp}.toml', 0o600)
    except OSError:
        pass
    before = replace_config_block(config_path, block, previous_receipt.get('inserted_block'))
    guidance['write'](rules_path, rules_before, rules_after)
    _codex_config.write_receipt(home, config_path, block, rules_receipt, mode, before)
    if setup_url is not None:
        # Printed as a fallback: the browser should already show this page.
        # It carries the per-install loopback token, so it stays operator-private.
        print(f'open {setup_url} to connect your OpenRouter key')
        webbrowser.open(setup_url)
    # launchd keeps the updater command it loaded until the job is reloaded,
    # and a scheduled run defers that reload. Pruning the release that command
    # names would leave the updater firing a missing file every 15 minutes.
    prune_releases(home, latest['version'], previous,
                   backend.pinned_release(home))
    if not args.feed:
        # One-shot rule, as for the feed URL: a pinned feed keeps its own
        # serial, so recording it makes the real feed look stale for good.
        (home / 'feed-serial').write_text(str(serial) + '\n')
    backend.start_updates(home)
    print(f"installed {latest['version']}; health ok; restart Codex to load the router")
    return 0


def attach_claude(home, state, settings_path=None, env=None):
    return _claude_config.attach(home, state, _codex_config,
                                 settings_path_override=settings_path, env=env)


def detach_claude(home, settings_path=None, env=None):
    if settings_path is None and env is None: _desktop_config.detach(home, _codex_config)  # also sweep desktop
    return _claude_config.detach(home, _codex_config,
                                 settings_path_override=settings_path, env=env)


def _release_key(name):
    try:
        return [int(x) for x in name.split('.')]
    except ValueError:
        return None  # operator dirs sort out of version pruning entirely


def prune_releases(home, *keep):
    """Keep current plus two prior verified releases for rollback depth."""
    names = [p.name for p in (home / 'releases').glob('*') if p.is_dir()
             and not p.name.endswith('.partial')]
    versions = sorted((n for n in names if _release_key(n) is not None),
                      key=_release_key, reverse=True)
    for stale in versions[3:]:
        if stale not in keep:
            shutil.rmtree(home / 'releases' / stale, ignore_errors=True)


MAX_VERSION_FAILURES = _updater.MAX_VERSION_FAILURES


def _park(home, etag, etag_path, version):
    return _updater._park(home, etag, etag_path, version)


def do_check_update(args, _fetch=fetch, _read_feed=None, _sleep=None):
    return _updater.do_check_update(args, _fetch=_fetch, _read_feed=_read_feed,
                                    _sleep=_sleep)


def do_uninstall(args):
    _sync_seams()
    home = Path(args.home).expanduser()
    backend = platform_backend()
    backend.check(home)
    # A missing receipt with a managed block still present means manual
    # interference: fail closed before any release or service decision rather
    # than orphan the client configuration.
    config_path = Path.home() / '.codex' / 'config.toml'
    try:
        configured = config_path.read_text()
    except OSError:
        configured = ''
    attached = _codex_config.codex_attachment(home)
    if (attached == {}
            and (_codex_config.BEGIN in configured or _codex_config.END in configured)):
        raise SystemExit('managed Codex block present without a receipt; '
                         'run tools/disable.py first')
    release = current_release_dir(home)
    detach_claude(home)  # sweep first: each surface no-ops without its claim
    if release is not None and attached == {} and not _codex_config.read_receipt(home).get('clients', {}):
        # Service-only installation: no client settings were ever touched,
        # so there is no receipt and no restore to run.
        backend.uninstall(home)
        print(f'uninstalled services; {home} left in place for the operator to delete')
        return 0
    if release is not None:
        # Use this installer's matching remover even after rolling back old code.
        disable = Path(__file__).resolve().parents[1] / 'tools' / 'disable.py'
        if disable.exists():
            result = run([sys.executable, str(disable)], capture_output=True, text=True,
                              env={**os.environ, 'ROUTER_HOME': str(home),
                                   'ROUTER_RESTORE_ONLY': '1'})
            print((result.stdout or '')[-2000:])
            if result.returncode != 0:
                print((result.stderr or '')[-2000:])
                raise SystemExit('configuration restore failed; '
                                 'services left running for manual review')
            # As on a client switch: a stale receipt makes the next install
            # refuse guidance it finds missing rather than changed.
            _codex_config.drop_client(home, 'codex')
    detach_claude(home)
    backend.uninstall(home)
    print(f'uninstalled services; {home} left in place for the operator to delete')
    return 0


def do_preflight(args):
    _sync_seams()
    return _diag.do_preflight(args)


def do_status(args):
    _sync_seams()
    return _diag.do_status(args)


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('--feed', default=None)
    parser.add_argument('--version', default=None)
    parser.add_argument('--home', default='~/.codex/mixed-model-router')
    parser.add_argument('--python', default=None)
    parser.add_argument('--install-python', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--check-update', action='store_true')
    parser.add_argument('--uninstall', action='store_true')
    parser.add_argument('--preflight', action='store_true',
                        help='Report missing install prerequisites and exit.')
    parser.add_argument('--status', action='store_true',
                        help='Print installed version, service, client, and key status.')
    parser.add_argument('--json', action='store_true',
                        help='With --status, print machine-readable JSON.')
    parser.add_argument('--static-catalogue', action='store_true',
                        help='No-op: the static catalogue file is now always configured.')
    parser.add_argument('--setup', action='store_true',
                        help='First-run key window: mint a setup link and open it instead of '
                             'requiring the key up front.')
    parser.add_argument('--openai-mode', default=None)
    parser.add_argument('--anthropic-mode', default=None,
                        choices=('subscription', 'none'),
                        help='Independent Claude subscription choice; '
                             'unset follows the OpenAI mode as before.')
    parser.add_argument('--client', default=None, choices=('codex', 'none'),
                        help='Client to activate (default codex); none leaves '
                             'all client settings and guidance untouched.')
    parser.add_argument('--clients', default=None, choices=('codex', 'claude', 'both'),
                        help='Clients to attach (default codex); both attaches '
                             'Codex and Claude Code.')
    parser.add_argument('--claude-mode', default=None,
                        choices=('subscription', 'none'),
                        help='Independent Claude subscription choice; '
                             'unset follows the Anthropic mode as before.')
    parser.add_argument('--desktop', action='store_true', help='Also attach the Claude desktop gateway profile.')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    action = do_status if args.status else do_preflight if args.preflight else do_uninstall if args.uninstall else do_check_update if args.check_update else do_install
    if not (args.status or args.preflight):
        # Plan 057 Stage 1: refuse before any router home or bundle work.
        # Read-only --status/--preflight run everywhere; everything else
        # (install, update, rollback, uninstall) stays refused.
        require_supported_platform()
    home = Path(args.home).expanduser()
    backend = platform_backend()
    # --check-update spawns the installer as a child, and that child takes the
    # lock itself; holding it here would deadlock every scheduled update. A
    # dry run mutates nothing, so it takes no lock and creates no home.
    if args.status or args.preflight or args.check_update or args.dry_run:
        return action(args)
    # Before the lock: a host with no service manager must be refused
    # without leaving a router home behind.
    backend.check(home)
    with install_lock(home) as held:
        if not held:
            # A scheduled pass and a manual run can fire at the same moment,
            # and both would swap `current`, rewrite both plists and reload
            # the same service. Second one out: the winner has this covered.
            print('deferred: another router operation is in progress')
            return 0
        return action(args)


if __name__ == '__main__':
    sys.exit(main())
