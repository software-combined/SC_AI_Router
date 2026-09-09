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
_linux_spec = importlib.util.spec_from_file_location(
    'router_systemd', Path(__file__).resolve().parent / 'systemd.py')
_linux = importlib.util.module_from_spec(_linux_spec)
_linux_spec.loader.exec_module(_linux)
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
_write_state = _svc._write_state
fetch = _svc.fetch
fetch_feed = _svc.fetch_feed
feed_serial = _svc.feed_serial
find_python = _svc.find_python
install_launcher = _svc.install_launcher
main_plist_exe = _svc.main_plist_exe
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
wait_idle = _svc.wait_idle
wait_version = _svc.wait_version


def systemd_manager(home):
    return _linux.Manager(home, run) if PLATFORM == 'linux' else None


def restart_router(home):
    manager = systemd_manager(home)
    if manager:
        manager.restart()
    else:
        run(['launchctl', 'kill', 'TERM', f'gui/{os.getuid()}/{LABEL}'], capture_output=True)


def stop_router(home):
    manager = systemd_manager(home)
    if manager:
        manager.stop()
    else:
        run(['launchctl', 'bootout', f'gui/{os.getuid()}/{LABEL}'], capture_output=True)


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
                       'from codex_router import catalogue, registry; assert registry.MODELS'],
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
    result = run([python, '-m', 'codex_router.catalogue', '--merge', str(home / 'mixed-models.json')],
                      cwd=str(release_dir), capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit('catalogue merge failed')


def _preserve_picker_selection(config_path, previous_block, block):
    """Carry owner-chosen picker lines across managed block rewrites.

    The installer owns the connection lines (base URL, catalogue) but the
    owner picks `model` / `model_reasoning_effort` inside the same marked
    block. A plain rewrite would silently reset that choice on every
    update, so re-emit those lines from the previous owned block.
    """
    if not previous_block:
        return block
    try:
        before = Path(config_path).read_text() if Path(config_path).exists() else ''
    except OSError:
        return block
    if previous_block not in before:
        return block
    keep = [line for line in previous_block.splitlines()
            if line.startswith('model = ') or line.startswith('model_reasoning_effort = ')]
    if not keep:
        return block
    lines = block.splitlines()
    lines[-1:-1] = keep
    return '\n'.join(lines) + '\n'


def replace_config_block(config_path, block, previous_block=None):
    """Insert or replace the marked block; refuse hand-edited markers."""
    config_path = Path(config_path)
    before = config_path.read_text() if config_path.exists() else ''
    if previous_block and previous_block in before:
        if before.count(previous_block) != 1:
            raise SystemExit('config block was edited by hand; run tools/disable.py first')
        after = before.replace(previous_block, block, 1)
    elif '# BEGIN local mixed model picker' in before or '# END local mixed model picker' in before:
        raise SystemExit('config block was edited by hand; run tools/disable.py first')
    else:
        after = block + '\n' + before
    home = config_path.parent
    if not config_path.exists():
        home.mkdir(parents=True, exist_ok=True)
    fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(after)
    try:
        os.chmod(config_path, 0o600)
    except OSError:
        pass
    return before


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
    manager = systemd_manager(home)
    if manager:
        manager.check()
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
    if not wait_idle(state):
        print('deferred: router busy')
        return 0
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
    global run, health, wait_idle, wait_version, main_plist_exe
    run, health, wait_idle, wait_version, main_plist_exe = (
        _svc.run, _svc.health, _svc.wait_idle, _svc.wait_version, _svc.main_plist_exe)


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
            print('No Python 3.14 found: brew install python@3.14')
            raise SystemExit(2)
    feed = args.feed or channel_feed(home)
    latest = json.loads(_fetch(feed).decode())
    serial = check_serial(home, latest)
    if not newer(latest['version'], current_version(home)):
        print(f"up to date {current_version(home)}")
        return 0
    if args.dry_run:
        print(f'would fetch {feed}; interpreter {python}')
        print('would verify, unpack, self-test, swap current, restart, write config')
        return 0
    manager = systemd_manager(home)
    if manager:
        manager.check()
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
    (home / 'logs').mkdir(exist_ok=True)
    # --feed is one-shot: it selects this run's source only. Never pin it,
    # or one local test would freeze every future scheduled update on it.
    state = ensure_state(home)
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
        # TTL mirrors codex_router.setup.SETUP_TTL_S; kept literal so the
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
    if current_release_dir(home) is not None and not wait_idle(state):
        # Busy router: keep serving the old pointer; the updater retries next
        # pass instead of killing live Codex traffic mid-request.
        print('deferred: router busy')
        return 0
    catalog_path = home / 'mixed-models.json'
    before_catalog = catalog_path.read_bytes() if catalog_path.exists() else None
    previous = install_bundle(home, latest['version'], tarball, manifest_doc, python)
    try:
        if manager:
            manager.install(python, current_release_dir(home))
        else:
            agents = Path.home() / 'Library' / 'LaunchAgents'
            legacy_exe = main_plist_exe()
            write_plist(agents / (LABEL + '.plist'), render_plist(python, home, state))
            write_plist(agents / (UPDATE_LABEL + '.plist'), render_update_plist(python, home))
            if previous is None:
                restart_service(os.getuid())
            elif legacy_exe is not None and legacy_exe != python:
                # Reload the old in-memory plist so it uses the absolute interpreter.
                try:
                    reload_main_service(os.getuid())
                except (SystemExit, OSError, subprocess.SubprocessError):
                    swap_current(home, home / 'releases' / previous)
                    if before_catalog is not None:
                        catalog_path.write_bytes(before_catalog)
                    healed = run(['launchctl', 'bootstrap', f'gui/{os.getuid()}',
                                  str(agents / (LABEL + '.plist'))], capture_output=True)
                    if healed.returncode != 0:
                        print(f'reload failed; restored pointer {previous} but the '
                              f'router is NOT loaded, bootstrap it by hand')
                    else:
                        print(f'reload failed; restored {previous}, re-run the installer')
                    raise SystemExit(1)
            else:
                restart_router(home)
        healthy = wait_version(state, latest['version'])
    except (OSError, subprocess.CalledProcessError):
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
            if manager:
                manager.start_updates()
            print(f'rolled back to {previous}: new version failed health check')
        else:
            if current_release_dir(home) == home / 'releases' / latest['version']:
                _clear_current(home)
            stop_router(home)
            print('new version failed health check; inspect the service logs')
        raise SystemExit(1)
    config_path = Path.home() / '.codex' / 'config.toml'
    catalog_line = f'model_catalog_json = "{home}/mixed-models.json"\n'
    block = ('# BEGIN local mixed model picker\n'
             f'openai_base_url = "http://127.0.0.1:{state["port"]}/{state["token"]}/backend-api/codex"\n'
             + catalog_line + '# END local mixed model picker\n')
    if mode == 'none':
        # No env var: the per-install path token embedded in base_url carries
        # auth, the same mechanism subscription mode uses in openai_base_url.
        # Nothing on staff machines provisions SCG_ROUTER_TOKEN, so naming it
        # here fails closed at the router with a 403. The 043 spike (2026-09-08,
        # Codex 0.153.4) showed thread+turn reaching the router on a custom
        # provider with bearer auth; live desktop proof that Codex keeps the
        # path prefix on a custom provider base_url is still the gate.
        block = ('# BEGIN local mixed model picker\n'
                 'model_provider = "scg_router"\n'
                 + catalog_line +
                 'approvals_reviewer = "user"\n'
                 '[model_providers.scg_router]\n'
                 'name = "SC router"\n'
                 f'base_url = "http://127.0.0.1:{state["port"]}/{state["token"]}/backend-api/codex"\n'
                 'wire_api = "responses"\n'
                 + '# END local mixed model picker\n')
    receipt_path = home / 'activation.json'
    previous_receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
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
    receipt_path.write_text(json.dumps({'config_path': str(config_path), 'inserted_block': block,
                                        'global_instructions': rules_receipt,
                                        'openai_mode': mode,
                                        'previous_sha256': hashlib.sha256(before.encode()).hexdigest()},
                                       indent=2) + '\n')
    try:
        os.chmod(receipt_path, 0o600)
    except OSError:
        pass
    if setup_url is not None:
        # Printed as a fallback: the browser should already show this page.
        # It carries the per-install loopback token, so it stays operator-private.
        print(f'open {setup_url} to connect your OpenRouter key')
        webbrowser.open(setup_url)
    prune_releases(home, latest['version'], previous)
    (home / 'feed-serial').write_text(str(serial) + '\n')
    if manager:
        manager.start_updates()
    print(f"installed {latest['version']}; health ok; restart Codex to load the router")
    return 0


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


def do_check_update(args, _fetch=fetch, _read_feed=None, _sleep=None):
    _sync_seams()
    import random
    import tempfile
    read_feed = _read_feed or (lambda url, etag: _svc.fetch_feed(url, etag, _fetch))
    sleep = _sleep or time.sleep
    home = Path(args.home).expanduser()
    feed = args.feed or channel_feed(home)
    sleep(random.uniform(0, 120))
    etag_path = home / 'update-etag'
    etag = etag_path.read_text().strip() if etag_path.exists() else None
    # Transient fetch failures (offline, locked-keychain TLS, DNS blip) retry
    # in-run with bounded backoff. HTTPError is an OSError subclass, so HTTP
    # errors re-raise without retry; deterministic errors (SystemExit from
    # serial/version checks, HTTP status) still fail fast below.
    for attempt in range(4):
        try:
            status, body, etag = read_feed(feed, etag)
            break
        except OSError as exc:
            if isinstance(exc, urllib.error.HTTPError) or attempt == 3:
                raise
            sleep(30 * 2 ** attempt)
            print(f'retrying feed fetch ({exc})')
    if status == 304:
        print(f"up to date {current_version(home)}")
        return 0
    latest = json.loads(body.decode())
    check_serial(home, latest)
    if not newer(latest['version'], current_version(home)):
        if etag:
            etag_path.write_text(etag + '\n')
        print(f"up to date {current_version(home)}")
        return 0
    state = json.loads((home / 'mixed-router-state.json').read_text())
    if not wait_idle(state):
        print('deferred: router busy')
        return 0
    tarball = _fetch(latest['url'])
    if latest.get('sha256'):
        verify_sha256(tarball, latest['sha256'])
    with tempfile.TemporaryDirectory() as tmp:
        safe_extract(tarball, tmp)
        installer = Path(tmp) / 'packaging' / 'install.py'
        if not installer.exists():
            raise SystemExit('downloaded bundle has no installer')
        # Only forward an explicitly pinned feed; a channel-resolved feed must
        # not pin home/'feed', or beta would freeze on one release asset URL.
        cmd = [sys.executable, str(installer), '--home', str(home)]
        if args.feed:
            cmd += ['--feed', feed]
        result = run(cmd, capture_output=True, text=True, timeout=900)
        print(result.stdout[-2000:] if result.stdout else '')
        if result.returncode != 0:
            print(result.stderr[-2000:] if result.stderr else '')
            raise SystemExit(result.returncode)
    if current_version(home) != latest['version']:
        print('deferred: installer did not activate the requested version')
        return 0
    (home / 'logs').mkdir(exist_ok=True)
    with open(home / 'logs' / 'update.log', 'a') as stream:
        stream.write(json.dumps({'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                                 'version': latest['version']}) + '\n')
    if etag:
        etag_path.write_text(etag + '\n')
    print(f"installed {latest['version']}")
    return 0


def do_uninstall(args):
    _sync_seams()
    home = Path(args.home).expanduser()
    manager = systemd_manager(home)
    if manager:
        manager.check()
    release = current_release_dir(home)
    if release is not None:
        # Use this installer's matching remover even after rolling back old code.
        disable = Path(__file__).resolve().parents[1] / 'tools' / 'disable.py'
        if disable.exists():
            result = run([sys.executable, str(disable)], capture_output=True, text=True,
                              env={**os.environ, 'ROUTER_HOME': str(home),
                                   'ROUTER_RESTORE_ONLY': '1'})
            out = result.stdout or ''
            print(out[-2000:])
            if 'OpenAI direct routing restored' not in out:
                print((result.stderr or '')[-2000:])
                raise SystemExit('configuration restore failed; '
                                 'services left running for manual review')
    if manager:
        manager.uninstall()
        print(f'uninstalled services; {home} left in place for the operator to delete')
        return 0
    run(['launchctl', 'bootout', f'gui/{os.getuid()}/{LABEL}'], capture_output=True)
    run(['launchctl', 'bootout', f'gui/{os.getuid()}/{UPDATE_LABEL}'], capture_output=True)
    agents = Path.home() / 'Library' / 'LaunchAgents'
    for name in (LABEL, UPDATE_LABEL):
        try:
            (agents / (name + '.plist')).unlink()
        except FileNotFoundError:
            pass
    print(f'uninstalled agents; {home} left in place for the operator to delete')
    return 0


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
    parser.add_argument('--static-catalogue', action='store_true',
                        help='No-op: the static catalogue file is now always configured.')
    parser.add_argument('--setup', action='store_true',
                        help='First-run key window: mint a setup link and open it instead of '
                             'requiring the key up front.')
    parser.add_argument('--openai-mode', default=None)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    action = do_uninstall if args.uninstall else do_check_update if args.check_update else do_install
    manager = systemd_manager(Path(args.home).expanduser())
    # The updater spawns the installer, which takes its own lock. Holding
    # one in the parent would prevent every scheduled update from installing.
    if manager and not args.check_update and not args.dry_run:
        with manager.operation():
            return action(args)
    return action(args)


if __name__ == '__main__':
    sys.exit(main())
