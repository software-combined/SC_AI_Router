"""Shared launchd/plist/feed helpers for install and scheduled update.

Split out of packaging/install.py (which hit the 700-line entrypoint
limit). Behavioral deltas vs the original live here, not in install.py:
ExitTimeOut 150 on the main plist, restart_service bootstraps the updater
only when missing, render_update_plist takes no feed (one-shot --feed).
Runs on Python 3.9+ like the installer.
"""
import io
import json
import os
import plistlib
import secrets
import shutil
import socket
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_router import feed_verify  # noqa: E402  (3.9-safe, no router import)

# Subscription-side roster for the combined picker: bare slugs that route on
# the ChatGPT subscription. Matches the live picker and state file; the
# OpenRouter-side roster lives in codex_router/models.json instead.
DEFAULT_OPENAI_MODELS = ['gpt-6-astra', 'gpt-reserve', 'gpt-5.6-sol',
                         'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5',
                         'gpt-5.4-mini', 'gpt-5.3-codex-spark', 'codex-auto-review']

LABEL = 'com.local.codex-mixed-model-router'
UPDATE_LABEL = LABEL + '.update'
FEED_URL = 'https://github.com/software-combined/SC_OpenRouter_adapter/releases/latest/download/latest.json'
MIN_PYTHON = (3, 14)

RELEASES_PREFIX = 'https://github.com/software-combined/SC_OpenRouter_adapter/releases/'


def github_asset(url):
    if not url.startswith(RELEASES_PREFIX):
        return None
    parts = url[len(RELEASES_PREFIX):].split('/')
    if len(parts) != 3 or not ((parts[0] == 'latest' and parts[1] == 'download')
                               or parts[0] == 'download'):
        raise SystemExit('unsupported router GitHub release URL')
    tag = None if parts[0] == 'latest' else parts[1]
    asset = parts[2]
    if not asset or any(c in asset for c in '?*[]'):
        raise SystemExit('invalid router release asset name')
    gh = shutil.which('gh') or next((p for p in (
        '/opt/homebrew/bin/gh', '/usr/local/bin/gh', '/usr/bin/gh') if Path(p).is_file()), None)
    if gh is None:
        raise SystemExit('Private router updates require GitHub CLI (gh), signed in as this user.')
    cmd = [gh, 'release', 'download', '--repo', 'software-combined/SC_OpenRouter_adapter',
           '--pattern', asset, '--output', '-']
    if tag is not None:
        cmd += ['--', tag]
    result = run(cmd, capture_output=True, timeout=120)
    if result.returncode:
        raise SystemExit('Cannot read private router release; check gh auth status and repository access.')
    return result.stdout


def fetch(url):
    """Single network entry point; tests inject a fake."""
    if url.startswith('file://'):
        return Path(url[len('file://'):]).read_bytes()
    asset = github_asset(url)
    if asset is not None:
        return asset
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def run(cmd, **kwargs):
    """Single subprocess entry point; tests inject a fake."""
    return subprocess.run(cmd, **kwargs)


def find_python(explicit=None):
    # Candidates are argv prefixes; the probe asks each for its own
    # sys.executable and only that absolute path is ever returned. A bare
    # discovery token must never reach a plist: launchd has no Homebrew PATH.
    # Order is portable-first: bare token, then POSIX standards, then
    # platform shims, then this interpreter last (it may be older than 3.14).
    candidates = [[explicit]] if explicit else []
    candidates += [['python3.14'], ['/usr/bin/python3.14'], ['/usr/local/bin/python3.14'],
                   ['/opt/homebrew/bin/python3.14'], ['/opt/homebrew/bin/python3'],
                   [shutil.which('python3')],
                   [sys.executable]]
    if sys.platform == 'win32':
        candidates.append(['py', '-V:3.14'])
    for candidate in candidates:
        if not candidate[0]:
            continue
        try:
            out = run(candidate + ['-c', 'import sys,compression.zstd;print(sys.version_info[0],sys.version_info[1]);print(sys.executable)'],
                      capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode == 0:
            try:
                version, exe, *_ = out.stdout.splitlines()
                if tuple(int(x) for x in version.split()) >= MIN_PYTHON and exe.strip():
                    return exe.strip()
            except ValueError:
                continue
    return None


def _require_absolute(python):
    # launchd never sees a shell PATH: persist the validated interpreter
    # identity, never a discovery token.
    if not python or not os.path.isabs(python):
        raise SystemExit(f'refusing non-absolute interpreter: {python!r}')
    return python


def safe_extract(tarball, dest):
    dest = Path(dest)
    with tarfile.open(fileobj=io.BytesIO(tarball), mode='r') as tar:
        for member in tar.getmembers():
            if member.name.startswith('/') or '..' in Path(member.name).parts:
                raise SystemExit('bundle has unsafe path: ' + member.name)
            if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                raise SystemExit('bundle has non-file member: ' + member.name)
        tar.extractall(dest, filter='data')


def current_release_dir(home):
    """Resolved release dir from the pointer file (or a legacy symlink)."""
    current = home / 'current'
    try:
        if current.is_symlink():
            target = Path(os.readlink(current))
        elif current.is_file():
            # Basename rule matches the launcher: pointer content never
            # escapes the releases dir, even if hand-edited.
            name = current.read_text().strip().split('/')[-1]
            target = home / 'releases' / name if name else None
        else:
            return None
    except (OSError, ValueError):
        return None
    return target if target is not None and target.is_dir() else None


def current_version(home):
    release = current_release_dir(home)
    return release.name if release is not None else '0.0.0'


def swap_current(home, release_dir):
    """Atomically point current at release_dir; returns the previous version."""
    resolved = current_release_dir(home)
    previous = resolved.name if resolved is not None else None
    tmp = home / 'current.tmp'
    if tmp.is_symlink() or tmp.is_file():
        tmp.unlink()
    elif tmp.exists():
        shutil.rmtree(tmp)
    # Pointer file, not a symlink: Windows needs elevation for symlinks.
    tmp.write_text(release_dir.name + '\n')
    os.replace(tmp, home / 'current')
    return previous


def render_plist(python, home, state):
    python = _require_absolute(python)
    return {'Label': LABEL,
            'ProgramArguments': [python, str(home / 'router_launch.py')],
            'Sockets': {'Listeners': {'SockNodeName': '127.0.0.1',
                                      'SockServiceName': str(state['port']),
                                      'SockFamily': 'IPv4',
                                      'SockType': 'stream'}},
            # No WorkingDirectory: the router resolves everything from
            # ROUTER_HOME and its own file location, so the plist stays valid
            # across releases and a plain TERM restarts into the new pointer.
            # ExitTimeOut covers the router drain deadline so launchd stops wait
            # instead of SIGKILLing mid-drain on bootout/uninstall.
            'EnvironmentVariables': {'ROUTER_HOME': str(home)},
            'KeepAlive': True, 'RunAtLoad': True, 'ThrottleInterval': 10, 'Umask': 63,
            'ExitTimeOut': 150,
            'StandardOutPath': str(home / 'logs' / 'launchd.log'),
            'StandardErrorPath': str(home / 'logs' / 'launchd.log')}


def render_update_plist(python, home):
    python = _require_absolute(python)
    base = current_release_dir(home) or home / 'current'
    installer = base / 'packaging' / 'install.py'
    args = [python, str(installer), '--check-update', '--home', str(home)]
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


def wait_idle(state, timeout=600, fetch_health=None):
    """True once inflight reads 0 three polls apart; False on timeout.

    A dead router (health None) counts as idle: no live traffic to
    protect, and the install must proceed to heal it. Only observed
    inflight > 0 defers.
    """
    good = 0
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = fetch_health(state) if fetch_health else health(state, timeout=5)
        if body is None or body.get('inflight') == 0:
            good += 1
            if good >= 3:
                return True
        else:
            good = 0
        time.sleep(1)
    return False


def fetch_feed(url, etag, _fetch=fetch):
    """Read a feed document, revalidating with a saved ETag. Returns (status, body, etag)."""
    if url.startswith('file://') or url.startswith(RELEASES_PREFIX):
        return 200, _fetch(url), etag
    req = urllib.request.Request(url, headers={'If-None-Match': etag} if etag else {})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.read(), response.headers.get('ETag', etag)
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return 304, b'', etag
        raise


def restart_service(uid):
    # Fresh install only: no live service to preserve.
    run(['launchctl', 'bootout', f'gui/{uid}/{LABEL}'], capture_output=True)
    agents = Path.home() / 'Library' / 'LaunchAgents'
    run(['launchctl', 'bootstrap', f'gui/{uid}', str(agents / (LABEL + '.plist'))], check=True)
    loaded = run(['launchctl', 'print', f'gui/{uid}/{UPDATE_LABEL}'],
                   capture_output=True)
    if loaded.returncode != 0:
        run(['launchctl', 'bootstrap', f'gui/{uid}', str(agents / (UPDATE_LABEL + '.plist'))],
            check=True)


def main_plist_exe(agents=None):
    """Installed main plist's ProgramArguments[0], or None when unreadable."""
    try:
        doc = plistlib.loads(((agents or Path.home() / 'Library' / 'LaunchAgents')
                              / (LABEL + '.plist')).read_bytes())
        return doc['ProgramArguments'][0]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def reload_main_service(uid):
    """bootout+bootstrap the main agent only (legacy bare-python repair).

    Rewriting a loaded plist does not update launchd's in-memory copy;
    only a reload picks up the absolute interpreter. The updater is never
    touched here. Raises SystemExit when the agent fails to load again.
    """
    agents = Path.home() / 'Library' / 'LaunchAgents'
    run(['launchctl', 'bootout', f'gui/{uid}/{LABEL}'], capture_output=True)
    loaded = run(['launchctl', 'bootstrap', f'gui/{uid}', str(agents / (LABEL + '.plist'))],
                 capture_output=True)
    if loaded.returncode != 0:
        raise SystemExit(f'bootstrap failed for {LABEL}')


def install_launcher(home, release_dir):
    """Copy the stable entry point beside the state directory, atomically."""
    try:
        blob = (release_dir / 'packaging' / 'router_launch.py').read_bytes()
    except OSError:
        raise SystemExit('bundle has no launcher')
    tmp = home / 'router_launch.tmp'
    if tmp.is_symlink() or tmp.is_file():
        tmp.unlink()
    elif tmp.exists():
        shutil.rmtree(tmp)
    tmp.write_bytes(blob)
    os.replace(tmp, home / 'router_launch.py')


def _write_state(home, state):
    fd = os.open(home / 'mixed-router-state.json', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(json.dumps(state, indent=2) + '\n')


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


def channel_feed(home):
    # A --feed pin file from an older install wins over the channel file, so
    # scheduled updates keep following it. Delete the file to return to
    # channel resolution; new installs never write it (one-shot --feed).
    if (home / 'feed').exists():
        return (home / 'feed').read_text().strip()
    channel = (home / 'channel').read_text().strip() if (home / 'channel').exists() else 'stable'
    if channel == 'beta':
        return feed_verify.beta_feed_url(FEED_URL)
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
