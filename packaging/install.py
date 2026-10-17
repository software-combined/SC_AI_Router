#!/usr/bin/env python3
"""Install the Codex model router. Runs on Python 3.9+; finds 3.14 for the router itself.

Shared launchd/plist/feed helpers live in packaging/service.py. This
module owns first install, explicit upgrade, rollback and uninstall only.
"""
import argparse
import io
import shutil  # noqa: F401 (re-exported: tests patch install_mod.shutil.which)
import json
import os
import secrets
import subprocess
import time
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import importlib.util
# Bootstrap loader (Plan 123 exception): service must be spec-loaded before
# service.load() exists, so this single bootstrap copy stays.
_spec = importlib.util.spec_from_file_location(
    'packaging.service',
    Path(__file__).resolve().parent / 'service.py')
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)
_platforms = _svc.load(
    'router_platforms', Path(__file__).resolve().parent / 'platforms' / '__init__.py')
_codex_config = _svc.load(
    'router_codex_config', Path(__file__).resolve().parent / 'codex_config.py')
_codex_config._atomic_write = _svc.load('router_atomic_write', Path(__file__).resolve().parent / 'atomic_write.py')
_claude_config = _svc.load(
    'router_claude_config', Path(__file__).resolve().parent / 'claude_config.py')
_desktop_config = _svc.load(
    'router_claude_desktop_config', Path(__file__).resolve().parent / 'claude_desktop_config.py')
_client_choice = _svc.load(
    'router_client_choice', Path(__file__).resolve().parent / 'client_choice.py')
_diag = _svc.load(
    'router_diagnostics', Path(__file__).resolve().parent / 'diagnostics.py')
# Never name a packaging module after a standard-library one: scripts run with
# packaging/ as sys.path[0], so packaging/operator.py shadowed the stdlib
# operator that collections imports, breaking every entry point with a circular import.
_operator = _svc.load(
    'router_operator_surface', Path(__file__).resolve().parent / 'operator_surface.py')
_client_roster = _svc.load('router_client_roster', Path(__file__).resolve().parents[1] / 'ai_router' / 'clients' / 'roster.py')
_linux = _platforms._linux_mod().systemd
_updater = _svc.load(
    'router_updater', Path(__file__).resolve().parent / 'updater.py')
# One shared service module: tests patch install_mod._svc attrs and the
# updater must see the same object. _sync_seams keeps seams fresh per call.
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
require_live_home = _svc.require_live_home
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


_bundle = _svc.load(
    'router_bundle', Path(__file__).resolve().parent / 'bundle.py')

# Bundle seams (Plan 130): _patch_attrs mirrors swaps onto _svc; _sync_seams
# pushes the callable seams into the bundle module, while the rest travel as
# explicit wrapper arguments. The aliases below keep test patch points resolving.


verify_sha256 = _bundle.verify_sha256
newer = _bundle.newer
check_manifest = _bundle.check_manifest
check_identity = _bundle.check_identity

_delivery = _svc.load('router_install_delivery', Path(__file__).resolve().parent / 'install_delivery.py')


def self_test(python, release_dir):
    return _bundle.self_test(python, release_dir, run=run)


def ensure_credentials(home, state, env=None):
    return _bundle.ensure_credentials(
        home, state, env,
        lambda path: platform_backend().protect_secret(path),
        provider_keys=provider_keys)


provider_keys = _bundle.provider_keys


def install_bundle(home, version, tarball, manifest_doc, python):
    return _bundle.install_bundle(
        home, version, tarball, manifest_doc, python,
        self_test=self_test, write_catalogue=write_catalogue,
        safe_extract=safe_extract, install_launcher=install_launcher,
        swap_current=swap_current)


def write_catalogue(home, release_dir, python):
    return _bundle.write_catalogue(home, release_dir, python, run=run)


replace_config_block = _codex_config.replace_config_block


def _restore_owned_config(home):
    """Detach an active client via the single owned remover path.

    Runs the matching tools/disable.py with ROUTER_RESTORE_ONLY=1: exact
    owned-block restore with atomic temp and concurrent-edit checks. The
    machine result decides; success text alone never passes.
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
    _sync_seams(); _client_choice.refuse_switched(Path(args.home).expanduser())  # older releases may lack Switch Codex
    return _bundle.do_rollback(
        args, platform_backend=platform_backend, restart_router=restart_router,
        wait_version=wait_version, current_version=current_version,
        swap_current=swap_current)


def _sync_seams():
    """Mirror _patch_attrs swaps from install_mod onto _svc call sites."""
    global run, health, wait_version, ensure_serving
    run, health, wait_version, ensure_serving = (
        _svc.run, _svc.health, _svc.wait_version, _svc.ensure_serving)
    _bundle.bind_seams(run=run, safe_extract=safe_extract,
                       install_launcher=install_launcher,
                       swap_current=swap_current)
    _updater.bind(svc=_svc, newer=newer, verify_sha256=verify_sha256,
                  sync_seams=_sync_seams)
    _diag.bind(find_python=find_python, health=health,
               current_version=current_version, codex_config=_codex_config)
    _operator.bind(run=run, diag=_diag)


def _resolve_clients_and_modes(args, home, state, repair=False):
    return _client_choice.resolve(args, home, state, _codex_config, _write_state, repair=repair)


def _current_ready(home, state, previous, python, only_if_changed=False):
    def modes(doc):
        mode = doc.get('openai_mode', 'subscription')
        return mode, doc.get('anthropic_mode', mode)
    changed = modes(state) != modes(previous)
    if only_if_changed and not changed:
        return
    backend, release, version = platform_backend(), current_release_dir(home), current_version(home)
    try:
        if changed:
            # The repair lifecycle waits for the old process to leave. A TERM
            # followed by same-version health could accept the old policy.
            backend.install(python, home, state, release, None)
        if not wait_version(state, version):
            raise SystemExit('the current router did not become healthy')
    except (OSError, subprocess.SubprocessError, SystemExit):
        _write_state(home, previous)
        if changed:
            try:
                backend.install(python, home, previous, release, None)
                if not wait_version(previous, version):
                    raise SystemExit('health check failed')
            except (OSError, subprocess.SubprocessError, SystemExit):
                print('Previous settings restored; router needs repair with --setup.')
        raise SystemExit('Client connection stopped: could not verify the current router.')


def _rollback_failed_install(home, state, backend, latest, previous, catalog_path,
                             before_catalog):
    # TERM, not bootout: KeepAlive restarts the old release; bootout would
    # unload the service and strand a busy machine. A TERM cannot revive a
    # job that is not loaded, so never report a clean rollback over a router
    # that is not actually serving.
    if before_catalog is None: catalog_path.unlink(missing_ok=True)
    else: catalog_path.write_bytes(before_catalog)
    if previous:
        swap_current(home, home / 'releases' / previous); restart_router(home)
        rolled_back = f'rolled back to {previous}: new version failed health check'
        if backend.rollback_serving_ok(home, state, previous): print(rolled_back)
        else: print(f'{rolled_back}; router is NOT serving on port '
                    f'{state["port"]}, run the installer again')
    else:
        if current_release_dir(home) == home / 'releases' / latest['version']:
            _bundle._clear_current(home)
        stop_router(home); print('new version failed health check; inspect the service logs')
    raise SystemExit(1)


def _open_key_window(python, home, setup_url, clients):
    """Open the native key window; the setup URL prints only on a TTY."""
    if sys.stdout.isatty(): print(f'open {setup_url} to connect your OpenRouter key')
    try:  # URL on stdin, never argv; write once, close, never read.
        proc = subprocess.Popen([python, '-m', 'ai_router.key_prompt', '--stdin', '--clients',
                                 clients], cwd=str(current_release_dir(home)),
                                start_new_session=True, stdin=subprocess.PIPE,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try: proc.stdin.write((setup_url + '\n').encode()); proc.stdin.close()
        except OSError: pass
    except OSError:
        if not sys.stdout.isatty(): print('could not open the key window; the next request opens it')


def do_install(args, _fetch=fetch, _run=None):
    _svc._feed.configure_home(Path(args.home).expanduser())
    rc = _do_install(args, _fetch, _run)
    if rc == 0 and not args.dry_run:
        _delivery.finish(Path(args.home).expanduser(), run=run)
    return rc


def _do_install(args, _fetch=fetch, _run=None):
    _client_choice.validate(args)
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
    feed = args.feed or _svc.channel_feed(home)
    latest = _updater._verified_feed(feed, _svc.feed_read(_fetch, feed), _fetch)
    serial = check_serial(home, latest, pinned=bool(args.feed))
    current = current_version(home)
    # --setup on a current install is a repair run: it restarts the current
    # release with a fresh setup nonce and never re-extracts or downgrades
    # anything, so it also works when the feed lags the installed version.
    # Only a newer feed version takes the full install path.
    repair = bool(args.setup) and not newer(latest['version'], current)
    if not newer(latest['version'], current) and not repair:
        if PLATFORM == 'win32' and not args.dry_run:
            platform_backend().recover_pending(python, home, current_release_dir(home), current)
        print(f'up to date {current}')
        if (args.clients is None and args.client is None and not args.choose_clients
                and not args.desktop and args.claude_mode is None
                and args.anthropic_mode is None and args.openai_mode is None):
            return 0
        return _client_choice.attach_current(
            args, home, codex=_codex_config, desktop=_desktop_config,
            claude=attach_claude, write_state=_write_state, python=python,
            resolve=_resolve_clients_and_modes, ensure_state=ensure_state, ready=_current_ready)
    if args.dry_run:
        print(f'would fetch {feed}; interpreter {python}')
        print('would verify, unpack, self-test, swap current, restart, write config')
        return 0
    backend = platform_backend()
    backend.check(home)
    want = _updater._required_sha256(latest)
    tarball = _svc.feed_read(_fetch, _svc.sibling_bundle(feed, latest['url']))
    verify_sha256(tarball, want)
    manifest_doc = {'files': {}}
    with tarfile.open(fileobj=io.BytesIO(tarball), mode='r') as tar:
        try:
            manifest_doc = json.loads(tar.extractfile('MANIFEST.json').read())
        except KeyError:
            raise SystemExit('bundle has no MANIFEST.json')
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Plan 116 Stage 2: harden the home before any token or key is minted
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
    client, clients, claude_mode, mode = _resolve_clients_and_modes(args, home, state, repair=repair)
    # First-run window: the router boots keyless on a single-use link and
    # the operator pastes one key there instead of into the terminal. TTL
    # mirrors ai_router.setup.SETUP_TTL_S; kept literal so the 3.9-compatible
    # installer never imports the router package. --setup forces the window;
    # otherwise a fresh install arms it whenever the installed service has
    # no service-visible key.
    missing = provider_keys().unhandled(home, state, _diag._key_private)
    env_named = [defn.key.env for defn in missing
                 if os.environ.get(defn.key.env, '').strip()]
    setup_url = None
    if args.setup or missing:
        state['setup'] = {'nonce': secrets.token_urlsafe(32),
                          'expires': int(time.time()) + 15 * 60}
        _write_state(home, state)
        setup_url = (f"http://127.0.0.1:{state['port']}/{state['token']}"
                     f"/setup/{state['setup']['nonce']}")
    if env_named:
        # The service environment carries only ROUTER_HOME, so a shell-only key
        # never reaches it; the window collects it and never prints the value.
        print('%s is set in this shell; the installer passes only ROUTER_HOME '
              'to the installed service, so the key window collects the key '
              'instead' % ', '.join(env_named))
    try:
        ensure_credentials(home, state)
    except SystemExit as exc:
        if exc.code != 3 or setup_url is None:
            raise
    if repair:
        # --setup on a current install changes no code: restart the current
        # release so the service reads the fresh setup nonce, then open the
        # window. Never re-extract a release the running service is using.
        try:
            backend.install(python, home, state, current_release_dir(home), None)
            healthy = wait_version(state, current)
        except (OSError, subprocess.CalledProcessError, SystemExit) as exc:
            print(f'service restart failed: {exc}')
            healthy = False
        if not healthy:
            print('the service did not come back with the fresh setup link; '
                  're-run the installer')
            return 1
        # A receipt that predates the listing snapshot (or one whose fetch
        # failed) can only be refreshed from here: a plain re-run returns
        # "up to date" before the client stage, and the scheduled child never
        # passes --clients. The merge is idempotent for unchanged values.
        _claude_config.refresh_snapshot(
            home, state, _codex_config,
            lambda: _operator.listing(state))
        if setup_url is not None and os.environ.get('ROUTER_NO_KEY_WINDOW') != '1':
            _open_key_window(python, home, setup_url, clients)
        print(f'installed {current}; health ok; key window ready')
        return 0
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
        _rollback_failed_install(home, state, backend, latest, previous, catalog_path,
                                 before_catalog)
    # Stage the restart notice once the new version is healthy (fresh
    # installs are a no-op); notice failures never surface.
    _svc.notice.record(home, previous, latest['version'], args.clients)
    previous_receipt = _codex_config.codex_attachment(home)
    if setup_url is not None and os.environ.get('ROUTER_NO_KEY_WINDOW') != '1':
        _open_key_window(python, home, setup_url, clients)
    saved = None if args.desktop or args.client == 'none' else _desktop_config.saved_profile(home, _codex_config)
    if clients == 'none':
        if args.desktop or saved:
            # An explicit desktop request attaches that profile alone;
            # a saved profile is refreshed without detaching other clients.
            _client_choice.attach_desktop_only(args, home, state, _codex_config,
                                               _desktop_config, saved, python)
        else:
            if args.client == 'none':
                if previous_receipt.get('inserted_block'):
                    # Never silently detach an active Codex configuration:
                    # restore the exact owned settings first, or refuse when
                    # the block was edited.
                    _restore_owned_config(home)
                detach_claude(home)
        prune_releases(home, latest['version'], previous,
                       backend.pinned_release(home))
        if not args.feed:
            (home / 'feed-serial').write_text(str(serial) + '\n')
        backend.start_updates(home)
        print(f"installed {latest['version']}; health ok; {_client_choice.none_outcome(args, bool(saved))}")
        return 0
    if claude_mode == 'none' and clients in ('claude', 'both') and (
            'claude' not in _codex_config.read_receipt(home).get('clients', {})):
        raise SystemExit('claude_mode is none: re-run with --claude-mode subscription '
                         'to attach Claude Code, or select --clients codex')
    if clients in ('claude', 'both'): attach_claude(home, state, python=python)
    if args.desktop or saved: _desktop_config.attach(home, state, _codex_config, saved, python=python, refresh=bool(saved))
    # Only explicit service-only installation or uninstall drops attachments.
    if clients == 'claude':
        # Claude-only: the shared service is up; Codex settings untouched.
        if not args.feed:
            (home / 'feed-serial').write_text(str(serial) + '\n')
        backend.start_updates(home)
        print(f"installed {latest['version']}; health ok; Claude Code attached")
        return 0
    _client_choice.attach_codex(home, state, mode, _codex_config, previous_receipt, static_catalogue=args.static_catalogue, python=python)
    # launchd keeps the updater command until the job is reloaded and a
    # scheduled run defers that reload, so pruning its release breaks it.
    prune_releases(home, latest['version'], previous,
                   backend.pinned_release(home))
    if not args.feed:
        # One-shot rule, as for the feed URL: a pinned feed keeps its own
        # serial, so recording it makes the real feed look stale for good.
        (home / 'feed-serial').write_text(str(serial) + '\n')
    backend.start_updates(home)
    print(f"installed {latest['version']}; health ok; restart Codex to load the router")
    return 0


def attach_claude(home, state, settings_path=None, env=None, listing=None,
                  python=None):
    if listing is None:
        listing = _operator.listing(state)
    return _claude_config.attach(home, state, _codex_config,
                                 settings_path_override=settings_path, env=env,
                                 listing=listing)


def detach_claude(home, settings_path=None, env=None):
    if settings_path is None and env is None: _desktop_config.detach(home, _codex_config)  # also sweep desktop
    return _claude_config.detach(home, _codex_config, settings_path_override=settings_path, env=env)


_release_key = _bundle._release_key
prune_releases = _bundle.prune_releases


MAX_VERSION_FAILURES = _updater.MAX_VERSION_FAILURES


def do_update(args, _fetch=None, _read_feed=None, _sleep=None, _announce=None):
    _sync_seams()
    return _updater.do_update(args, _fetch=_fetch, _read_feed=_read_feed,
                              _sleep=_sleep, _announce=_announce)


def do_check_update(args, _fetch=None, _read_feed=None, _sleep=None):
    _sync_seams()
    return _updater.do_check_update(args, _fetch=_fetch, _read_feed=_read_feed,
                                    _sleep=_sleep)


def do_doctor(args):
    _sync_seams(); return _operator.do_doctor(args)


def do_support(args):
    _sync_seams(); return _operator.do_support(args)


def do_rollback_list(args):
    _sync_seams(); return _operator.do_rollback_list(args)


def do_uninstall(args):
    _sync_seams()
    home = Path(args.home).expanduser()
    if args.dry_run:
        print(f'would uninstall services under {home}')
        return 0
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
        raise SystemExit('managed Codex block present without a receipt; run tools/disable.py first')
    _client_choice.refuse_switched(home)  # also before anything changes: switch back first
    release = current_release_dir(home)
    detach_claude(home)  # sweep first: each surface no-ops without its claim
    if release is not None and attached == {} and not _codex_config.read_receipt(home).get('clients', {}):
        # Service-only installation: no client settings were ever touched,
        # so there is no receipt and no restore to run.
        backend.uninstall(home)
        _delivery._load('desktop_startup').remove(home)
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
            # refuse a block it finds missing rather than changed.
            _codex_config.drop_client(home, 'codex')
    detach_claude(home)
    backend.uninstall(home)
    _delivery._load('desktop_startup').remove(home)
    print(f'uninstalled services; {home} left in place for the operator to delete')
    return 0


def do_preflight(args):
    _sync_seams(); return _diag.do_preflight(args)


def do_status(args):
    _sync_seams(); return _diag.do_status(args)


def do_restart(args):
    _sync_seams(); return _delivery._load('desktop_service').restart(args, _svc, platform_backend())


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('--feed', default=None)
    parser.add_argument('--version', default=None)
    parser.add_argument('--home', default='~/.codex/mixed-model-router')
    parser.add_argument('--python', default=None)
    parser.add_argument('--install-python', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--check-update', action='store_true',
                        help='Read-only: print the installed and available versions.')
    parser.add_argument('--update', action='store_true',
                        help='Apply an available update (the scheduled action).')
    parser.add_argument('--express-only', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--rollback', action='store_true',
                        help='List installed releases; with --to, restore one.')
    parser.add_argument('--to', default=None, help='With --rollback: the release version to restore.')
    parser.add_argument('--doctor', action='store_true', help='Read-only health report with one Fix line per failing row.')
    parser.add_argument('--support', action='store_true', help='Write a redacted support bundle and print its path.')
    parser.add_argument('--uninstall', action='store_true')
    parser.add_argument('--restart', action='store_true', help='Restart SCG Router after running replies finish.')
    parser.add_argument('--preflight', action='store_true',
                        help='Report missing install prerequisites and exit.')
    parser.add_argument('--status', action='store_true',
                        help='Print installed version, service, client, and key status.')
    parser.add_argument('--json', action='store_true',
                        help='With --status, --check-update or --doctor: machine-readable JSON.')
    parser.add_argument('--static-catalogue', action='store_true', help='Use the static catalogue fallback.')
    parser.add_argument('--setup', action='store_true',
                        help='First-run key window: mint a setup link and open it even when a key exists.')
    parser.add_argument('--choose-clients', action='store_true', help='Ask which assistant and surface this computer uses.')
    parser.add_argument('--openai-mode', default=None)
    parser.add_argument('--anthropic-mode', default=None,
                        choices=('subscription', 'none'),
                        help='Independent Claude subscription choice; '
                             'unset follows the OpenAI mode as before.')
    parser.add_argument('--client', default=None, choices=(_client_roster.DEFAULT_CLIENT, 'none'),
                        help='Client to activate (default codex); none leaves '
                             'all client settings and guidance untouched.')
    parser.add_argument('--clients', default=None, choices=_client_roster.CLIENT_IDS + ('both', 'none'),
                        help='Clients to attach (default codex); both attaches '
                             'Codex and Claude Code; none attaches no terminal client.')
    parser.add_argument('--claude-mode', default=None,
                        choices=('subscription', 'none'),
                        help='Independent Claude subscription choice; '
                             'unset follows the Anthropic mode as before.')
    parser.add_argument('--desktop', action='store_true', help='Also attach the Claude desktop gateway profile.')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    _client_choice.validate(args)
    if args.express_only and not args.update: raise SystemExit('--express-only needs --update')
    if args.to and not args.rollback:
        raise SystemExit('--to needs --rollback')
    if args.rollback and args.to:
        args.version = args.to  # --version stays the pre-147 alias
    list_rollback = args.rollback and not args.version
    action = (do_status if args.status else
              do_preflight if args.preflight else
              do_uninstall if args.uninstall else
              do_restart if args.restart else
              do_doctor if args.doctor else
              do_support if args.support else
              do_rollback_list if list_rollback else
              do_update if args.update else
              do_check_update if args.check_update else
              do_install)
    # Plan 116 Stage 1: read-only verbs run everywhere and take no lock; a
    # dry run mutates nothing and keeps its historic exemptions. --update is
    # the scheduled applying pass: it spawns the installer as a child and
    # that child takes the lock itself, so a parent holding it would make
    # every automatic update defer. Everything else (install, rollback,
    # uninstall) is refused before any router home or bundle work.
    read_only = (args.status or args.preflight or args.doctor or args.support
                 or list_rollback or args.check_update or args.dry_run)
    home = Path(args.home).expanduser()
    if args.update:
        require_supported_platform()
        require_live_home(home, '--update')
        return action(args)
    if not read_only:
        require_supported_platform()
    if read_only:
        if args.check_update or args.uninstall:
            require_live_home(home, '--uninstall' if args.uninstall else '--check-update')
        return action(args)
    backend = platform_backend()
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
        require_live_home(home, 'this action')
        rc = action(args)
        if rc == 0 and action is do_install:
            # A pending restart notice fires only from this CLI entry point,
            # never from do_install, so in-process callers cannot spawn one.
            _svc.notice.show_pending(home)
        return rc


if __name__ == '__main__':
    sys.exit(main())
