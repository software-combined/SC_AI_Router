#!/usr/bin/env python3
"""Install and update the Codex model router. Runs on Python 3.9+; finds 3.14 for the router itself."""
import argparse
import hashlib
import io
import json
import os
import plistlib
import random
import secrets
import time
import webbrowser
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

LABEL = 'com.local.codex-mixed-model-router'
UPDATE_LABEL = LABEL + '.update'
FEED_URL = 'https://github.com/software-combined/SC_Codex_openRouter_adapter/releases/latest/download/latest.json'
BETA_API_URL = 'https://api.github.com/repos/software-combined/SC_Codex_openRouter_adapter/releases?per_page=5'
MIN_PYTHON = (3, 14)


def fetch(url):
    """Single network entry point; tests inject a fake."""
    if url.startswith('file://'):
        return Path(url[len('file://'):]).read_bytes()
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def run(cmd, **kwargs):
    """Single subprocess entry point; tests inject a fake."""
    return subprocess.run(cmd, **kwargs)


def verify_sha256(data, want):
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise SystemExit('bundle checksum mismatch')
    return True


def newer(a, b):
    return tuple(int(x) for x in a.split('.')) > tuple(int(x) for x in b.split('.'))


def find_python(explicit=None):
    candidates = [explicit] if explicit else []
    candidates += ['python3.14', '/opt/homebrew/bin/python3.14', '/opt/homebrew/bin/python3',
                   '/usr/local/bin/python3.14', shutil.which('python3')]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            out = run([candidate, '-c', 'import sys,compression.zstd;print(sys.version_info[0],sys.version_info[1])'],
                      capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode == 0:
            try:
                if tuple(int(x) for x in out.stdout.split()) >= MIN_PYTHON:
                    return candidate
            except ValueError:
                continue
    return None


def safe_extract(tarball, dest):
    dest = Path(dest)
    with tarfile.open(fileobj=io.BytesIO(tarball), mode='r') as tar:
        for member in tar.getmembers():
            if member.name.startswith('/') or '..' in Path(member.name).parts:
                raise SystemExit('bundle has unsafe path: ' + member.name)
            if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                raise SystemExit('bundle has non-file member: ' + member.name)
        tar.extractall(dest, filter='data')


def check_manifest(release_dir, manifest):
    for name, want in manifest['files'].items():
        got = hashlib.sha256((release_dir / name).read_bytes()).hexdigest()
        if got != want:
            raise SystemExit('bundle manifest mismatch: ' + name)


def self_test(python, release_dir):
    # Bundle smoke: the runtime import closure must load from the extraction.
    # Full discover cannot run here: repo tests reference files outside the bundle.
    result = run([python, '-c',
                  'from codex_router import catalogue, registry; assert registry.MODELS'],
                 cwd=str(release_dir), capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise SystemExit('bundle self-test failed')


def current_version(home):
    marker = home / 'current' / 'packaging' / 'VERSION'
    return marker.read_text().strip() if marker.exists() else '0.0.0'


# Subscription-side roster for the combined picker: bare slugs that route on
# the ChatGPT subscription. Matches the live picker and state file; the
# OpenRouter-side roster lives in codex_router/models.json instead.
DEFAULT_OPENAI_MODELS = ['gpt-6-astra', 'gpt-reserve', 'gpt-5.6-sol',
                         'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5',
                         'gpt-5.4-mini', 'gpt-5.3-codex-spark', 'codex-auto-review']


def ensure_state(home):
    path = home / 'mixed-router-state.json'
    if path.exists():
        state = json.loads(path.read_text())
        if not isinstance(state.get('openai_models'), list):
            state['openai_models'] = list(DEFAULT_OPENAI_MODELS)
            path.write_text(json.dumps(state, indent=2) + '\n')
        return state
    port = 18749
    probe = socket.socket()
    try:
        probe.bind(('127.0.0.1', port))
    except OSError:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    finally:
        probe.close()
    state = {'port': port, 'token': secrets.token_urlsafe(32),
             'openai_models': list(DEFAULT_OPENAI_MODELS)}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(json.dumps(state, indent=2) + '\n')
    return state


def _write_state(home, state):
    fd = os.open(home / 'mixed-router-state.json', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(json.dumps(state, indent=2) + '\n')


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


def swap_current(home, release_dir):
    previous = os.readlink(home / 'current') if (home / 'current').is_symlink() else None
    tmp = home / 'current.tmp'
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    os.symlink(release_dir, tmp)
    os.replace(tmp, home / 'current')
    return previous


def render_plist(python, home, state):
    return {'Label': LABEL,
            'ProgramArguments': [python, '-m', 'codex_router'],
            'Sockets': {'Listeners': {'SockNodeName': '127.0.0.1',
                                      'SockServiceName': str(state['port']),
                                      'SockFamily': 'IPv4',
                                      'SockType': 'stream'}},
            'WorkingDirectory': str(home / 'current'),
            'EnvironmentVariables': {'ROUTER_HOME': str(home)},
            'KeepAlive': True, 'RunAtLoad': True, 'ThrottleInterval': 10, 'Umask': 63,
            'StandardOutPath': str(home / 'logs' / 'launchd.log'),
            'StandardErrorPath': str(home / 'logs' / 'launchd.log')}


def render_update_plist(python, home, feed=None):
    args = [python, str(home / 'current' / 'packaging' / 'install.py'), '--check-update',
            '--home', str(home)]
    if feed:
        args += ['--feed', feed]
    return {'Label': UPDATE_LABEL,
            'ProgramArguments': args,
            'RunAtLoad': True,
            'StartInterval': 900,
            'StandardOutPath': str(home / 'logs' / 'update.log'),
            'StandardErrorPath': str(home / 'logs' / 'update.log')}


def write_plist(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as stream:
        plistlib.dump(content, stream)


def health(state, timeout=20):
    url = f"http://127.0.0.1:{state['port']}/{state['token']}/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                body = json.loads(response.read())
                if response.status == 200 and body.get('status') == 'ok':
                    return body
        except (OSError, ValueError):
            time.sleep(0.5)
    return None


def wait_version(state, version, timeout=150, fetch_health=None):
    """True once /health reports the given version."""
    get = fetch_health or (lambda s: health(s, timeout=5))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = get(state)
        if body and body.get('version') == version:
            return body
        time.sleep(1)
    return None


def restart_service(home, uid):
    run(['launchctl', 'bootout', f'gui/{uid}/{LABEL}'], capture_output=True)
    run(['launchctl', 'bootout', f'gui/{uid}/{UPDATE_LABEL}'], capture_output=True)
    agents = Path.home() / 'Library' / 'LaunchAgents'
    run(['launchctl', 'bootstrap', f'gui/{uid}', str(agents / (LABEL + '.plist'))], check=True)
    run(['launchctl', 'bootstrap', f'gui/{uid}', str(agents / (UPDATE_LABEL + '.plist'))], check=True)


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
        self_test(python, partial)
        write_catalogue(home, partial, python)
    except (SystemExit, OSError):
        shutil.rmtree(partial, ignore_errors=True)
        raise
    final = releases / version
    if final.exists():
        shutil.rmtree(final)
    partial.rename(final)
    previous = swap_current(home, final)
    return previous


def write_catalogue(home, release_dir, python):
    # Seed the picker file the config block points at; refresh owns it after.
    result = run([python, '-m', 'codex_router.catalogue', '--merge', str(home / 'mixed-models.json')],
                 cwd=str(release_dir), capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit('catalogue merge failed')


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


def wait_idle(state, timeout=600, fetch_health=None):
    """True once inflight reads 0 three polls apart; False on timeout."""
    good = 0
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = fetch_health(state) if fetch_health else health(state, timeout=5)
        if body and body.get('inflight') == 0:
            good += 1
            if good >= 3:
                return True
        else:
            good = 0
        time.sleep(1)
    return False


def fetch_feed(url, etag, _fetch=fetch):
    """Read a feed document, revalidating with a saved ETag. Returns (status, body, etag)."""
    if url.startswith('file://'):
        return 200, _fetch(url), etag
    req = urllib.request.Request(url, headers={'If-None-Match': etag} if etag else {})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.read(), response.headers.get('ETag', etag)
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return 304, b'', etag
        raise


def resolve_beta_feed(_fetch=fetch):
    payload = json.loads(_fetch(BETA_API_URL).decode())
    for entry in payload:
        if entry.get('prerelease'):
            for asset in entry.get('assets', []):
                if asset.get('name') == 'latest-beta.json':
                    return asset['browser_download_url']
    raise SystemExit('no beta release found')


def channel_feed(home, _fetch=fetch):
    # An explicit --feed at install time is pinned in home/'feed' and wins
    # over the channel file, so scheduled updates keep following it. Delete
    # the file to return to channel resolution.
    if (home / 'feed').exists():
        return (home / 'feed').read_text().strip()
    channel = (home / 'channel').read_text().strip() if (home / 'channel').exists() else 'stable'
    if channel == 'beta':
        return resolve_beta_feed(_fetch)
    return FEED_URL


def feed_serial(home):
    """Last accepted feed serial; 0 when no serialed release was installed."""
    try:
        return int((home / 'feed-serial').read_text().strip())
    except FileNotFoundError:
        return 0
    except ValueError:
        raise SystemExit('feed serial file is corrupt')


def check_serial(home, latest):
    """Refuse feeds older than the last accepted one (replay protection)."""
    serial = latest.get('serial', 0)
    if type(serial) is not int:
        raise SystemExit('feed has a bad serial')
    stored = feed_serial(home)
    if serial < stored:
        raise SystemExit(f'stale feed serial {serial} is older than {stored}')
    return serial


def do_rollback(args):
    """Point current at a previously installed release and verify it serves.

    Only releases still present under home/releases can be restored; the feed
    carries the latest bundle only, so there is nothing to download a
    rollback from. The feed serial is never touched.
    """
    home = Path(args.home).expanduser()
    if args.dry_run:
        print(f'would roll back to {args.version} under {home}')
        return 0
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
    run(['launchctl', 'kill', 'TERM', f'gui/{os.getuid()}/{LABEL}'], capture_output=True)
    if not wait_version(state, args.version):
        if previous is not None:
            swap_current(home, Path(previous))
            print(f'rollback to {args.version} failed health check; restored {previous}')
        else:
            if (home / 'current').is_symlink():
                (home / 'current').unlink()
            print(f'rollback to {args.version} failed health check; no previous release')
        run(['launchctl', 'kill', 'TERM', f'gui/{os.getuid()}/{LABEL}'], capture_output=True)
        raise SystemExit(1)
    print(f'rolled back to {args.version}; health ok; restart Codex to load the router')
    return 0


def do_install(args, _fetch=fetch, _run=None):
    global run
    if _run is not None:
        run = _run
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
    tarball = _fetch(latest['url'])
    if latest.get('sha256'):
        verify_sha256(tarball, latest['sha256'])
    manifest_doc = {'files': {}}
    with tarfile.open(fileobj=io.BytesIO(tarball), mode='r') as tar:
        try:
            manifest_doc = json.loads(tar.extractfile('MANIFEST.json').read())
        except KeyError:
            raise SystemExit('bundle has no MANIFEST.json')
    home.mkdir(parents=True, exist_ok=True)
    (home / 'logs').mkdir(exist_ok=True)
    pinned_feed = args.feed.strip() if args.feed else ''
    if pinned_feed:
        (home / 'feed').write_text(pinned_feed + '\n')
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
    previous = install_bundle(home, latest['version'], tarball, manifest_doc, python)
    agents = Path.home() / 'Library' / 'LaunchAgents'
    write_plist(agents / (LABEL + '.plist'), render_plist(python, home, state))
    write_plist(agents / (UPDATE_LABEL + '.plist'),
                render_update_plist(python, home, pinned_feed or None))
    uid = os.getuid()
    if previous is None:
        restart_service(home, uid)
    else:
        run(['launchctl', 'kill', 'TERM', f'gui/{uid}/{LABEL}'], capture_output=True)
    if not wait_version(state, latest['version']):
        if previous:
            swap_current(home, Path(previous))
            restart_service(home, os.getuid())
            print(f'rolled back to {previous}: new version failed health check')
        else:
            failed = home / 'releases' / latest['version']
            try:
                if (home / 'current').is_symlink() and (home / 'current').readlink() == failed:
                    (home / 'current').unlink()
            except OSError:
                pass
            run(['launchctl', 'bootout', f'gui/{os.getuid()}/{LABEL}'], capture_output=True)
            print('new version failed health check; see logs/launchd.log')
        raise SystemExit(1)
    config_path = Path.home() / '.codex' / 'config.toml'
    catalog_line = f'model_catalog_json = "{home}/mixed-models.json"\n'
    block = ('# BEGIN local mixed model picker\n'
             f'openai_base_url = "http://127.0.0.1:{state["port"]}/{state["token"]}/backend-api/codex"\n'
             + catalog_line + '# END local mixed model picker\n')
    if mode == 'none':
        # Root keys stay above the provider table; the key name matches the
        # Plan 043 spike shape (staff export the router path token as its
        # value) instead of a per-port variable nothing provisions.
        block = ('# BEGIN local mixed model picker\n'
                 'model_provider = "scg_router"\n'
                 + catalog_line +
                 '[model_providers.scg_router]\n'
                 'name = "SC router"\n'
                 f'base_url = "http://127.0.0.1:{state["port"]}/{state["token"]}/backend-api/codex"\n'
                 'wire_api = "responses"\n'
                 'env_key = "SCG_ROUTER_TOKEN"\n'
                 + '# END local mixed model picker\n')
    receipt_path = home / 'activation.json'
    previous_receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    stamp = time.strftime('%Y%m%d-%H%M%S', time.gmtime())
    (home / f'config-before-{stamp}.toml').write_bytes(
        (config_path.read_text() if config_path.exists() else '').encode())
    try:
        os.chmod(home / f'config-before-{stamp}.toml', 0o600)
    except OSError:
        pass
    before = replace_config_block(config_path, block, previous_receipt.get('inserted_block'))
    receipt_path.write_text(json.dumps({'config_path': str(config_path), 'inserted_block': block,
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
    for stale in home.glob('releases/*'):
        if stale.name not in (latest['version'], Path(previous).name if previous else ''):
            shutil.rmtree(stale, ignore_errors=True)
    (home / 'feed-serial').write_text(str(serial) + '\n')
    print(f"installed {latest['version']}; health ok; restart Codex to load the router")
    return 0


def do_check_update(args, _fetch=fetch, _read_feed=None, _sleep=None):
    read_feed = _read_feed or (lambda url, etag: fetch_feed(url, etag, _fetch))
    sleep = _sleep or time.sleep
    home = Path(args.home).expanduser()
    feed = args.feed or channel_feed(home)
    sleep(random.uniform(0, 120))
    etag_path = home / 'update-etag'
    etag = etag_path.read_text().strip() if etag_path.exists() else None
    status, body, etag = read_feed(feed, etag)
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
    (home / 'logs').mkdir(exist_ok=True)
    with open(home / 'logs' / 'update.log', 'a') as stream:
        stream.write(json.dumps({'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                                 'version': latest['version']}) + '\n')
    if etag:
        etag_path.write_text(etag + '\n')
    print(f"installed {latest['version']}")
    return 0


def do_uninstall(args):
    home = Path(args.home).expanduser()
    current = home / 'current'
    if current.is_symlink():
        disable = current / 'tools' / 'disable.py'
        if disable.exists():
            result = run([sys.executable, str(disable)], capture_output=True, text=True,
                         env={**os.environ, 'ROUTER_HOME': str(home)})
            out = result.stdout or ''
            print(out[-2000:])
            if 'OpenAI direct routing restored' not in out:
                print((result.stderr or '')[-2000:])
                raise SystemExit('configuration restore failed; '
                                 'services left running for manual review')
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
    if args.uninstall:
        return do_uninstall(args)
    if args.check_update:
        return do_check_update(args)
    return do_install(args)


if __name__ == '__main__':
    sys.exit(main())
