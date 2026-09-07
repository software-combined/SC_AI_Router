#!/usr/bin/env python3
"""Install and update the Codex model router. Runs on Python 3.9+; finds 3.14 for the router itself."""
import argparse
import hashlib
import io
import json
import os
import plistlib
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

LABEL = 'com.local.codex-mixed-model-router'
UPDATE_LABEL = LABEL + '.update'
FEED_URL = 'https://github.com/software-combined/SC_Codex_openRouter_adapter/releases/latest/download/latest.json'
BETA_FEED_URL = 'https://github.com/software-combined/SC_Codex_openRouter_adapter/releases/download/v999-beta/latest-beta.json'
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


def ensure_state(home):
    path = home / 'mixed-router-state.json'
    if path.exists():
        return json.loads(path.read_text())
    port = 18749
    probe = socket.socket()
    try:
        probe.bind(('127.0.0.1', port))
    except OSError:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    finally:
        probe.close()
    state = {'port': port, 'token': secrets.token_urlsafe(32)}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(json.dumps(state, indent=2) + '\n')
    return state


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


def render_plist(python, home):
    return {'Label': LABEL,
            'ProgramArguments': [python, '-m', 'codex_router'],
            'WorkingDirectory': str(home / 'current'),
            'EnvironmentVariables': {'ROUTER_HOME': str(home)},
            'KeepAlive': True, 'RunAtLoad': True, 'ThrottleInterval': 10, 'Umask': 63,
            'StandardOutPath': str(home / 'logs' / 'launchd.log'),
            'StandardErrorPath': str(home / 'logs' / 'launchd.log')}


def render_update_plist(python, home):
    return {'Label': UPDATE_LABEL,
            'ProgramArguments': [python, str(home / 'current' / 'packaging' / 'install.py'), '--check-update'],
            'RunAtLoad': False,
            'StartCalendarInterval': {'Hour': 10, 'Minute': 0},
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


def restart_service(home, uid):
    run(['launchctl', 'bootout', f'gui/{uid}/{LABEL}'], capture_output=True)
    agents = Path.home() / 'Library' / 'LaunchAgents'
    run(['launchctl', 'bootstrap', f'gui/{uid}', str(agents / (LABEL + '.plist'))], check=True)


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
    except (SystemExit, OSError):
        shutil.rmtree(partial, ignore_errors=True)
        raise
    final = releases / version
    if final.exists():
        shutil.rmtree(final)
    partial.rename(final)
    previous = swap_current(home, final)
    return previous


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


def channel_feed(home):
    channel = (home / 'channel').read_text().strip() if (home / 'channel').exists() else 'stable'
    if channel == 'beta':
        return BETA_FEED_URL
    return FEED_URL


def do_install(args, _fetch=fetch, _run=None):
    global run
    if _run is not None:
        run = _run
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
    if args.version:
        latest = {'version': args.version, 'url': feed, 'sha256': None, 'min_python': '3.14'}
    else:
        latest = json.loads(_fetch(feed).decode())
    if not args.version and not newer(latest['version'], current_version(home)):
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
    state = ensure_state(home)
    if args.openai_mode:
        if args.openai_mode not in ('subscription', 'none'):
            raise SystemExit('openai_mode must be subscription or none')
        state['openai_mode'] = args.openai_mode
        fd = os.open(home / 'mixed-router-state.json', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(state, indent=2) + '\n')
    ensure_credentials(home, state)
    previous = install_bundle(home, latest['version'], tarball, manifest_doc, python)
    agents = Path.home() / 'Library' / 'LaunchAgents'
    write_plist(agents / (LABEL + '.plist'), render_plist(python, home))
    write_plist(agents / (UPDATE_LABEL + '.plist'), render_update_plist(python, home))
    restart_service(home, os.getuid())
    got = health(state)
    if not got or got.get('version') != latest['version']:
        if previous:
            swap_current(home, Path(previous))
            restart_service(home, os.getuid())
            print(f'rolled back to {previous}: new version failed health check')
        else:
            run(['launchctl', 'bootout', f'gui/{os.getuid()}/{LABEL}'], capture_output=True)
            print('new version failed health check; see logs/launchd.log')
        raise SystemExit(1)
    config_path = Path.home() / '.codex' / 'config.toml'
    catalog_line = f'model_catalog_json = "{home}/mixed-models.json"\n'
    block = ('# BEGIN local mixed model picker\n'
             f'openai_base_url = "http://127.0.0.1:{state["port"]}/{state["token"]}/backend-api/codex"\n'
             + catalog_line + '# END local mixed model picker\n')
    if args.openai_mode == 'none':
        block = ('# BEGIN local mixed model picker\n'
                 'model_provider = "scg_router"\n'
                 '[model_providers.scg_router]\n'
                 'name = "SC router"\n'
                 f'base_url = "http://127.0.0.1:{state["port"]}/{state["token"]}/backend-api/codex"\n'
                 'wire_api = "responses"\n'
                 f'env_key = "ROUTER_OPENROUTER_KEY_{state["port"]}"\n'
                 + catalog_line + '# END local mixed model picker\n')
    receipt_path = home / 'activation.json'
    previous_receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    before = replace_config_block(config_path, block, previous_receipt.get('inserted_block'))
    stamp = time.strftime('%Y%m%d-%H%M%S', time.gmtime())
    (home / f'config-before-{stamp}.toml').write_bytes(before.encode())
    try:
        os.chmod(home / f'config-before-{stamp}.toml', 0o600)
    except OSError:
        pass
    receipt_path.write_text(json.dumps({'config_path': str(config_path), 'inserted_block': block,
                                        'previous_sha256': hashlib.sha256(before.encode()).hexdigest()},
                                       indent=2) + '\n')
    try:
        os.chmod(receipt_path, 0o600)
    except OSError:
        pass
    for stale in home.glob('releases/*'):
        if stale.name not in (latest['version'], Path(previous).name if previous else ''):
            shutil.rmtree(stale, ignore_errors=True)
    print(f"installed {latest['version']}; health ok; restart Codex to load the router")
    return 0


def do_check_update(args, _fetch=fetch):
    home = Path(args.home).expanduser()
    feed = args.feed or channel_feed(home)
    latest = json.loads(_fetch(feed).decode())
    if not newer(latest['version'], current_version(home)):
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
        result = run([sys.executable, str(installer), '--feed', feed,
                      '--home', str(home)], capture_output=True, text=True, timeout=900)
        print(result.stdout[-2000:] if result.stdout else '')
        if result.returncode != 0:
            print(result.stderr[-2000:] if result.stderr else '')
            raise SystemExit(result.returncode)
    (home / 'logs').mkdir(exist_ok=True)
    with open(home / 'logs' / 'update.log', 'a') as stream:
        stream.write(json.dumps({'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                                 'version': latest['version']}) + '\n')
    print(f"installed {latest['version']}")
    return 0


def do_uninstall(args):
    home = Path(args.home).expanduser()
    current = home / 'current'
    if current.is_symlink():
        disable = current / 'tools' / 'disable.py'
        if disable.exists():
            run([sys.executable, str(disable)], check=False)
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
    parser.add_argument('--static-catalogue', action='store_true')
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
