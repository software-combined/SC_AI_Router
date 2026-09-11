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

LABEL = 'com.local.codex-mixed-model-router'
UPDATE_LABEL = LABEL + '.update'
FEED_URL = _feed.FEED_URL
MIN_PYTHON = (3, 14)

# Feed routing lives in feed.py; these are the names its callers read here.
RELEASES_PREFIX = _feed.RELEASES_PREFIX
feed_token = _feed.feed_token
persist_feed_token = _feed.persist_feed_token
trusted_origin = _feed.trusted_origin
channel_feed = _feed.channel_feed
feed_source = _feed.feed_source
gh_binary = _feed.gh_binary
notice = _notice


def github_asset(url):
    route = _feed.github_route_parts(url)
    if route is None:
        return None
    tag, asset = route
    gh = _feed.gh_binary()
    if gh is None:
        raise SystemExit('Private router updates require GitHub CLI (gh), signed in as this user.')
    result = run(_feed.github_command(gh, tag, asset), capture_output=True, timeout=120)
    if result.returncode:
        raise SystemExit('Cannot read private router release; check gh auth status and repository access.')
    return result.stdout


def fetch(url, home=None):
    """Single network entry point; tests inject a fake.

    The token header goes only to the feed origin. GitHub asset URLs keep
    the gh path; anything off the trusted origins is refused before fetch
    so a compromised feed cannot redirect a host elsewhere.
    """
    if url.startswith('file://'):
        return Path(url[len('file://'):]).read_bytes()
    if not _feed.trusted_origin(url):
        raise SystemExit('refusing untrusted feed URL: %s' % _feed._safe_url(url))
    asset = github_asset(url)
    if asset is not None:
        return asset
    headers = _feed.feed_headers(home) if url.startswith(_feed.FEED_ORIGIN + '/') else {}
    req = urllib.request.Request(url, headers=headers) if headers else url
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def feed_read(fetcher, url, home):
    """Fetch one feed/bundle URL, home-bound when the fetcher allows it.

    The default fetch sends the stored feed token to the feed origin;
    injected test fakes keep their one-argument shape.
    """
    if fetcher is fetch and not trusted_origin(url):
        raise SystemExit('feed points off the trusted update origin; refusing')
    try:
        return fetcher(url, home)
    except TypeError:
        return fetcher(url)


def run(cmd, **kwargs):
    """Single subprocess entry point; tests inject a fake."""
    if sys.platform == 'win32':
        # The scheduled updater runs this installer under pythonw.exe; a
        # console child (python, gh, schtasks, icacls) spawned from there
        # would otherwise open a console window on the desktop.
        kwargs.setdefault('creationflags', getattr(subprocess, 'CREATE_NO_WINDOW', 0))
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
    # The stable home launcher, never a per-release install.py path. launchd
    # keeps running its in-memory copy of a loaded plist, so a versioned path
    # outlives the release it names: after a prune the updater keeps firing a
    # deleted or obsolete installer every 15 minutes. update_launch.py
    # resolves `current` at exec time instead, exactly like router_launch.py.
    args = [python, str(home / 'update_launch.py')]
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


def fetch_feed(url, etag, _fetch=None, home=None):
    """Read a feed document, revalidating with a saved ETag.

    Returns (status, body, etag). The default fetch sends the stored feed
    token to the feed origin; injected fakes keep their old one-argument
    shape and bypass the header path.
    """
    if _fetch is None:
        return _feed.live_feed(url, etag, home, fetch)
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
def install_lock(home):
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
    handle = os.open(path / 'install.lock', os.O_RDWR | os.O_CREAT, 0o600)
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


def restart_service(uid, agents=None):
    # First install: a reload rather than a plain load, because "no previous
    # release" does not prove no job is loaded -- a half-finished earlier
    # attempt can leave one behind running a release that is now gone.
    agents = _agents(agents)
    if not _launchd.reload_job(run, uid, LABEL, agents=agents,
                               unload_timeout=UNLOAD_TIMEOUT_S,
                               load_timeout=LOAD_TIMEOUT_S, sleep=_sleep):
        raise SystemExit(f'bootstrap failed for {LABEL}')
    if not _launchd.load(run, uid, UPDATE_LABEL, agents=agents,
                         timeout=LOAD_TIMEOUT_S, sleep=_sleep):
        raise SystemExit(f'bootstrap failed for {UPDATE_LABEL}')


def same_interpreter(left, right):
    """True when two paths name the same interpreter binary.

    `/opt/homebrew/bin/python3.14` and
    `/opt/homebrew/opt/python@3.14/bin/python3.14` are one binary reached by
    two symlink spellings. A string compare calls them different and forces
    the destructive reload path on a run that only needed a TERM handover.
    """
    if not left or not right:
        return False
    try:
        return os.path.realpath(left) == os.path.realpath(right)
    except OSError:
        return left == right


def command_matches(loaded, rendered):
    """True when launchd's loaded command is the one we intend to run.

    argv[0] is compared by resolved path because two symlink spellings name
    one interpreter; every later argument must match exactly, so a changed
    launcher path is never mistaken for no change at all.
    """
    if not loaded or not rendered or len(loaded) != len(rendered):
        return False
    if not same_interpreter(loaded[0], rendered[0]):
        return False
    return list(loaded[1:]) == list(rendered[1:])


def running_under(label):
    """True when this process is inside the launchd job for `label`.

    launchd stamps XPC_SERVICE_NAME into the job's environment and children
    inherit it, so the scheduled updater's own installer can tell that
    booting out that label would kill the process issuing the bootout.
    """
    return os.environ.get('XPC_SERVICE_NAME') == label


def plist_differs(path, content):
    """True when the plist on disk does not already say exactly this."""
    try:
        return plistlib.loads(Path(path).read_bytes()) != content
    except (OSError, ValueError):
        return True


def main_plist_needs_reload(uid, python, home, state, agents=None):
    """True when launchd is running something other than what we will write.

    Compared against launchd's in-memory program rather than the file: a
    previous failed run may already have rewritten the plist while the loaded
    job kept the old command.
    """
    agents = _agents(agents)
    rendered = render_plist(python, home, state)
    loaded = _launchd.loaded_command(run, uid, LABEL)
    if loaded is None or not command_matches(loaded, rendered['ProgramArguments']):
        return True
    # Catches everything launchd owns that is not argv, the port above all.
    return plist_differs(agents / (LABEL + '.plist'), rendered)


def ensure_updater(uid, python, home, agents=None):
    """Keep the scheduled updater loaded and running the current command.

    Writing the file is not enough: launchd adopts a rewritten plist only on
    reload, which is how the updater kept invoking an installer from a release
    that had already been pruned.

    But the scheduled updater is what runs this installer, so a bootout here
    would kill the process issuing it and leave the job unloaded with no
    bootstrap -- the same silent-loss failure this release fixes for the
    router. When this run *is* that job, the rewritten file is left for the
    next manual install or login to adopt; the plist now names a
    release-independent launcher, so one adoption is final.
    """
    agents = _agents(agents)
    rendered = render_update_plist(python, home)['ProgramArguments']
    loaded = _launchd.loaded_command(run, uid, UPDATE_LABEL)
    if loaded is None:
        return _launchd.load(run, uid, UPDATE_LABEL, agents=agents,
                             timeout=LOAD_TIMEOUT_S, sleep=_sleep)
    if command_matches(loaded, rendered):
        return True
    if running_under(UPDATE_LABEL):
        print('scheduled updater command changed; adopting it needs a reload '
              'from outside its own job, so the next manual install or login '
              'will pick it up')
        return True
    return _launchd.reload_job(run, uid, UPDATE_LABEL, agents=agents,
                               unload_timeout=UNLOAD_TIMEOUT_S,
                               load_timeout=LOAD_TIMEOUT_S, sleep=_sleep)


def _read_failures(home):
    """State document plus its failure map; (None, {}) when unreadable.

    Always read fresh here rather than reusing a copy taken earlier in the
    run: the child installer writes the same file, and merging onto a stale
    copy would drop its changes.
    """
    try:
        state = json.loads((home / 'mixed-router-state.json').read_text())
    except (OSError, ValueError):
        return None, {}
    failures = state.get('update_failures')
    return state, dict(failures) if isinstance(failures, dict) else {}


def update_failures(home):
    """Failed attempts per version; {} when none are recorded."""
    return _read_failures(home)[1]


def record_update_failure(home, version):
    """Count a failed attempt at one version; returns the new count."""
    state, failures = _read_failures(home)
    if state is None:
        return 0
    failures[version] = failures.get(version, 0) + 1
    state['update_failures'] = failures
    _write_state(home, state)
    return failures[version]


def clear_update_failures(home, version):
    state, failures = _read_failures(home)
    if state is None or version not in failures:
        return
    del failures[version]
    state['update_failures'] = failures
    _write_state(home, state)

def loaded_updater_release(uid, home):
    """Release name inside launchd's loaded updater command, or None.

    Before this release the updater plist named a per-release installer, and
    launchd runs the command it loaded until the job is reloaded -- which a
    scheduled run deliberately defers, because it cannot bootout its own job.
    Pruning that release would leave the updater firing a missing file.
    """
    prefix = str(Path(home) / 'releases') + os.sep
    for token in (_launchd.loaded_command(run, uid, UPDATE_LABEL) or [])[1:]:
        if token.startswith(prefix):
            return token[len(prefix):].split(os.sep)[0] or None
    return None


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


def reload_main_service(uid, agents=None):
    """Make launchd adopt the rewritten main plist. True when loaded again.

    Rewriting a loaded plist does not update launchd's in-memory copy; only a
    reload picks up a changed interpreter or port. The updater is never
    touched here. Returns False rather than raising so the caller can roll
    back and then restore service on the previous release.
    """
    return _launchd.reload_job(run, uid, LABEL, agents=_agents(agents),
                               unload_timeout=UNLOAD_TIMEOUT_S,
                               load_timeout=LOAD_TIMEOUT_S, sleep=_sleep)


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


def _install_home_file(home, release_dir, name):
    """Copy one stable entry point beside the state directory, atomically."""
    try:
        blob = (release_dir / 'packaging' / name).read_bytes()
    except OSError:
        raise SystemExit(f'bundle has no {name}')
    tmp = home / (name + '.tmp')
    if tmp.is_symlink() or tmp.is_file():
        tmp.unlink()
    elif tmp.exists():
        shutil.rmtree(tmp)
    tmp.write_bytes(blob)
    os.replace(tmp, home / name)


def install_launcher(home, release_dir):
    """Install both stable entry points beside the state directory.

    Each resolves `current` at exec time, so the plists that name them stay
    valid across every future update and prune.
    """
    _install_home_file(home, release_dir, 'router_launch.py')
    _install_home_file(home, release_dir, 'update_launch.py')


def _write_state(home, state):
    _atomic_write.replace_text(home / 'mixed-router-state.json', json.dumps(state, indent=2) + '\n')


def ensure_state(home):
    path = home / 'mixed-router-state.json'
    if path.exists():
        state = json.loads(path.read_text())
        if not isinstance(state.get('openai_models'), list):
            state['openai_models'] = list(DEFAULT_OPENAI_MODELS)
            _atomic_write.replace_text(path, json.dumps(state, indent=2) + '\n')
        elif any(slug in state['openai_models'] for slug in RETIRED_SUBSCRIPTION_SLUGS):
            # Retired slugs: prune so routing stops authorizing them on update.
            # Type-check first: a corrupt non-string element must not be hashed.
            state['openai_models'] = [
                s for s in state['openai_models']
                if not (isinstance(s, str) and s in RETIRED_SUBSCRIPTION_SLUGS)]
            _atomic_write.replace_text(path, json.dumps(state, indent=2) + '\n')
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
    """Last accepted feed serial; 0 when no serialed release was installed."""
    try:
        return int((home / 'feed-serial').read_text().strip())
    except FileNotFoundError:
        return 0
    except ValueError:
        raise SystemExit('feed serial file is corrupt')


def check_serial(home, latest, pinned=False):
    """Refuse feeds older than the last accepted one (replay protection).

    A pinned `--feed` is exempt on both sides: it is operator-supplied for
    this one run, so it is neither the unattended channel the guard protects
    nor recorded afterwards. Without the exemption a locally built bundle
    (`--build` defaults to 0) is refused as stale against whatever the real
    feed last recorded, which is a trap that invites picking a build number
    high enough to win -- and that number then freezes the real channel.
    """
    if pinned:
        return 0
    serial = latest.get('serial', 0)
    if type(serial) is not int:
        raise SystemExit('feed has a bad serial')
    stored = feed_serial(home)
    if serial < stored:
        raise SystemExit(f'stale feed serial {serial} is older than {stored}')
    # Learn the feed token after the serial check but before the version
    # comparison, so a host that is already current still migrates: its
    # next poll resolves the token-gated origin. A feed without a token
    # leaves the host on its existing route untouched.
    persist_feed_token(home, latest)
    return serial
