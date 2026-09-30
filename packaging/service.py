"""Shared launchd/plist/feed helpers for install and scheduled update.

Split out of packaging/install.py (which hit the 700-line entrypoint
limit). Behavioral deltas vs the original live here, not in install.py:
ExitTimeOut 150 on the main plist, restart_service bootstraps the updater
only when missing, render_update_plist takes no feed (one-shot --feed).
Runs on Python 3.9+ like the installer.
"""
import contextlib
import io
import json
import os
import secrets
import shutil
import socket
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

try:                      # POSIX advisory locking
    import fcntl
except ImportError:       # pragma: no cover - Windows
    fcntl = None
try:                      # Windows advisory locking
    import msvcrt
except ImportError:       # pragma: no cover - POSIX
    msvcrt = None

import sys

import importlib.util  # noqa: E402


def load(name, filename):
    """Load one sibling module from its file path (Plan 123).

    The single 3.9-safe loader for every packaging module: the
    spec-from-file + module_from_spec + exec_module sequence.
    Callers resolve `filename` against their own __file__ so relocated
    (installed) trees keep working.
    """
    spec = importlib.util.spec_from_file_location(name, filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_launchd = load('router_launchd', Path(__file__).resolve().parent / 'launchd.py')
_feed = load('router_feed', Path(__file__).resolve().parent / 'feed.py')
_roster = load('router_subscription_roster',
               Path(__file__).resolve().parents[1] / 'ai_router' / 'subscription_roster.py')
_retired = load('router_retired_slugs',
                Path(__file__).resolve().parents[1] / 'ai_router' / 'retired_slugs.py')
_atomic_write = load('router_atomic_write',
                     Path(__file__).resolve().parent / 'atomic_write.py')
_state = load('router_state',
              Path(__file__).resolve().parents[1] / 'ai_router' / 'state.py')
_notice = load('router_notice',
                Path(__file__).resolve().parent / 'notice.py')

# Patchable seam so tests never sleep through a real launchd settle window.
_sleep = time.sleep
# Bounded by the router drain deadline (ExitTimeOut 150 on the main plist).
UNLOAD_TIMEOUT_S = 180
LOAD_TIMEOUT_S = 60

# Subscription-side roster for the combined picker: bare slugs that route on
# the ChatGPT subscription. Single-sourced from ai_router/subscription_roster.py
# (spec-loaded above: a package import would break the installed launchers,
# which spec-load this module before any sys.path insert). Matches the live
# picker and state file; the OpenRouter-side roster lives in
# ai_router/models.json instead.
DEFAULT_OPENAI_MODELS = list(_roster.SUBSCRIPTION_SLUGS)

# Subscription slugs withdrawn from the picker, single-sourced from
# ai_router/retired_slugs.py (Plan 100; spec-loaded above for the same
# relocated-tree reason as the roster).
RETIRED_SUBSCRIPTION_SLUGS = frozenset(_retired.SUBSCRIPTION)

LABEL = _launchd.LABEL
UPDATE_LABEL = _launchd.UPDATE_LABEL
FEED_URL = _feed.FEED_URL
MIN_PYTHON = (3, 14)

# Feed routing lives in feed.py; these are the names its callers read here.
trusted_origin = _feed.trusted_origin
sibling_bundle = _feed.sibling_bundle
channel_feed = _feed.channel_feed
feed_source = _feed.feed_source
fetch = _feed.fetch
feed_read = _feed.feed_read
notice = _notice


def run(cmd, **kwargs):
    """Single subprocess entry point; tests inject a fake."""
    if sys.platform == 'win32':
        # The scheduled updater runs this installer under pythonw.exe; a
        # console child (python, schtasks, icacls) spawned from there
        # would otherwise open a console window on the desktop.
        kwargs.setdefault('creationflags', getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return subprocess.run(cmd, **kwargs)


def find_python(explicit=None):
    # Candidates are argv prefixes; the probe asks each for its own
    # sys.executable and only that absolute path is ever returned. A bare
    # discovery token must never reach a plist: launchd has no Homebrew PATH.
    # Order: bare token, POSIX paths (never on Windows: drive-root folders any
    # account can create), shims, this interpreter last (may predate 3.14).
    candidates = ([[explicit]] if explicit else []) + [['python3.14']]
    if sys.platform != 'win32':
        candidates += [['/usr/bin/python3.14'], ['/usr/local/bin/python3.14'],
                       ['/opt/homebrew/bin/python3.14'], ['/opt/homebrew/bin/python3']]
    candidates += [[shutil.which('python3')], [sys.executable]]
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


# --- launchd rendering/reload delegations (Plan 103) -------------------------
# The implementations live in launchd.py; these thin wrappers keep the
# packaging/install.py bindings and the installer test seams working. Move
# the seams they read (run, _sleep, timeouts) at call time, never at import.

def render_plist(python, home, state):
    return _launchd.render_plist(python, home, state)


def render_update_plist(python, home):
    return _launchd.render_update_plist(python, home)


def write_plist(path, content):
    return _launchd.write_plist(path, content)


def same_interpreter(left, right):
    return _launchd.same_interpreter(left, right)


def main_plist_needs_reload(uid, python, home, state, agents=None):
    return _launchd.main_plist_needs_reload(run, uid, python, home, state,
                                            _agents(agents))


def ensure_updater(uid, python, home, agents=None):
    return _launchd.ensure_updater(run, uid, python, home, _agents(agents),
                                   sleep=_sleep,
                                   unload_timeout=UNLOAD_TIMEOUT_S,
                                   load_timeout=LOAD_TIMEOUT_S)


def loaded_updater_release(uid, home):
    return _launchd.loaded_updater_release(run, uid, home)


def reload_main_service(uid, agents=None):
    return _launchd.reload_main_service(run, uid, _agents(agents), sleep=_sleep,
                                        unload_timeout=UNLOAD_TIMEOUT_S,
                                        load_timeout=LOAD_TIMEOUT_S)


def restart_service(uid, agents=None):
    return _launchd.restart_service(run, uid, _agents(agents), sleep=_sleep,
                                    unload_timeout=UNLOAD_TIMEOUT_S,
                                    load_timeout=LOAD_TIMEOUT_S)


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


def fetch_feed(url, etag, _fetch=None):
    """Read a feed document (Plan 131: owned by feed.py, re-exported here).

    The default path calls back into this module's fetch seam so installer
    patches still apply; injected fakes keep their one-argument shape.
    """
    live = _feed.live_feed
    if _fetch is None:
        return live(url, etag, fetch)
    return _feed.fetch_feed(url, etag, _fetch=_fetch)


def _agents(agents=None):
    return Path(agents) if agents else Path.home() / 'Library' / 'LaunchAgents'


def require_live_home(home, action):
    """Refuse service mutations against a scratch router home.

    Service names are machine-wide (launchd labels, systemd units,
    Scheduled Tasks): a run against a scratch --home still mutates the
    production jobs. Mutating entry points refuse unless ROUTER_LIVE_RUN=1.
    """
    prod = Path('~/.codex/mixed-model-router').expanduser().resolve()
    if Path(home).expanduser().resolve() == prod or os.environ.get('ROUTER_LIVE_RUN') == '1':
        return
    raise SystemExit(f'refusing {action} against scratch home {home}; use {prod} or ROUTER_LIVE_RUN=1')


@contextlib.contextmanager
def install_lock(home, name='install.lock'):
    """Serialise installs on one router home. Yields False when one is running.

    The scheduled updater and a manual run fire independently, and both swap
    `current`, rewrite both plists and reload the same launchd label. The lock
    is advisory and held on an open descriptor, so the OS releases it when the
    holder exits and a killed installer never leaves one behind for an
    operator to clear.
    """
    path = Path(home)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Note: callers that must not write (--dry-run) skip the lock entirely.
    if fcntl is None and msvcrt is None:  # pragma: no cover - neither platform
        print('warning: no advisory file locking here; concurrent installs '
              'are not serialised')
        yield True
        return
    handle = os.open(path / name, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
        except OSError:
            yield False
            return
        yield True
    finally:
        os.close(handle)


_updater_mod = None


def _updater():
    """updater.py loaded once (it spec-loads this module, so no top import)."""
    global _updater_mod
    if _updater_mod is None:
        _updater_mod = load(
            'router_updater', Path(__file__).resolve().parent / 'updater.py')
    return _updater_mod


def _read_failures(home):
    """Update-failure state (Plan 131: owned by updater.py)."""
    return _updater()._read_failures(home)


def update_failures(home):
    """Failed attempts per version (Plan 131: owned by updater.py)."""
    return _updater().update_failures(home)


def record_update_failure(home, version):
    """Count a failed attempt (Plan 131: owned by updater.py)."""
    return _updater().record_update_failure(home, version)


def clear_update_failures(home, version):
    _updater().clear_update_failures(home, version)


def ensure_serving(uid, home, state, agents=None, timeout=180, version=None):
    """Guarantee a loaded main job that answers /health; returns the body.

    The installer's last act on every path, success or rollback. A pointer
    swap plus `launchctl kill TERM` cannot recover a machine whose job is not
    loaded, because KeepAlive has nothing to keep alive -- and that is exactly
    the state a failed reload leaves behind.
    """
    _launchd.load(run, uid, LABEL, agents=_agents(agents),
                  timeout=LOAD_TIMEOUT_S, sleep=_sleep)
    if version is not None:
        return wait_version(state, version, timeout=timeout)
    return health(state, timeout=timeout)


def rotate_log(path, limit_bytes=1024 * 1024, backups=2):
    """Bound a supervisor-captured log with rotate-on-start semantics.

    launchd/systemd own the open file description, so a rename takes effect
    on the next job start; each start keeps at most limit*(backups+1) bytes.
    Pure stdlib, no logging framework; never touches request content.
    """
    path = Path(path)
    try:
        if path.stat().st_size <= limit_bytes:
            return
    except OSError:
        return
    for index in range(backups, 0, -1):
        src = path if index == 1 else Path(str(path) + f'.{index - 1}')
        dst = Path(str(path) + f'.{index}')
        try:
            if src.exists():
                os.replace(src, dst)
        except OSError:
            return
    try:
        path.touch()
    except OSError:
        pass


def prune_logs(logs_dir, days=30, now=None, live=('router.jsonl', 'launchd.log', 'update.log')):
    """Age logs out; live sinks and symlinks stay, and OSError never escapes.

    Rotated backups, old support bundles and task XML age out a month after
    their last write; this runs at every service start and scheduled update.
    """
    cutoff = (time.time() if now is None else now) - days * 86400
    removed = 0
    try:
        for path in list(Path(logs_dir).iterdir()):
            if (path.name not in live and path.is_file()
                    and not path.is_symlink() and path.stat().st_mtime < cutoff):
                path.unlink()
                removed += 1
    except OSError:
        pass
    return removed


def _install_home_file(home, release_dir, name, target=None):
    """Copy one stable entry point beside the state directory, atomically."""
    target = target or name
    try:
        blob = (release_dir / 'packaging' / name).read_bytes()
    except OSError:
        raise SystemExit(f'bundle has no {name}')
    tmp = home / (target + '.tmp')
    if tmp.is_symlink() or tmp.is_file():
        tmp.unlink()
    elif tmp.exists():
        shutil.rmtree(tmp)
    tmp.write_bytes(blob)
    os.replace(tmp, home / target)


def install_launcher(home, release_dir):
    """Install both stable entry points beside the state directory.

    Each resolves `current` at exec time, so the plists that name them stay
    valid across every future update and prune.
    """
    _install_home_file(home, release_dir, 'router_launch.py')
    _install_home_file(home, release_dir, 'update_launch.py')
    if "'--express-only'" in (release_dir / 'packaging' / 'update_launch.py').read_text():
        _install_home_file(home, release_dir, 'update_launch.py', 'express_launch.py')


def install_task_launcher(home, release_dir):
    """Install the Windows Task Scheduler entry point beside the state dir.

    The task XML names `<home>/task_launch.py`; copying the packaged file
    keeps the installed launcher byte-identical to the one CI parses. A
    repair run can name a release that predates the packaged launcher (or no
    release at all): the home copy the previous install wrote is then already
    correct, so it is kept instead of failing the repair.
    """
    if release_dir is not None:
        try:
            _install_home_file(home, release_dir, 'task_launch.py')
            return
        except SystemExit:
            pass
    if not (Path(home) / 'task_launch.py').is_file():
        raise SystemExit('bundle has no task_launch.py')


def _write_state(home, state):
    _atomic_write.replace_json(_state.path(home), state)
def ensure_state(home):
    path = _state.path(home)
    if path.exists():
        state = _state.read_strict(path)
        models = state.get('openai_models')
        # Empty hides every ChatGPT row; no installer writer produces it.
        if not (isinstance(models, list) and any(
                isinstance(s, str) and s for s in models)):
            state['openai_models'] = list(DEFAULT_OPENAI_MODELS)
            _atomic_write.replace_json(path, state)
        else:
            pruned = [s for s in _roster.replace_successors(models)
                      if not (isinstance(s, str) and s in RETIRED_SUBSCRIPTION_SLUGS)]
            if pruned != models:
                state['openai_models'] = pruned
                _atomic_write.replace_json(path, state)
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


def feed_serial(home):
    """Last accepted feed serial (Plan 131: owned by feed.py)."""
    return _feed.feed_serial(home)


def check_serial(home, latest, pinned=False):
    """Replay guard (Plan 131: owned by feed.py)."""
    return _feed.check_serial(home, latest, pinned)
